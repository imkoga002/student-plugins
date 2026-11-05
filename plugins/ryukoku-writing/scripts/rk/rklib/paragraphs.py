"""Paragraphs of a manuscript file: the unit that provenance, the number lint and the verification work on.

A block is a run of non-empty lines separated by blank lines. The YAML front matter at the top and a fenced code
block are one block each, whatever blank lines they contain. A block whose first line is an ATX heading
(`#`..`######`) is a heading; everything else is a paragraph (lists, tables, block quotes and footnote
definitions included). Line numbers are 1-based and inclusive. The hash is the SHA-256 of the block text with
trailing spaces of each line removed, so re-saving a file without real changes does not look like an edit.
"""
import difflib
import re

from .common import sha256_bytes

HEADING = re.compile(r"^\s{0,3}(#{1,6})\s+(.*?)\s*#*\s*$")
FENCE = re.compile(r"^\s{0,3}(```+|~~~+)")
FOOTDEF = re.compile(r"^\[\^([^\]]+)\]:\s*(.*)$")


def norm(text):
    return "\n".join(ln.rstrip() for ln in text.strip("\n").split("\n"))


def phash(text):
    return sha256_bytes(norm(text).encode("utf-8"))


def blocks(text):
    """[{start, end, text, kind: heading|paragraph|frontmatter|code|comment, sha, section}] in file order. An HTML
    comment that starts a block runs to its closing -->."""
    lines = text.split("\n")
    out = []
    i, n = 0, len(lines)
    section = ""
    if n and lines[0].strip() == "---":
        j = 1
        while j < n and lines[j].strip() not in ("---", "..."):
            j += 1
        if j < n:
            out.append(_mk(lines, 0, j, "frontmatter", section))
            i = j + 1
    while i < n:
        if not lines[i].strip():
            i += 1
            continue
        m = FENCE.match(lines[i])
        if m:
            mark = m.group(1)[0] * 3
            j = i + 1
            while j < n and not lines[j].lstrip().startswith(mark):
                j += 1
            j = min(j, n - 1)
            out.append(_mk(lines, i, j, "code", section))
            i = j + 1
            continue
        h = HEADING.match(lines[i])
        if h:
            section = re.sub(r"\s*\{[^}]*\}\s*$", "", h.group(2)).strip()
            out.append(_mk(lines, i, i, "heading", section))
            i += 1
            continue
        if lines[i].lstrip().startswith("<!--"):
            j = i
            while j < n - 1 and "-->" not in lines[j]:
                j += 1
            out.append(_mk(lines, i, j, "comment", section))
            i = j + 1
            continue
        j = i
        while j + 1 < n and lines[j + 1].strip() and not HEADING.match(lines[j + 1]) and not FENCE.match(lines[j + 1]):
            j += 1
        out.append(_mk(lines, i, j, "paragraph", section))
        i = j + 1
    return out


def _mk(lines, i, j, kind, section):
    t = "\n".join(lines[i:j + 1])
    return {"start": i + 1, "end": j + 1, "text": t, "kind": kind, "sha": phash(t), "section": section}


def paragraphs(text):
    return [b for b in blocks(text) if b["kind"] == "paragraph"]


def footnotes(text):
    """{label: definition text} of the footnote definitions ([^label]: ...)."""
    out = {}
    for b in paragraphs(text):
        m = FOOTDEF.match(b["text"].split("\n")[0])
        if m:
            out[m.group(1)] = b["text"]
    return out


def diff(old_text, new_text):
    """What changed between two versions, paragraph by paragraph:
    [{"op": "insert"|"replace"|"delete", "old": block or None, "new": block or None}]. A replaced run is paired
    one to one in order; extra blocks on either side become inserts or deletes. Headings, front matter and code
    count as blocks too (the caller decides what to record)."""
    a = [b for b in blocks(old_text or "") if b["kind"] != "frontmatter"]
    b = [x for x in blocks(new_text or "") if x["kind"] != "frontmatter"]
    sm = difflib.SequenceMatcher(None, [x["sha"] for x in a], [x["sha"] for x in b], autojunk=False)
    out = []
    for op, i1, i2, j1, j2 in sm.get_opcodes():
        if op == "equal":
            continue
        olds, news = a[i1:i2], b[j1:j2]
        k = 0
        while k < max(len(olds), len(news)):
            o = olds[k] if k < len(olds) else None
            w = news[k] if k < len(news) else None
            out.append({"op": "replace" if (o and w) else ("insert" if w else "delete"), "old": o, "new": w})
            k += 1
    return out


def similarity(a, b):
    return difflib.SequenceMatcher(None, a or "", b or "", autojunk=False).ratio()
