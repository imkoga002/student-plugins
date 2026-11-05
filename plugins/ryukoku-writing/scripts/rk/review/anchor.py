"""W3C Web Annotation 風のセレクタ(TextQuoteSelector + TextPositionSelector)の生成と再特定。

標準ライブラリのみ。位置は原稿(Markdown ソース)の Unicode 文字(code point)単位のオフセット。
"""
import difflib

CONTEXT = 32
FUZZY_THRESHOLD = 0.75
MAX_FUZZY_TEXT = 400_000


def make_selectors(text, start, end, ctx=CONTEXT):
    if not (0 <= start < end <= len(text)):
        raise ValueError("invalid range")
    return [
        {"type": "TextQuoteSelector", "exact": text[start:end],
         "prefix": text[max(0, start - ctx):start], "suffix": text[end:end + ctx]},
        {"type": "TextPositionSelector", "start": start, "end": end},
    ]


def split_selectors(selectors):
    quote = pos = None
    for s in selectors or []:
        if s.get("type") == "TextQuoteSelector":
            quote = s
        elif s.get("type") == "TextPositionSelector":
            pos = s
    return quote, pos


def _common_suffix(a, b):
    n = 0
    while n < len(a) and n < len(b) and a[-1 - n] == b[-1 - n]:
        n += 1
    return n


def _common_prefix(a, b):
    n = 0
    while n < len(a) and n < len(b) and a[n] == b[n]:
        n += 1
    return n


def _occurrences(text, quote):
    out, i = [], text.find(quote)
    while i != -1:
        out.append(i)
        i = text.find(quote, i + 1)
    return out


def locate(text, selectors):
    """返り値: {state, start, end, score, ambiguous}
    state: exact(位置も引用も一致) / moved(引用で再特定) / fuzzy(近似一致、要人間確認) / orphaned(特定不能)
    """
    quote, pos = split_selectors(selectors)
    if not quote or not quote.get("exact"):
        return {"state": "orphaned", "start": None, "end": None, "score": 0.0, "ambiguous": False}
    exact = quote["exact"]
    prefix, suffix = quote.get("prefix", ""), quote.get("suffix", "")
    ps = pos.get("start") if pos else None

    if ps is not None and text[ps:ps + len(exact)] == exact:
        return {"state": "exact", "start": ps, "end": ps + len(exact), "score": 1.0, "ambiguous": False}

    occ = _occurrences(text, exact)
    if occ:
        def score(i):
            return (_common_suffix(prefix, text[max(0, i - len(prefix)):i]) +
                    _common_prefix(suffix, text[i + len(exact):i + len(exact) + len(suffix)]))
        scored = sorted(((score(i), -abs(i - (ps or 0)), i) for i in occ), reverse=True)
        best = scored[0]
        ambiguous = len(scored) > 1 and scored[1][0] == best[0]
        return {"state": "moved", "start": best[2], "end": best[2] + len(exact),
                "score": 1.0, "ambiguous": ambiguous}

    return _fuzzy(text, exact, prefix, suffix, ps)


def _fuzzy(text, exact, prefix, suffix, ps):
    orphan = {"state": "orphaned", "start": None, "end": None, "score": 0.0, "ambiguous": False}
    n = len(exact)
    if n < 4 or len(text) > MAX_FUZZY_TEXT:
        return orphan
    step = max(1, n // 4)
    best = (0.0, None, None)
    sm = difflib.SequenceMatcher(autojunk=False)
    sm.set_seq2(exact)
    for wlen in (n, int(n * 0.85) or n, int(n * 1.15) + 1):
        for i in range(0, max(1, len(text) - wlen + 1), step):
            win = text[i:i + wlen]
            sm.set_seq1(win)
            if sm.real_quick_ratio() < FUZZY_THRESHOLD or sm.quick_ratio() < FUZZY_THRESHOLD:
                continue
            r = sm.ratio()
            if r > best[0]:
                best = (r, i, i + len(win))
    if best[1] is None or best[0] < FUZZY_THRESHOLD:
        return orphan
    # 粗い探索の周辺を 1 文字刻みで精密化する(窓の始点と長さ)
    cs = best[1]
    for i in range(max(0, cs - step), min(len(text), cs + step + 1)):
        for wlen in range(max(1, n - 6), n + 7):
            win = text[i:i + wlen]
            if not win:
                continue
            sm.set_seq1(win)
            r = sm.ratio()
            if r > best[0] + 1e-9:
                best = (r, i, i + len(win))
    return {"state": "fuzzy", "start": best[1], "end": best[2], "score": round(best[0], 3), "ambiguous": False}
