"""Shared helpers for the project tools of ryukoku-writing (standard library only)."""
import datetime
import hashlib
import json
import os
import re
import sys

MARKER = os.path.join(".ryukoku", "config.yml")


def _human_commands():
    p = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "human-commands.txt")
    try:
        with open(p, encoding="utf-8") as f:
            return tuple(ln.strip() for ln in f if ln.strip() and not ln.startswith("#"))
    except OSError:  # fail closed: the list as shipped
        return ("setup", "confirm", "apply", "verify", "style", "resolve", "signoff", "disclose", "changes", "optout",
                "import-docx", "sign", "trust", "update-tools", "notebook", "unattributed", "review")


HUMAN_COMMANDS = _human_commands()


class RkError(Exception):
    """A user-facing error: printed without a traceback."""


def find_project(start=None):
    d = os.path.abspath(start or os.getcwd())
    while True:
        if os.path.isfile(os.path.join(d, MARKER)):
            return d
        parent = os.path.dirname(d)
        if parent == d:
            raise RkError("プロジェクトの目印 .ryukoku/config.yml が見つからない。プロジェクトのフォルダで実行すること。"
                          " / Project marker .ryukoku/config.yml not found; run inside the project folder.")
        d = parent


def _unquote(v):
    v = v.strip()
    if v[:1] in ("\"", "'"):
        end = v.find(v[0], 1)
        if end > 0 and not v[end + 1:].strip() or (end > 0 and re.match(r"^\s+#", v[end + 1:])):
            return v[1:end]  # a quoted value, optionally followed by a comment
    if len(v) >= 2 and v[0] == v[-1] and v[0] in "\"'":
        return v[1:-1]
    return re.sub(r"\s+#.*$", "", v).strip()


def load_config(proj):
    """Top-level 'key: value' pairs of .ryukoku/config.yml (comments ignored)."""
    out = {}
    try:
        with open(os.path.join(proj, MARKER), encoding="utf-8") as f:
            for line in f:
                if not line.strip() or line.lstrip().startswith("#") or line[0].isspace():
                    continue
                m = re.match(r"^([A-Za-z_][A-Za-z0-9_]*)[ \t]*:[ \t]*(.*)$", line.rstrip("\n"))
                if m and m.group(1) not in out:  # the first line that sets a key counts (as the hooks read it)
                    out[m.group(1)] = _unquote(m.group(2))
    except (OSError, UnicodeDecodeError):
        pass
    return out


POLICIES = ("allowed", "limited", "prohibited", "unknown")


# The one rule for the ai_policy line, shared by the hooks (hookcore.py cfgcheck; lib.sh cfg_policy_bash is the same
# rule for a computer without Python 3): the file is UTF-8, exactly one line starts with "ai_policy" followed by ":"
# (indented or not), and that line is the key, optional spaces or tabs, one of the four lower-case values (optionally
# in matching quotes), optional spaces or tabs, an optional "# comment", and an optional CR. Anything else on that line
# (a no-break space, a vertical tab, a second word, upper case) makes the settings unreadable: the hooks deny
# manuscript writes until it is fixed.
POLICY_LINE = re.compile(r"^ai_policy[ \t]*:[ \t]*([\"']?)(allowed|limited|prohibited|unknown)\1[ \t]*(?:#[^\r\n]*)?\r?$")
POLICY_KEY = re.compile(r"^[ \t]*ai_policy[ \t]*:")


def config_problems(proj):
    """Why .ryukoku/config.yml cannot be trusted as written: missing or unreadable (not UTF-8), a key set on more than
    one line, or the ai_policy line not in the one accepted form (POLICY_LINE). The hooks then treat the policy as
    unreadable and deny manuscript writes."""
    p = os.path.join(proj, MARKER)
    try:
        with open(p, "rb") as f:
            raw = f.read()
        text = raw.decode("utf-8")
    except (OSError, UnicodeDecodeError) as e:
        return ["%s を読めない(%s。UTF-8 で保存する) / cannot read it (%s; save it as UTF-8)" % (MARKER, type(e).__name__, type(e).__name__)]
    lines = text.split("\n")
    seen, out = {}, []
    for ln in lines:
        m = re.match(r"^([A-Za-z_][A-Za-z0-9_]*)[ \t]*:", ln)
        if m:
            seen[m.group(1)] = seen.get(m.group(1), 0) + 1
    for k, n in sorted(seen.items()):
        if n > 1 and k != "ai_policy":
            out.append("%s が %d 行ある(どちらが正しいか分からない) / %s is set on %d lines" % (k, n, k, n))
    pl = [ln for ln in lines if POLICY_KEY.match(ln)]
    if not pl:
        out.append("ai_policy の行がない / no ai_policy line")
    elif len(pl) > 1:
        out.append("ai_policy が %d 行ある(どちらが正しいか分からない) / ai_policy is set on %d lines" % (len(pl), len(pl)))
    elif not POLICY_LINE.match(pl[0]):
        v = pl[0].split(":", 1)[1].strip(" \t\r")
        out.append("ai_policy の行 %r は「ai_policy: allowed」の形(値は allowed・limited・prohibited・unknown の小文字、余分な文字なし)ではない / "
                   "the ai_policy line %r is not of the form 'ai_policy: allowed' (one of the four lower-case values, nothing else)" % (v, v))
    try:
        from . import msguard
        ids = msguard.config_detections_open(proj)
    except Exception:  # noqa: BLE001 - the check itself must not open the gate
        ids = []
    if ids:
        out.append("AI のツールの実行中に .ryukoku/config.yml が変わった(検知 %s)。学生が ./rk changes で判断するまで、設定は信用しない / "
                   ".ryukoku/config.yml changed during an AI tool call (detection %s); the settings are not trusted until you decide with ./rk changes"
                   % (", ".join(ids[:3]), ", ".join(ids[:3])))
    return out


def course_policy(proj):
    """The course AI policy as the hooks decide it: one of the four values, or 'unreadable' when config_problems
    finds anything."""
    if config_problems(proj):
        return "unreadable"
    with open(os.path.join(proj, MARKER), encoding="utf-8") as f:
        text = f.read()
    for ln in text.split("\n"):
        m = POLICY_LINE.match(ln)
        if m:
            return m.group(2)
    return "unreadable"


def set_config_value(proj, key, value):
    """Replace (or append) a top-level scalar in .ryukoku/config.yml, keeping comments."""
    path = os.path.join(proj, MARKER)
    with open(path, encoding="utf-8") as f:
        lines = f.read().splitlines(True)
    pat = re.compile(r"^%s\s*:" % re.escape(key))
    rendered = "%s: %s" % (key, value)
    for i, line in enumerate(lines):
        if pat.match(line):
            comment = ""
            m = re.search(r"\s+#.*$", line.rstrip("\n"))
            if m and not re.match(r"^%s\s*:\s*[\"']" % re.escape(key), line):
                comment = m.group(0)
            lines[i] = rendered + comment + "\n"
            break
    else:
        lines.append(rendered + "\n")
    with open(path, "w", encoding="utf-8") as f:
        f.writelines(lines)


def feedback_lang(proj):
    cfg = load_config(proj)
    lang = cfg.get("feedback_lang") or cfg.get("manuscript_lang") or "ja"
    return "en" if lang.lower().startswith("en") else "ja"


def tr(lang, ja, en):
    return en if lang == "en" else ja


def now_iso():
    return datetime.datetime.now().astimezone().strftime("%Y-%m-%dT%H:%M:%S%z")


def today():
    return datetime.date.today().isoformat()


def sha256_bytes(b):
    return hashlib.sha256(b).hexdigest()


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def canonical(obj):
    return json.dumps(obj, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def subject_hash(obj):
    return sha256_bytes(canonical(obj).encode("utf-8"))


def read_jsonl(path):
    out = []
    if not os.path.exists(path):
        return out
    with open(path, encoding="utf-8") as f:
        for ln, line in enumerate(f, 1):
            if line.strip():
                try:
                    out.append(json.loads(line))
                except ValueError:
                    raise RkError("%s %d 行目が JSON でない / line %d is not JSON" % (path, ln, ln))
    return out


def _written_path(proj, relp):
    return os.path.join(state_dir(proj), "written", relp.replace("\\", "/").replace("/", "__") + ".txt")


def note_written(proj, relp, lines):
    """Remember (outside the project) the hash of every line the plugin's own code appends to an append-only record.
    msguard reports any line that appears in such a record during an AI tool call without being noted here (a line
    appended by printf, an editor or a foreign script)."""
    try:
        p = _written_path(proj, relp)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "a", encoding="utf-8") as f:
            for ln in lines:
                f.write(sha256_bytes(ln.rstrip("\r\n").encode("utf-8")) + "\n")
    except OSError:
        pass


def written_hashes(proj, relp):
    try:
        with open(_written_path(proj, relp), encoding="utf-8") as f:
            return {x.strip() for x in f if x.strip()}
    except OSError:
        return set()


def append_jsonl(path, rec):
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")


def rel(proj, path):
    return os.path.relpath(os.path.abspath(path), proj).replace(os.sep, "/")


# Hardened git for the plugin's own calls: run only against the project's own <proj>/.git
# directory, name GIT_DIR / GIT_WORK_TREE explicitly, and switch off the config entries that let git run code
# (a planted core.fsmonitor / pager / sshCommand / [diff].external / [filter].process / core.hooksPath).
GIT_SAFE_FLAGS = ["-c", "core.fsmonitor=false", "-c", "core.hooksPath=/dev/null", "-c", "core.pager=cat",
                  "-c", "core.sshCommand=false", "-c", "core.editor=false", "-c", "diff.external=",
                  "-c", "protocol.ext.allow=never", "-c", "uploadpack.packObjectsHook="]


def git_repo_ok(proj):
    """True when PROJ has its own .git DIRECTORY (not a gitdir file, not a bare dir elsewhere)."""
    return os.path.isdir(os.path.join(proj, ".git"))


def run_git(proj, args, timeout=60):
    """subprocess.run of a read-only git command against PROJ's own repo, with code-executing config disabled.
    Returns the CompletedProcess, or None when PROJ has no .git directory."""
    import subprocess
    if not git_repo_ok(proj):
        return None
    env = dict(os.environ, GIT_DIR=os.path.join(proj, ".git"), GIT_WORK_TREE=proj, GIT_CONFIG_NOSYSTEM="1",
               GIT_CONFIG_GLOBAL=os.devnull, GIT_TERMINAL_PROMPT="0", GIT_OPTIONAL_LOCKS="0")
    try:
        return subprocess.run(["git"] + GIT_SAFE_FLAGS + list(args), cwd=proj, env=env,
                              capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.SubprocessError):
        return None


def safe_rel(proj, relpath, must_start=None):
    """Resolve RELPATH inside PROJ; refuse '..' escapes and (optionally) paths outside MUST_START."""
    full = os.path.realpath(os.path.join(proj, relpath))
    root = os.path.realpath(proj)
    if not (full == root or full.startswith(root + os.sep)):
        raise RkError("プロジェクトの外のパスは扱わない: %s / path outside the project" % relpath)
    r = os.path.relpath(full, root).replace(os.sep, "/")
    if must_start and not (r == must_start.rstrip("/") or r.startswith(must_start)):
        raise RkError("%s の外のパスは扱わない: %s" % (must_start, relpath))
    return full, r


def state_home():
    """Per-user folder outside every project: the folder-mode trust copy of the signers and the change-detection
    baseline live here (not in the project, where an AI tool could rewrite them together with what they guard).
    RK_STATE_HOME overrides it (tests). ${CLAUDE_PLUGIN_DATA} is not used because the student's terminal and the
    AI's Bash do not see that variable (development observation, DESIGN.md (e))."""
    d = os.environ.get("RK_STATE_HOME")
    if not d:
        d = os.path.join(os.path.expanduser("~"), ".ryukoku-writing")
    return d


def project_id(proj):
    pid = load_config(proj).get("project_id") or ""
    if re.fullmatch(r"[A-Za-z0-9_-]{6,64}", pid):
        return pid
    known = known_projects().get(os.path.realpath(proj))
    if known:
        return known  # the marker is missing or unreadable: keep using the same state
    return "p" + sha256_bytes(os.path.realpath(proj).encode("utf-8"))[:16]


REGISTRY = "projects.tsv"


def known_projects():
    """{real path: project id} of the projects this user has used (state_home()/projects.tsv). The hooks keep
    guarding a registered folder even when its marker .ryukoku/config.yml is moved away."""
    out = {}
    try:
        with open(os.path.join(state_home(), REGISTRY), encoding="utf-8") as f:
            for line in f:
                parts = line.rstrip("\n").split("\t")
                if len(parts) == 2 and parts[0]:
                    out[parts[0]] = parts[1]
    except OSError:
        pass
    return out


def register_project(proj):
    pid = load_config(proj).get("project_id") or ""
    if not re.fullmatch(r"[A-Za-z0-9_-]{6,64}", pid):
        return
    real = os.path.realpath(proj)
    known = known_projects()
    if known.get(real) == pid:
        return
    known[real] = pid
    try:
        atomic_write(os.path.join(state_home(), REGISTRY),
                     "".join("%s\t%s\n" % (k, v) for k, v in sorted(known.items()) if os.path.isdir(k)))
    except OSError:
        pass


def state_dir(proj):
    d = os.path.join(state_home(), "state", project_id(proj))
    os.makedirs(d, exist_ok=True)
    return d


def trust_path(proj):
    return os.path.join(state_home(), "trust", project_id(proj) + ".json")


def atomic_write(path, text):
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    tmp = path + ".tmp%d" % os.getpid()
    with open(tmp, "w", encoding="utf-8", newline="") as f:
        f.write(text)
    os.replace(tmp, path)


class FileLock(object):
    """Tiny cross-platform lock (O_EXCL); a lock older than STALE seconds is taken over."""
    STALE = 15.0

    def __init__(self, path, timeout=10.0):
        self.path, self.timeout, self.fd = path, timeout, None

    def __enter__(self):
        import time
        os.makedirs(os.path.dirname(os.path.abspath(self.path)), exist_ok=True)
        t0 = time.time()
        while True:
            try:
                self.fd = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                return self
            except FileExistsError:
                try:
                    if time.time() - os.path.getmtime(self.path) > self.STALE:
                        os.remove(self.path)
                        continue
                except OSError:
                    continue
                if time.time() - t0 > self.timeout:
                    raise RkError("ロックを取れない: %s" % self.path)
                time.sleep(0.05)

    def __exit__(self, *a):
        try:
            os.close(self.fd)
        finally:
            try:
                os.remove(self.path)
            except OSError:
                pass


class ExclusiveLock(object):
    """An exclusive lock held for a whole read-modify-write: fcntl.flock on POSIX, msvcrt.locking on Windows (both
    are released by the system if the process dies, so no stale-lock takeover is needed); FileLock (O_EXCL) where
    neither exists. Waits up to TIMEOUT seconds, then raises RkError (the caller fails closed)."""

    def __init__(self, path, timeout=15.0):
        self.path, self.timeout, self.f, self.fallback = path, timeout, None, None

    def __enter__(self):
        import time
        os.makedirs(os.path.dirname(os.path.abspath(self.path)), exist_ok=True)
        try:
            import fcntl
        except ImportError:
            fcntl = None
        try:
            import msvcrt
        except ImportError:
            msvcrt = None
        if fcntl is None and msvcrt is None:
            self.fallback = FileLock(self.path + ".x", self.timeout)
            self.fallback.__enter__()
            return self
        self.f = open(self.path, "a+b")
        t0 = time.time()
        while True:
            try:
                if fcntl is not None:
                    fcntl.flock(self.f.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                else:
                    self.f.seek(0)
                    msvcrt.locking(self.f.fileno(), msvcrt.LK_NBLCK, 1)
                return self
            except OSError:
                if time.time() - t0 > self.timeout:
                    self.f.close()
                    raise RkError("ロックを取れない: %s" % self.path)
                time.sleep(0.02)

    def __exit__(self, *a):
        if self.fallback is not None:
            return self.fallback.__exit__(*a)
        try:
            try:
                import fcntl
                fcntl.flock(self.f.fileno(), fcntl.LOCK_UN)
            except ImportError:
                import msvcrt
                self.f.seek(0)
                msvcrt.locking(self.f.fileno(), msvcrt.LK_UNLCK, 1)
        except OSError:
            pass
        finally:
            self.f.close()


# ---------------------------------------------------------------- where the plugin is
ROOT_RECORD = "plugin-root.log"


def plugin_version(root):
    try:
        with open(os.path.join(root, ".claude-plugin", "plugin.json"), encoding="utf-8") as f:
            return str(json.load(f).get("version") or "?")
    except (OSError, ValueError):
        return "?"


def manifest_digest(root):
    try:
        return sha256_file(os.path.join(root, "scripts", "rk", "MANIFEST.sha256"))
    except OSError:
        return ""


def root_records():
    out = []
    try:
        with open(os.path.join(state_home(), ROOT_RECORD), encoding="utf-8") as f:
            for line in f:
                try:
                    out.append(json.loads(line))
                except ValueError:
                    continue
    except OSError:
        pass
    return out


def record_plugin_root(root, source=""):
    """Called by the SessionStart hook (with CLAUDE_PLUGIN_ROOT from Claude Code) and by init-project.sh: write
    ~/.ryukoku-writing/plugin-root for the ./rk launchers and append {root, manifest digest, version} to
    plugin-root.log. Returns a problem text when plugin-root had been changed since the last record (the launchers
    would have started other code; the caller logs it as a detection), else ''."""
    if not re.match(r"^[A-Za-z]:[\\/]", root):  # a Windows path given on another OS (tests) is kept as it is
        root = os.path.realpath(root)
    p = os.path.join(state_home(), "plugin-root")
    prob = ""
    try:
        old = open(p, encoding="utf-8").read().strip() if os.path.exists(p) else ""
    except OSError:
        old = ""
    recs = root_records()
    last = recs[-1] if recs else None
    if old and last and os.path.realpath(old) != os.path.realpath(last.get("root", "")):
        prob = ("~/.ryukoku-writing/plugin-root(./rk の行き先)が、Claude Code の記録の外で書き換えられていた: %s"
                " / the ./rk launcher target was changed outside Claude Code: %s" % (old, old))
    if old != root:
        atomic_write(p, root + "\n")
    rec = {"at": now_iso(), "root": root, "manifest": manifest_digest(root), "version": plugin_version(root),
           "by": source[:40]}
    if not last or any(last.get(k) != rec[k] for k in ("root", "manifest", "version")) or prob:
        append_jsonl(os.path.join(state_home(), ROOT_RECORD), rec)
    return prob


def check_running_code(here):
    """(ok, lines) before any passphrase prompt: the running plugin must be the one Claude Code last recorded
    (location and MANIFEST digest), and its files must match its MANIFEST."""
    here = os.path.realpath(here)
    lines = []
    recs = root_records()
    last = recs[-1] if recs else None
    ok = True
    if not last:
        lines.append(("Claude Code が記録した Plugin の場所がない(この PC で Claude Code をプロジェクトのフォルダで一度開くか、"
                      "/start で初期化してから実行する)",
                      "No plugin location recorded by Claude Code (open Claude Code in the project folder once, or "
                      "initialise with /start, then run this again)"))
        return False, lines
    if os.path.realpath(last.get("root", "")) != here:
        ok = False
        lines.append(("動いているコード(%s)が、Claude Code が最後に記録した Plugin の場所(%s)と違う" % (here, last.get("root")),
                      "The running code (%s) is not where Claude Code last recorded the plugin (%s)" % (here, last.get("root"))))
    if last.get("manifest") and last.get("manifest") != manifest_digest(here):
        ok = False
        lines.append(("動いているコードの一覧(MANIFEST)が、Claude Code が記録したものと違う",
                      "The running code's MANIFEST differs from the one Claude Code recorded"))
    return ok, lines


def is_inside(child, parent):
    c, p = os.path.realpath(child), os.path.realpath(parent)
    return c == p or c.startswith(p.rstrip(os.sep) + os.sep)


def color_enabled(stream=None):
    stream = stream or sys.stdout
    return stream.isatty() and not os.environ.get("NO_COLOR")


DOC_EXT = (".md", ".markdown", ".tex", ".txt")


def manuscript_files(proj):
    """Absolute paths of the manuscript files (manuscript/**, no dot files), sorted."""
    out = []
    base = os.path.join(proj, "manuscript")
    for dp, dns, fns in os.walk(base):
        dns[:] = sorted(d for d in dns if not d.startswith("."))
        for fn in sorted(fns):
            if fn.endswith(DOC_EXT) and not fn.startswith("."):
                out.append(os.path.join(dp, fn))
    return sorted(out)


def manuscript_rels(proj):
    return [rel(proj, p) for p in manuscript_files(proj)]


def read_text(path):
    with open(path, encoding="utf-8") as f:
        return f.read()
