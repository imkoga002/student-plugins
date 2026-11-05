"""The mechanical part of the rigorous verification (claim-verifier). The agent does the reading and the
reasoning; this module gives it facts it must not guess, and checks the shape of what it writes.

  scaffold   review/verification/<date>-<target>.md with section 0 filled by the tool:
             - citations per paragraph and their ledger state (IDENTITY_CONFIRMED or below), and whether a saved
               excerpt of the source exists (without one the support is "unchecked", never "supports")
             - numbers without a citation or a data reference
             - AI-written paragraphs (provenance) with an uncited assertive factual sentence (important)
             - AI-written paragraphs compared with the claim card they came from: words that strengthen the claim,
               a dropped qualifier, a reversed direction, a scope figure that disappeared (candidate: fatal)
  lint       every finding line has a severity (致命・重要・軽微 / fatal, major, minor), an aspect and a basis;
             "supports" only with an excerpt; novelty never asserted without the searches; counter-evidence tied
             to the search log
These are lexical candidates, not verdicts: the agent confirms or dismisses each one with a reason. Lists of words
are the plugin author's choice and have not been evaluated on real manuscripts.
"""
import os
import re
import unicodedata

from . import claimcards, ledger, paragraphs as P, provenance
from .common import RkError, manuscript_files, read_text, rel, safe_rel, today, tr

VDIR = os.path.join("review", "verification")
SEVERITIES = {"致命": "fatal", "重要": "major", "軽微": "minor", "fatal": "fatal", "major": "major", "minor": "minor"}
ASPECTS = ("論理", "根拠の対応", "反証", "新規性", "すり替え", "logic", "support", "counter", "novelty", "swap")
OK_STATES = ("IDENTITY_CONFIRMED",)

STRONG = {"ja": ("必ず", "常に", "すべての", "全ての", "完全に", "明らかに", "証明", "決定的", "唯一", "確実に", "間違いなく",
                 "例外なく", "一切", "あらゆる", "唯一の原因", "最大の要因"),
          "en": ("always", "never", "all ", "every ", "prove", "proves", "proven", "certainly", "clearly", "definitely",
                 "must ", "only ", "undoubtedly", "conclusively", "the cause", "the main cause")}
HEDGE = {"ja": ("可能性", "示唆", "一因", "傾向", "場合がある", "ことがある", "かもしれない", "と考えられる", "と思われる", "だろう",
                "一部", "うる", "得る", "程度", "限って", "限り", "に限る", "おそれ"),
         "en": ("may ", "might", "could", "suggest", "tend", "partly", "in part", "likely", "possibly", "some ", "can ",
                "limited to", "only in", "under ")}
UP = {"ja": ("増加", "増える", "上昇", "高める", "高まる", "促進", "強める", "拡大", "改善"),
      "en": ("increase", "raise", "rise", "promote", "strengthen", "expand", "improve")}
DOWN = {"ja": ("減少", "減る", "低下", "低める", "下げる", "抑制", "弱める", "縮小", "悪化"),
        "en": ("decrease", "reduce", "lower", "decline", "inhibit", "weaken", "shrink", "worsen")}
FACTUAL = ("によれば", "調査", "統計", "データ", "研究", "報告", "割合", "増加", "減少", "率", "件数", "人数",
           "according to", "survey", "data", "study", "studies", "report", "rate", "percent", "share")
OPINION = ("と考える", "と考えられる", "と思われる", "だろう", "ではないか", "かもしれない", "と主張する", "と論じる", "本稿は",
           "筆者は", "と言える", "といえる", "I argue", "we argue", "this paper", "this essay", "I suggest", "may ", "might")
# Figures. Every number in body prose is a candidate: Arabic digits (full-width ones are read as ASCII first) and
# kanji numerals followed by a counter or unit (三割, 百人, 数百人, 二千人; a lone 一 and words such as 十分 are not
# numbers). A short, explicit list is exempt: years and year ranges (2020年, 1990年代, 2019-2021, a bare 2030), dates
# and clock times (11月5日, 午後3時), references to figures, tables, equations, sections, chapters, questions and pages
# (図1, 表3.1, 式 (2.3), (2.3) より, 3.2 節, 第2章, Section 3.2, p. 3), versions (v1.2, ver 2.0.0, Python 3.13, 3.2.1),
# standard identifiers (ISO 27001, JIS X 0208, RFC 9110), ordinals (第1位, 2回目, 3番目, 1人ずつ, 2つの), list
# numbers at the start of a line, and numbers in headings, code, math, URLs, citation keys, data paths and HTML
# comments. It is a heuristic: numbers spelled out in words ("three", 三つ) slip through, and a number the list does
# not exempt is reported even when it needs no source (the student can mark it: ./rk figures).
UNITS = (r"%|パーセント|ポイント|percentage points?|per ?cent|percent|か国|カ国|ヵ国|ヶ国|ケ国|箇国|か所|カ所|ヶ所|箇所|"
         r"割|倍|位|人|名|件|冊|円|万|億|兆|社|校|学部|大学|館|店|時間|分|秒|日間|週間|か月|ヶ月|カ月|年間|点|ドル|歳|才|回|"
         r"世帯|個|台|枚|本|頁|ページ|字|語|times|million|billion|thousand|trillion|points?|hours?|minutes?|days?|"
         r"weeks?|years? old|respondents?|students?|books?|people|persons?|items?|cases?|participants?|visitors?|users?")
KANJI_NUM = "〇一二三四五六七八九十百千万億兆数"
COUNTERS_J = (r"%|パーセント|ポイント|か国|カ国|ヵ国|ヶ国|ケ国|か所|カ所|ヶ所|箇所|割|倍|位|人|名|件|冊|円|社|校|学部|大学|館|店|"
              r"時間|分|秒|日間|週間|か月|ヶ月|カ月|年間|点|ドル|歳|才|回|世帯|個|台|枚|本|頁|ページ|字|語|万|億|兆")
NUM = re.compile(r"(?<![0-9A-Za-z.])\d[\d,]*(?:\.\d+)?(?:\s*/\s*\d+)?(?:\s*(?:" + UNITS + r"))?(?:\s*の\s*\d+)?"
                 r"|[" + KANJI_NUM + r"]+\s*(?:" + COUNTERS_J + r")")
_YEAR = r"(?:1[5-9]\d{2}|20\d{2})"
# software whose version numbers follow its name (a version is exempt only after one of these or v/ver/version)
PRODUCTS = (r"Python|R|Stata|SPSS|Excel|Word|PowerPoint|Office|pandoc|Pandoc|Windows|macOS|iOS|Android|Ubuntu|Debian|"
            r"Node(?:\.js)?|Java|MATLAB|SAS|Mplus|Amos|JASP|jamovi|Zotero|LaTeX|TeX Live|Chrome|Firefox|Safari|"
            r"PostgreSQL|MySQL|SQLite|Claude Code|NVivo|MAXQDA|KH Coder|HAD")
NOT_FIGURE = re.compile(
    r"(?<![\d.,])" + _YEAR + r"(?:\s*[-–—〜~～]\s*" + _YEAR + r")?\s*(?:年度|年代|年|s\b)"
    r"|(?<![\d.,])" + _YEAR + r"\s*[-–—〜~～]\s*" + _YEAR + r"(?![\d.,])"
    r"|\b(?:[Ii]n|[Ss]ince|[Bb]y|[Uu]ntil|[Tt]ill|[Ff]rom|[Dd]uring|[Oo]f|[Bb]etween|[Aa]fter|[Bb]efore|[Aa]round|[Cc]irca)\s+" + _YEAR + r"(?![\d.,])"
    r"|(?<![\d.,])" + _YEAR + r"\s*[/.\-]\s*\d{1,2}(?:\s*[/.\-]\s*\d{1,2})?(?![\d])"
    r"|\d{1,2}\s*月(?:\s*\d{1,2}\s*日)?|(?<!\d)\d{1,2}\s*日(?!間)|(?:午前|午後)\s*\d{1,2}\s*時(?:\s*\d{1,2}\s*分)?"
    r"|(?<!\d)\d{1,2}\s*時(?!間)(?:\s*\d{1,2}\s*分)?|(?<!\d)\d{1,2}:\d{2}(?!\d)"
    r"|(?:図|表|式|写真|資料|付録|別表|設問|問|Q|Figure|Fig\.|Table|Tab\.|Eq\.|Equation|Appendix|Section|Sec\.|Chapter|Ch\.|"
    r"§|第|節|章|項|pp?\.)\s*[(（]?\s*\d+(?:\s*[.\-‐–]\s*\d+)*\s*[)）]?"
    r"|\d+(?:\.\d+)*\s*(?:節|章|項|条|編)"
    r"|[(（]\s*\d+(?:\.\d+)*\s*[)）](?!\s*(?:" + UNITS + r"))"
    r"|\b[vV](?:er\.?|ersion)?\s?\d+(?:\.\d+)+|\b[Vv]er(?:sion)?\.?\s*\d+(?:\.\d+)*|\b\d+\.\d+\.\d+(?:\.\d+)*"
    r"|(?<![A-Za-z])(?:" + PRODUCTS + r")\s*v?\d+(?:\.\d+)*(?![\d.])"
    r"|\d+\s*(?:段階|群|問|項目|件法|回目|波)|[" + KANJI_NUM[:-1] + r"]+\s*(?:段階|群|問|項目|件法|回目|波)"
    r"|\b(?:ISO|IEC|JIS|IEEE|RFC|ANSI|DIN|EN|BS|ECMA|ITU-T|ISBN|ISSN|DOI|NCID|CRID)(?:/IEC)?\s*[A-Z]?\s*[-:/]?\s*\d[\d.\-:/]*"
    r"|\d+\s*(?:回目|番目|つ目|人目|度目|件目|冊目|日目|年目)|\d+\s*(?:人|件|冊|個|つ|名|問)\s*ずつ|(?<!\d)[1-9]\s*つ"
    r"|(?m:^\s*\d+[.)]\s)")
KANJI_NOT = re.compile(r"十分|一[" + KANJI_NUM[:-1] + r"]*?(?=[^" + KANJI_NUM + r"])|万一|数(?:回|人|件|名|点|日|本|個|社|校)")
DATAREF = re.compile(r"(?<![\w/])data/(?:raw|processed)/[\w./-]+")
FOOTREF = re.compile(r"\[\^([^\]]+)\](?!:)")


def _lang(text):
    return "en" if len(re.findall(r"[A-Za-z]", text)) > 3 * len(re.findall(r"[぀-ヿ一-鿿]", text)) else "ja"


def _has(text, words):
    t = " " + text.lower() + " "
    return [w for w in words if w.lower() in t]


ABBREV = re.compile(r"\b(?:pp|p|e\.g|i\.e|cf|Figs?|Eqs?|Nos?|Vols?|vol|eds?|et al|vs|ver|Secs?|Ch|Tabs?|approx|Dr|Mr|Ms|Prof|St|etc|n)\.(?=\s)")


def sentences(text):
    """Sentences of TEXT (。．!? and ". "; the period of an abbreviation such as "pp." or "e.g." does not end one)."""
    t = ABBREV.sub(lambda m: m.group(0)[:-1] + "\x00", text)
    return [x.replace("\x00", ".").strip() for x in re.split(r"(?<=[。．!?！？])|(?<=\.)\s+", t) if x.strip()]


# ------------------------------------------------------------------------------------------- per paragraph facts
def ledger_states(proj):
    by = {}
    for r in ledger.read(ledger.paths(proj)[0], ledger.REGISTER):
        for k in (r.get("citekey"), r.get("id")):
            if k:
                by[k] = r
    return by


def excerpt_sources(proj):
    """Source ids that have a saved excerpt (excerpts/*: first line 'source_id: S001')."""
    out = {}
    d = os.path.join(proj, "excerpts")
    if not os.path.isdir(d):
        return out
    for fn in sorted(os.listdir(d)):
        p = os.path.join(d, fn)
        if fn.lower().startswith("readme") or not os.path.isfile(p):
            continue
        try:
            first = read_text(p).split("\n", 1)[0]
        except (OSError, UnicodeDecodeError):
            continue
        m = re.match(r"^\s*source_id\s*:\s*(\S+)", first)
        if m:
            out.setdefault(m.group(1), []).append("excerpts/" + fn)
    return out


def trusted_data(proj, relp):
    """A data file counts as a source when it exists under data/raw/ or data/processed/, was not written or changed
    by an AI tool call (execgate's list of AI-written files, by path and content hash; msguard records every file a
    call changed), and, under data/raw/, is in the data manifest with the same content (rk.py data add)."""
    from . import execgate
    relp = relp.replace("\\", "/").lstrip("./")
    if not re.match(r"^data/(raw|processed)/", relp) or ".." in relp.split("/"):
        return False
    full = os.path.join(proj, relp)
    if not os.path.isfile(full):
        return False
    real = os.path.realpath(full)
    ai = execgate.ai_files()
    shas = {v.get("sha") for v in ai.values() if isinstance(v, dict) and v.get("sha")}
    sha = execgate._sha(real)
    if real in ai or sha in shas:
        return False
    if relp.startswith("data/raw/"):
        from .datacheck import read_manifest
        try:
            man = read_manifest(os.path.join(proj, "data", "manifest-sha256.txt"))
        except ValueError:
            return False
        from .common import sha256_file
        return man.get(relp) == sha256_file(full)
    return True


def numeric_values(proj):
    """Values of data/numeric-claims.csv rows that check out: the data file is trusted (trusted_data), the key names
    exactly one row and the cell equals the value (the same rule as rk.py data numbers). A row that does not check
    out exempts nothing."""
    import csv
    p = os.path.join(proj, "data", "numeric-claims.csv")
    vals = set()
    try:
        with open(p, newline="", encoding="utf-8") as f:
            rows = list(csv.DictReader(f))
    except (OSError, UnicodeDecodeError, csv.Error):
        return vals
    for r in rows:
        tv = (r.get("text_value") or "").strip()
        rel_ = (r.get("file") or "").strip()
        if not tv or not trusted_data(proj, rel_):
            continue
        try:
            with open(os.path.join(proj, rel_), newline="", encoding="utf-8") as g:
                hit = [x for x in csv.DictReader(g) if x.get(r.get("key_column") or "") == r.get("key")]
        except (OSError, UnicodeDecodeError, csv.Error):
            continue
        if len(hit) != 1:
            continue
        cell = (hit[0].get(r.get("column") or "") or "").strip()
        want = tv.replace(",", "").rstrip("%％").strip()
        try:
            ok = abs(float(cell.replace(",", "").rstrip("%％")) - float(want)) < 1e-9
        except ValueError:
            ok = cell == tv
        if ok:
            vals.add(tv)
    return vals


def has_source(par_text, notes, proj=None):
    """A citation, or a reference to a trusted data file (trusted_data) in the text or its footnotes. Without PROJ,
    any data reference counts (used where no project is at hand)."""
    t = par_text
    for lab in FOOTREF.findall(par_text):
        t += "\n" + notes.get(lab, "")
    if provenance.citekeys(t):
        return True
    for m in DATAREF.finditer(t):
        if proj is None or trusted_data(proj, m.group(0).rstrip(".,;:)）」』")):
            return True
    return False


def _clean(text):
    body = unicodedata.normalize("NFKC", text or "")
    body = re.sub(r"(?s)<!--.*?-->", " ", body)
    body = re.sub(r"\$\$.*?\$\$|\$[^$\n]*\$", " ", re.sub(r"`[^`]*`", " ", body))
    body = re.sub(r"https?://\S+|\]\([^)]*\)", " ", body)
    body = re.sub(r"\[\^[^\]]+\]", " ", body)
    body = re.sub(r"\[@[^\]]*\]|@\{[^}]*\}|@[\w:.#$%&+?<>~/-]+", " ", body)
    body = DATAREF.sub(" ", body)
    return NOT_FIGURE.sub(" ", body)


def figures(text):
    """The figures (NUM above) in TEXT after the exempt forms are removed."""
    out = []
    for m in NUM.finditer(_clean(text)):
        tok = m.group(0).strip()
        if re.match("^[" + KANJI_NUM + "]", tok):
            num = re.match("^[" + KANJI_NUM + "]+", tok).group(0)
            if num == "一" or KANJI_NOT.match(tok) or num == "数" or num == "万":
                continue
        out.append(tok)
    return out


def _sentence_source(sent, notes, proj):
    """A sentence is sourced when it (or a footnote it refers to) has a citation key outside comments and code, or
    a reference to a data file that exists."""
    t = sent
    for lab in FOOTREF.findall(sent):
        t += "\n" + notes.get(lab, "")
    return has_source(t, {}, proj)


def figure_subject(sentence, tok):
    """The id a student's 'no source needed' mark is bound to: the sentence (normalised) and the figure."""
    from .common import sha256_bytes
    norm = re.sub(r"\s+", " ", unicodedata.normalize("NFKC", sentence)).strip()
    return "%s:%s" % (sha256_bytes(norm.encode("utf-8"))[:16], tok), sha256_bytes(norm.encode("utf-8"))


def figure_marks(proj):
    """{subject: digest} of the student's light confirmations 'this figure needs no source' (kind figure, decision
    no_source_needed, recorded at the terminal with ./rk figures). Only confirmations that count under
    sign.valid_index are taken (written by the plugin's student-only path or appended outside any AI tool call)."""
    from . import sign
    idx, _b = sign.valid_index(proj, {})
    out = {}
    for (kind, subj), recs in idx.items():
        if kind == "figure" and recs and recs[-1].get("decision") == "no_source_needed":
            out[subj] = recs[-1].get("digest")
    return out


def unsourced_figures(proj, text, relp="", marks=None):
    """[(line, token, sentence, subject, digest)] for figures in sentences without a source (not in
    data/numeric-claims.csv, not marked by the student). Headings, code, tables, math blocks, front matter and
    footnote definitions are skipped."""
    notes = P.footnotes(text)
    known = numeric_values(proj)
    marks = figure_marks(proj) if marks is None else marks
    out = []
    for b in P.paragraphs(text):
        first = b["text"].lstrip()
        if P.FOOTDEF.match(b["text"].split("\n")[0]) or first.startswith("|") or first.startswith("$$") or first.startswith("#"):
            continue
        lines = unicodedata.normalize("NFKC", b["text"]).split("\n")
        for sent in sentences(b["text"]):
            toks = figures(sent)
            if not toks or _sentence_source(sent, notes, proj):
                continue
            for tok in toks:
                if tok in known or re.sub(r"[^\d.,]", "", tok) in known:
                    continue
                subj, dg = figure_subject(sent, tok)
                if marks.get(subj) == dg:
                    continue
                key = tok.split()[0][:6]
                ln = b["start"] + next((i for i, x in enumerate(lines) if key in x), 0)
                out.append((ln, tok, sent, subj, dg))
    return out


def numbers_without_source(proj, text, relp=""):
    """[(line, token)] (see unsourced_figures)."""
    return [(ln, tok) for ln, tok, _s, _subj, _d in unsourced_figures(proj, text, relp)]


def assertive_uncited(text, notes):
    """Sentences of a paragraph without a source that state a fact assertively (a number or a factual marker, and
    no opinion or hedge marker)."""
    if has_source(text, notes):
        return []
    out = []
    for s in sentences(text):
        if _has(s, OPINION) or _has(s, HEDGE["ja"] + HEDGE["en"]):
            continue
        if figures(s) or _has(s, FACTUAL):
            out.append(s)
    return out


def swap_check(card, text):
    """Candidates that the paragraph says something stronger, wider or in another direction than the card."""
    base = "\n".join(it["text"] for k in ("claim", "scope") for it in card["items"].get(k, []) if not it["ai"])
    lang = _lang(base + text)
    out = []
    added = [w for w in _has(text, STRONG[lang]) if w not in _has(base, STRONG[lang])]
    if added:
        out.append(("強さ", "主張カードにない強める語: %s" % "、".join(w.strip() for w in added),
                    "stronger wording than the card: %s" % ", ".join(w.strip() for w in added)))
    if _has(base, HEDGE[lang]) and not _has(text, HEDGE[lang]):
        out.append(("限定", "主張カードの限定(%s)が段落にない" % "、".join(w.strip() for w in _has(base, HEDGE[lang])[:3]),
                    "the card's qualifier (%s) is missing from the paragraph" % ", ".join(w.strip() for w in _has(base, HEDGE[lang])[:3])))
    for a, b in ((UP, DOWN), (DOWN, UP)):
        if _has(base, a[lang]) and not _has(base, b[lang]) and _has(text, b[lang]) and not _has(text, a[lang]):
            out.append(("向き", "主張カードと逆の向きの語: %s" % "、".join(_has(text, b[lang])[:3]),
                        "direction opposite to the card: %s" % ", ".join(_has(text, b[lang])[:3])))
    scope = "\n".join(it["text"] for it in card["items"].get("scope", []) if not it["ai"])
    for n in sorted(set(re.findall(r"\d{2,4}", scope))):
        if n not in text:
            out.append(("範囲", "範囲の数字・年(%s)が段落にない" % n, "the scope figure or year (%s) is missing from the paragraph" % n))
    return out


# ------------------------------------------------------------------------------------------- scaffold
def _slug(target):
    return re.sub(r"[^A-Za-z0-9_-]+", "-", target.replace("manuscript/", "").rsplit(".", 1)[0]).strip("-")[:60] or "target"


def F(sev, aspect, where, what, basis):
    label = "basis" if sev in ("fatal", "major", "minor") else "根拠"
    return "- [%s] %s %s: %s / %s: %s" % (sev, aspect, where, what, label, basis)


def mechanical(proj, relp, text, lang="ja"):
    en = lang == "en"
    t = lambda ja, e: e if en else ja  # noqa: E731
    lines = []
    states = ledger_states(proj)
    exc = excerpt_sources(proj)
    notes = P.footnotes(text)
    aiset = {(r["start"], r["sha"]): r for r in provenance.ai_paragraphs(proj, relp)}
    cards = {c["id"]: c for c in claimcards.cards(proj)}
    from . import sign, subjects, trust
    trusted, _p, _n = trust.local_trusted(proj)
    idx, _b = sign.valid_index(proj, trusted)
    unchecked = set()
    for b in P.paragraphs(text):
        where = "%s L%d-%d" % (relp, b["start"], b["end"])
        for k in provenance.citekeys(b["text"] + "".join("\n" + notes.get(x, "") for x in FOOTREF.findall(b["text"]))):
            r = states.get(k)
            if r is None:
                lines.append(F(t("重要", "major"), t("根拠の対応", "support"), where, t("引用キー @%s が台帳にない(実在を確かめていない)" % k,
                               "citation key @%s is not in the ledger (existence not checked)" % k), "sources/register.csv"))
                continue
            ms = r.get("machine_status") or "CANDIDATE"
            if ms not in OK_STATES:
                lines.append(F(t("重要", "major"), t("根拠の対応", "support"), where, t("引用 @%s(%s)の台帳の状態が %s(IDENTITY_CONFIRMED 未満)" % (k, r.get("id"), ms),
                               "citation @%s (%s) has ledger state %s (below IDENTITY_CONFIRMED)" % (k, r.get("id"), ms)), "sources/register.csv"))
            if r.get("id") not in exc:
                unchecked.add(r.get("id"))
        ai = aiset.get((b["start"], b["sha"]))
        for s in (assertive_uncited(b["text"], notes) if ai else []):
            lines.append(F(t("重要", "major"), t("根拠の対応", "support"), where, t("AI が書いた段落に、引用のない断定的な事実の主張:「%s」" % s[:80],
                           "an AI-written paragraph states a fact without a source: \"%s\"" % s[:80]), ".ryukoku/provenance.jsonl"))
        if ai:
            mats = ((ai.get("entry") or {}).get("materials") or {})
            cids = [c for c in mats.get("claims") or [] if c]
            if not cids:
                lines.append(F(t("重要", "major"), t("すり替え", "swap"), where, t("AI が書いた段落だが、材料の主張カードが記録されていない(すり替えを照合できない)",
                               "an AI-written paragraph with no claim card recorded as its material (the swap check cannot run)"), ".ryukoku/provenance.jsonl"))
            for cid in cids:
                c = cards.get(cid)
                if c is None:
                    lines.append(F(t("致命", "fatal"), t("すり替え", "swap"), where, t("材料の主張カード %s がない" % cid, "claim card %s (its material) does not exist" % cid), "claims/"))
                    continue
                if not sign.current(idx, "card", cid, claimcards.digest(c)):
                    lines.append(F(t("致命", "fatal"), t("すり替え", "swap"), where, t("材料の主張カード %s が学生の確認済みでない(draft か、確認の後に変わった)" % cid,
                                   "claim card %s is not confirmed by the student (draft, or changed after confirmation)" % cid), "claims/%s.md" % cid))
                for _k, ja, e in swap_check(c, b["text"]):
                    lines.append(F(t("致命", "fatal"), t("すり替え", "swap"), where, t("(候補)" + ja, "(candidate) " + e), "claims/%s.md" % cid))
    for ln, tok in numbers_without_source(proj, text, relp):
        lines.append(F(t("軽微", "minor"), t("根拠の対応", "support"), "%s L%d" % (relp, ln), t("数字「%s」に出典もデータの参照もない" % tok,
                       "the figure \"%s\" has no citation or data reference" % tok), relp))
    for sid in sorted(x for x in unchecked if x):
        lines.append("- %s" % t("%s: 保存された原典の抜粋がない。主張を支えるかは未照合(推測で『支える』と書かない)" % sid,
                                "%s: no saved excerpt of the source; support is unchecked (do not write 'supports' by guessing)" % sid))
    return lines


def scaffold(proj, target, lang="ja"):
    en = lang == "en"
    if claimcards.ID_RE.match(target or ""):
        card = claimcards.find(proj, target)
        if card is None:
            raise RkError(tr(lang, "主張カード %s がない" % target, "claim card %s not found" % target))
        kind, mech = "card", []
        text = read_text(os.path.join(proj, "claims", target + ".md"))
        for k in ("claim", "scope"):
            if not card["sections"].get(k):
                mech.append(F(tr(lang, "重要", "major"), tr(lang, "論理", "logic"), "claims/%s.md" % target,
                              tr(lang, "「%s」が空" % dict(claimcards.SECTIONS)[k][0], "'%s' is empty" % dict(claimcards.SECTIONS)[k][1]), "claims/%s.md" % target))
        relp = "claims/%s.md" % target
        del text
        mech += [F(tr(lang, "重要", "major"), tr(lang, "根拠の対応", "support"), relp,
                   tr(lang, "必要な根拠に挙げた資料が台帳にない: %s" % k, "evidence named on the card is not in the ledger: %s" % k), "sources/register.csv")
                 for k in sorted(set(re.findall(r"@([A-Za-z0-9_:.-]+)", card["sections"].get("evidence", "")))) if k not in ledger_states(proj)]
    else:
        full, relp = safe_rel(proj, target, "manuscript/")
        kind = "manuscript"
        mech = mechanical(proj, relp, read_text(full), lang)
    d = os.path.join(proj, VDIR)
    os.makedirs(d, exist_ok=True)
    out = os.path.join(d, "%s-%s.md" % (today(), _slug(target)))
    n = 2
    while os.path.exists(out):
        out = os.path.join(d, "%s-%s-%d.md" % (today(), _slug(target), n))
        n += 1
    if en:
        heads = ["## 0. Mechanical checks (from the tool; facts, not judgements)", "## 1. Logic", "## 2. Support by the sources",
                 "## 3. Counter-evidence", "## 4. Novelty and position", "## 5. Swap check (AI text vs the student's claim)",
                 "## 6. Suggested revisions (the student decides)"]
        hint = ("<!-- Finding lines: - [fatal|major|minor] <aspect> <where>: <what> / basis: <evidence>. Aspects: logic, support, "
                "counter, novelty, swap (or a taxonomy code). 'supports' needs an excerpt (excerpts/...); otherwise write 'unchecked'. "
                "Never assert novelty: 'not found in the searches recorded (search log ids)'. -->")
    else:
        heads = ["## 0. 機械の照合(道具が出した事実。判断ではない)", "## 1. 論理", "## 2. 根拠の対応", "## 3. 反証", "## 4. 新規性・位置づけ",
                 "## 5. すり替えの検知(AI の文と学生の主張)", "## 6. 修正案(採るかは学生が決める)"]
        hint = ("<!-- 指摘の行: - [致命|重要|軽微] <観点> <場所>: <内容> / 根拠: <根拠>。観点は 論理・根拠の対応・反証・新規性・すり替え"
                "(または taxonomy のコード)。「支える」は抜粋(excerpts/...)があるときだけ。無ければ「未照合」。新規性は断定しない"
                "(「記録した検索の範囲では見当たらない」+検索記録の id)。 -->")
    body = ["---", "target: %s" % relp, "kind: %s" % kind, "date: %s" % today(),
            "generated_by: rk.py verification scaffold", "---",
            "# %s %s" % ("Verification:" if en else "検証:", relp), "", hint, "", heads[0]]
    body += mech or ["- " + tr(lang, "(機械の照合で出たものはない)", "(nothing from the mechanical checks)")]
    for h in heads[1:]:
        body += ["", h, ""]
    with open(out, "w", encoding="utf-8") as f:
        f.write("\n".join(body) + "\n")
    return out, mech


# ------------------------------------------------------------------------------------------- lint
FIND = re.compile(r"^\s*[-*]\s+\[([^\]]+)\]\s*(\S+)\s+(.*)$")


def lint_text(text, proj=None, lang="ja"):
    errs, warns = [], []
    sec = None
    secs = {}
    for ln, line in enumerate(text.split("\n"), 1):
        m = re.match(r"^##\s+(\d)\.", line)
        if m:
            sec = int(m.group(1))
            secs.setdefault(sec, [])
            continue
        if sec is not None:
            secs[sec].append((ln, line))
        f = FIND.match(line)
        if not f or sec is None or sec == 6:
            continue
        sev, aspect, rest = f.group(1).strip(), f.group(2).strip(), f.group(3)
        if sev not in SEVERITIES:
            errs.append(tr(lang, "%d 行目: 重大度 [%s] は 致命・重要・軽微(fatal・major・minor)のどれか" % (ln, sev),
                           "line %d: severity [%s] must be fatal, major or minor (致命・重要・軽微)" % (ln, sev)))
        if aspect not in ASPECTS and not re.match(r"^[A-Z]\d$", aspect):
            errs.append(tr(lang, "%d 行目: 観点 %s は 論理・根拠の対応・反証・新規性・すり替え か taxonomy のコード" % (ln, aspect),
                           "line %d: aspect %s must be logic, support, counter, novelty, swap or a taxonomy code" % (ln, aspect)))
        if not re.search(r"/\s*(根拠|basis)\s*[:：]\s*\S", rest):
            errs.append(tr(lang, "%d 行目: 根拠(/ 根拠: …)がない" % ln, "line %d: no basis (/ basis: ...)" % ln))
        if re.search(r"支える|裏づける|裏付ける|supports|is supported", rest) and not re.search(r"未照合|支えない|unchecked|does not support|not supported", rest) \
                and "excerpts/" not in rest:
            errs.append(tr(lang, "%d 行目: 「支える」と書くなら、保存した抜粋(excerpts/…)を根拠に示す。抜粋が無ければ「未照合」" % ln,
                           "line %d: 'supports' needs a saved excerpt (excerpts/...) as the basis; without one write 'unchecked'" % ln))
    nov = "\n".join(x for _l, x in secs.get(4, []))
    if re.search(r"新規である|新しい知見である|前例がない|初めて明らか|誰も.{0,6}ない|is novel|no prior (work|study)|first to", nov) \
            and not re.search(r"調べた範囲|記録した検索|検索記録|in the searches|search log", nov):
        errs.append(tr(lang, "4. 新規性: 新規性を断定している。「記録した検索の範囲では見当たらない」と検索記録を示す",
                       "4. novelty is asserted; write 'not found in the recorded searches' with the search log"))
    mech_fatal = any(re.search(r"\[(致命|fatal)\]", x) for _l, x in secs.get(0, []))
    swap = "\n".join(x for _l, x in secs.get(5, []) if x.strip() and not x.strip().startswith("<!--"))
    if mech_fatal and not swap.strip():
        warns.append(tr(lang, "0 に致命の候補があるのに 5. すり替えの検知 が空。一件ずつ確かめ、残すか退けるかを理由つきで書く",
                        "section 0 has fatal candidates but 5 (swap check) is empty: confirm or dismiss each with a reason"))
    counter = "\n".join(x for _l, x in secs.get(3, []))
    if counter.strip() and proj is not None:
        from . import searchlog
        try:
            ids = {r.get("id") for r in searchlog.load(proj) if r.get("purpose") == "counter"}
        except Exception:  # noqa: BLE001
            ids = set()
        cited = set(re.findall(r"\b(S\d{3,})\b", counter))
        if not (cited & ids) and not re.search(r"検索していない|not searched", counter):
            warns.append(tr(lang, "3. 反証: --purpose counter の検索記録の id が書かれていない(反証の検索をしたなら id を、していないならそう書く)",
                            "3. counter-evidence: no search record id with --purpose counter (cite it, or say it was not searched)"))
    for k in (1, 2, 3, 4, 5):
        if k not in secs:
            errs.append(tr(lang, "節 %d がない" % k, "section %d is missing" % k))
    return errs, warns


def lint(proj, relp, lang="ja"):
    full, _r = safe_rel(proj, relp, "review/verification/")
    return lint_text(read_text(full), proj, lang)


def files(proj):
    d = os.path.join(proj, VDIR)
    if not os.path.isdir(d):
        return []
    return sorted(os.path.join(d, f) for f in os.listdir(d) if f.endswith(".md"))


def latest_for(proj, relp):
    """The newest verification file whose target is RELP (None when there is none)."""
    best = None
    for p in files(proj):
        try:
            head = read_text(p).split("\n", 8)
        except OSError:
            continue
        if any(h.strip() == "target: %s" % relp for h in head):
            best = p
    return best


def manuscript_targets(proj):
    return [rel(proj, p) for p in manuscript_files(proj)]
