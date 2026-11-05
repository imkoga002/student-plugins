"""Overlap check between the manuscript and source excerpts the student saved.

excerpts/<anything>.md|.txt  : text the student copied from a source while reading, with a first line
                                 'source_id: S001' (the register id). Kept out of Git by default when the
                                 source's licence does not allow sharing (see templates/common/.gitignore).
For every run of at least N shared characters (Japanese: characters after removing spaces; English: N/4
words) the report shows where it is, which excerpt it comes from, and whether it is
  - marked as a quotation (inside 「」『』“” "" or a '>' block quote)        -> 明瞭区別性 (JSPS 第2版 Ⅳ-5.4.1)
  - followed by a citation in the same paragraph ([@key], [^n], （著者 年）) -> 出所の明示 (著作権法48条)
Overlaps that are neither are listed first. The tool never decides plagiarism; a person reads each one.
Japanese is compared as character n-grams because Japanese text has no spaces between words.
"""
import os
import re
import unicodedata

CITE_RE = re.compile(r"\[[^\]]*@[^\]]*\]|\[\^[^\]]+\]|[（(][^（）()]{0,40}[0-9]{4}[^（）()]{0,20}[）)]")


def _norm_map(text):
    """Return (normalised chars, index map to the original) dropping whitespace."""
    out, idx = [], []
    for i, ch in enumerate(text):
        c = unicodedata.normalize("NFKC", ch).lower()
        for cc in c:
            if not cc.isspace():
                out.append(cc)
                idx.append(i)
    return "".join(out), idx


def load_excerpts(proj):
    d = os.path.join(proj, "excerpts")
    out = []
    if not os.path.isdir(d):
        return out
    for fn in sorted(os.listdir(d)):
        if fn.lower().endswith((".md", ".txt")) and not fn.lower().startswith("readme"):
            with open(os.path.join(d, fn), encoding="utf-8") as f:
                text = f.read()
            m = re.match(r"^\s*source_id:\s*(\S+)", text)
            sid = m.group(1) if m else "(source_id 未記入)"
            body = text[m.end():] if m else text
            out.append((fn, sid, body))
    return out


def _quoted(text, start, end):
    line_start = text.rfind("\n", 0, start) + 1
    if text[line_start:start].lstrip().startswith(">"):
        return True
    for a, b in (("「", "」"), ("『", "』"), ("“", "”")):
        o = text.rfind(a, 0, start)
        c = text.rfind(b, 0, start)
        if o > c and text.find(b, end - 1) != -1:
            return True
    before = text[line_start:start]
    if before.count('"') % 2 == 1:
        return True
    return False


def _cited(text, end):
    para_end = text.find("\n\n", end)
    para_end = len(text) if para_end == -1 else para_end
    return bool(CITE_RE.search(text[end:para_end]))


def find(ms_text, ex_text, n=12):
    a, ai = _norm_map(ms_text)
    b, _ = _norm_map(ex_text)
    if len(a) < n or len(b) < n:
        return []
    grams = {}
    for i in range(len(b) - n + 1):
        grams.setdefault(b[i:i + n], i)
    spans, i = [], 0
    while i <= len(a) - n:
        if a[i:i + n] in grams:
            j = i + n
            while j < len(a) and grams.get(a[j - n + 1:j + 1]) is not None:
                j += 1
            spans.append((ai[i], ai[j - 1] + 1))
            i = j
        else:
            i += 1
    return spans


def report(proj, files, n=12):
    exs = load_excerpts(proj)
    rows = []
    for path in files:
        with open(path, encoding="utf-8") as f:
            text = f.read()
        for fn, sid, body in exs:
            nn = n if re.search(r"[぀-ヿ㐀-鿿]", body) else max(n * 3, 30)
            for s, e in find(text, body, nn):
                line = text.count("\n", 0, s) + 1
                rows.append({"file": os.path.relpath(path, proj).replace(os.sep, "/"), "line": line, "excerpt": fn,
                             "source_id": sid, "text": text[s:e].replace("\n", " "),
                             "quoted": _quoted(text, s, e), "cited": _cited(text, e)})
    rows.sort(key=lambda r: (r["quoted"] or r["cited"], r["file"], r["line"]))
    return rows


def to_markdown(rows):
    if not rows:
        return "重なりは見つからなかった(保存した抜粋の範囲で。抜粋にない資料は調べていない)。\n"
    out = ["| 判断の要否 | 箇所 | 抜粋(出典) | 引用符 | 出典表示 | 重なり |", "|---|---|---|---|---|---|"]
    for r in rows:
        need = "要確認" if not (r["quoted"] and r["cited"]) else "引用の形あり"
        out.append("| %s | %s:%d | %s (%s) | %s | %s | %s |" % (
            need, r["file"], r["line"], r["excerpt"], r["source_id"], "あり" if r["quoted"] else "なし",
            "あり" if r["cited"] else "なし", r["text"][:80].replace("|", "\\|")))
    out.append("")
    out.append("判定は人間が行う。引用なら「」かブロック引用で区別し出典を示す(著作権法32条・48条、JSPS 第2版 Ⅳ-5.4.1)。"
               "言い換えるなら自分の言葉で書き、出典を示す。")
    return "\n".join(out) + "\n"
