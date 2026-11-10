# =============================================================================
#  dashboard/app/term.py — Terminal tab (administrator only): browser shells on the core machine.
#
#  The dashboard pod has no privileges (read-only filesystem, no capabilities), so the shells run in
#  term-agent.py, a service of the install user on the core machine. The dashboard only pairs and
#  relays WebSocket messages:
#
#    browser --WS /api/term/ws?t=<admin token>--> dashboard <--WS /api/ingest/term/ws?id=<sid>-- term-agent
#
#  1. The browser opens /api/term/ws; the dashboard queues a session request.
#  2. term-agent long-polls POST /api/ingest/term/poll (X-Ingest-Token), gets the request, starts a PTY
#     with the chosen profile and connects back to /api/ingest/term/ws?id=<sid>.
#  3. The dashboard relays both directions until one side closes (the agent then ends the shell).
#
#  Messages: browser -> agent are text frames, JSON {"i": "<keys>"} (input) or {"r": [cols, rows]}
#  (resize); agent -> browser are binary frames with the raw terminal output; text frames from the
#  agent are JSON notices ({"exit": code} or {"error": "..."}).
#  Python standard library only.
# =============================================================================
import base64
import hashlib
import json
import secrets
import struct
import threading
import time

GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"
MAX_FRAME = 1 << 20          # 1 MiB: terminal messages are small
MAX_SESSIONS = 12            # open terminals at the same time (all browsers)
ATTACH_TIMEOUT = 15          # s to wait for the agent to pick up a new session
AGENT_ALIVE = 45             # s since the last poll to consider the agent connected


def ws_accept(handler):
    """Answers the WebSocket upgrade of a BaseHTTPRequestHandler. Returns a WebSocket or None."""
    key = handler.headers.get("Sec-WebSocket-Key", "")
    if "websocket" not in handler.headers.get("Upgrade", "").lower() or not key:
        return None
    acc = base64.b64encode(hashlib.sha1((key + GUID).encode()).digest()).decode()
    handler.wfile.write(("HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n"
                         "Sec-WebSocket-Accept: %s\r\n\r\n" % acc).encode())
    handler.wfile.flush()
    handler.close_connection = True
    handler.connection.settimeout(None)
    # rfile is buffered: frames that arrived with the request are already inside it
    return WebSocket(handler.rfile, handler.connection)


class WebSocket:
    """Minimal RFC 6455 endpoint (server side: frames sent unmasked)."""

    def __init__(self, rfile, sock, mask=False):
        self.r = rfile
        self.s = sock
        self.mask = mask
        self.wlock = threading.Lock()
        self.closed = False

    def _read(self, n):
        buf = b""
        while len(buf) < n:
            chunk = self.r.read(n - len(buf))
            if not chunk:
                return None
            buf += chunk
        return buf

    def recv(self):
        """Next data message as (opcode, bytes): 1 = text, 2 = binary. None when the connection ends."""
        parts, first_op = [], None
        while not self.closed:
            try:
                h = self._read(2)
                if not h:
                    break
                fin, op, masked, n = h[0] & 0x80, h[0] & 0x0F, h[1] & 0x80, h[1] & 0x7F
                if n == 126:
                    n = struct.unpack(">H", self._read(2))[0]
                elif n == 127:
                    n = struct.unpack(">Q", self._read(8))[0]
                if n > MAX_FRAME:
                    break
                key = self._read(4) if masked else None
                data = self._read(n) if n else b""
                if data is None:
                    break
                if key:
                    k = (key * (n // 4 + 1))[:n]
                    data = (int.from_bytes(data, "big") ^ int.from_bytes(k, "big")).to_bytes(n, "big")
            except (OSError, ValueError, struct.error, TypeError):
                break
            if op == 8:                       # close
                self.close()
                return None
            if op == 9:                       # ping -> pong
                self.send(data, 10)
                continue
            if op == 10:
                continue
            if op != 0:
                first_op = op
            parts.append(data)
            if fin:
                return first_op or 2, b"".join(parts)
        self.close()
        return None

    def send(self, data, op=2):
        if isinstance(data, str):
            data, op = data.encode(), (1 if op == 2 else op)
        n = len(data)
        head = bytes([0x80 | op])
        mbit = 0x80 if self.mask else 0
        if n < 126:
            head += bytes([mbit | n])
        elif n < 65536:
            head += bytes([mbit | 126]) + struct.pack(">H", n)
        else:
            head += bytes([mbit | 127]) + struct.pack(">Q", n)
        if self.mask:
            key = secrets.token_bytes(4)
            k = (key * (n // 4 + 1))[:n]
            data = key + ((int.from_bytes(data, "big") ^ int.from_bytes(k, "big")).to_bytes(n, "big") if n else b"")
        try:
            with self.wlock:
                self.s.sendall(head + data)
            return True
        except OSError:
            self.close()
            return False

    def close(self):
        if self.closed:
            return
        self.closed = True
        try:
            with self.wlock:
                self.s.sendall(b"\x88\x00")
        except OSError:
            pass
        try:
            self.s.shutdown(2)
        except OSError:
            pass


class TermHub:
    """Pairs browser terminals with the agent and keeps the agent's status (profiles, last poll)."""

    def __init__(self):
        self.cv = threading.Condition()
        self.pending = []           # requests the agent has not taken yet
        self.slots = {}             # sid -> {"ev": Event, "ws": agent WebSocket, "done": Event}
        self.active = 0
        self.agent_seen = 0.0
        self.profiles = []
        self.agent_host = ""

    def status(self):
        with self.cv:
            return {"agent": time.time() - self.agent_seen < AGENT_ALIVE, "host": self.agent_host,
                    "profiles": list(self.profiles), "sessions": self.active, "max_sessions": MAX_SESSIONS}

    # ---- agent side
    def poll(self, info, timeout=25.0):
        with self.cv:
            self.agent_seen = time.time()
            self.profiles = [str(p)[:40] for p in (info.get("profiles") or [])][:20]
            self.agent_host = str(info.get("host") or "")[:60]
            self.cv.wait_for(lambda: self.pending, timeout)
            out, self.pending = self.pending, []
            self.agent_seen = time.time()
            return out

    def attach(self, sid, ws):
        """The agent connected the session sid: hand its socket to the browser and wait until it ends."""
        with self.cv:
            slot = self.slots.get(sid)
            if not slot or slot["ws"] is not None:
                return False
            slot["ws"] = ws
        slot["ev"].set()
        slot["done"].wait()
        return True

    # ---- browser side
    def run(self, bws, profile, cols, rows):
        """Relays one browser terminal until it closes. Runs in the browser's request thread."""
        with self.cv:
            if self.active >= MAX_SESSIONS:
                bws.send(json.dumps({"error": "too many open terminals (max. %d)" % MAX_SESSIONS}), 1)
                bws.close()
                return
            if time.time() - self.agent_seen > AGENT_ALIVE:
                bws.send(json.dumps({"error": "terminal agent not connected (journalctl -u open5gs-k3s-term)"}), 1)
                bws.close()
                return
            sid = secrets.token_hex(12)
            slot = {"ev": threading.Event(), "ws": None, "done": threading.Event()}
            self.slots[sid] = slot
            self.pending.append({"id": sid, "profile": profile, "cols": cols, "rows": rows})
            self.active += 1
            self.cv.notify_all()
        try:
            if not slot["ev"].wait(ATTACH_TIMEOUT):
                bws.send(json.dumps({"error": "the terminal agent did not answer"}), 1)
                return
            aws = slot["ws"]

            def agent_to_browser():
                while True:
                    m = aws.recv()
                    if m is None or not bws.send(m[1], m[0]):
                        break
                bws.close()

            t = threading.Thread(target=agent_to_browser, daemon=True)
            t.start()
            while True:
                m = bws.recv()
                if m is None or not aws.send(m[1], m[0]):
                    break
            aws.close()
            t.join(5)
        finally:
            bws.close()
            with self.cv:
                self.slots.pop(sid, None)
                self.pending = [p for p in self.pending if p["id"] != sid]
                self.active -= 1
            slot["done"].set()
