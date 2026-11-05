"""Path classes: the Python twin of path_class in scripts/hooks/lib.sh, used by execgate for the targets of shell
writes after the shell lexer has resolved them (quotes, backslashes, globs, cd). The two must agree; a test compares
them on a fixed list (tests/test_v2.Hardening.test_path_classes_agree_with_the_hook).

classify(rel) takes a path relative to the project (or absolute, outside it) and returns one of:
  statehome claude runconfig startup manuscript ryukoku tools questions searchlog thinking statement disclosure
  annotations ledger bibliography raw ci pandoc proposals claims verification research other
"""
import fnmatch
import os

# (class, patterns on "/" + lower-case path); the first match wins, in this order (as in lib.sh)
RULES = (
    ("statehome", ("*/.ryukoku-writing/*", "*/.ryukoku-writing")),
    ("claude", ("*/.claude/*", "*/.claude")),
    ("runconfig", ("*/.git/*", "*/.git", "*/.gitconfig", "*/.gitmodules", "*/.config/git/*", "*/site-packages/*",
                   "*/sitecustomize.py", "*/usercustomize.py", "*.pth")),
    ("startup", ("*/.bashrc", "*/.bash_profile", "*/.bash_login", "*/.bash_logout", "*/.profile", "*/.zshrc", "*/.zprofile",
                 "*/.zshenv", "*/.zlogin", "*/.inputrc", "*/.kshrc", "*/.cshrc", "*/.tcshrc", "*/.netrc", "*/.envrc",
                 "*/config.fish", "*/profile.ps1", "*/microsoft.powershell_profile.ps1")),
    ("startup", ("*/.local/bin/*", "*/bin/*", "*/.config/autostart/*", "*/.config/systemd/user/*", "*/library/launchagents/*",
                 "*/.vscode/*", "*/.config/fish/*")),
    ("manuscript", ("*/manuscript/*", "*/manuscript")),
    ("ryukoku", ("*/.ryukoku/*", "*/.ryukoku")),
    ("tools", ("*/tools/rk/*", "*/tools/rk", "*/tools")),
    ("tools", ("*/rk", "*/rk.cmd", "*/rk.ps1")),
    ("questions", ("*/research/questions.md",)),
    ("searchlog", ("*/research/search-log.jsonl",)),
    ("thinking", ("*/thinking/*", "*/thinking")),
    ("statement", ("*/disclosure/statement*.md",)),
    ("disclosure", ("*/disclosure/*", "*/disclosure")),
    ("annotations", ("*/review/annotations.json", "*/review/annotations-log.jsonl")),
    ("ledger", ("*/sources/register.csv", "*/sources/claims.csv", "*/sources/identity.json")),
    ("bibliography", ("*/sources/references.json",)),
    ("raw", ("*/data/raw/*",)),
    ("ci", ("*/.github/*", "*/.githooks/*", "*/.git/hooks/*", "*/.github", "*/.githooks")),
    ("pandoc", ("*/pandoc/*", "*/pandoc")),
    ("proposals", ("*/proposals/*",)),
    ("claims", ("*/claims/*",)),
    ("verification", ("*/review/verification/*",)),
    ("research", ("*/research/*", "*/sources/*", "*/review/*", "*/excerpts/*")),
)
# classes a shell write must never reach (the Write/Edit gate denies them too; manuscript follows the policy there,
# but from the shell it is always denied). ci (.github/, .githooks/) and pandoc/ (the export settings) are the
# student's to change: the AI never writes them
PROTECTED = {"statehome", "claude", "runconfig", "startup", "manuscript", "ryukoku", "tools", "questions", "searchlog",
             "thinking", "disclosure", "annotations", "ledger", "raw", "statement", "ci", "pandoc"}
# file names that are protected wherever the directory is unknown (a cd the scanner could not follow)
PROTECTED_NAMES = {"signoffs.jsonl", "provenance.jsonl", "ai-use-log.jsonl", "config.yml", "signers.json", "style.yml",
                   "questions.md", "search-log.jsonl", "annotations.json", "annotations-log.jsonl", "register.csv",
                   "claims.csv", "identity.json", "references.json", "log.md", "rq-worksheet.md", "root-changes.jsonl", "rk", "rk.cmd",
                   "rk.ps1", "main.md", "check.yml", "pre-commit", "pre-push"}


def norm(path):
    p = path.replace("\\", "/").lower()
    if len(p) > 2 and p[1] == ":" and p[2] == "/":
        p = p[2:]
    while "//" in p:
        p = p.replace("//", "/")
    while "/./" in p:
        p = p.replace("/./", "/")
    if p.startswith("./"):
        p = p[2:]
    return p


def classify(rel):
    r = "/" + norm(rel).lstrip("/")
    for cls, pats in RULES:
        for pat in pats:
            if fnmatch.fnmatchcase(r, pat):
                return cls
    return "other"


def classify_abs(path, proj):
    """Class of an absolute PATH for project PROJ (symlinks resolved; the raw spelling is classified too and the
    stricter of the two wins)."""
    out = []
    for p in (path, os.path.realpath(path)):
        if proj and (p == proj or p.startswith(proj.rstrip(os.sep) + os.sep)):
            out.append(classify(os.path.relpath(p, proj)))
        else:
            out.append(classify(p))
    for c in out:
        if c in PROTECTED:
            return c
    return next((c for c in out if c != "other"), "other")
