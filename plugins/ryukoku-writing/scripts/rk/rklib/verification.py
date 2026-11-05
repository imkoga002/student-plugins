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
# A figure: a number with a unit of quantity, a decimal, or a large integer (a thousands separator or five digits and
# more), written in Arabic digits (full-width ones are read as ASCII first) or in kanji numerals (三割, 百万人). A number
# right after kana or kanji counts (only an ASCII letter, digit or "." before it says it is part of a name). Not
# figures: years (2020年, 1990年代, a bare 2030), section, chapter, article, figure, table and equation numbers (3.2 節,
# 第 2 章, 図 1.2, 表 3, 式 (2.3), Figure 2, Table 3.1), versions (v1.2, 2.0.0, Python 3.13), page ranges, numbers in
# URLs, code and math. It is a heuristic: a figure in words ("twelve per cent") or with a unit not listed is missed.
UNITS = (r"%|パーセント|ポイント|percentage points?|per ?cent|percent|か国|カ国|ヵ国|ヶ国|ケ国|箇国|割|倍|位|人|名|件|円|"
         r"万|億|兆|社|校|時間|点|ドル|歳|才|回|世帯|times|million|billion|thousand|trillion|points?")
NUM = re.compile(r"(?<![0-9A-Za-z.第])\d[\d,]*(?:\.\d+)?\s*(?:" + UNITS + r")"
                 r"|(?<![0-9A-Za-z.第§])\d+\.\d+(?![\w.]|\s*(?:節|章|項|条|版|section|chapter))"
                 r"|(?<![0-9A-Za-z.])\d{1,3}(?:,\d{3})+(?![\d.,])|(?<![0-9A-Za-z.])\d{5,}(?![\d.,])"
                 r"|[〇一二三四五六七八九十百千]{2,}(?:万|億|兆)?\s*(?:" + UNITS + r")"
                 r"|[〇一二三四五六七八九十百千](?:割|倍|パーセント|万|億|兆)")
# labels and names that a number follows without being a figure (removed before matching)
NOT_FIGURE = re.compile(r"(?:図|表|式|写真|資料|付録|Figure|Fig\.|Table|Tab\.|Eq\.|Equation|Appendix)\s*[(（]?\s*[0-9]+(?:[.\-‐][0-9]+)*\s*[)）]?"
                        r"|\b[A-Z][A-Za-z+#]*\s+v?[0-9]+(?:\.[0-9]+)+\b(?!\s*(?:" + UNITS + r"))"
                        r"|\b[vV](?:er\.?|ersion)?\s?[0-9]+(?:\.[0-9]+)+|第\s*[0-9]+")
DATAREF = re.compile(r"(?<![\w/])data/(?:raw|processed)/[\w./-]+")
FOOTREF = re.compile(r"\[\^([^\]]+)\](?!:)")


def _lang(text):
    return "en" if len(re.findall(r"[A-Za-z]", text)) > 3 * len(re.findall(r"[぀-ヿ一-鿿]", text)) else "ja"


def _has(text, words):
    t = " " + text.lower() + " "
    return [w for w in words if w.lower() in t]


def sentences(text):
    return [s.strip() for s in re.split(r"(?<=[。．!?！？])|(?<=\.)\s+", text) if s.strip()]


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


def numeric_values(proj):
    import csv
    p = os.path.join(proj, "data", "numeric-claims.csv")
    vals = set()
    try:
        with open(p, newline="", encoding="utf-8") as f:
            for r in csv.DictReader(f):
                if r.get("text_value"):
                    vals.add(r["text_value"].strip())
    except OSError:
        pass
    return vals


def has_source(par_text, notes, proj=None):
    """A citation, or a reference to a data file under data/raw|processed/ (in the paragraph or its footnotes). With
    PROJ, a data reference counts only when that file exists."""
    t = par_text
    for lab in FOOTREF.findall(par_text):
        t += "\n" + notes.get(lab, "")
    if provenance.citekeys(t):
        return True
    for m in DATAREF.finditer(t):
        if proj is None or os.path.isfile(os.path.join(proj, m.group(0).rstrip(".,;:)）」』"))):
            return True
    return False


def figures(text):
    """The figures (NUM above) in TEXT, after full-width characters are read as ASCII and code, math, URLs, citations
    and figure/table/equation/version labels are removed."""
    body = unicodedata.normalize("NFKC", text or "")
    body = re.sub(r"\$[^$]*\$", "", re.sub(r"`[^`]*`", "", body))
    body = re.sub(r"https?://\S+|\]\([^)]*\)", " ", body)
    body = re.sub(r"\[@[^\]]*\]|@\{[^}]*\}|@[\w:.#$%&+?<>~/-]+", " ", body)
    body = DATAREF.sub(" ", body)
    body = NOT_FIGURE.sub(" ", body)
    return [m.group(0).strip() for m in NUM.finditer(body)]


def numbers_without_source(proj, text, relp=""):
    """[(line, token)] for numbers in a paragraph that has neither a citation nor a data reference (and is not in
    data/numeric-claims.csv). Headings, code, front matter and footnote definitions are skipped."""
    notes = P.footnotes(text)
    known = numeric_values(proj)
    out = []
    for b in P.paragraphs(text):
        if P.FOOTDEF.match(b["text"].split("\n")[0]) or b["text"].lstrip().startswith("|") or b["text"].lstrip().startswith("$$"):
            continue
        toks = figures(b["text"])
        if not toks or has_source(b["text"], notes, proj):
            continue
        lines = unicodedata.normalize("NFKC", b["text"]).split("\n")
        for tok in toks:
            if tok in known or re.sub(r"[^\d.,]", "", tok) in known:
                continue
            ln = b["start"] + next((i for i, x in enumerate(lines) if tok.split()[0] in x), 0)
            out.append((ln, tok))
    return out


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
