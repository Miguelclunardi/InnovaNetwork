# =============================================================================
#  dashboard/app/configedit.py — edição do config.env pela aba Configuração.
#
#  Segurança (o config.env é carregado com `source` pelo install.sh como root):
#    - só altera o VALOR de variáveis que já existem; nunca cria linhas livres;
#    - valores sem quebra de linha, sem $ ` " \ (aspas duplas) e sem ' (aspas simples);
#    - antes de gravar roda a mesma validação do install (validate_config);
#    - guarda backup do arquivo anterior; recusa se o arquivo mudou desde a leitura.
#  Aplicar continua sendo `sudo ./install.sh ...` feito pelo usuário.
# =============================================================================
import difflib
import hashlib
import os
import re
import subprocess
import tempfile
import time

RE_ASSIGN = re.compile(r"^([A-Z][A-Z0-9_]*)=(.*)$")
RE_ITEM = re.compile(r'^(\s*)"([^"]*)"(\s*#.*)?\s*$')
RE_DASHES = re.compile(r"^#\s*-{10,}\s*$")
SAFE_BARE = re.compile(r"^[A-Za-z0-9_.:/+@,%=-]+$")
ANSI = re.compile(r"\x1b\[[0-9;]*m")

# Variáveis cujo valor é segredo (mascarado na tela até o usuário pedir para mostrar)
SECRET = {"UE_KEY", "UE_OPC", "SUBSCRIBERS", "DASHBOARD_PASSWORD"}

# Qual comando aplica cada variável
DASHBOARD_VARS = re.compile(r"^(DASHBOARD_|GNB_METRICS_URL$|GNB_NAME$|GNB_LOG_|ENERGY_)")
TEST_VARS = re.compile(r"^TEST_")
FULL_VARS = re.compile(r"^(K3S_|HELM_VERSION$|NODE_|STABLE_|ENV_PROFILE$|INSTALL_DIR$|GRADIANT_|CONFIGURE_|"
                       r"KUBECONFIG_USER$|SHELL_EXTRAS$|AUTO_INSTALL_MODULES|K8S_NAMESPACE$|OPEN5GS_RELEASE$|"
                       r"UERANSIM_RELEASE$|MULTUS_)")


class ConfigError(Exception):
    pass


def sha(text):
    return hashlib.sha256(text.encode()).hexdigest()


def _scalar_token(raw):
    """Separa o valor do comentário: retorna (valor, estilo, resto)."""
    if raw.startswith('"'):
        end = raw.find('"', 1)
        if end < 0:
            raise ConfigError("aspas não fechadas")
        return raw[1:end], "dq", raw[end + 1:]
    if raw.startswith("'"):
        end = raw.find("'", 1)
        if end < 0:
            raise ConfigError("aspas não fechadas")
        return raw[1:end], "sq", raw[end + 1:]
    m = re.match(r"(\S*)(.*)$", raw)
    return m.group(1), "bare", m.group(2)


def parse(text):
    """config.env -> lista de seções com variáveis (preserva posição de cada uma)."""
    lines = text.split("\n")
    sections = [{"title": "Geral", "vars": []}]
    doc = []
    i = 0
    while i < len(lines):
        ln = lines[i]
        s = ln.strip()
        # Cabeçalho de seção: "# ----" / "#  Título" (/ mais linhas) / "# ----"
        if RE_DASHES.match(s):
            j = i + 1
            title_lines = []
            while j < len(lines) and lines[j].startswith("#") and not RE_DASHES.match(lines[j].strip()):
                title_lines.append(lines[j].lstrip("#").strip())
                j += 1
            if j < len(lines) and RE_DASHES.match(lines[j].strip()) and title_lines:
                sections.append({"title": title_lines[0], "notes": " ".join(title_lines[1:]), "vars": []})
                doc = []
                i = j + 1
                continue
        if s.startswith("#"):
            doc.append(s.lstrip("#").strip())
            i += 1
            continue
        if not s:
            doc = []
            i += 1
            continue
        m = RE_ASSIGN.match(ln)
        if not m:
            doc = []
            i += 1
            continue
        name, raw = m.group(1), m.group(2)
        var = {"name": name, "doc": "\n".join(d for d in doc if d), "line": i, "secret": name in SECRET}
        doc = []
        if raw.startswith("("):
            var["kind"] = "array"
            close = raw.find(")")
            if close >= 0:   # NAME=( "a" "b" )  # comentário
                var["items"] = re.findall(r'"([^"]*)"', raw[1:close])
                var["comment"] = raw[close + 1:].strip()
                var["end"] = i
                var["inline"] = True
            else:
                items, extra = [], []
                j = i + 1
                while j < len(lines) and not lines[j].strip().startswith(")"):
                    im = RE_ITEM.match(lines[j])
                    if im:
                        items.append(im.group(2))
                    elif lines[j].strip():
                        extra.append(lines[j].strip())
                    j += 1
                if j >= len(lines):
                    raise ConfigError("%s=( sem ')' de fechamento" % name)
                var.update(items=items, comment="", end=j, inline=False, notes_in_array=extra)
                i = j
        else:
            val, style, rest = _scalar_token(raw)
            var.update(kind="scalar", value=val, style=style, comment=rest.strip())
            if style == "bare" and val.lower() in ("true", "false"):
                var["kind"] = "bool"
        sections[-1]["vars"].append(var)
        i += 1
    return [s for s in sections if s["vars"]]


def _check_value(name, v, style):
    if not isinstance(v, str):
        raise ConfigError("%s: valor deve ser texto" % name)
    if any(c in v for c in "\n\r\x00") or any(ord(c) < 32 and c != "\t" for c in v):
        raise ConfigError("%s: quebra de linha ou caractere de controle não é permitido" % name)
    if len(v) > 500:
        raise ConfigError("%s: valor longo demais" % name)
    if style == "sq":
        if "'" in v:
            raise ConfigError("%s: aspas simples não são permitidas neste campo" % name)
    else:
        bad = [c for c in '"$`\\' if c in v]
        if bad:
            raise ConfigError("%s: caracteres não permitidos: %s" % (name, " ".join(bad)))


def _token(v, style):
    if style == "sq":
        return "'%s'" % v
    if style == "bare" and v and SAFE_BARE.match(v):
        return v
    return '"%s"' % v


def apply_changes(text, changes):
    """Aplica {NOME: valor | [itens]} ao texto e devolve o novo texto."""
    if not isinstance(changes, dict) or not changes:
        raise ConfigError("nenhuma alteração")
    by_name = {v["name"]: v for s in parse(text) for v in s["vars"]}
    lines = text.split("\n")
    # Da última linha para a primeira, para os índices continuarem válidos
    for name in sorted(changes, key=lambda n: -by_name[n]["line"] if n in by_name else 0):
        if name not in by_name:
            raise ConfigError("variável desconhecida: %s (a interface só altera variáveis existentes)" % name)
        var, new = by_name[name], changes[name]
        if var["kind"] in ("scalar", "bool"):
            if var["kind"] == "bool" and new not in ("true", "false"):
                raise ConfigError("%s: use true ou false" % name)
            _check_value(name, new, var["style"])
            old = lines[var["line"]]
            prefix = name + "="
            raw = old[len(prefix):]
            _, _, rest = _scalar_token(raw)
            newline = prefix + _token(new, var["style"])
            if rest.strip():
                col = len(old) - len(rest.lstrip())   # mantém a coluna do comentário
                newline = newline.ljust(max(col, len(newline) + 1)) + rest.strip()
            lines[var["line"]] = newline
        else:
            if not isinstance(new, list):
                raise ConfigError("%s: lista esperada" % name)
            items = [x.strip() for x in new if isinstance(x, str) and x.strip()]
            for x in items:
                _check_value(name, x, "dq")
            if var["inline"]:
                body = " ".join('"%s"' % x for x in items)
                newline = "%s=(%s)" % (name, (" " + body + " ") if body else "")
                if var["comment"]:
                    old = lines[var["line"]]
                    col = old.find(var["comment"])
                    newline = newline.ljust(max(col, len(newline) + 1)) + var["comment"]
                block = [newline]
            else:
                # comentários dentro da lista são mantidos no topo; o comentário de cada item é preservado
                old_comments = {}
                for k in range(var["line"] + 1, var["end"]):
                    im = RE_ITEM.match(lines[k])
                    if im and im.group(3):
                        old_comments[im.group(2)] = im.group(3).strip()
                block = [lines[var["line"]]]
                block += ["  " + n for n in var.get("notes_in_array", [])]
                for x in items:
                    c = old_comments.get(x)
                    block.append('  "%s"%s' % (x, ("   " + c) if c else ""))
                block.append(lines[var["end"]])
            lines[var["line"]:var["end"] + 1] = block
    return "\n".join(lines)


def diff(old, new):
    return "".join(difflib.unified_diff(old.splitlines(True), new.splitlines(True),
                                        "config.env (atual)", "config.env (novo)", n=2))


def changed_vars(old, new):
    a = {v["name"]: (v.get("value"), tuple(v.get("items", []))) for s in parse(old) for v in s["vars"]}
    b = {v["name"]: (v.get("value"), tuple(v.get("items", []))) for s in parse(new) for v in s["vars"]}
    return sorted(n for n in set(a) | set(b) if a.get(n) != b.get(n))


def impact(names):
    """Comando necessário para aplicar as variáveis alteradas."""
    if not names:
        return {"level": "none", "command": "", "text": "Nada para aplicar."}
    if all(TEST_VARS.match(n) for n in names):
        return {"level": "test", "command": "./test.sh",
                "text": "Só configurações do teste: valem no próximo ./test.sh, sem reinstalar."}
    if any(FULL_VARS.match(n) for n in names):
        return {"level": "full", "command": "sudo ./install.sh",
                "text": "Mexe no k3s/host: rode a instalação completa. Pode reiniciar o cluster — faça sem usuários na rede."}
    if all(DASHBOARD_VARS.match(n) or TEST_VARS.match(n) for n in names):
        return {"level": "dashboard", "command": "sudo ./install.sh --dashboard-only",
                "text": "Só o painel: core e gNB não são tocados."}
    return {"level": "deploy", "command": "sudo ./install.sh --deploy-only",
            "text": "Mexe no core/UERANSIM: os NFs afetados reiniciam (UEs reconectam). Faça sem usuários testando."}


def validate(project_dir, text, timeout=30):
    """Roda load_config + validate_config do install sobre o texto candidato."""
    lib = os.path.join(project_dir, "scripts", "lib", "common.sh")
    if not os.path.isfile(lib):
        return {"ok": None, "output": "validação indisponível (scripts/lib/common.sh não encontrado)"}
    fd, path = tempfile.mkstemp(prefix="cand-", suffix=".env")
    try:
        with os.fdopen(fd, "w") as f:
            f.write(text)
        script = ('set -Eeuo pipefail; source "$1"; CONFIG="$2"; '
                  'die() { echo "[erro] $*"; exit 1; }; load_config; validate_config; echo "[ok] config válido"')
        p = subprocess.run(["bash", "-c", script, "validar", lib, path], capture_output=True, text=True,
                           timeout=timeout, env={"PATH": "/usr/local/bin:/usr/bin:/bin", "HOME": "/tmp"})
        out = ANSI.sub("", (p.stdout + p.stderr)).replace(path, "config.env").strip()
        return {"ok": p.returncode == 0, "output": out[-4000:]}
    except subprocess.TimeoutExpired:
        return {"ok": False, "output": "validação demorou demais"}
    finally:
        os.unlink(path)


class ConfigStore:
    """Lê/grava o config.env com backup e checagem de concorrência."""

    def __init__(self, path, view_path, project_dir, backup_dir, keep=50):
        self.path = path            # arquivo montado para escrita
        self.view_path = view_path  # mesmo arquivo visto pelo diretório do projeto (sempre o atual)
        self.project_dir = project_dir
        self.backup_dir = backup_dir
        self.keep = keep

    def read(self):
        with open(self.view_path) as f:
            text = f.read()
        return text, sha(text)

    def _stale(self):
        """True se o arquivo do host foi substituído (novo inode) e a montagem de escrita ficou velha."""
        try:
            with open(self.path) as a, open(self.view_path) as b:
                return a.read() != b.read()
        except OSError:
            return True

    def backups(self):
        try:
            names = sorted((n for n in os.listdir(self.backup_dir) if n.startswith("config.env.")), reverse=True)
        except OSError:
            return []
        return [{"name": n, "size": os.path.getsize(os.path.join(self.backup_dir, n))} for n in names[: self.keep]]

    def backup_text(self, name):
        if not re.match(r"^config\.env\.\d{8}-\d{6}$", name or ""):
            raise ConfigError("backup inválido")
        with open(os.path.join(self.backup_dir, name)) as f:
            return f.read()

    def write(self, new_text, expected_hash):
        cur, h = self.read()
        if h != expected_hash:
            raise ConfigError("o config.env mudou desde que você abriu a página (alguém editou no servidor). Recarregue.")
        if self._stale():
            raise ConfigError("o config.env foi substituído no servidor depois que o painel subiu (ex.: git pull ou "
                              "editor que recria o arquivo). Rode 'sudo ./install.sh --dashboard-only' para o painel "
                              "enxergar o arquivo novo, e tente de novo.")
        os.makedirs(self.backup_dir, exist_ok=True)
        name = "config.env." + time.strftime("%Y%m%d-%H%M%S")
        with open(os.path.join(self.backup_dir, name), "w") as f:
            f.write(cur)
        for old in self.backups()[self.keep:]:
            try:
                os.unlink(os.path.join(self.backup_dir, old["name"]))
            except OSError:
                pass
        # Escrita no mesmo arquivo (a montagem é de arquivo: não dá para trocar por rename)
        with open(self.path, "r+") as f:
            f.seek(0)
            f.write(new_text)
            f.truncate()
            f.flush()
            os.fsync(f.fileno())
        return name
