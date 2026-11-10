#!/usr/bin/env python3
# =============================================================================
#  dashboard/agent/term-agent.py — shells for the dashboard Terminal tab (administrator only).
#
#  Runs on the core machine as the install user (systemd unit open5gs-k3s-term). It long-polls the
#  dashboard for new terminals, starts each one in a pseudo-terminal with the chosen profile and
#  connects back to the dashboard over a WebSocket, which relays it to the browser (dashboard/app/term.py).
#  Nothing listens on the network here: the agent only makes outgoing connections to the dashboard.
#
#  Profiles (TERM_PROFILES, "name|command;name|command"): the first one is the default, e.g.
#    TERM_PROFILES="torre2|bash -l;innovaserver|ssh -t innovaserver@10.10.0.1"
#  Each shell starts in the user's home with TERM=xterm-256color and ends when its browser tab closes.
#
#  Usage:
#    DASHBOARD_URL=http://10.254.254.1:30998 INGEST_TOKEN=... TERM_PROFILES=... python3 term-agent.py
# =============================================================================
import base64
import fcntl
import json
import os
import pty
import secrets
import shlex
import signal
import socket
import struct
import sys
import termios
import threading
import time
import urllib.parse
import urllib.request

URL = os.environ.get("DASHBOARD_URL", "").rstrip("/")
TOKEN = os.environ.get("INGEST_TOKEN", "")
HOST = socket.gethostname()


def profiles():
    out = {}
    for item in os.environ.get("TERM_PROFILES", "").split(";"):
        name, _, cmd = item.partition("|")
        if name.strip() and cmd.strip():
            out[name.strip()] = cmd.strip()
    return out or {HOST: "bash -l"}


PROFILES = profiles()


def log(*a):
    print(time.strftime("%H:%M:%S"), *a, flush=True)


# ---------------------------------------------------------------------------
#  WebSocket client (RFC 6455, frames from the client are masked)
# ---------------------------------------------------------------------------
class WS:
    def __init__(self, url, headers):
        u = urllib.parse.urlparse(url)
        self.s = socket.create_connection((u.hostname, u.port or 80), timeout=10)
        key = base64.b64encode(secrets.token_bytes(16)).decode()
        req = ("GET %s HTTP/1.1\r\nHost: %s:%d\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n"
               "Sec-WebSocket-Key: %s\r\nSec-WebSocket-Version: 13\r\n" % (u.path + ("?" + u.query if u.query else ""),
                                                                          u.hostname, u.port or 80, key))
        req += "".join("%s: %s\r\n" % kv for kv in headers.items()) + "\r\n"
        self.s.sendall(req.encode())
        self.r = self.s.makefile("rb")
        status = self.r.readline()
        while self.r.readline() not in (b"\r\n", b"\n", b""):
            pass
        if b" 101 " not in status:
            raise OSError("WebSocket refused: %s" % status.decode(errors="replace").strip())
        self.s.settimeout(None)
        self.lock = threading.Lock()
        self.closed = False

    def _read(self, n):
        buf = b""
        while len(buf) < n:
            c = self.r.read(n - len(buf))
            if not c:
                return None
            buf += c
        return buf

    def recv(self):
        parts, first = [], None
        while not self.closed:
            try:
                h = self._read(2)
                if not h:
                    break
                fin, op, n = h[0] & 0x80, h[0] & 0x0F, h[1] & 0x7F
                if n == 126:
                    n = struct.unpack(">H", self._read(2))[0]
                elif n == 127:
                    n = struct.unpack(">Q", self._read(8))[0]
                data = self._read(n) if n else b""
                if data is None:
                    break
            except (OSError, struct.error, TypeError):
                break
            if op == 8:
                break
            if op == 9:
                self.send(data, 10)
                continue
            if op == 10:
                continue
            if op:
                first = op
            parts.append(data)
            if fin:
                return first or 2, b"".join(parts)
        self.close()
        return None

    def send(self, data, op=2):
        n = len(data)
        head = bytes([0x80 | op])
        if n < 126:
            head += bytes([0x80 | n])
        elif n < 65536:
            head += bytes([0x80 | 126]) + struct.pack(">H", n)
        else:
            head += bytes([0x80 | 127]) + struct.pack(">Q", n)
        key = secrets.token_bytes(4)
        k = (key * (n // 4 + 1))[:n]
        body = (int.from_bytes(data, "big") ^ int.from_bytes(k, "big")).to_bytes(n, "big") if n else b""
        try:
            with self.lock:
                self.s.sendall(head + key + body)
            return True
        except OSError:
            self.close()
            return False

    def close(self):
        if self.closed:
            return
        self.closed = True
        try:
            with self.lock:
                self.s.sendall(b"\x88\x80" + secrets.token_bytes(4))
        except OSError:
            pass
        try:
            self.s.close()
        except OSError:
            pass


# ---------------------------------------------------------------------------
#  One terminal
# ---------------------------------------------------------------------------
def set_size(fd, cols, rows):
    try:
        cols, rows = max(2, min(int(cols), 1000)), max(2, min(int(rows), 500))
        fcntl.ioctl(fd, termios.TIOCSWINSZ, struct.pack("HHHH", rows, cols, 0, 0))
    except (ValueError, TypeError, OSError):
        pass


def session(req):
    sid = req.get("id", "")
    name = req.get("profile") if req.get("profile") in PROFILES else next(iter(PROFILES))
    try:
        ws = WS("%s/api/ingest/term/ws?id=%s" % (URL, urllib.parse.quote(sid)), {"X-Ingest-Token": TOKEN})
    except OSError as e:
        log("session", sid[:6], "connect failed:", e)
        return
    home = os.path.expanduser("~")
    pid, fd = pty.fork()
    if pid == 0:                                   # child: the shell
        try:
            os.chdir(home)
        except OSError:
            pass
        env = dict(os.environ, TERM="xterm-256color", COLORTERM="truecolor", HOME=home)
        for k in ("INGEST_TOKEN", "DASHBOARD_URL", "TERM_PROFILES", "INVOCATION_ID", "JOURNAL_STREAM"):
            env.pop(k, None)
        argv = shlex.split(PROFILES[name])
        try:
            os.execvpe(argv[0], argv, env)
        finally:
            os._exit(127)
    set_size(fd, req.get("cols", 80), req.get("rows", 24))
    log("session", sid[:6], "open:", name, "pid", pid)

    def pty_to_ws():
        while True:
            try:
                data = os.read(fd, 65536)
            except OSError:
                break
            if not data or not ws.send(data, 2):
                break
        ws.close()

    t = threading.Thread(target=pty_to_ws, daemon=True)
    t.start()
    while True:
        m = ws.recv()
        if m is None:
            break
        try:
            msg = json.loads(m[1].decode("utf-8", "replace"))
        except ValueError:
            continue
        if "i" in msg:
            try:
                os.write(fd, str(msg["i"]).encode())
            except OSError:
                break
        elif "r" in msg and isinstance(msg["r"], list) and len(msg["r"]) == 2:
            set_size(fd, *msg["r"])
    # browser closed (or the shell ended): finish the shell and everything it started
    try:
        os.killpg(pid, signal.SIGHUP)
    except OSError:
        pass
    code = None
    for _ in range(20):
        try:
            p, st = os.waitpid(pid, os.WNOHANG)
        except ChildProcessError:
            break
        if p:
            code = os.waitstatus_to_exitcode(st)
            break
        time.sleep(0.1)
    else:
        try:
            os.killpg(pid, signal.SIGKILL)
            os.waitpid(pid, 0)
        except OSError:
            pass
    if not ws.closed:
        ws.send(json.dumps({"exit": code}).encode(), 1)
    ws.close()
    try:
        os.close(fd)
    except OSError:
        pass
    log("session", sid[:6], "closed, exit", code)


def main():
    if not URL or not TOKEN:
        sys.exit("DASHBOARD_URL and INGEST_TOKEN are required")
    log("term-agent: dashboard", URL, "profiles", ", ".join(PROFILES))
    body = json.dumps({"profiles": list(PROFILES), "host": HOST}).encode()
    while True:
        try:
            req = urllib.request.Request(URL + "/api/ingest/term/poll", data=body, method="POST",
                                         headers={"Content-Type": "application/json", "X-Ingest-Token": TOKEN})
            with urllib.request.urlopen(req, timeout=40) as r:
                todo = json.load(r).get("sessions", [])
        except Exception as e:                      # dashboard restarting, network down, terminal off
            log("poll failed:", e)
            time.sleep(10)
            continue
        for s in todo:
            threading.Thread(target=session, args=(s,), daemon=True).start()


if __name__ == "__main__":
    main()
