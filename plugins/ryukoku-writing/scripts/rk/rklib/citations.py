"""Which bibliography entries a manuscript would render, whether each is in the ledger at IDENTITY_CONFIRMED, and
whether the entry pandoc would print says the same as the ledger.

Keys are found two ways and the union counts:
  1. pandoc itself, when it is installed: `pandoc -f markdown -t json` and every Cite node of the document and of its
     metadata (so `nocite` counts). This is exactly what the export would cite.
  2. a reader that follows pandoc's key rule (pandoc's manual, "Citation syntax", and the behaviour of the installed
     pandoc checked in tests/test_v2): a key starts with a letter, a digit or `_` and may contain letters, digits, `_`
     and internal punctuation `:.#$%&-+?<>~/`; letters and digits are Unicode ones, so `[@山田2020]` is the key
     `山田2020`; punctuation at the end is not part of the key; `@` right after a letter or digit (an e-mail address)
     or after `.` does not start a citation; `@{...}` takes any characters but `}`. Inline code and fenced code
     blocks are skipped. Example-list labels (`(@label)` starting a list item, and `(@label)` referring to one) are not
     citations; `(@name)` with no such list item is a citation, as in pandoc.
Cross-references (`@fig:`, `@tbl:`, `@sec:`, `@eq:`, `@lst:`) are not citations. The YAML front matter's `nocite`
(a string or a list) adds keys; `@*` renders every entry of the bibliography, so every id in sources/references.json
counts.

The bibliography is always sources/references.json (export refuses any other `bibliography:` and inline
`references:`). Each rendered entry is compared with its ledger row: a DOI or ISBN on both sides must be the same,
the title must match (the same rule as the identity check: equal after normalisation, 90 % similar, or a prefix of
20 characters or more), the year must be the same, and every author family name of the entry must be among the
ledger's authors. A difference is an error at export and at submission: the ledger is what was checked against the
identifier, so the printed entry must not say something else.

Not checked: author-year mentions written as plain prose ("Smith (2020) shows ...").
"""
import json
import os
import re
import shutil
import subprocess
import tempfile
import unicodedata

from . import ledger

NONCITE = ("fig:", "tbl:", "sec:", "eq:", "lst:")
PUNCT = r":.#$%&+?<>~/\-"
KEY = r"[^\W]+(?:[" + PUNCT + r"]+[^\W]+)*"
BRACED = re.compile(r"(?<![^\W_])(?<!\.)-?@\{([^}\n]+)\}")
PLAIN = re.compile(r"(?<![^\W_])(?<!\.)-?@(" + KEY + r")")
EXAMPLE_ITEM = re.compile(r"(?m)^[ \t]*(?:[-*+][ \t]+)?\(@([A-Za-z0-9_-]+)\)(?=[ \t])")
FENCE = re.compile(r"(?ms)^[ \t]*(```+|~~~+)[^\n]*\n.*?^[ \t]*\1[ \t]*$")
BIB_FILE = os.path.join("sources", "references.json")


def front_matter(text):
    lines = text.split("\n")
    if lines and lines[0].strip() == "---":
        for i in range(1, len(lines)):
            if lines[i].strip() in ("---", "..."):
                return "\n".join(lines[1:i]), "\n".join(lines[i + 1:])
    return "", text


def _strip_code(text):
    t = FENCE.sub("", text)
    return re.sub(r"`[^`\n]*`", "", t)


def _keys_in(text):
    t = _strip_code(text)
    labels = set(EXAMPLE_ITEM.findall(t))
    if labels:
        t = re.sub(r"\(@(%s)\)" % "|".join(re.escape(x) for x in labels), " ", t)
    out = {k.strip() for k in BRACED.findall(t)}
    t = BRACED.sub(" ", t)
    out |= set(PLAIN.findall(t))
    return {k for k in out if k and not k.startswith(NONCITE)}


def body_keys(text):
    """Citation keys in a piece of manuscript text (no front matter), by the reader above (no pandoc)."""
    return _keys_in(text or "")


def nocite(fm):
    """Keys named by the front matter's nocite (and whether '@*' is among them)."""
    block, on = [], False
    for ln in fm.split("\n"):
        if re.match(r"^nocite[ \t]*:", ln):
            on = True
            block.append(ln.split(":", 1)[1])
            continue
        if on and ln[:1] not in (" ", "\t", "-") and ln.strip():
            on = False
        if on:
            block.append(ln)
    txt = "\n".join(block)
    star = bool(re.search(r"(?<![\w.])@\*", txt))
    return _keys_in(txt.replace("@*", " ")), star


def _pandoc_keys(text):
    """(keys, star) from pandoc's own reading, or None when pandoc is missing or fails."""
    exe = shutil.which("pandoc")
    if not exe:
        return None
    try:
        r = subprocess.run([exe, "-f", "markdown", "-t", "json"], input=text.encode("utf-8"), capture_output=True,
                           timeout=60, cwd=tempfile.gettempdir())
        if r.returncode != 0:
            return None
        doc = json.loads(r.stdout.decode("utf-8"))
    except (OSError, ValueError, subprocess.SubprocessError):
        return None
    out = set()
    stack = [doc]
    while stack:
        x = stack.pop()
        if isinstance(x, dict):
            if x.get("t") == "Cite" and isinstance(x.get("c"), list) and x["c"] and isinstance(x["c"][0], list):
                for c in x["c"][0]:
                    if isinstance(c, dict) and c.get("citationId"):
                        out.add(str(c["citationId"]))
            stack.extend(x.values())
        elif isinstance(x, list):
            stack.extend(x)
    star = "*" in out
    out.discard("*")
    return {k for k in out if not k.startswith(NONCITE)}, star


def extract(text, use_pandoc=False):
    """(keys, star): the citation keys a file would render, and whether nocite '@*' is set. With USE_PANDOC, the keys
    pandoc finds are added (the union counts)."""
    fm, body = front_matter(text)
    keys = _keys_in(body)
    nk, star = nocite(fm)
    keys |= nk
    if use_pandoc:
        pk = _pandoc_keys(text)
        if pk is not None:
            keys |= pk[0]
            star = star or pk[1]
    return keys, star


def front_matter_overrides(text):
    """Front-matter fields that would change what the bibliography prints (export refuses them)."""
    fm, _ = front_matter(text)
    return [m.group(1) for m in re.finditer(r"(?m)^(bibliography|references|csl|citation-style|citation-abbreviations)[ \t]*:", fm)]


def bibliography(proj):
    """{id: entry} of sources/references.json (CSL JSON); {} when missing or unreadable."""
    try:
        with open(os.path.join(proj, BIB_FILE), encoding="utf-8") as f:
            data = json.load(f)
        return {str(x.get("id")): x for x in data if isinstance(x, dict) and x.get("id") is not None}
    except (OSError, ValueError, TypeError, AttributeError):
        return {}


def bibliography_ids(proj):
    return set(bibliography(proj))


def rendered(proj, texts, use_pandoc=True):
    keys, star = set(), False
    for t in texts:
        k, s = extract(t, use_pandoc=use_pandoc)
        keys |= k
        star = star or s
    if star:
        keys |= bibliography_ids(proj)
    return keys, star


def _ledger_by_key(proj):
    by = {}
    for r in ledger.read(ledger.paths(proj)[0], ledger.REGISTER):
        for k in (r.get("citekey"), r.get("id")):
            if k:
                by[k] = r
    return by


def _norm_name(s):
    from .refcheck import normalize_text
    return normalize_text(s).replace(" ", "")


def entry_mismatches(row, entry):
    """[field] where the CSL entry says something other than the ledger row."""
    from . import refcheck as R
    out = []
    a, b = R.normalize_doi(row.get("doi")), R.normalize_doi(entry.get("DOI"))
    if a and b and a != b:
        out.append("DOI")
    a, b = R.clean_isbn(row.get("isbn")), R.clean_isbn(entry.get("ISBN"))
    if a and b and a != b:
        out.append("ISBN")
    if (row.get("title") or "").strip():
        if not R.titles_match(row.get("title"), entry.get("title") or ""):
            out.append("title")
    y = (row.get("year") or "").strip()
    if y:
        try:
            ey = R.first_year(entry)
        except (TypeError, ValueError, AttributeError):
            ey = None
        if ey is None or str(ey) != re.sub(r"\D", "", unicodedata.normalize("NFKC", y))[:4]:
            out.append("year")
    names = [n for n in R.split_authors(row.get("authors") or "")]
    if names:
        known = set()
        for n in names:
            fam, _gi = R.author_key(n)
            known.add(fam)
            known.add(_norm_name(n))
        for au in entry.get("author") or []:
            if not isinstance(au, dict):
                out.append("author")
                break
            fam = _norm_name(au.get("family") or au.get("literal") or "")
            if fam and fam not in known and not any(fam and fam in k for k in known):
                out.append("author")
                break
    return out


def problems(proj, keys):
    """[(key, why)]: not in the ledger, below IDENTITY_CONFIRMED, or the bibliography entry differs from the ledger
    ("mismatch:title,year" and the like)."""
    by = _ledger_by_key(proj)
    bib = bibliography(proj)
    out = []
    for k in sorted(keys):
        r = by.get(k)
        if r is None:
            out.append((k, "not_in_ledger"))
            continue
        st = (r.get("machine_status") or "CANDIDATE").strip()
        if st != "IDENTITY_CONFIRMED":
            out.append((k, st))
            continue
        e = bib.get(k)
        if e is not None:
            mm = entry_mismatches(r, e)
            if mm:
                out.append((k, "mismatch:" + ",".join(mm)))
    return out
