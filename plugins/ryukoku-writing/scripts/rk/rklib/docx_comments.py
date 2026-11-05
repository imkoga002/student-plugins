"""Word comment round trip: read the comments and tracked changes an advisor put into the docx.

pandoc -f docx --track-changes=all -t json keeps comments as Span(class comment-start, attrs id or
comment-id, author, date; content = the comment text) ... Span(class comment-end), and tracked changes as
Span(class insertion|deletion). The default 'accept' mode silently drops comments (pandoc manual, --track-changes,
https://pandoc.org/MANUAL.html#option--track-changes; also checked with pandoc 3.1.3 during development). pandoc >= 3.12 uses comment-id instead of id; both are read.
`rk.py docx-comments FILE.docx` (AI may run it) only lists them. Importing them as advisor annotations is a
human command (`./rk import-docx`), because the annotations are then attributed to the advisor.
The advisor's tracked insertions/deletions are never applied to the manuscript: they become annotations
that the student reads and acts on.
"""
import json
import re
import shutil
import subprocess

from .common import RkError


def _text(inlines):
    out = []
    for el in inlines or []:
        t = el.get("t")
        c = el.get("c")
        if t == "Str":
            out.append(c)
        elif t in ("Space", "SoftBreak"):
            out.append(" ")
        elif t == "LineBreak":
            out.append("\n")
        elif t in ("Emph", "Strong", "Strikeout", "Superscript", "Subscript", "SmallCaps", "Underline"):
            out.append(_text(c))
        elif t in ("Span", "Link", "Quoted", "Cite"):
            out.append(_text(c[1] if t != "Cite" else c[1]))
        elif t in ("Code", "Math"):
            out.append(c[1] if isinstance(c, list) else "")
    return "".join(out)


def _attrs(span):
    ident, classes, kv = span["c"][0]
    d = dict(kv)
    cid = d.get("comment-id") or d.get("id") or ident
    return classes, cid, d


def _flatten(blocks):
    """Yield lists of inlines, one per paragraph-like block."""
    for b in blocks:
        t, c = b.get("t"), b.get("c")
        if t in ("Para", "Plain"):
            yield c
        elif t == "Header":
            yield c[2]
        elif t in ("BlockQuote", "Div"):
            yield from _flatten(c if t == "BlockQuote" else c[1])
        elif t in ("BulletList", "OrderedList"):
            items = c if t == "BulletList" else c[1]
            for it in items:
                yield from _flatten(it)


def extract_ast(ast):
    out = []
    for inl in _flatten(ast.get("blocks", [])):
        para = _text(inl)
        open_ = {}
        for el in inl:
            if el.get("t") == "Span":
                classes, cid, d = _attrs(el)
                if "comment-start" in classes:
                    open_[cid] = {"kind": "comment", "id": cid, "author": d.get("author", ""), "date": d.get("date", ""),
                                  "comment": _text(el["c"][1]).strip(), "anchor": [], "paragraph": para}
                    continue
                if "comment-end" in classes:
                    item = open_.pop(cid, None)
                    if item:
                        item["anchor"] = "".join(item["anchor"]).strip()
                        out.append(item)
                    continue
                if "insertion" in classes or "deletion" in classes:
                    out.append({"kind": "insertion" if "insertion" in classes else "deletion", "id": cid,
                                "author": d.get("author", ""), "date": d.get("date", ""),
                                "comment": _text(el["c"][1]).strip(), "anchor": _text(el["c"][1]).strip(), "paragraph": para})
            seg = _text([el])
            for item in open_.values():
                item["anchor"].append(seg)
        for item in open_.values():  # comment spanning paragraphs: keep what we have
            item["anchor"] = "".join(item["anchor"]).strip()
            out.append(item)
    return out


def extract(docx_path):
    if not shutil.which("pandoc"):
        raise RkError("pandoc が見つからない。Word で開いてコメントを読み、レビュー画面で手で写す(手作業の経路)")
    r = subprocess.run(["pandoc", "-f", "docx", "--track-changes=all", "-t", "json", docx_path],
                       capture_output=True, timeout=120)
    if r.returncode != 0:
        raise RkError("pandoc の読み込みに失敗: " + r.stderr.decode("utf-8", "replace")[:300])
    return extract_ast(json.loads(r.stdout.decode("utf-8")))


def locate(text, anchor):
    """(start, end) of ANCHOR in TEXT, tolerating whitespace and line-break differences; None if not unique."""
    if not anchor:
        return None
    i = text.find(anchor)
    if i != -1 and text.find(anchor, i + 1) == -1:
        return i, i + len(anchor)
    pat = r"\s*".join(re.escape(ch) for ch in re.sub(r"\s+", "", anchor))
    ms = list(re.finditer(pat, text))
    if len(ms) == 1:
        return ms[0].start(), ms[0].end()
    return None
