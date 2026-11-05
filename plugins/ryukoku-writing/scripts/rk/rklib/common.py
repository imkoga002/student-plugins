"""Shared helpers for the project tools of ryukoku-writing (standard library only)."""
import datetime
import hashlib
import json
import os
import re
import sys

MARKER = os.path.join(".ryukoku", "config.yml")


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
                m = re.match(r"^([A-Za-z_][A-Za-z0-9_]*)\s*:\s*(.*)$", line.rstrip("\n"))
                if m:
                    out[m.group(1)] = _unquote(m.group(2))
    except OSError:
        pass
    return out


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
