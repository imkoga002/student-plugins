"""Which bibliography entries a manuscript would render, and whether each is in the ledger at IDENTITY_CONFIRMED.

Keys are read the way pandoc's citation syntax writes them: `@key`, `[@key, p. 3]`, `-@key`, `@{key with odd
characters}` and `[@{key}]`, outside inline code; cross-references (`@fig:`, `@tbl:`, `@sec:`, `@eq:`, `@lst:`)
are not citations. The YAML front matter's `nocite` (a string or a list, e.g. `nocite: '@a, @b'` or `nocite: '@*'`)
adds keys; `@*` renders every entry of the bibliography, so every id in sources/references.json counts.
Not checked: author-year mentions written as plain prose ("Smith (2020) shows ..."), and bibliography files other
than sources/references.json (a .bib or .yaml file named in the pandoc defaults is not parsed for `@*`).
"""
import json
import os
import re

from . import ledger

NONCITE = ("fig:", "tbl:", "sec:", "eq:", "lst:")
BRACED = re.compile(r"(?<![\w.])-?@\{([^}\n]+)\}")
PLAIN = re.compile(r"(?<![\w.])-?@([A-Za-z0-9_][A-Za-z0-9_:.#$%&+?<>~/-]*)")


def front_matter(text):
    lines = text.split("\n")
    if lines and lines[0].strip() == "---":
        for i in range(1, len(lines)):
            if lines[i].strip() in ("---", "..."):
                return "\n".join(lines[1:i]), "\n".join(lines[i + 1:])
    return "", text


def _keys_in(text):
    t = re.sub(r"`[^`]*`", "", text)
    out = {k.strip() for k in BRACED.findall(t)}
    t = BRACED.sub(" ", t)
    out |= {k.rstrip(".:,;") for k in PLAIN.findall(t)}
    return {k for k in out if k and not k.startswith(NONCITE)}


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


def extract(text):
    """(keys, star): the citation keys a file would render, and whether nocite '@*' is set."""
    fm, body = front_matter(text)
    keys = _keys_in(body)
    nk, star = nocite(fm)
    return keys | nk, star


def bibliography_ids(proj):
    try:
        with open(os.path.join(proj, "sources", "references.json"), encoding="utf-8") as f:
            data = json.load(f)
        return {str(x.get("id")) for x in data if isinstance(x, dict) and x.get("id") is not None}
    except (OSError, ValueError, TypeError):
        return set()


def rendered(proj, texts):
    keys, star = set(), False
    for t in texts:
        k, s = extract(t)
        keys |= k
        star = star or s
    if star:
        keys |= bibliography_ids(proj)
    return keys, star


def problems(proj, keys):
    """[(key, why)] for keys not in the ledger, or in it below IDENTITY_CONFIRMED."""
    by = {}
    for r in ledger.read(ledger.paths(proj)[0], ledger.REGISTER):
        for k in (r.get("citekey"), r.get("id")):
            if k:
                by[k] = r
    out = []
    for k in sorted(keys):
        r = by.get(k)
        if r is None:
            out.append((k, "not_in_ledger"))
        elif (r.get("machine_status") or "CANDIDATE").strip() != "IDENTITY_CONFIRMED":
            out.append((k, (r.get("machine_status") or "CANDIDATE").strip()))
    return out
