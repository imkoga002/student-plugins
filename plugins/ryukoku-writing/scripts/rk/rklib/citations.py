"""Which bibliography entries a manuscript renders, and the bibliography the export prints.

The bibliography is generated from the ledger (sources/register.csv), never from a file the AI can edit:
  * Only rows at IDENTITY_CONFIRMED qualify. A cited key (citekey or id) that is not such a row is an error at
    `rk check --submit` and at export.
  * Each entry is built by csl_items(): the fields the machine identity check recorded from the registry
    (sources/identity.json, written by `rk.py refcheck check` only: Crossref / DataCite title, authors, editors,
    year, container, publisher, volume, issue, pages, type; CiNii / NDL the matched title) win; a field the check
    did not record (CiNii / NDL authors and year, for example) comes from the ledger row, which the AI's tools cannot
    write directly and which the student's signed VERIFIED covers at submission. A row without a title, or without
    any name (author, editor, or an issuing body written as the author), cannot be rendered: an error.
  * The export writes these entries to a temporary CSL JSON file in its work folder and passes it as the only
    bibliography, with `references: []` and the style fixed in the defaults it builds, so metadata inside the
    document cannot add or replace entries. sources/references.json is at most an input the student or refcheck
    reconciles into the ledger; it is never given to pandoc (entry_mismatches only reports how it differs).
  * Document metadata that would inject or redirect the bibliography or the style (references, bibliography, csl,
    citation-style, citation-abbreviations) is rejected wherever it appears: pandoc reads YAML metadata blocks
    anywhere in the body, so scan_document reads the `meta` of pandoc's JSON for all files joined, and a line-based
    reader looks for those keys anywhere when pandoc is missing. Raw TeX, OpenXML or HTML that builds a bibliography
    of its own (\\bibitem, thebibliography, BIBLIOGRAPHY / CITATION fields, csl-entry) is rejected too.
  * With nocite '@*', the rendered set is every qualifying ledger row.

Keys are found two ways and the union counts:
  1. pandoc itself, when it is installed: `pandoc -f markdown -t json` and every Cite node of the document and of its
     metadata (so `nocite` counts).
  2. a reader that follows pandoc's key rule (pandoc's manual, "Citation syntax", and the behaviour of the installed
     pandoc checked in the tests): a key starts with a letter, a digit or `_` and may contain letters, digits, `_` and
     internal punctuation `:.#$%&-+?<>~/`; letters and digits are Unicode ones, so `[@山田2020]` is the key
     `山田2020`; punctuation at the end is not part of the key; `@` right after a letter or digit (an e-mail address)
     or after `.` does not start a citation; `@{...}` takes any characters but `}`. Inline code, fenced code blocks
     and HTML comments are skipped. Example-list labels are not citations.
Cross-references (`@fig:`, `@tbl:`, `@sec:`, `@eq:`, `@lst:`) are not citations.

Not checked: author-year mentions and reference lists typed as plain prose ("Smith (2020) shows ...").
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
    t = FENCE.sub("", re.sub(r"(?s)<!--.*?-->", " ", text))
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


FORBIDDEN_META = ("references", "bibliography", "csl", "citation-style", "citation-abbreviations")
META_LINE = re.compile(r"(?m)^(%s)[ \t]*:" % "|".join(re.escape(k) for k in FORBIDDEN_META))
# bibliography constructs in raw TeX (pandoc's markdown passes bare TeX commands through as raw TeX)
RAW_TEX = re.compile(r"\\(?:bibitem|bibliography|addbibresource|printbibliography|bibliographystyle|nocite)\b|\\begin\s*\{thebibliography\}")
# ... and in any raw block or inline of another format (OpenXML field codes, HTML of a rendered bibliography)
RAW_BIB = re.compile(RAW_TEX.pattern + r"|thebibliography|\bBIBLIOGRAPHY\b|\bCITATION\b|csl-entry|csl-bib-body|w:fldSimple|w:instrText")
RAW_FENCE = re.compile(r"(?ms)^[ \t]*(```+|~~~+)[ \t]*\{=([A-Za-z0-9_-]+)\}[^\n]*\n(.*?)^[ \t]*\1[ \t]*$|`([^`\n]*)`\{=([A-Za-z0-9_-]+)\}")


def _strip_display_code(text):
    """Remove fenced code blocks that are not raw blocks (```{=latex} stays) and inline code."""
    t = re.sub(r"(?ms)^[ \t]*(```+|~~~+)(?![ \t]*\{=)[^\n]*\n.*?^[ \t]*\1[ \t]*$", "", text)
    return re.sub(r"`[^`\n]*`(?!\{=)", "", t)


def _walk_raw_and_cites(node, raws, cites):
    stack = [node]
    while stack:
        x = stack.pop()
        if isinstance(x, dict):
            t = x.get("t")
            if t in ("RawBlock", "RawInline") and isinstance(x.get("c"), list) and len(x["c"]) == 2:
                raws.append((str(x["c"][0]), str(x["c"][1])))
            elif t == "Cite" and isinstance(x.get("c"), list) and x["c"] and isinstance(x["c"][0], list):
                for c in x["c"][0]:
                    if isinstance(c, dict) and c.get("citationId"):
                        cites.add(str(c["citationId"]))
            stack.extend(x.values())
        elif isinstance(x, list):
            stack.extend(x)


def scan_document(texts, fmt="markdown", use_pandoc=True):
    """Read the manuscript as pandoc would: TEXTS are the files' contents in order (joined as pandoc joins several
    input files). Returns {"keys", "star", "meta_bad": [keys], "raw_bad": [snippets], "pandoc": bool}."""
    keys, star, meta_bad, raw_bad = set(), False, set(), []
    for t in texts:
        k, st = extract(t)
        keys |= k
        star = star or st
        bare = _strip_display_code(re.sub(r"(?s)<!--.*?-->", "", t))
        meta_bad |= set(META_LINE.findall(bare))
        for m in RAW_TEX.finditer(bare):
            raw_bad.append(bare[max(0, m.start() - 20):m.end() + 20].replace("\n", " "))
        for m in RAW_FENCE.finditer(bare):
            body = m.group(3) if m.group(3) is not None else (m.group(4) or "")
            if RAW_BIB.search(body):
                raw_bad.append("{=%s} %s" % (m.group(2) or m.group(5), body[:60].replace("\n", " ")))
    used = False
    exe = shutil.which("pandoc") if use_pandoc else None
    if exe and texts:
        try:
            joined = "\n\n".join(texts)
            r = subprocess.run([exe, "-f", fmt or "markdown", "-t", "json"], input=joined.encode("utf-8"), capture_output=True,
                               timeout=120, cwd=tempfile.gettempdir())
            if r.returncode == 0:
                doc = json.loads(r.stdout.decode("utf-8"))
                used = True
                meta = doc.get("meta") or {}
                meta_bad |= {k for k in meta if k in FORBIDDEN_META}
                raws, cites = [], set()
                _walk_raw_and_cites(doc, raws, cites)
                for fmt_, txt in raws:
                    if RAW_BIB.search(txt):
                        raw_bad.append("{=%s} %s" % (fmt_, txt[:60].replace("\n", " ")))
                star = star or "*" in cites
                keys |= {c for c in cites if c != "*" and not c.startswith(NONCITE)}
        except (OSError, ValueError, subprocess.SubprocessError):
            pass
    return {"keys": keys, "star": star, "meta_bad": sorted(meta_bad), "raw_bad": raw_bad[:10], "pandoc": used}


def bibliography(proj):
    """{id: entry} of sources/references.json (CSL JSON): only for the informational comparison."""
    try:
        with open(os.path.join(proj, "sources", "references.json"), encoding="utf-8") as f:
            data = json.load(f)
        return {str(x.get("id")): x for x in data if isinstance(x, dict) and x.get("id") is not None}
    except (OSError, ValueError, TypeError, AttributeError):
        return {}


def _ledger_by_key(proj):
    by = {}
    for r in ledger.read(ledger.paths(proj)[0], ledger.REGISTER):
        for k in (r.get("id"), r.get("citekey")):
            if k:
                by[k] = r
    return by


def qualifying(proj):
    """{primary key: row} of the rows at IDENTITY_CONFIRMED (primary key: citekey, else id)."""
    out = {}
    for r in ledger.read(ledger.paths(proj)[0], ledger.REGISTER):
        if (r.get("machine_status") or "").strip() == "IDENTITY_CONFIRMED":
            out[(r.get("citekey") or r.get("id") or "").strip()] = r
    out.pop("", None)
    return out


def rendered(proj, texts, use_pandoc=True):
    sc = scan_document(texts, use_pandoc=use_pandoc)
    keys = set(sc["keys"])
    if sc["star"]:
        keys |= set(qualifying(proj))
    return keys, sc["star"]


EDITOR_MARK = re.compile(r"\s*(\((?:ed|eds|編|編著|監修)\.?\)|編著?|監修)$", re.I)


def parse_names(s):
    """Ledger 'authors' ("Family, Given; ..." or "山田 太郎; ...") -> (authors, editors) as CSL names. A name without a
    separator (an organisation, or a name written as one word) is a literal."""
    from .refcheck import split_authors
    authors, editors = [], []
    for raw in split_authors(s or ""):
        n = unicodedata.normalize("NFKC", raw).strip()
        role = authors
        m = EDITOR_MARK.search(n)
        if m:
            role, n = editors, n[:m.start()].strip()
        if not n:
            continue
        if "," in n:
            fam, giv = [x.strip() for x in n.split(",", 1)]
            d = {"family": fam, "given": giv} if giv else {"family": fam}
        elif " " in n:
            parts = n.split()
            if re.search(r"[\u3040-\u30ff\u3400-\u9fff]", n):
                d = {"family": parts[0], "given": " ".join(parts[1:])}
            else:
                d = {"family": parts[-1], "given": " ".join(parts[:-1])}
        else:
            d = {"literal": n}
        role.append(d)
    return authors, editors


CROSSREF_TYPES = {"journal-article": "article-journal", "book-chapter": "chapter", "proceedings-article": "paper-conference",
                  "book": "book", "monograph": "book", "edited-book": "book", "reference-book": "book", "report": "report",
                  "dissertation": "thesis", "posted-content": "article", "dataset": "dataset"}


def _identity_meta(proj, row, ident):
    rec = ident.get(row.get("id"))
    if not rec:
        return {}, ""
    if rec.get("digest") != ledger.source_subject(row):
        return {}, "identity_stale"
    return rec.get("meta") or {}, ""


def csl_item(key, row, meta):
    """(CSL JSON item, [missing fields]) for KEY from ledger ROW and the registry META the identity check recorded."""
    authors, editors = parse_names(row.get("authors"))
    item = {"id": key}
    title = (meta.get("title") or row.get("title") or "").strip()
    if title:
        item["title"] = title
    a = meta.get("author") or authors
    e = meta.get("editor") or editors
    if a:
        item["author"] = a
    if e:
        item["editor"] = e
    y = str(meta.get("year") or "").strip() or re.sub(r"\D", "", unicodedata.normalize("NFKC", row.get("year") or ""))[:4]
    if y.isdigit():
        item["issued"] = {"date-parts": [[int(y)]]}
    cont = meta.get("container-title") or (row.get("container") or "").strip()
    if cont:
        item["container-title"] = cont
    for k in ("publisher", "volume", "issue", "page"):
        if meta.get(k):
            item[k] = meta[k]
    from .refcheck import clean_isbn, normalize_doi
    if row.get("doi"):
        item["DOI"] = normalize_doi(row.get("doi"))
    if row.get("isbn"):
        item["ISBN"] = clean_isbn(row.get("isbn"))
    if (row.get("url") or "").strip():
        item["URL"] = row["url"].strip()
    t = CROSSREF_TYPES.get(str(meta.get("type") or ""))
    if not t:
        t = "book" if (row.get("isbn") or row.get("ncid") or row.get("ndl_id")) else ("article-journal" if row.get("doi") else "document")
    item["type"] = t
    missing = []
    if not title:
        missing.append("title")
    if not (a or e):
        missing.append("author/editor/issuer")
    return item, missing


def csl_items(proj, keys, star=False):
    """(items for the generated bibliography, {key: why} for keys that cannot be rendered). KEYS: the cited keys;
    with STAR every qualifying row is included."""
    by = _ledger_by_key(proj)
    ident = ledger.read_identity(proj)
    want = set(keys) | (set(qualifying(proj)) if star else set())
    items, bad = [], {}
    for k in sorted(want):
        r = by.get(k)
        if r is None or (r.get("machine_status") or "").strip() != "IDENTITY_CONFIRMED":
            continue
        meta, why = _identity_meta(proj, r, ident)
        if why:
            bad[k] = why
            continue
        it, missing = csl_item(k, r, meta)
        if missing:
            bad[k] = "missing:" + ",".join(missing)
            continue
        items.append(it)
    return items, bad


def problems(proj, keys):
    """[(key, why)]: not in the ledger, below IDENTITY_CONFIRMED, or a qualifying row that cannot be rendered
    ("missing:title", "identity_stale")."""
    by = _ledger_by_key(proj)
    _items, bad = csl_items(proj, keys)
    out = []
    for k in sorted(keys):
        r = by.get(k)
        if r is None:
            out.append((k, "not_in_ledger"))
            continue
        st = (r.get("machine_status") or "CANDIDATE").strip()
        if st != "IDENTITY_CONFIRMED":
            out.append((k, st))
        elif k in bad:
            out.append((k, bad[k]))
    return out


# ------------------------------------------------------------------------------------------------ informational
def _nt(s):
    from .refcheck import normalize_text
    return normalize_text(re.sub(r"<[^>]+>", " ", str(s or "")))


def _names_norm(lst):
    out = []
    for a in lst or []:
        if isinstance(a, dict):
            out.append(_nt(" ".join(str(a.get(k, "")) for k in ("literal", "family", "given"))).replace(" ", ""))
    return sorted(out)


def entry_mismatches(row, entry, meta=None):
    """[field] where a CSL entry (e.g. in sources/references.json) differs from what the export would print for the
    ledger ROW: exact comparison after normalisation (title, every name of every role, DOI and ISBN when either side
    has one, container title, issued year; other fields of the entry are listed as 'extra'). Informational only:
    the export never prints the entry."""
    item, _m = csl_item(entry.get("id") or "", row, meta or {})
    out = []
    if _nt(item.get("title")) != _nt(entry.get("title")):
        out.append("title")
    for role in ("author", "editor", "translator", "container-author", "collection-editor", "director", "interviewer",
                 "composer", "recipient", "reviewed-author"):
        if _names_norm(item.get(role)) != _names_norm(entry.get(role)):
            out.append(role)
    from .refcheck import clean_isbn, first_year, normalize_doi
    if normalize_doi(item.get("DOI")) != normalize_doi(entry.get("DOI")):
        out.append("DOI")
    if clean_isbn(item.get("ISBN")) != clean_isbn(entry.get("ISBN")):
        out.append("ISBN")
    if _nt(item.get("container-title")) != _nt(entry.get("container-title")):
        out.append("container-title")
    try:
        ey = first_year(entry)
    except (TypeError, ValueError, AttributeError):
        ey = None
    iy = (item.get("issued") or {}).get("date-parts", [[None]])[0][0]
    if iy != ey:
        out.append("issued")
    known = {"id", "type", "title", "issued", "DOI", "ISBN", "URL", "container-title", "publisher", "volume", "issue",
             "page", "language", "author", "editor"}
    extra = sorted(k for k in entry if k not in known and entry.get(k))
    if extra:
        out.append("extra:" + "/".join(extra[:5]))
    return out
