"""Export to submission formats: docx (first), PDF (LuaLaTeX + LuaTeX-ja; jlreq/ltjsarticle for
Japanese, standard classes for English), LaTeX source. Reads manuscript_lang from .ryukoku/config.yml and
picks pandoc/defaults-<lang>-<fmt>.yaml, so switching the language is one line in the config.

Mermaid: blocks are written to fig-N.mmd and rendered to PNG with mmdc when it is installed
(`mmdc -i in.mmd -o out.png`; mermaid-cli README, https://github.com/mermaid-js/mermaid-cli: SVG, PNG
and PDF output); a copy of the manuscript then points to the PNGs.
Without mmdc the code block stays as code and a warning says how to export the figures by hand.
pandoc-ext/diagram is the alternative filter (not bundled; see skills/export-submission).
The manuscript itself is never modified.

Where the external programs run: pandoc, the LaTeX engine it starts and
mmdc read configuration from their working directory and from files named in the defaults (pandoc: custom
readers/writers given as `from`/`to` file names, filters, templates; LaTeX: .sty/.cls/.tex found in the working
directory; mmdc/puppeteer: .puppeteerrc* and similar found from the working directory upwards). An AI tool can
write anywhere in the project, so none of them runs with the project as its working directory: the copies, the
figures and the plugin-built defaults go to a fresh folder under the per-user state folder (outside the project;
AI writes there are denied by the hooks), and only the finished output and the figure files are copied to build/.
`from`/`to` must be pandoc's built-in format names, and the values of `variables`/`metadata` are checked.
"""
import json
import os
import re
import shutil
import subprocess
import tempfile

from . import criticmarkup
from .common import feedback_lang, tr, RkError, load_config, manuscript_files, read_text, state_dir

FMT = ("docx", "pdf", "latex")


def manuscript_sources(proj):
    base = os.path.join(proj, "manuscript")
    files = sorted(f for f in os.listdir(base) if f.endswith(".md") and not f.startswith(("_", ".")))
    return [os.path.join(base, f) for f in files]


def _safe_write(path, data):
    """Write PATH without following a link an AI tool may have planted there (build/ is writable by the AI)."""
    if os.path.islink(path):
        os.unlink(path)
    flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_BINARY", 0)
    fd = os.open(path, flags, 0o644)
    with os.fdopen(fd, "wb") as f:
        f.write(data if isinstance(data, bytes) else data.encode("utf-8"))


def render_mermaid(text, build, n0=0, fmt="docx", work=None):
    """BUILD: where the student finds fig-N.mmd/.png. WORK: where mmdc runs (outside the project; see above)."""
    work = work or build
    warns = []
    out, i, n = [], 0, n0
    lines = text.split("\n")
    mmdc = shutil.which("mmdc")
    while i < len(lines):
        ln = lines[i]
        if re.match(r"^\s*```+\s*\{?\.?mermaid", ln.strip()):
            j = i + 1
            while j < len(lines) and not lines[j].strip().startswith("```"):
                j += 1
            n += 1
            src = "\n".join(lines[i + 1:j]) + "\n"
            mmd = os.path.join(work, "fig-%d.mmd" % n)
            _safe_write(mmd, src)
            _safe_write(os.path.join(build, "fig-%d.mmd" % n), src)
            png = os.path.join(work, "fig-%d.png" % n)
            if mmdc:
                r = subprocess.run([mmdc, "-i", mmd, "-o", png], cwd=work, capture_output=True, timeout=180)
                if r.returncode == 0 and os.path.exists(png) and not os.path.islink(png):
                    with open(png, "rb") as f:
                        _safe_write(os.path.join(build, "fig-%d.png" % n), f.read())
                    out.append("![](%s)" % os.path.basename(png))
                    i = j + 1
                    continue
                warns.append("mmdc が図 %d の書き出しに失敗した(日本語フォントの不足に注意)。コードのまま出力した" % n)
            else:
                warns.append("mmdc がないので Mermaid 図 %d はコードのまま出力した。mmdc -i %s -o fig-%d.png で書き出して挿入する"
                             % (n, os.path.relpath(os.path.join(build, "fig-%d.mmd" % n)), n))
            out += lines[i:j + 1]
            i = j + 1
            continue
        out.append(ln)
        i += 1
    return "\n".join(out), n, warns


ALLOWED_DEFAULTS = {"from", "to", "standalone", "reference-doc", "citeproc", "bibliography", "csl", "metadata",
                    "variables", "pdf-engine", "wrap"}
ALLOWED_META = {"lang"}
ALLOWED_VARS = {"documentclass", "papersize", "fontsize", "mainfont", "CJKmainfont"}
ALLOWED_ENGINES = {"lualatex", "xelatex"}
# pandoc's built-in format names only: a value with "." or "/" is a custom Lua reader/writer, i.e. code.
# Extensions (+name / -name) are allowed.
FORMAT_NAMES = {"markdown", "commonmark", "commonmark_x", "gfm", "markdown_strict", "markdown_mmd",
                "markdown_phpextra", "docx", "latex", "pdf", "odt", "html", "html5"}
FORMAT_RE = re.compile(r"^([a-z0-9_]+)((?:[+-][a-z0-9_]+)*)$")
DOCUMENT_CLASSES = {"ltjsarticle", "ltjsreport", "ltjsbook", "jlreq", "article", "report", "book"}
# values that go into the LaTeX template as they are: no TeX control characters (\directlua etc.)
TEX_SAFE_RE = re.compile(r"^[^\\{}%$#&^~\[\]<>|;\"'`\x00-\x1f]{1,80}$")
VAR_RULES = {
    "documentclass": lambda v: v in DOCUMENT_CLASSES,
    "papersize": lambda v: re.fullmatch(r"[a-z0-9]{1,12}", v) is not None,
    "fontsize": lambda v: re.fullmatch(r"\d{1,2}(\.\d)?pt", v) is not None,
    "mainfont": lambda v: TEX_SAFE_RE.match(v) is not None,
    "CJKmainfont": lambda v: TEX_SAFE_RE.match(v) is not None,
}
PATH_EXT = {"reference-doc": (".docx",), "bibliography": (".bib", ".json", ".yaml", ".yml", ".ris"), "csl": (".csl",)}


def _unquote(v):
    v = str(v).strip()
    if len(v) >= 2 and v[0] == v[-1] and v[0] in "\"'":
        v = v[1:-1]
    return v


def _parse_defaults(path):
    """A tiny parser for the simple pandoc defaults this plugin ships: top-level `key: value`, and the two nested
    maps `metadata:` / `variables:` with `  key: value`. Anything else (a list such as `filters:`, an unknown
    nested shape) is returned as an unknown key so the caller rejects it. No external YAML library."""
    out, unknown, i = {}, [], 0
    lines = open(path, encoding="utf-8").read().split("\n")
    while i < len(lines):
        raw = lines[i]
        i += 1
        line = raw.split("#", 1)[0].rstrip() if not raw.lstrip().startswith("#") else ""
        if not line.strip():
            continue
        if raw[:1] in (" ", "\t"):   # stray indented line at top level
            unknown.append(raw.strip()[:40])
            continue
        m = re.match(r"^([A-Za-z0-9_-]+):(.*)$", line)
        if not m:
            unknown.append(line.strip()[:40])
            continue
        key, val = m.group(1), m.group(2).strip()
        if val == "":
            # a nested block or a list follows
            block, kids = {}, []
            while i < len(lines):
                nxt = lines[i]
                if not nxt.strip() or nxt.lstrip().startswith("#"):
                    i += 1
                    continue
                if nxt[:1] not in (" ", "\t"):
                    break
                i += 1
                mm = re.match(r"^\s+([A-Za-z0-9_-]+):(.*)$", nxt)
                if mm:
                    block[mm.group(1)] = re.sub(r"\s+#.*$", "", mm.group(2)).strip()  # an inline comment
                else:
                    kids.append(nxt.strip())   # a list item "- x" etc.
            if kids:
                out[key] = ("__list__", kids)
            else:
                out[key] = block
        else:
            out[key] = val
    return out, unknown


def sanitize_defaults(path, proj):
    """(safe dict for pandoc, [rejected items]). Only the allow-listed keys and values survive."""
    parsed, unknown = _parse_defaults(path)
    safe, bad = {}, list(unknown)

    def _bool(v):
        return str(v).strip().lower() in ("true", "yes", "1")

    def _inside(rel):
        full = os.path.realpath(os.path.join(proj, str(rel)))
        root = os.path.realpath(proj)
        return full == root or full.startswith(root + os.sep)
    for key, val in parsed.items():
        if key not in ALLOWED_DEFAULTS:
            bad.append(key)
            continue
        if isinstance(val, tuple):            # a list value: not allowed for any allow-listed key
            bad.append(key)
            continue
        if key in ("from", "to"):
            m = FORMAT_RE.match(_unquote(val))
            if m and m.group(1) in FORMAT_NAMES:
                safe[key] = _unquote(val)
            else:
                bad.append("%s=%s(組み込みの形式名ではない / not a built-in format name)" % (key, _unquote(val)[:40]))
        elif key == "wrap":
            if _unquote(val) in ("auto", "none", "preserve"):
                safe[key] = _unquote(val)
            else:
                bad.append("wrap")
        elif key == "standalone":
            safe[key] = _bool(val)
        elif key == "citeproc":
            safe[key] = _bool(val)
        elif key in ("reference-doc", "bibliography", "csl"):
            v = _unquote(val)
            if not _inside(v):
                bad.append("%s(プロジェクトの外)" % key)
            elif not v.lower().endswith(PATH_EXT[key]):
                bad.append("%s(拡張子 / extension)" % key)
            elif key == "bibliography" and os.path.realpath(os.path.join(proj, v)) != os.path.realpath(os.path.join(proj, "sources", "references.json")):
                # the printed bibliography is the one whose entries are compared with the ledger
                bad.append("bibliography(sources/references.json だけ / only sources/references.json)")
            elif key == "csl" and not os.path.realpath(os.path.join(proj, v)).startswith(os.path.realpath(os.path.join(proj, "pandoc")) + os.sep):
                bad.append("csl(pandoc/ の中だけ / only inside pandoc/)")
            else:
                # absolute, because pandoc runs outside the project (see the module docstring)
                safe[key] = os.path.realpath(os.path.join(proj, v))
        elif key == "pdf-engine":
            if str(val) in ALLOWED_ENGINES:
                safe[key] = str(val)
            else:
                bad.append("pdf-engine=%s" % val)
        elif key in ("metadata", "variables") and not isinstance(val, dict):
            # a flow mapping ({lang: en}) or a scalar: this small parser reads only the block form
            bad.append("%s(ブロック形式で書く / write it as an indented block)" % key)
        elif key == "metadata":
            m = {k: _unquote(v) for k, v in (val or {}).items()
                 if k in ALLOWED_META and re.fullmatch(r"[A-Za-z]{2,3}(-[A-Za-z0-9]{2,8})*", _unquote(v))}
            for k in (val or {}):
                if k not in m:
                    bad.append("metadata.%s" % k)
            if m:
                safe[key] = m
        elif key == "variables":
            vv = {k: _unquote(v) for k, v in (val or {}).items()
                  if k in ALLOWED_VARS and VAR_RULES[k](_unquote(v))}
            for k in (val or {}):
                if k not in vv:
                    bad.append("variables.%s" % k)
            if vv:
                safe[key] = vv
    return safe, bad


def defaults_problems(proj, lang="ja"):
    """For `rk check`: disallowed items in any pandoc/defaults-*.yaml."""
    probs = []
    d = os.path.join(proj, "pandoc")
    if not os.path.isdir(d):
        return probs
    for fn in sorted(os.listdir(d)):
        if re.match(r"^defaults-.*\.yaml$", fn):
            try:
                _safe, bad = sanitize_defaults(os.path.join(d, fn), proj)
            except Exception as ex:  # fail closed with a message, never a traceback
                bad = ["読めない設定 / unreadable defaults: %s" % type(ex).__name__]
            if bad:
                probs.append((fn, bad))
    return probs


def build(proj, fmt="docx", out=None, files=None):
    if fmt not in FMT:
        raise RkError("形式は docx|pdf|latex")
    cfg = load_config(proj)
    lang = "en" if cfg.get("manuscript_lang", "ja").startswith("en") else "ja"
    if not shutil.which("pandoc"):
        raise RkError("pandoc が見つからない。手作業の経路: manuscript/*.md を Word に貼り、Mermaid 図は mmdc などで PNG にして"
                      "挿入、数式は Word の数式機能で入力する(skills/export-submission 参照)")
    defaults = os.path.join(proj, "pandoc", "defaults-%s-%s.yaml" % (lang, fmt))
    if not os.path.exists(defaults):
        raise RkError("設定 %s がない" % os.path.relpath(defaults, proj))
    try:
        safe, bad = sanitize_defaults(defaults, proj)
    except Exception as ex:  # fail closed with a message
        safe, bad = {}, ["読めない設定 / unreadable defaults: %s" % type(ex).__name__]
    if bad:
        raise RkError(tr(feedback_lang(proj),
            "pandoc の設定 %s に、許可していない項目がある(外部のプログラムを動かしうるので使わない): %s。許可するのは "
            "from・to・standalone・reference-doc・citeproc・bibliography・csl・metadata.lang・variables(documentclass・papersize・fontsize)・"
            "pdf-engine(lualatex/xelatex)だけ。" % (os.path.relpath(defaults, proj), ", ".join(bad)),
            "The pandoc defaults %s has items that are not allowed (they could run external programs): %s. Only from, to, "
            "standalone, reference-doc, citeproc, bibliography, csl, metadata.lang, variables (documentclass/papersize/fontsize) "
            "and pdf-engine (lualatex/xelatex) are allowed." % (os.path.relpath(defaults, proj), ", ".join(bad))))
    # every bibliography entry the manuscript would render must be in the ledger at IDENTITY_CONFIRMED (the same rule
    # as rk check --submit); a sample file outside manuscript/ (examples/...) is exported with a warning only
    from . import citations
    srcs = files or manuscript_sources(proj)
    # the bibliography is sources/references.json only: a front matter that names another one (or inline references,
    # or another style) would print entries nobody compared with the ledger
    for p in srcs:
        ov = citations.front_matter_overrides(read_text(p))
        if ov:
            raise RkError(tr(feedback_lang(proj),
                "書き出さなかった: %s の front matter に %s がある。文献一覧は sources/references.json だけから、書式は pandoc/ の設定から作る。"
                "その行を消してから書き出す。" % (os.path.relpath(p, proj), ", ".join(ov)),
                "Not exported: the front matter of %s sets %s. The bibliography comes from sources/references.json only and its style "
                "from the pandoc/ settings. Remove that line and export again." % (os.path.relpath(p, proj), ", ".join(ov))))
    # the export settings are the student's: a change from the shipped copies needs the student's confirmation
    from . import sign, subjects, trust
    g = subjects.guarded_subject(proj)
    pchanged = sorted(k for k in g.content["files"] if k.startswith("pandoc/"))
    if pchanged:
        trusted, _p, _n = trust.local_trusted(proj)
        idx, _b = sign.valid_index(proj, trusted)
        if not sign.current(idx, "guarded", g.sid, g.digest):
            raise RkError(tr(feedback_lang(proj),
                "書き出さなかった: 書き出しの設定(%s)が Plugin の写しと違い、本人の確認がない。自分で中身を確かめ、意図した変更なら"
                "自分の端末で ./rk sign guarded tools --decision confirmed で確認する(AI は pandoc/ を書かない)。" % ", ".join(pchanged[:6]),
                "Not exported: the export settings (%s) differ from the plugin's copies and you have not confirmed them. Read them; if the "
                "change is intended, confirm it in your terminal with ./rk sign guarded tools --decision confirmed (the AI does not write pandoc/)."
                % ", ".join(pchanged[:6])))
    ms_dir = os.path.realpath(os.path.join(proj, "manuscript")) + os.sep
    if any(os.path.realpath(p).startswith(ms_dir) for p in srcs):
        keys, _star = citations.rendered(proj, [read_text(p) for p in srcs if os.path.realpath(p).startswith(ms_dir)])
        probs = citations.problems(proj, keys)
        if probs:
            raise RkError(tr(feedback_lang(proj),
                "書き出さなかった: 原稿が出す参考文献のうち、台帳にない・IDENTITY_CONFIRMED 未満・文献一覧の項目が台帳と違う(mismatch)ものがある(%s)。"
                "rk.py refcheck check で確かめるか、sources/references.json の項目を台帳に合わせるか、引用から外す。" % ", ".join("%s(%s)" % kv for kv in probs[:8]),
                "Not exported: bibliography entries the manuscript renders are missing from the ledger, below IDENTITY_CONFIRMED, or differ from "
                "the ledger (mismatch) (%s). Check them with rk.py refcheck check, make the entry in sources/references.json match the ledger, "
                "or remove the citations." % ", ".join("%s (%s)" % kv for kv in probs[:8])))
    if fmt == "docx" and not os.path.exists(os.path.join(proj, "pandoc", "reference.docx")):
        raise RkError("pandoc/reference.docx がない。作り方: pandoc -o pandoc/reference.docx --print-default-data-file reference.docx")
    if fmt == "pdf":
        eng = safe.get("pdf-engine", "lualatex")
        if not shutil.which(eng):
            # say what to do instead of passing pandoc's raw error through
            raise RkError(tr(feedback_lang(proj),
                "PDF には %s が要るが見つからない。(1) 提出が Word なら docx で書き出す(python3 tools/rk/rk.py export docx)。"
                "(2) PDF が要るなら TeX Live を入れ、日本語は collection-langjapanese(LuaLaTeX + LuaTeX-ja・jlreq を含む)を入れる"
                "(TeX Live: https://tug.org/texlive/ 。collection-langjapanese の中身は TeX Live の tlpdb による)。(3) LaTeX のファイル(export latex)を Overleaf などで組む。" % eng,
                "PDF needs %s, which was not found. (1) If the submission is Word, export docx (python3 tools/rk/rk.py export docx). "
                "(2) For PDF, install TeX Live (for Japanese, collection-langjapanese: LuaLaTeX + LuaTeX-ja, jlreq; TeX Live: "
                "https://tug.org/texlive/ , the contents as listed in the TeX Live tlpdb). (3) Or export latex and typeset it elsewhere, e.g. Overleaf." % eng))
    bdir = os.path.join(proj, "build")
    if os.path.islink(bdir):
        raise RkError("build/ がリンクになっている。消してから書き出す / build/ is a link; remove it first")
    os.makedirs(bdir, exist_ok=True)
    srcs = files or manuscript_sources(proj)
    if not srcs:
        raise RkError("manuscript/*.md がない")
    work = tempfile.mkdtemp(prefix="export-", dir=state_dir(proj))
    try:
        warns, n, copies = [], 0, []
        for s in srcs:
            with open(s, encoding="utf-8") as f:
                text = f.read()
            if criticmarkup.has_markup(text):
                warns.append("%s に CriticMarkup が残っている(書き出しでは記号を除いた文で出す)" % os.path.basename(s))
                text = criticmarkup.convert(text, "reject")
            text, n, w = render_mermaid(text, bdir, n, fmt, work=work)
            warns += w
            c = os.path.join(work, "src-" + os.path.basename(s))
            _safe_write(c, text)
            copies.append(c)
        ext = {"docx": "docx", "pdf": "pdf", "latex": "tex"}[fmt]
        stem = "manuscript" if not files else os.path.splitext(os.path.basename(files[0]))[0]
        target = out or os.path.join(bdir, "%s.%s" % (stem, ext))
        produced = os.path.join(work, "out." + ext)
        safe_defaults = os.path.join(work, "defaults.json")  # built by the plugin, not the project's file
        with open(safe_defaults, "w", encoding="utf-8") as f:
            json.dump(safe, f, ensure_ascii=False)
        cmd = ["pandoc", "--defaults", safe_defaults, "--resource-path", work + os.pathsep + proj, "-o", produced] + copies
        r = subprocess.run(cmd, cwd=work, capture_output=True, timeout=600)
        if r.returncode != 0:
            raise RkError("pandoc が失敗した: " + r.stderr.decode("utf-8", "replace")[:800])
        with open(produced, "rb") as f:
            _safe_write(target, f.read())
        return target, warns
    finally:
        shutil.rmtree(work, ignore_errors=True)
