"""Proposal files: the only way AI output reaches manuscript/ (direction A).

A proposal is a unified diff for one manuscript file, preceded by '# key: value' header lines:

  # rk-proposal: 1
  # id: P0003
  # status: pending            pending | done
  # kind: format               format | citation | diagram | heading
  # target: manuscript/01-intro.md
  # base_sha256: <sha256 of the target when the proposal was made>
  # created: 2026-11-04T12:00:00+0900
  # by: ai                     ai | tool (a deterministic fixer run by the AI)
  # model: <model name or unknown>
  # rule: punct                (optional) approved style rule id
  # why: <one line: why this is proposed>
  # decided: 1=y,2=n           (filled by ./rk apply; hunks not listed are still pending)
  --- a/manuscript/01-intro.md
  +++ b/manuscript/01-intro.md
  @@ -3,3 +3,3 @@ <note for this hunk>
   context
  -old
  +new
   context

Content invariance (the mechanical check that a proposal never changes the student's words, numbers or marks).
It is an ALLOW-list: both sides are reduced to a canonical form using only the
transforms below, and the hunk is refused unless the canonical forms are exactly equal, line by line (the number
of lines may not change). Every other character change -- letters, digits, decimal points, signs, operators,
arrows, symbols, quotation marks, Markdown marks, invisible characters, look-alike letters, citation pages --
is a content change.
  format   (1) full-width <-> half-width forms of letters and digits (and half-width katakana), (2) the
           punctuation systems a course can configure: 、 <-> ，  and  。 <-> ．  (never a point or comma between
           digits: 10.5 stays 10.5), (3) whitespace that only touches Japanese characters, trailing whitespace and
           full-width spaces at the start of a line (spaces between two Latin words or digits, and the indentation
           that makes Markdown structure, are kept)
  heading  the format transforms, plus the numbering prefix of a heading line (the level, # vs ##, is kept)
  citation the format transforms, plus the form of an existing citation: "(Author Year)" <-> [@key] when
           sources/references.json gives that key the same author family name(s) and year; every citation keeps its
           place in the text, its pages, prefix and suffix; none is added or removed
  diagram  only lines inside ```mermaid blocks, and only front-matter config lines (---, config:, theme:, look:,
           layout:) may be added or removed; every other line stays exactly as it is
Anything else is refused when the proposal is made AND again when it is applied (a hand-edited proposal file
cannot slip through). Content issues go to the student as questions (annotations), never as proposals.
"""
import difflib
import json
import os
import re
import unicodedata

from .common import RkError, now_iso, sha256_bytes, sha256_file

KINDS = ("format", "citation", "diagram", "heading")
HEADER_RE = re.compile(r"^# ([a-z_0-9-]+): ?(.*)$")
HUNK_RE = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@ ?(.*)$")
CONFIG_LINE = re.compile(r"^\s*(---|config:|theme:\s*[\w-]+|look:\s*[\w-]+|layout:\s*[\w-]+)\s*$")
HEADING = re.compile(r"^(#{1,6})\s+")
HEADING_NUM = re.compile(r"^(#{1,6})\s*((第[0-9０-９一二三四五六七八九十百]+[章節項])|([0-9０-９]+([.．][0-9０-９]+)*[.．]?))?\s*")


# ---------------------------------------------------------------- invariance (allow-list canonical form)
COMMA_T, PERIOD_T, CITE_T = "\x10", "\x11", "\x12"
COMMA_SYS = set("、，､")            # the configurable reading commas (、 ， and half-width ､)
PERIOD_SYS = set("。．｡")           # the configurable full stops (。 ． and half-width ｡)
DIGITS = set("0123456789０１２３４５６７８９")
WIDTH_SYMBOLS = set("％（）：；！？%():;!?")   # full-width / ASCII pairs that carry no content difference
LINE_WS = " \t　"
INVISIBLE = set("­͏؜ᅟᅠ឴឵᠎​‌‍‎‏‪‫‬"
                "‭‮⁠⁡⁢⁣⁤⁦⁧⁨⁩⁪⁫⁬⁭"
                "⁮⁯ㅤ﻿ﾠ")
PANDOC_CITE = re.compile(r"\[[^\[\]]*@[^\[\]]*\]")
PAREN_CITE = re.compile(r"[（(][^（）()]{0,60}?[0-9０-９]{4}[a-zａ-ｚ]?[^（）()]{0,30}[）)]")
YEAR_RE = re.compile(r"(?<![0-9])([12][0-9]{3})(?![0-9])")
KEY_RE = re.compile(r"(-?)@([A-Za-z0-9_][A-Za-z0-9_:.#$%&+?<>~/-]*)")
AUTHOR_GLUE = {"et", "al", "al.", "and", "&", "ほか", "他", "ら", "・"}


def _width_char(ch):
    """Full-width/half-width form of a letter, digit or katakana -> its ordinary form. Nothing else."""
    o = ord(ch)
    if 0xFF10 <= o <= 0xFF19 or 0xFF21 <= o <= 0xFF3A or 0xFF41 <= o <= 0xFF5A or 0xFF65 <= o <= 0xFF9F:
        return unicodedata.normalize("NFKC", ch)
    return ch


def _cls(ch):
    """'w' a Latin-type letter or digit, 'j' a Japanese (wide) character, 's' anything else (symbols, marks).
    The punctuation and citation placeholders count as Japanese: a space next to them carries no meaning."""
    if not ch:
        return "e"
    if ch in (COMMA_T, PERIOD_T, CITE_T):
        return "j"
    if unicodedata.east_asian_width(ch) in ("W", "F"):
        return "j"
    if ch.isalnum():
        return "w"
    return "s"


def canon_line(line):
    """The canonical form of one line under the format allow-list (see the module docstring)."""
    line = line.rstrip(LINE_WS)
    m = re.match(r"^[ \t　]*", line)
    lead = m.group(0).replace("　", "")         # full-width spaces at the start: allowed; ASCII indent: kept
    raw = line[m.end():]
    body = []
    n = len(raw)
    for i, ch in enumerate(raw):
        prev_d = i > 0 and raw[i - 1] in DIGITS
        next_d = i + 1 < n and raw[i + 1] in DIGITS
        if ch in COMMA_SYS or ch in PERIOD_SYS:
            if prev_d and next_d:                          # a decimal point / digit separator: its form only
                body.append(unicodedata.normalize("NFKC", ch) if ch in "，．" else ch)
            else:
                body.append(COMMA_T if ch in COMMA_SYS else PERIOD_T)
        elif ch in WIDTH_SYMBOLS:
            # full-width ％（）：；！？ <-> ASCII, except where the ASCII form would become Markdown: "](" makes
            # a link, "![" an image and "]:" a footnote or link definition
            prev = raw[i - 1] if i else ""
            nxt = raw[i + 1] if i + 1 < n else ""
            if (ch in "（(:：" and prev == "]") or (ch in "！!" and nxt == "["):
                body.append(ch)
            else:
                body.append(unicodedata.normalize("NFKC", ch))
        else:
            body.append(_width_char(ch))
    s = unicodedata.normalize("NFC", "".join(body))
    out, i, n = [], 0, len(s)
    while i < n:
        ch = s[i]
        if ch in LINE_WS:
            j = i
            while j < n and s[j] in LINE_WS:
                j += 1
            a = _cls(s[i - 1]) if i else "e"
            b = _cls(s[j]) if j < n else "e"
            pair = {a, b}
            if "s" in pair or pair == {"w"}:
                out.append(" ")                            # between Latin words / next to a mark: significant
            i = j
            continue
        out.append(ch)
        i += 1
    return lead + "\x00" + "".join(out)


def canon(lines):
    return [canon_line(x) for x in lines]


def signature(text):
    """Letters and digits only (NFKC). Kept for callers that only need a rough 'same words' test."""
    s = unicodedata.normalize("NFKC", text)
    return "".join(ch for ch in s if unicodedata.category(ch)[0] in "LN" or unicodedata.category(ch) == "Mn")


def format_signature(text):
    """Canonical form of a whole text (lines joined); equal forms = the change is a pure format change."""
    return "\n".join(canon(text.split("\n")))


def _mermaid_regions(lines):
    inside, out = False, set()
    for i, ln in enumerate(lines):
        s = ln.strip()
        if not inside and re.match(r"^```+\s*\{?\.?mermaid", s):
            inside = True
            out.add(i)
            continue
        if inside:
            out.add(i)
            if s.startswith("```"):
                inside = False
    return out


def _refs(proj):
    """{key: ([author family names], year)} from sources/references.json (CSL-JSON)."""
    p = os.path.join(proj, "sources", "references.json") if proj else ""
    try:
        with open(p, encoding="utf-8") as f:
            items = json.load(f)
    except (OSError, ValueError):
        return {}
    out = {}
    for it in items if isinstance(items, list) else []:
        if not isinstance(it, dict) or not it.get("id"):
            continue
        y = None
        dp = ((it.get("issued") or {}).get("date-parts") or [[None]])
        if dp and dp[0] and dp[0][0]:
            y = str(dp[0][0])
        fams = []
        for au in (it.get("author") or it.get("editor") or []):
            if isinstance(au, dict):
                f = au.get("family") or au.get("literal") or ""
                if f:
                    fams.append(unicodedata.normalize("NFKC", f).strip())
        out[str(it["id"])] = (fams, y)
    return out


def _tokens(text):
    """Canonical tokens of a citation's free text (pages, prefix, suffix): split on spaces and list separators."""
    c = canon_line(text).split("\x00", 1)[1]
    c = c.replace(COMMA_T, " ").replace(";", " ").replace("；", " ")
    c = re.sub(r"(?<![0-9]),|,(?![0-9])", " ", c)
    return [t for t in c.split(" ") if t]


def _pandoc_parts(span):
    """[@a, p. 3; see @b] -> [(prefix_tokens, suppress, key, suffix_tokens), ...]"""
    out = []
    for part in span[1:-1].split(";"):
        m = KEY_RE.search(part)
        if not m:
            return None
        out.append((_tokens(part[:m.start()]), m.group(1), m.group(2), _tokens(part[m.end():])))
    return out


def _paren_to_keys(paren, parts, refs):
    """'(Walters 2023, p. 3)' -> [@walters2023, p. 3]: same family names and year, and the same pages/words."""
    body = unicodedata.normalize("NFC", paren[1:-1])
    norm = "".join(_width_char(c) for c in body)
    if len(YEAR_RE.findall(norm)) != len(parts):
        return False, "年の数と文献の数が合わない / the number of years and works differ"
    rest = norm
    for _pre, sup, key, _suf in parts:
        fams, y = refs.get(key, ([], None))
        if not y or not re.search(r"(?<![0-9])%s[a-z]?(?![0-9])" % y, rest):
            return False, "references.json の %s の発行年が括弧の中に無い / year of %s not in the parenthesis" % (key, key)
        rest = re.sub(r"(?<![0-9])%s[a-z]?(?![0-9])" % y, " ", rest, count=1)
        if not sup:
            if not fams or fams[0] not in rest:
                return False, ("references.json の %s の第一著者の姓が括弧の中に無い / first author of %s not in the parenthesis"
                               % (key, key))
        for f in fams:
            rest = rest.replace(f, " ", 1)
    left = [t for t in _tokens(rest) if t.lower() not in AUTHOR_GLUE]
    right = []
    for pre, _sup, _key, suf in parts:
        right += pre + suf
    if left != right:
        return False, ("頁・語句が変わる(%s → %s) / pages or words change" % (" ".join(left) or "∅", " ".join(right) or "∅"))
    return True, ""


def _cite_line(old, new, refs):
    """Citation hunks, one line pair. Citations become placeholders so their places are fixed."""
    def spans(s):
        found = []
        for kind, rx in (("p", PANDOC_CITE), ("a", PAREN_CITE)):
            for m in rx.finditer(s):
                if not any(m.start() < e and st < m.end() for st, e, _k, _t in found):
                    found.append((m.start(), m.end(), kind, m.group(0)))
        return sorted(found)

    so, sn = spans(old), spans(new)

    def holed(s, sp):
        out, last = [], 0
        for st, e, _k, _t in sp:
            out.append(s[last:st])
            out.append(CITE_T)
            last = e
        out.append(s[last:])
        return "".join(out)

    if len(so) != len(sn):
        return False, "引用の数が変わる(新しい引用の付加・既存の引用の削除は提案にできない) / the number of citations changes"
    if canon_line(holed(old, so)) != canon_line(holed(new, sn)):
        return False, ("引用の外の文、または引用の位置が変わる / the text outside the citations, or a citation's place, changes: "
                       + _explain([holed(old, so)], [holed(new, sn)]))
    for (_s1, _e1, k1, t1), (_s2, _e2, k2, t2) in zip(so, sn):
        if k1 == "a" and k2 == "a":
            if canon_line(t1) != canon_line(t2):
                return False, "括弧の中の語・数字が変わる / words or numbers in the parenthesis change: %s → %s" % (t1, t2)
            continue
        if k1 == "p" and k2 == "p":
            a, b = _pandoc_parts(t1), _pandoc_parts(t2)
            if a is None or b is None or a != b:
                return False, ("引用の鍵・頁・接頭辞・接尾辞が変わる(頁を足す・変える・contra などを足すことはできない) / "
                               "the key, pages, prefix or suffix of a citation change: %s → %s" % (t1, t2))
            continue
        paren, pan = (t1, t2) if k1 == "a" else (t2, t1)
        parts = _pandoc_parts(pan)
        if parts is None:
            return False, "引用の形を読めない / cannot read the citation: %s" % pan
        ok, why = _paren_to_keys(paren, parts, refs)
        if not ok:
            return False, "同じ文献の書式の変更と確かめられない / not the same work in another form: %s → %s (%s)" % (t1, t2, why)
    return True, ""


def check_hunk(kind, old_lines, new_lines, old_all=None, new_all=None, old_idx=None, new_idx=None, proj=None):
    """Return (ok, reason). old_idx/new_idx: 0-based indices of the changed lines in old_all/new_all."""
    if kind not in KINDS:
        return False, "unknown kind %r (format|citation|diagram|heading)" % kind
    if kind == "diagram":
        if old_all is None or new_all is None:
            return False, "diagram の検査には全文が要る"
        ro, rn = _mermaid_regions(old_all), _mermaid_regions(new_all)
        if any(i not in ro for i in (old_idx or [])) or any(i not in rn for i in (new_idx or [])):
            return False, "Mermaid のコードブロックの外が変わる / change outside a ```mermaid block"
        a = [x.rstrip() for x in old_lines if not CONFIG_LINE.match(x)]
        b = [x.rstrip() for x in new_lines if not CONFIG_LINE.match(x)]
        if a != b:
            return False, ("front matter の設定(theme・look・layout)以外の行が変わる(図の中身は変えられない)"
                           " / a line other than the front-matter config changes")
        return True, ""
    if len(old_lines) != len(new_lines):
        return False, ("行の数が変わる(行の追加・削除・結合・分割は内容や構造の変更) / the number of lines changes "
                       "(adding, removing, joining or splitting lines changes content or structure)")
    if kind == "format":
        if canon(old_lines) != canon(new_lines):
            return False, _explain(old_lines, new_lines)
        for a, b in zip(old_lines, new_lines):
            why = _marker_or_math_change(a, b)
            if why:
                return False, why
        return True, ""
    if kind == "heading":
        if new_all is None or new_idx is None:
            return False, "見出しの番号の検査には全文が要る / the heading check needs the whole file"
        expected = heading_numbers(new_all)
        for k, (a, b) in enumerate(zip(old_lines, new_lines)):
            if not a.strip() and not b.strip():
                continue
            ha, hb = heading_parts(a), heading_parts(b)
            if not ha or not hb:
                return False, "見出し以外の行が変わる / a non-heading line changes"
            if ha[0] != hb[0]:
                return False, "見出しの段(# の数)が変わる / the heading level changes"
            if canon_line(ha[0] + " " + ha[2]) != canon_line(hb[0] + " " + hb[2]):
                return False, "見出しの番号以外が変わる / more than the heading number changes: " + _explain([a], [b])
            if hb[1] is not None and hb[1] != ha[1]:
                want = expected.get(new_idx[k] if k < len(new_idx) else -1)
                if not want or not _number_matches(hb[1], want):
                    return False, ("見出しの番号は道具が段と順番から決める(%s)。提案の番号 %s はそれと違う / heading numbers are computed "
                                   "from level and order (%s); %s differs" % (want or "-", hb[1], want or "-", hb[1]))
        return True, ""
    refs = _refs(proj)
    for a, b in zip(old_lines, new_lines):
        ok, why = _cite_line(a, b, refs)
        if not ok:
            return False, why
    return True, ""


UNIT_AFTER_NUMBER = re.compile(r"^(年|年代|年度|つ|個|倍|%|％|人|件|名|回|日|月|時|分|秒|歳|割|万|億|千|百|点|位|度|か|カ|ヶ|ケ|本|冊|枚|社|校|国|種|項目|段階|世紀|号|円|ドル|kg|km|cm|mm|m\b)")
HEADING_NUMBER = re.compile(r"^(#{1,6})[ \t]+((?:第[0-9０-９一二三四五六七八九十百]+[章節項])|(?:[0-9０-９]+(?:[.．][0-9０-９]+){0,2}[.．]?))[ \t\u3000]+(.*)$")


def heading_parts(line):
    """'## 1.2 方法' -> ('##', '1.2', '方法'); '# 1990 年代の状況' -> ('#', None, '1990 年代の状況') because a number
    followed by a unit (年代・つ・倍・% …) is content, not a section number."""
    m = HEADING.match(line)
    if not m:
        return None
    hashes = m.group(1)
    mm = HEADING_NUMBER.match(line.rstrip())
    if mm and not UNIT_AFTER_NUMBER.match(mm.group(3)):
        return hashes, mm.group(2), mm.group(3)
    return hashes, None, line[m.end():].rstrip()


def _kanji_number(t):
    digits = {"一": 1, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9}
    t = unicodedata.normalize("NFKC", t)
    if t.isdigit():
        return int(t)
    n, cur = 0, 0
    for ch in t:
        if ch in digits:
            cur = digits[ch]
        elif ch == "十":
            n += (cur or 1) * 10
            cur = 0
        elif ch == "百":
            n += (cur or 1) * 100
            cur = 0
        else:
            return None
    return n + cur


def heading_numbers(lines):
    """{line index: 'N.N'} - the numbers the headings of LINES should carry, from their levels and order. Levels
    above the highest numbered level (a title) are not numbered. The AI cannot choose a number."""
    parts, fence = [], False
    for i, ln in enumerate(lines):
        if ln.strip().startswith("```"):
            fence = not fence
            continue
        if fence:
            continue
        hp = heading_parts(ln)
        if hp:
            parts.append((i, len(hp[0]), hp[1]))
    numbered = [lv for _i, lv, num in parts if num is not None]
    if not numbered:
        top = min((lv for _i, lv, _n in parts), default=1)
    else:
        top = min(numbered)
    out, counters = {}, {}
    for i, lv, _num in parts:
        if lv < top:
            counters = {}
            continue
        counters[lv] = counters.get(lv, 0) + 1
        for deeper in [x for x in counters if x > lv]:
            del counters[deeper]
        out[i] = ".".join(str(counters.get(x, 0)) for x in range(top, lv + 1))
    return out


def _number_matches(num, want):
    n = unicodedata.normalize("NFKC", num).replace("．", ".").rstrip(".")
    if n.startswith("第"):
        v = _kanji_number(n[1:-1])
        return v is not None and str(v) == want.split(".")[-1]
    return n == want


LINE_MARKERS = set(":~%#>+-*|")


def _lead_marker(line):
    """The Markdown block marker at the start of the line (after optional whitespace), or '' - computed on the RAW
    line so a full-width character does not count as a marker."""
    t = line.lstrip(" \t\u3000")
    return t[0] if t[:1] in LINE_MARKERS else ""


def _math_mask(line):
    """Indices of LINE that are inside a $...$ or $$...$$ span, or on a raw-TeX line."""
    n = len(line)
    if re.match(r"^\s*\\[A-Za-z]", line) or "\\(" in line or "\\[" in line:
        return set(range(n))
    mask, i, indollar, dbl = set(), 0, False, False
    while i < n:
        if line[i] == "$":
            if i + 1 < n and line[i + 1] == "$":
                dbl = not dbl
                mask.add(i); mask.add(i + 1)
                i += 2
                continue
            indollar = not indollar
            mask.add(i)
            i += 1
            continue
        if indollar or dbl:
            mask.add(i)
        i += 1
    return mask


def _marker_or_math_change(a, b):
    """A width/punctuation change that is content even though the canonical forms match: it creates or
    alters a line-initial Markdown marker, or it changes a % / ％ inside math or raw TeX."""
    if _lead_marker(a) != _lead_marker(b):
        return ("全角半角の変換で行頭に Markdown の記号(%s)ができる(定義リスト・引用・見出し・箇条書きなどになる) / the "
                "change creates a line-initial Markdown marker" % (_lead_marker(b) or _lead_marker(a)))
    if len(a) == len(b):
        ma = _math_mask(a)
        for i, (ca, cb) in enumerate(zip(a, b)):
            if ca != cb and (ca in "%\uff05" or cb in "%\uff05") and i in ma:
                return "数式・raw TeX の中の % を変えると意味が変わる(TeX では % は行コメント) / changing % inside math or raw TeX"
    elif ("$" in a or "$" in b) and ("\uff05" in a + b) and a.replace("\uff05", "%") == b.replace("\uff05", "%") and a != b:
        return "数式・raw TeX の中の % を変えると意味が変わる / changing % inside math or raw TeX"
    return ""


def _explain(old_lines, new_lines):
    """Name what changed, in words a student can check against the diff."""
    for a, b in zip(old_lines, new_lines):
        ca, cb = canon_line(a), canon_line(b)
        if ca == cb:
            continue
        if ca.split("\x00", 1)[0] != cb.split("\x00", 1)[0]:
            return ("行頭の字下げが変わる(Markdown ではコードや入れ子の構造になる) / the indentation at the start of a line "
                    "changes (it is Markdown structure)")
        x, y = ca.split("\x00", 1)[1], cb.split("\x00", 1)[1]
        sm = difflib.SequenceMatcher(None, x, y, autojunk=False)
        dels, adds = [], []
        for op, i1, i2, j1, j2 in sm.get_opcodes():
            if op in ("replace", "delete"):
                dels.append(x[i1:i2])
            if op in ("replace", "insert"):
                adds.append(y[j1:j2])
        changed = "".join(dels + adds)

        def show(t):
            t = t.replace(COMMA_T, "、").replace(PERIOD_T, "。").replace(CITE_T, "[引用]")
            return "".join("U+%04X" % ord(c) if c in INVISIBLE or unicodedata.category(c) in ("Cf", "Cc") else c
                           for c in t)[:20] or "∅"
        what = []
        if any(c in INVISIBLE or unicodedata.category(c) == "Cf" for c in changed):
            what.append("見えない文字(ゼロ幅など) / invisible characters")
        if any(c in DIGITS for c in changed):
            what.append("数字 / digits")
        if any(c in ".,-+−" for c in changed):
            what.append("小数点・符号・半角の句読点 / decimal points, signs or ASCII punctuation")
        if " " in changed:
            what.append("語と語の間の空白 / spaces between words")
        if COMMA_T in changed or PERIOD_T in changed:
            what.append("句読点の数・位置 / the number or place of punctuation marks")
        if any(unicodedata.category(c)[0] in "PS" and c not in ".,-+−" and c not in COMMA_SYS | PERIOD_SYS
               for c in changed):
            what.append("記号(引用符・括弧・演算子・矢印・Markdown の記号など) / marks (quotes, brackets, operators, arrows, "
                        "Markdown marks)")
        if any(unicodedata.category(c)[0] in "LM" for c in changed):
            what.append("文字(語・似た形の別の文字) / letters (words or look-alike letters)")
        return ("内容が変わるため提案にできない。変わるもの: %s(消える: %s / 加わる: %s)。"
                "提案にできるのは全角半角・句読点の組・日本語の周りの空白・見出しの番号・同じ文献の引用の書式だけ。"
                "内容の問題は問いの形の指摘(annot flag)にする / content changes; only width, punctuation system, "
                "whitespace around Japanese, heading numbers and the form of the same citation can be proposed"
                % ("、".join(what) or "?", " / ".join(show(d) for d in dels[:3]) or "∅",
                   " / ".join(show(d) for d in adds[:3]) or "∅"))
    return "内容が変わる / content changes"


def change_summary(old_lines, new_lines, lang="ja"):
    """A short header for a hunk that names the KINDS of change, e.g. '句読点 2・全角半角 3'."""
    counts = {"punct": 0, "width": 0, "space": 0, "cite": 0, "num": 0, "other": 0}
    for a, b in zip(old_lines, new_lines):
        sm = difflib.SequenceMatcher(None, a, b, autojunk=False)
        for op, i1, i2, j1, j2 in sm.get_opcodes():
            if op == "equal":
                continue
            x, y = a[i1:i2], b[j1:j2]
            if (x + y) and all(c in LINE_WS for c in x + y):
                counts["space"] += 1
            elif x and len(x) == len(y) and all(
                    (cx in COMMA_SYS | PERIOD_SYS and cy in COMMA_SYS | PERIOD_SYS)
                    or unicodedata.normalize("NFKC", cx) == unicodedata.normalize("NFKC", cy) for cx, cy in zip(x, y)):
                for cx, cy in zip(x, y):
                    if unicodedata.normalize("NFKC", cx) == unicodedata.normalize("NFKC", cy):
                        counts["width"] += 1
                    else:
                        counts["punct"] += 1
            elif "@" in x + y or "[" in x + y or "(" in x + y or "（" in x + y:
                counts["cite"] += 1
            elif HEADING.match(a) and HEADING.match(b):
                counts["num"] += 1
            else:
                counts["other"] += 1
    names = {"ja": {"punct": "句読点", "width": "全角半角", "space": "空白", "cite": "引用の書式", "num": "見出しの番号",
                    "other": "その他"},
             "en": {"punct": "punctuation", "width": "full/half width", "space": "spacing", "cite": "citation form",
                    "num": "heading number", "other": "other"}}[lang if lang in ("ja", "en") else "ja"]
    parts = ["%s %d" % (names[k], v) for k, v in counts.items() if v]
    return ("・" if lang != "en" else ", ").join(parts)[:120]


# ---------------------------------------------------------------- diff build / parse
def split_lines(text):
    return text.split("\n")


def make_hunks(old_text, new_text, context=1):
    a, b = split_lines(old_text), split_lines(new_text)
    sm = difflib.SequenceMatcher(None, a, b, autojunk=False)
    hunks = []
    for op, i1, i2, j1, j2 in sm.get_opcodes():
        if op == "equal":
            continue
        cb = a[max(0, i1 - context):i1]
        ca = a[i2:i2 + context]
        hunks.append({"old_start": i1 + 1, "old": a[i1:i2], "new": b[j1:j2],
                      "before": cb, "after": ca, "note": "",
                      "old_idx": list(range(i1, i2)), "new_idx": list(range(j1, j2))})
    return hunks


def render(meta, hunks):
    out = ["# rk-proposal: 1"]
    for k in ("id", "status", "kind", "target", "base_sha256", "created", "by", "model", "rule", "why", "decided"):
        if meta.get(k) not in (None, ""):
            out.append("# %s: %s" % (k, str(meta[k]).replace("\n", " ")))
    out.append("--- a/%s" % meta["target"])
    out.append("+++ b/%s" % meta["target"])
    for h in hunks:
        nb, na = len(h["before"]), len(h["after"])
        os_ = h["old_start"] - nb
        out.append("@@ -%d,%d +%d,%d @@ %s" % (os_, nb + len(h["old"]) + na, os_, nb + len(h["new"]) + na,
                                              h.get("note", "")))
        out += [" " + x for x in h["before"]]
        out += ["-" + x for x in h["old"]]
        out += ["+" + x for x in h["new"]]
        out += [" " + x for x in h["after"]]
    return "\n".join(out) + "\n"


def parse(path):
    with open(path, encoding="utf-8") as f:
        lines = f.read().split("\n")
    if lines and lines[-1] == "":
        lines = lines[:-1]
    meta, hunks, cur, i = {}, [], None, 0
    while i < len(lines) and lines[i].startswith("# "):
        m = HEADER_RE.match(lines[i])
        if m:
            meta[m.group(1)] = m.group(2)
        i += 1
    if meta.get("rk-proposal") != "1":
        raise RkError("%s: 提案ファイルの形式でない / not a proposal file" % path)
    for ln in lines[i:]:
        if ln.startswith("--- ") or ln.startswith("+++ "):
            continue
        m = HUNK_RE.match(ln)
        if m:
            cur = {"start": int(m.group(1)), "note": m.group(5).strip(), "body": []}
            hunks.append(cur)
            continue
        if cur is None:
            continue
        if ln[:1] in (" ", "-", "+"):
            cur["body"].append((ln[0], ln[1:]))
        elif ln == "":
            cur["body"].append((" ", ""))
    out = []
    for n, h in enumerate(hunks, 1):
        body = h["body"]
        before, old, new, after = [], [], [], []
        seen_change = False
        for tag, txt in body:
            if tag == " ":
                (after if seen_change else before).append(txt)
            else:
                seen_change = True
                (old if tag == "-" else new).append(txt)
        out.append({"n": n, "old_start": h["start"] + len(before), "old": old, "new": new,
                    "before": before, "after": after, "note": h["note"]})
    meta["hunks"] = out
    meta["path"] = path
    return meta


def decided(meta):
    out = {}
    for part in (meta.get("decided") or "").split(","):
        if "=" in part:
            k, v = part.split("=", 1)
            if k.strip().isdigit():
                out[int(k)] = v.strip()
    return out


# ---------------------------------------------------------------- locate / apply
def locate(lines, h, base_ok):
    """Index (0-based) where h['old'] starts in LINES, or None."""
    n_old = len(h["old"])
    if base_ok:
        i = h["old_start"] - 1
        if 0 <= i <= len(lines) and lines[i:i + n_old] == h["old"]:
            return i
    block = h["before"] + h["old"] + h["after"]
    hits = [k for k in range(0, len(lines) - len(block) + 1) if lines[k:k + len(block)] == block]
    if len(hits) == 1:
        return hits[0] + len(h["before"])
    if n_old:
        hits = [k for k in range(0, len(lines) - n_old + 1) if lines[k:k + n_old] == h["old"]]
        if len(hits) == 1:
            return hits[0]
    return None


def recheck(meta, proj, current_text):
    """Re-run the invariance check at apply time. Returns {n: reason} for refused hunks."""
    bad = {}
    kind = meta.get("kind", "")
    lines = split_lines(current_text)
    for h in meta["hunks"]:
        if kind == "diagram":
            pos = locate(lines, h, False)
            if pos is None:
                bad[h["n"]] = "位置を特定できない / cannot locate"
                continue
            new_all = lines[:pos] + h["new"] + lines[pos + len(h["old"]):]
            ok, why = check_hunk(kind, h["old"], h["new"], lines, new_all,
                                 list(range(pos, pos + len(h["old"]))), list(range(pos, pos + len(h["new"]))), proj)
        else:
            if kind == "heading":
                pos = locate(lines, h, False)
                if pos is None:
                    bad[h["n"]] = "位置を特定できない / cannot locate"
                    continue
                new_all = lines[:pos] + h["new"] + lines[pos + len(h["old"]):]
                ok, why = check_hunk(kind, h["old"], h["new"], lines, new_all, list(range(pos, pos + len(h["old"]))),
                                     list(range(pos, pos + len(h["new"]))), proj)
            else:
                ok, why = check_hunk(kind, h["old"], h["new"], proj=proj)
        if not ok:
            bad[h["n"]] = why
    return bad


def apply_hunks(text, meta, accept):
    """Apply accepted hunk numbers. Returns (new_text, applied, unlocated)."""
    lines = split_lines(text)
    base_ok = sha256_bytes(text.encode("utf-8")) == meta.get("base_sha256")
    pos = {}
    unlocated = []
    for h in meta["hunks"]:
        if h["n"] in accept:
            p = locate(lines, h, base_ok)
            if p is None:
                unlocated.append(h["n"])
            else:
                pos[h["n"]] = p
    applied = []
    for n in sorted(pos, key=lambda k: pos[k], reverse=True):
        h = next(x for x in meta["hunks"] if x["n"] == n)
        p = pos[n]
        lines[p:p + len(h["old"])] = h["new"]
        applied.append(n)
    return "\n".join(lines), sorted(applied), unlocated


# ---------------------------------------------------------------- creating proposals
def proposals_dir(proj):
    return os.path.join(proj, "proposals")


def next_id(proj):
    n = 0
    for root in (proposals_dir(proj), os.path.join(proposals_dir(proj), "done")):
        if os.path.isdir(root):
            for fn in os.listdir(root):
                m = re.match(r"^P(\d{4,})", fn)
                if m:
                    n = max(n, int(m.group(1)))
    return "P%04d" % (n + 1)


def create(proj, target_rel, old_text, new_text, kind, why, rule="", by="ai", model="unknown", notes=None, lang=None):
    if lang is None:
        from .common import feedback_lang
        lang = feedback_lang(proj)
    if kind not in KINDS:
        raise RkError("kind は format|citation|diagram|heading のどれか")
    if not why.strip():
        raise RkError("--why(なぜこの提案か)を一行で書くこと。学生が採否を決める材料になる")
    if old_text == new_text:
        raise RkError("変更がない / no change")
    hunks = make_hunks(old_text, new_text)
    a, b = split_lines(old_text), split_lines(new_text)
    refused = []
    for k, h in enumerate(hunks):
        ok, reason = check_hunk(kind, h["old"], h["new"], a, b, h["old_idx"], h["new_idx"], proj)
        if not ok:
            refused.append(("%d 行目付近: %s" if lang != "en" else "near line %d: %s") % (h["old_start"], reason))
        if notes and k < len(notes):
            h["note"] = notes[k]
        elif not h.get("note"):
            h["note"] = _auto_note(h["old"], h["new"], lang)
    if refused:
        raise RkError("提案にできない変更がある(AI は内容を変える提案を作れない):\n  " + "\n  ".join(refused))
    meta = {"id": next_id(proj), "status": "pending", "kind": kind, "target": target_rel,
            "base_sha256": sha256_bytes(old_text.encode("utf-8")), "created": now_iso(), "by": by,
            "model": model, "rule": rule, "why": why}
    os.makedirs(proposals_dir(proj), exist_ok=True)
    slug = re.sub(r"[^A-Za-z0-9]+", "-", os.path.splitext(os.path.basename(target_rel))[0]).strip("-")[:30] or "x"
    path = os.path.join(proposals_dir(proj), "%s-%s-%s.diff" % (meta["id"], kind, slug))
    with open(path, "w", encoding="utf-8") as f:
        f.write(render(meta, hunks))
    return path, meta, len(hunks)


def _auto_note(old, new, lang="ja"):
    return change_summary(old, new, lang)


def pending(proj):
    out = []
    d = proposals_dir(proj)
    if os.path.isdir(d):
        for fn in sorted(os.listdir(d)):
            if fn.endswith(".diff"):
                try:
                    m = parse(os.path.join(d, fn))
                except (RkError, OSError, UnicodeDecodeError):
                    continue
                if m.get("status") == "pending":
                    out.append(m)
    return out


def write_meta(meta):
    hunks = []
    for h in meta["hunks"]:
        hunks.append(dict(h))
    text = render({k: v for k, v in meta.items() if k not in ("hunks", "path")}, hunks)
    with open(meta["path"], "w", encoding="utf-8") as f:
        f.write(text)


def finish(meta, proj):
    done = os.path.join(proposals_dir(proj), "done")
    os.makedirs(done, exist_ok=True)
    meta["status"] = "done"
    write_meta(meta)
    dst = os.path.join(done, os.path.basename(meta["path"]))
    os.replace(meta["path"], dst)
    meta["path"] = dst
    return dst


def target_sha(proj, meta):
    p = os.path.join(proj, meta["target"])
    return sha256_file(p) if os.path.exists(p) else None


def char_diff(a, b, color=True):
    """Return (old_marked, new_marked) with changed spans highlighted (color) or bracketed."""
    sm = difflib.SequenceMatcher(None, a, b, autojunk=False)
    oa, ob = [], []
    for op, i1, i2, j1, j2 in sm.get_opcodes():
        if op == "equal":
            oa.append(a[i1:i2])
            ob.append(b[j1:j2])
            continue
        if i2 > i1:
            oa.append(("\033[1;31;7m%s\033[0m" if color else "[-%s-]") % a[i1:i2])
        if j2 > j1:
            ob.append(("\033[1;32;7m%s\033[0m" if color else "{+%s+}") % b[j1:j2])
    return "".join(oa), "".join(ob)
