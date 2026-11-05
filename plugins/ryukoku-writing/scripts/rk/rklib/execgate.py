"""execgate - which shell commands may run without asking the student.

The root cause of the passphrase hijack and of erasing the detection layer is that the AI can make the student's
computer run code it wrote; that code can do anything the student can. A denylist of dangerous shapes was bypassed
by many simple forms (find -exec, cp then run, PYTHONPATH, BASH_ENV, a comment before a newline, ...). This module
is therefore an ALLOW-list. A command runs without asking only when every part of it is one of:

  (a) the plugin's own code: python3/python/py (bare name, only harmless flags) or bash/sh running a file whose real
      path is inside the installed plugin (CLAUDE_PLUGIN_ROOT of the hook), or the project's copy tools/rk/... when
      EVERY file of tools/rk matches the plugin's MANIFEST by content hash; ./rk when it is byte-identical to the
      shipped launcher and ~/.ryukoku-writing/plugin-root points at the installed plugin. No environment-variable
      assignment may precede it. The decision never uses a file's base name.
  (b) a fixed table of read-only commands with checked arguments (READ_ONLY): ls, cat, head, tail, wc, grep, rg,
      stat, pwd, diff, sort, uniq, cut, find (without -exec/-ok/-delete/-fprint), git status/log/diff/show/blame/
      ls-files/rev-parse (no -c, --exec-path, --git-dir, --work-tree, --ext-diff, --textconv, --output), echo,
      printf, true, false, test, cd, mkdir and a few more listed below. Output redirection is allowed only into the
      project (the deny layer still checks protected paths) and not into .git/, .githooks/ or .github/.
Everything else asks, naming the command ("Plugin の外のコードやコマンドを実行しうる"). A command that cannot be
analysed completely asks too: command or process substitution, backquotes, eval, source/., function definitions,
here-documents, subshells and braces, aliases, control keywords, assignments (PYTHONPATH=, BASH_ENV=, PATH=, ...),
a command name with a variable or a glob, and anything the lexer does not know. Newlines separate commands as in
bash, and a comment ends at the newline.

The scan returns findings (kind, detail):
  ("ask", text)          a part that is not on the allow-list
  ("unparsed", text)     a construct that is not analysed
  ("ai_file", path)      the command names a file the AI wrote or changed (by path or content hash): stronger wording
  ("outside_code", path) an interpreter runs code outside the plugin (it could fake the passphrase page)
  ("notebook_ok", path) / ("notebook_bad", path) / ("human", path)  the evidence notebook / a human-only command
  ("protected_write", "class<TAB>path")  a redirect or a write command reaches a path of that class (paths.classify,
                         after quotes, backslashes, globs and cd were resolved as bash would)
  ("loopback", host)      the command names a host that reaches this computer (the evidence notebook's API lives
                         there): 127.0.0.0/8 and ::1 in any spelling, 0.0.0.0, localhost names, hosts-file names
  ("unknown_target", text) a write whose target cannot be determined (a variable, an unresolvable glob, a relative
                         path after a cd the scanner could not follow)
Paths are classified after lexing, never on the raw command string: `man\\uscript/main.md` is manuscript/main.md, and
`cd m?nuscript` is followed to manuscript/ when the glob names exactly one directory (bash does the same).
"""
import glob as _glob
import hashlib
import json
import os
import re
import time

from . import paths
from .common import HUMAN_COMMANDS, state_home

AI_FILES = "ai-written.json"
HUMAN = set(HUMAN_COMMANDS)
# commands whose (non-option) arguments may be written: a protected target among them is denied, whatever else
WRITE_CMDS = {"tee", "cp", "mv", "dd", "install", "rsync", "ln", "truncate", "rm", "rmdir", "touch", "unlink", "shred",
              "patch", "split", "csplit", "chmod", "chown", "mkdir", "ed", "ex"}
INPLACE_CMDS = {"sed", "perl", "ruby"}            # write their file arguments only with -i / --in-place
OUTPUT_OPT_CMDS = {"pandoc", "curl", "wget", "iconv", "sort", "tree", "uniq"}  # write the value of -o / --output
PY_NAMES = {"python3", "python", "py"}
DIR_CMDS = {"cd", "pushd", "popd"}
KEYWORDS = {"if", "then", "elif", "else", "fi", "for", "while", "until", "do", "done", "case", "esac", "select",
            "function", "time", "!", "coproc", "[[", "]]"}
PY_FLAGS = {"-B", "-I", "-u", "-E", "-s", "-S", "-O", "-OO", "-q", "-3"}
SH_NAMES = {"bash", "sh"}
GIT_SUBS = {"status", "log", "diff", "show", "blame", "ls-files", "rev-parse"}
GIT_BAD = ("-c", "--exec-path", "--git-dir", "--work-tree", "--ext-diff", "--textconv", "--output", "--config-env",
           "--namespace", "--super-prefix", "--upload-pack", "-o")
# command -> forbidden options (prefix match on "--opt" / exact on short options)
READ_ONLY = {
    "ls": (), "cat": (), "head": (), "tail": (), "wc": (), "grep": (), "egrep": (), "fgrep": (), "stat": (),
    "pwd": (), "diff": (), "cut": (), "tr": (), "nl": (), "paste": (), "comm": (), "join": (), "column": (),
    "sha256sum": (), "sha1sum": (), "md5sum": (), "basename": (), "dirname": (), "realpath": (), "readlink": (),
    "du": (), "df": (), "tree": ("-o",), "jq": (), "od": (), "echo": (), "printf": (), "true": (), "false": (),
    "test": (), "[": (), "cd": (), "pushd": (), "popd": (), "dirs": (), "mkdir": (), "which": (), "type": (), "printenv": (), "date": ("-s", "--set"),
    "sort": ("--compress-program", "-o", "--output"), "uniq": (), "rg": ("--pre", "--pre-glob"), "file": ("-C", "-m"),
    "find": ("-exec", "-execdir", "-ok", "-okdir", "-delete", "-fprint", "-fprint0", "-fprintf", "-fls"),
    "env": (), "command": (), "git": (), "sed": ("-i", "--in-place", "-e", "--expression", "-f", "--file", "-s"),
}
VERSION_ONLY = {"pandoc", "lualatex", "xelatex", "node", "perl", "ruby", "pwsh", "mmdc", "lualatex"}  # allowed only as `<cmd> --version`
SED_PRINT = re.compile(r"^-n$|^[0-9]+p$|^[0-9]+,[0-9]+p$")
SAFE_REDIRECT_TARGETS = {"/dev/null", "/dev/stdout", "/dev/stderr"}
STARTUP_NAMES = {".bashrc", ".bash_profile", ".bash_login", ".bash_logout", ".profile", ".zshrc", ".zprofile",
                 ".zshenv", ".zlogin", ".zlogout", ".inputrc", ".kshrc", ".cshrc", ".tcshrc", ".netrc", ".envrc",
                 "config.fish", "profile.ps1", "microsoft.powershell_profile.ps1", "pyvenv.cfg"}
STARTUP_DIRS = ("/.config/fish/", "/.config/autostart/", "/library/launchagents/", "/.config/systemd/user/",
                "/.vscode/", "/.config/git/", "/site-packages/", "/.claude/", "/.ryukoku-writing/")
BIN_HINTS = ("/.local/bin/", "/bin/", "/usr/bin/", "/usr/local/bin/", "/sbin/")


def deny_write_path(raw, proj):
    """True when a WRITE to RAW must be denied outright (a .git component, a shell/boot/editor/python config, or a
    directory on PATH). These let an allow-listed command, or the student's own next terminal action, run code."""
    import os as _os
    n = raw.replace("\\", "/").lower()
    base = _os.path.basename(raw.rstrip("/")).lower()
    for part in n.split("/"):
        if part == ".git":
            return True
    if base in STARTUP_NAMES or base.endswith(".pth") or base in ("sitecustomize.py", "usercustomize.py", ".gitconfig", ".gitmodules"):
        return True
    for d in STARTUP_DIRS:
        if d in n + "/":
            return True
    for d in BIN_HINTS:
        if d in n + "/":
            return True
    return False


class Unparsed(Exception):
    pass


# ---------------------------------------------------------------- AI-written files (content hashes)
def _sha(path, limit=8 * 1024 * 1024):
    try:
        if os.path.getsize(path) > limit:
            return None
        h = hashlib.sha256()
        with open(path, "rb") as f:
            h.update(f.read())
        return h.hexdigest()
    except OSError:
        return None


def ai_files():
    try:
        with open(os.path.join(state_home(), AI_FILES), encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def add_ai_files(paths, tool=""):
    """Remember files the AI wrote or changed, by real path AND content hash (a later mv, cp, touch -d or tar
    round trip keeps the hash)."""
    paths = [os.path.realpath(p) for p in paths if p]
    if not paths:
        return
    d = ai_files()
    now = time.time()
    for p in paths:
        if os.path.isfile(p):
            d[p] = {"t": now, "tool": tool, "sha": _sha(p)}
    if len(d) > 5000:
        d = dict(sorted(d.items(), key=lambda kv: -float((kv[1] or {}).get("t", 0)))[:5000])
    p = os.path.join(state_home(), AI_FILES)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    tmp = p + ".tmp%d" % os.getpid()
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(d, f, ensure_ascii=False)
    os.replace(tmp, p)


# ---------------------------------------------------------------- a bash-like lexer (a subset; anything else is Unparsed)
def lex(cmd):
    """-> list of ("w", text, dynamic, globbed) and ("op", op). Raises Unparsed for constructs not analysed."""
    toks, i, n = [], 0, len(cmd)
    buf, dyn, glob, inword = [], False, False, False

    def end():
        nonlocal buf, dyn, glob, inword
        if inword:
            toks.append(("w", "".join(buf), dyn, glob))
        buf, dyn, glob, inword = [], False, False, False

    while i < n:
        c = cmd[i]
        if c == "\\":
            if i + 1 < n and cmd[i + 1] == "\n":
                i += 2
                continue
            if i + 1 < n:
                buf.append(cmd[i + 1])
                inword = True
                i += 2
                continue
            raise Unparsed("trailing backslash")
        if c == "'":
            j = cmd.find("'", i + 1)
            if j < 0:
                raise Unparsed("unclosed quote")
            buf.append(cmd[i + 1:j])
            inword = True
            i = j + 1
            continue
        if c == '"':
            j = i + 1
            while j < n and cmd[j] != '"':
                if cmd[j] == "\\" and j + 1 < n:
                    if cmd[j + 1] == "\n":       # a line continuation inside double quotes: bash drops both
                        j += 2
                        continue
                    if cmd[j + 1] in '$`"\\':
                        buf.append(cmd[j + 1])
                        j += 2
                        continue
                if cmd[j] == "`" or cmd.startswith("$(", j):
                    raise Unparsed("command substitution")
                if cmd[j] == "$":
                    dyn = True
                buf.append(cmd[j])
                j += 1
            if j >= n:
                raise Unparsed("unclosed quote")
            inword = True
            i = j + 1
            continue
        if c == "`":
            raise Unparsed("backquote")
        if c == "$":
            if cmd.startswith("$(", i) or cmd.startswith("$[", i):
                raise Unparsed("command substitution")
            if cmd.startswith("$'", i) or cmd.startswith('$"', i):
                raise Unparsed("ANSI-C / locale quoting")
            dyn = True
            buf.append(c)
            inword = True
            i += 1
            continue
        if c in " \t\r":
            end()
            i += 1
            continue
        if c == "\n":
            end()
            # a newline after && || | |& continues the list (bash reads the next line as the rest of it)
            if not (toks and toks[-1][0] == "op" and toks[-1][1] in ("&&", "||", "|", "|&")):
                toks.append(("op", ";"))
            i += 1
            continue
        if c == "\n" or c == ";":
            end()
            if cmd.startswith(";;", i):
                raise Unparsed("case")
            toks.append(("op", ";"))
            i += 1
            continue
        if c == "#" and not inword:
            j = cmd.find("\n", i)
            i = n if j < 0 else j  # a comment ends at the newline (the newline itself separates commands)
            continue
        if c in "|&":
            end()
            two = cmd[i:i + 2]
            if two in ("||", "&&", "|&"):
                toks.append(("op", two))
                i += 2
            elif cmd.startswith("&>", i):
                toks.append(("op", ">"))
                i += 2 + (1 if cmd.startswith("&>>", i) else 0)
            else:
                toks.append(("op", c))
                i += 1
            continue
        if c in "<>":
            fd = "".join(buf) if inword and "".join(buf).isdigit() else None
            if fd is not None:
                buf, inword = [], False
            else:
                end()
            if cmd.startswith("<<", i):
                raise Unparsed("here-document")
            if cmd.startswith("<(", i) or cmd.startswith(">(", i):
                raise Unparsed("process substitution")
            if cmd.startswith(">&", i) or cmd.startswith("<&", i):
                j = i + 2
                while j < n and (cmd[j].isdigit() or cmd[j] == "-"):
                    j += 1
                if j == i + 2:
                    raise Unparsed("redirection to a file descriptor")
                i = j
                continue
            op = ">>" if cmd.startswith(">>", i) else (">|" if cmd.startswith(">|", i) else c)
            toks.append(("op", ">" if op in (">", ">>", ">|") else "<"))
            i += len(op)
            continue
        if c == "{" and cmd.startswith("{}", i) and not inword:
            buf.append("{}")  # find's placeholder
            inword = True
            i += 2
            continue
        if c in "(){}":
            if c in "{}" and inword:
                buf.append(c)
                glob = True
                i += 1
                continue
            raise Unparsed("subshell, group or function")
        if c in "*?[":
            glob = True
        if c == "~" and not inword:
            buf.append(os.path.expanduser("~"))
            inword = True
            i += 1
            continue
        buf.append(c)
        inword = True
        i += 1
    end()
    return toks


def split_commands(toks):
    """-> [(words, redirects, sep_before)] where words are (text, dyn, glob) and redirects are (op, word)."""
    out, words, reds, sep = [], [], [], ""
    k = 0
    while k < len(toks):
        t = toks[k]
        if t[0] == "op" and t[1] in ("<", ">"):
            if k + 1 >= len(toks) or toks[k + 1][0] != "w":
                raise Unparsed("redirection without a target")
            reds.append((t[1], toks[k + 1][1:]))
            k += 2
            continue
        if t[0] == "op":
            if words or reds:
                out.append((words, reds, sep))
            elif t[1] not in (";",):
                raise Unparsed("empty command")
            words, reds, sep = [], [], t[1]
            k += 1
            continue
        words.append(t[1:])
        k += 1
    if words or reds:
        out.append((words, reds, sep))
    return out


# ---------------------------------------------------------------- the scan
def _manifest(plugin_root):
    out = {}
    try:
        with open(os.path.join(plugin_root, "scripts", "rk", "MANIFEST.sha256"), encoding="utf-8") as f:
            for line in f:
                parts = line.strip().split()
                if len(parts) == 2:
                    out[parts[1].lstrip("*")] = parts[0]
    except (OSError, TypeError):
        pass
    return out


LAUNCHERS = {"env", "command", "builtin", "exec", "xargs", "sudo", "nohup", "time", "nice", "eval"}


def could_change_dir(word, at_command=True):
    """WORD (text, dynamic, globbed) is or could become cd / pushd / popd: the name itself anywhere, or, where a
    command name stands (the first word, or after env / command / xargs / ...), a variable or a glob that matches
    one of them."""
    text, dyn, glob = word
    if text in DIR_CMDS:
        return True
    if not at_command:
        return False
    if dyn:
        return True
    if glob:
        import fnmatch
        return any(fnmatch.fnmatchcase(n, text) for n in DIR_CMDS)
    return False


class Scan(object):
    def __init__(self, cwd, plugin_root, proj):
        self.cwd = cwd or os.getcwd()
        self.plugin_root = os.path.realpath(plugin_root) if plugin_root else ""
        self.proj = os.path.realpath(proj) if proj else ""
        self.found = []
        self.cwd_unknown = False
        self._tools_ok = None
        self.ai = ai_files()
        self.ai_shas = {v.get("sha") for v in self.ai.values() if isinstance(v, dict) and v.get("sha")}

    def add(self, kind, what):
        if (kind, what) not in self.found:
            self.found.append((kind, what))

    def _resolve(self, text, glob, cwd):
        """The path bash would use for TEXT: a glob that names exactly one existing path is expanded."""
        p = self._abs(text, cwd)
        if glob:
            hits = _glob.glob(p)
            if len(hits) == 1:
                return hits[0]
        return p

    def classify_target(self, text, dyn, glob, cwd, what):
        """Record a protected or unknown write target. Returns the class (or 'unknown')."""
        if text in SAFE_REDIRECT_TARGETS:
            return "other"
        if re.search(r"[\x00-\x1f\x7f]", text):
            # a control character left in a target means the lexer and bash may disagree on the name: never allow it
            self.add("unknown_target", "%s %r" % (what, text))
            self.add("protected_write", "unknown\t%r" % text)
            return "unknown"
        rel_like = not (text.startswith("/") or text.startswith("~") or re.match(r"^[A-Za-z]:[\\/]", text))
        if dyn or (rel_like and self.cwd_unknown):
            self.add("unknown_target", "%s %s" % (what, text))
            if paths.protected_name(text) or not dyn and glob:
                self.add("protected_write", "unknown\t%s" % text)
            return "unknown"
        p = self._resolve(text, glob, cwd)
        cls = paths.classify_abs(p, self.proj) if self.proj else paths.classify(p)
        if glob and len(_glob.glob(self._abs(text, cwd))) != 1:
            # several or no matches: bash refuses or uses the pattern literally; classify the pattern's spellings too
            for hit in _glob.glob(self._abs(text, cwd)):
                c2 = paths.classify_abs(hit, self.proj)
                if c2 in paths.PROTECTED:
                    cls = c2
        if cls in paths.PROTECTED or cls in ("ci", "claims", "bibliography", "proposals"):
            self.add("protected_write", "%s\t%s" % (cls, p))
        return cls

    def _abs(self, word, cwd):
        w = word.replace("\\", "/")
        if re.match(r"^[A-Za-z]:/", w):
            return w
        return os.path.normpath(os.path.join(cwd, os.path.expanduser(w)))

    def _inside(self, path, root):
        return bool(root) and (path == root or path.startswith(root + os.sep))

    def tools_copy_ok(self):
        """The project's tools/rk matches the plugin's MANIFEST exactly (same files, same content hashes)."""
        if self._tools_ok is None:
            man = _manifest(self.plugin_root)
            base = os.path.join(self.proj, "tools", "rk")
            have = {}
            for dp, dns, fns in os.walk(base):
                dns[:] = [d for d in dns if d != "__pycache__"]
                for fn in fns:
                    if fn.endswith(".pyc") or (fn == "MANIFEST.sha256" and dp == base):
                        continue
                    full = os.path.join(dp, fn)
                    have[os.path.relpath(full, base).replace(os.sep, "/")] = _sha(full)
            self._tools_ok = bool(man) and have == man
        return self._tools_ok

    def shipped(self, path):
        """Plugin code: inside the installed plugin, or the project's verified copy (never by base name)."""
        real = os.path.realpath(path)
        if self._inside(real, self.plugin_root):
            return os.path.isfile(real)
        if self.proj and self._inside(real, os.path.join(self.proj, "tools", "rk")):
            return self.tools_copy_ok() and os.path.isfile(real)
        return False

    def note_ai_files(self, words, cwd):
        for text, dyn, glob in words:
            if dyn or glob or not text or text.startswith("-") and "=" not in text:
                continue
            for cand in (text, text.split("=", 1)[-1]):
                p = self._abs(cand, cwd)
                if os.path.isfile(p):
                    real = os.path.realpath(p)
                    if real in self.ai or (self.ai_shas and _sha(real) in self.ai_shas):
                        self.add("ai_file", real)

    def command(self, cmd):
        try:
            cmds = split_commands(lex(cmd))
        except Unparsed as e:
            self.add("unparsed", str(e))
            # a construct that is not analysed (a subshell, a function, a here-document...) with a write form in it:
            # its target is unknown (denied under prohibited / unreadable settings, asked otherwise)
            if re.search(r"(^|[^0-9&<>])>(?!\s*/dev/null)|(^|[\s;&|(])(%s)(\s|$)" % "|".join(sorted(WRITE_CMDS | INPLACE_CMDS)), cmd or ""):
                self.add("unknown_target", "(%s)" % str(e))
                for w in re.findall(r"[^\s'\"<>|;&()`$]+", cmd or ""):
                    if paths.protected_name(w):
                        self.add("protected_write", "unknown\t%s" % w)
            # still name AI-written files that appear in it
            self.note_ai_files([(w, False, False) for w in re.findall(r"[^\s'\"<>|;&()`$]+", cmd)], self.cwd)
            return
        # The directory is never followed. If the command contains any directory change anywhere (cd, pushd, popd, or
        # a word that could become one after expansion: a variable or a glob that matches one of those names), every
        # relative write target in the whole command is unknown; otherwise relative targets resolve against the tool's
        # working directory. (Following cd failed three times: an && chain whose earlier command fails, a newline after
        # && / || / |, a cd behind ||. Simpler and stricter is the rule.)
        if any(could_change_dir(w, k == 0 or words[k - 1][0] in LAUNCHERS)
               for words, _r, _s in cmds for k, w in enumerate(words)):
            self.cwd_unknown = True
        for words, reds, sep in cmds:
            self.simple(words, reds, self.cwd)

    def _redirects(self, reds, cwd):
        for op, (text, dyn, glob) in reds:
            if op != ">":
                continue
            if text in SAFE_REDIRECT_TARGETS:
                continue
            self.classify_target(text, dyn, glob, cwd, ">")
            if dyn or glob or self.cwd_unknown:
                self.add("ask", "> %s(書き込み先を特定できない)" % text)
                continue
            p = os.path.realpath(self._abs(text, cwd))
            raw = self._abs(text, cwd)
            if deny_write_path(raw, self.proj):            # a .git component, a startup/bin/boot/runconfig file
                self.add("deny_write", raw)
                continue
            rel = os.path.relpath(p, self.proj).replace(os.sep, "/") if self.proj else ""
            if not self.proj or not self._inside(p, self.proj):
                self.add("ask", "> %s(プロジェクトの外への書き込み)" % text)
            elif re.match(r"^(\.git|\.githooks|\.github)(/|$)", rel) or "/.git/" in "/" + rel:
                self.add("ask", "> %s(Git・CI の設定への書き込み)" % text)

    def simple(self, words, reds, cwd):
        if not words:
            self._redirects(reds, cwd)
            return cwd
        name, ndyn, nglob = words[0]
        if re.match(r"^[A-Za-z_][A-Za-z0-9_]*\+?=", name):
            self.add("ask", "%s(環境変数の代入は、後の起動の動きを変えうる)" % name.split("=")[0])
            self.note_ai_files(words, cwd)
            return cwd
        if ndyn or (nglob and name != "["):
            self.add("ask", "%s(実行するものを特定できない)" % name)
            return cwd
        args = [w[0] for w in words[1:]]
        self.note_ai_files(words, cwd)
        self._redirects(reds, cwd)
        base = name
        bname = os.path.basename(base)
        inplace = bname in INPLACE_CMDS and any(re.match(r"^-[a-zA-Z]*i|^--in-place", a) for a in args)
        if bname in WRITE_CMDS or inplace:
            for text, dyn, glob in words[1:]:
                if text.startswith("-") and "=" not in text:
                    continue
                for cand in ([text.split("=", 1)[1]] if re.match(r"^[A-Za-z]+=", text) else [text]):
                    if cand and not cand.startswith("-"):
                        self.classify_target(cand, dyn, glob, cwd, bname)
        elif bname in OUTPUT_OPT_CMDS:
            for k, (text, dyn, glob) in enumerate(words[1:]):
                if text in ("-o", "--output", "-O") and k + 2 < len(words):
                    t2 = words[k + 2]
                    self.classify_target(t2[0], t2[1], t2[2], cwd, bname)
                elif text.startswith("--output="):
                    self.classify_target(text.split("=", 1)[1], dyn, glob, cwd, bname)
        if base in VERSION_ONLY:
            if [a for a in args if not a.startswith("-")] == [] and all(a in ("--version", "-v", "-V", "--help", "-h") for a in args) and args:
                return cwd
            self.add("ask", "%s %s(--version 以外の起動は外部のプログラムを動かしうる)" % (base, " ".join(args[:3])))
            return cwd
        if base in DIR_CMDS:
            self.cwd_unknown = True
            return cwd
        if base in PY_NAMES:
            return self.python(name, args, cwd)
        if base in SH_NAMES:
            return self.shell(name, args, words, cwd)
        if "/" in name:
            return self.path_exec(name, args, cwd)
        if base in READ_ONLY:
            bad = self.read_only_bad(base, args, words, cwd)
            if bad:
                self.add("ask", "%s %s" % (base, bad))
            return cwd
        if base == "claude":
            sub = next((a for a in args if not a.startswith("-")), "")
            if sub in ("plugin", "plugins", "config", "mcp", "update", "install", "migrate-installer", "setup-token"):
                self.add("claude_deny", " ".join([base] + args)[:80])
            else:
                self.add("ask", "claude(別の Claude Code を起動する)")
            return cwd
        self.add("ask", base)
        return cwd

    def read_only_bad(self, base, args, words, cwd="."):
        if base == "sed":  # only `sed -n [N,Mp|Np] <file>` reads; e/w/s commands or a program run code
            prog = [a for a in args if not a.startswith("-")]
            opts = [a for a in args if a.startswith("-")]
            if opts == ["-n"] and len(prog) >= 2 and SED_PRINT.match(prog[0]):
                return ""
            if all(SED_PRINT.match(a) or a == "-n" for a in args if a.startswith("-") or a[:1].isdigit()):
                pass
            return "(sed は書き換え・実行を伴いうる。読むのは sed -n 'N,Mp' file だけ)"
        forb = READ_ONLY.get(base, ())
        for a in args:
            for f in forb:
                if f.startswith("--"):
                    hit = a.startswith(f)
                elif len(f) == 2:  # a short option, also inside a cluster such as -no
                    hit = a.startswith("-") and not a.startswith("--") and (a == f or (a[1:].isalpha() and f[1] in a[1:]))
                else:  # find's single-dash words: exact
                    hit = a == f
                if hit:
                    return "(%s は書き込みか実行を伴う)" % f
        if base == "env" and args:
            return "(env は後ろのコマンドを実行する)"
        if base == "command" and not (args and args[0] in ("-v", "-V")):
            return "(command は後ろのコマンドを実行する)"
        if base == "uniq":
            pos = [a for a in args if not a.startswith("-")]
            if len(pos) >= 2:
                return "(出力ファイルに書く)"
        if base == "git":
            if args and args[0] in ("--version", "version", "--help", "help"):
                return ""
            k, gitdir = 0, cwd
            while k < len(args) and args[k].startswith("-"):
                a = args[k]
                if a == "-C" and k + 1 < len(args):
                    gitdir = self._abs(args[k + 1], gitdir)
                    k += 2
                    continue
                if a.startswith("-C") and len(a) > 2:
                    gitdir = self._abs(a[2:], gitdir)
                    k += 1
                    continue
                if a in ("--no-pager", "--no-optional-locks", "-P", "--literal-pathspecs", "--literal-pathspecs=true", "--bare=false"):
                    k += 1
                    continue
                return "%s(git の全体のオプション。設定やリポジトリの指定を変えうる)" % a
            if k >= len(args) or args[k] not in GIT_SUBS:
                return "%s(読み取りだけの git のサブコマンドではない)" % (args[k] if k < len(args) else "")
            for a in args[k + 1:]:
                for b in GIT_BAD:
                    if a == b or a.startswith(b + "=") or (b.startswith("--") and a.startswith(b)):
                        return "%s(git の実行・書き込みのオプション)" % a
            # the repository git actually uses must be this project's own <proj>/.git directory, or any config
            # it reads (core.fsmonitor / pager / sshCommand, [diff].external, [filter].process, ...) runs code
            why = self._git_repo_is_project(gitdir)
            if why:
                return why
        return ""

    def _git_repo_is_project(self, start):
        want = os.path.realpath(os.path.join(self.proj, ".git")) if self.proj else ""
        if not want or not os.path.isdir(want):
            return "(このプロジェクトに .git のディレクトリが無いので、git は確認してから。別のリポジトリの設定がコードを実行しうる)"
        cur = os.path.realpath(start)
        seen = 0
        while True:
            seen += 1
            if seen > 60:
                return "(リポジトリの位置を特定できない)"
            dotgit = os.path.join(cur, ".git")
            if os.path.isdir(dotgit):
                if os.path.realpath(dotgit) == want:
                    return ""
                return "(このプロジェクト以外のリポジトリ(%s)を使う。別のリポジトリの設定がコードを実行しうる)" % cur
            if os.path.exists(dotgit):  # a .git FILE (gitdir: ...): the real git dir is elsewhere
                return "(.git ファイル(gitdir)経由のリポジトリ。別の場所の設定がコードを実行しうる)"
            if os.path.isfile(os.path.join(cur, "HEAD")) and os.path.exists(os.path.join(cur, "config")):
                return "(HEAD と config を持つディレクトリ(bare など)。その設定がコードを実行しうる)"
            parent = os.path.dirname(cur)
            if parent == cur:
                return "(リポジトリが見つからない。確認してから)"
            cur = parent

    def python(self, name, args, cwd):
        if args and all(a in ("--version", "-V", "--help", "-h", "-VV", "-3") for a in args) and any(a in ("--version", "-V", "-VV", "--help", "-h") for a in args):
            return cwd  # `python3 --version` only
        k = 0
        while k < len(args) and args[k] in PY_FLAGS:
            k += 1
        if k >= len(args) or args[k].startswith("-"):
            self.add("ask", "%s %s(Plugin の外のコード。インラインのコードやモジュールの実行)" % (name, " ".join(args[:3])))
            return cwd
        if self.cwd_unknown and not os.path.isabs(args[k]):
            self.add("ask", "%s %s(cd の行き先を特定できないので、実行するファイルも特定できない)" % (name, args[k]))
            return cwd
        script = self._abs(args[k], cwd)
        rest = args[k + 1:]
        if not self.shipped(script):
            self.add("outside_code", os.path.realpath(script))
            if self._subcommand(rest) == "notebook":
                self.add("notebook_bad", os.path.realpath(script))
            return cwd
        self._rk_sub(script, rest)
        return cwd

    def _subcommand(self, rest):
        k = 0
        while k < len(rest):
            a = rest[k]
            # --project VALUE, and any abbreviation of it (rk.py also refuses abbreviations: allow_abbrev=False)
            if len(a) > 2 and "--project".startswith(a) and k + 1 < len(rest):
                k += 2
                continue
            if a.startswith("-"):
                k += 1
                continue
            return a
        return ""

    def _rk_sub(self, script, rest):
        sub = self._subcommand(rest)
        real = os.path.realpath(script)
        if sub in HUMAN:
            self.add("human", real)
        elif sub == "notebook":
            want = os.path.realpath(os.path.join(self.plugin_root, "scripts", "rk", "rk.py")) if self.plugin_root else ""
            self.add("notebook_ok" if real == want else "notebook_bad", real)

    def shell(self, name, args, words, cwd):
        k = 0
        while k < len(args) and args[k] in ("-e", "-u", "--norc", "--noprofile"):
            k += 1
        if k < len(args) and not args[k].startswith("-") and not (self.cwd_unknown and not os.path.isabs(args[k])) \
                and self.shipped(self._abs(args[k], cwd)):
            return cwd
        self.add("ask", "%s %s(シェルはどんなコマンドも実行できる)" % (name, " ".join(args[:3])))
        return cwd

    def path_exec(self, name, args, cwd):
        if self.cwd_unknown and not os.path.isabs(name):
            self.add("ask", "%s(cd の行き先を特定できないので、実行するファイルも特定できない)" % name)
            return cwd
        p = self._abs(name, cwd)
        real = os.path.realpath(p)
        if self.proj and real == os.path.realpath(os.path.join(self.proj, "rk")) and self.launcher_ok(real):
            sub = self._subcommand(args)
            if sub in HUMAN:
                self.add("human", real)
            elif sub == "notebook":
                self.add("notebook_bad", real)  # ./rk follows a file outside the project: start it from the plugin
            return cwd
        if self.shipped(real):
            return cwd
        self.add("outside_code", real)
        return cwd

    def launcher_ok(self, real):
        if not self.plugin_root:
            return False
        if _sha(real) != _sha(os.path.join(self.plugin_root, "scripts", "rk", "launchers", "rk")):
            return False
        try:
            with open(os.path.join(state_home(), "plugin-root"), encoding="utf-8") as f:
                target = f.readline().strip()
        except OSError:
            return False
        return os.path.realpath(target) == self.plugin_root


# ------------------------------------------------------------------------------------------------ loopback hosts
LOOPBACK_NAMES = {"localhost", "localhost.localdomain", "ip6-localhost", "ip6-loopback", "localhost6",
                  "localhost6.localdomain6"}
NET_CMDS = {"nc", "ncat", "netcat", "telnet", "socat", "curl", "wget", "http", "https", "xh", "aria2c", "lynx", "w3m"}


def _hosts_file_loopback_names():
    """Names that the hosts file maps to a loopback address (read locally; no DNS query is made)."""
    out = set()
    for p in ("/etc/hosts", os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), "System32", "drivers", "etc", "hosts")):
        try:
            with open(p, encoding="utf-8", errors="replace") as f:
                for ln in f:
                    parts = ln.split("#", 1)[0].split()
                    if len(parts) >= 2 and _numeric_loopback(parts[0]):
                        out.update(x.lower().rstrip(".") for x in parts[1:])
        except OSError:
            pass
    return out


def _numeric_loopback(h):
    """An address in any spelling the C library accepts (inet_aton: 127.1, 0x7f.1, 2130706433, 0177.0.0.1) or an IPv6
    address (::1, ::ffff:7f00:1, 0:0:0:0:0:0:0:1) that is loopback or unspecified (0.0.0.0 and :: reach this host)."""
    import ipaddress
    import socket
    h = h.strip("[]").split("%", 1)[0]
    if not h:
        return False
    try:
        a = ipaddress.ip_address(h)
        if a.version == 6 and a.ipv4_mapped is not None:
            a = a.ipv4_mapped
        return a.is_loopback or a.is_unspecified
    except ValueError:
        pass
    if re.fullmatch(r"(?:0[xX][0-9a-fA-F]+|[0-9]+)(?:\.(?:0[xX][0-9a-fA-F]+|[0-9]+)){0,3}", h):
        try:
            a = ipaddress.IPv4Address(socket.inet_aton(h))
            return a.is_loopback or (a.is_unspecified and "." in h)
        except (OSError, ValueError):
            return False
    return False


def is_loopback(host, _names=None):
    h = (host or "").strip().strip("[]").rstrip(".").lower()
    if not h:
        return False
    if h in LOOPBACK_NAMES or h.endswith(".localhost"):
        return True
    if _numeric_loopback(h):
        return True
    names = _names if _names is not None else _hosts_file_loopback_names()
    return h in names


def loopback_targets(command):
    """Hosts in COMMAND that reach this computer: the host of every URL (with or without a scheme, e.g.
    'http://0x7f.1:8765/x' or '[::ffff:7f00:1]:8765/api'), every 'host:port' word, every address in curl's --resolve /
    --connect-to values, and the arguments of nc/telnet/socat. Names are matched against a fixed list and the hosts
    file only: a DNS name that some resolver points at 127.0.0.1 is not detected (README)."""
    text = (command or "").replace("\\", "")
    words = [w for w in re.split(r"[\s'\"`;|&()<>{}]+", text) if w]
    names = None
    out = []
    prev = ""
    for w in words:
        cands = []
        m = re.match(r"^(?:[A-Za-z][A-Za-z0-9+.-]*://)?(?:[^@/\s]*@)?(\[[^\]]+\]|[^/\s:\[\]]+)(?::(\d{1,5}))?(/|$)", w)
        netish = "://" in w or re.search(r":\d{1,5}(?:/|$)", w) or os.path.basename(prev) in ("nc", "ncat", "netcat", "telnet")
        if m and netish:
            cands.append(m.group(1))
        if re.match(r"^(?:tcp|tcp4|tcp6|udp|udp4|udp6|tcp-connect|tcp4-connect|tcp6-connect|udp-connect|unix-connect|open|connect):", w, re.I):
            cands += re.split(r"[:,]", w.split(":", 1)[1])
        if prev in ("--resolve", "--connect-to") or w.startswith(("--resolve=", "--connect-to=")):
            cands += [x for x in re.split(r"[:,=]", w) if x]
        if os.path.basename(prev) in ("nc", "ncat", "netcat", "telnet") and not w.startswith("-"):
            cands.append(w)
        for c in cands:
            if names is None and not (c.lower() in LOOPBACK_NAMES or _numeric_loopback(c)):
                names = _hosts_file_loopback_names()
            if is_loopback(c, names if names is not None else set()):
                out.append(c)
        prev = w
    return out


def scan(command, cwd, plugin_root, proj, session_start=0):
    s = Scan(cwd, plugin_root, proj)
    s.command(command or "")
    for h in loopback_targets(command or ""):
        s.add("loopback", h)
    return s.found


def session_start(sid):
    """First time this session was seen (kept for the SessionStart hook; the gate no longer uses it)."""
    sid = re.sub(r"[^A-Za-z0-9_-]", "", sid or "")[:64] or "nosession"
    d = os.path.join(state_home(), "sessions")
    p = os.path.join(d, sid)
    try:
        with open(p, encoding="utf-8") as f:
            return float(f.read().strip() or 0)
    except (OSError, ValueError):
        pass
    now = time.time()
    try:
        os.makedirs(d, exist_ok=True)
        with open(p, "w", encoding="utf-8") as f:
            f.write("%f" % now)
        for fn in os.listdir(d):
            fp = os.path.join(d, fn)
            if now - os.path.getmtime(fp) > 30 * 86400:
                os.remove(fp)
    except OSError:
        pass
    return now
