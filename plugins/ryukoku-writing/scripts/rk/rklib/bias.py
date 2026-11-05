"""Counts for the bias check (guideline II-2(2): do not take biased output at face value; verify critically).
It reads this plugin's ledger and search log, lists numbers and
returns questions; it never declares the student's sources "biased" (the judgement is the student's).
"""
import collections
import re

from . import ledger, searchlog


QUESTIONS = {
    "ja": {
        "counter": "反対の立場・対抗仮説を探す検索(purpose: counter)がまだない。あなたの主張に最も不利な資料は、どの DB でどう探せますか？",
        "one_lang": "資料が一つの言語に限られている。別の言語圏の研究や統計で、同じ問いを扱ったものはありますか？",
        "old": "資料の多くが 10 年以上前。その後に状況やデータが変わっていないかを確かめましたか？",
        "one_db": "検索が一つの DB に限られている。その DB が収録しない資料(紙の本、政府統計、他分野の雑誌)はどこで探しますか？",
        "unread": "台帳の資料のうち、原典を読んで確認したものが半分に満たない。読む順番をどう決めますか？",
        "ai": "AI の検索結果や要約そのものにも偏りがありえる(ガイドラインⅡ-2(2))。AI が挙げなかった資料を自分で探しましたか？",
    },
    "en": {
        "counter": "No search for the opposing view (purpose: counter) yet. Where and how would you look for the evidence least favourable to your claim?",
        "one_lang": "All sources are in one language. Are there studies or statistics in another language on the same question?",
        "old": "Most sources are over 10 years old. Have you checked whether the situation or data changed since?",
        "one_db": "All searches used one database. Where will you look for what it does not index (print books, official statistics, other fields)?",
        "unread": "Fewer than half of the sources have been read and confirmed. How will you decide what to read first?",
        "ai": "AI search results and summaries can be biased too (guideline II-2(2)). Did you search for sources the AI did not list?",
    },
}


def report(root, lang="ja"):
    rows = ledger.read(ledger.paths(root)[0], ledger.REGISTER)
    try:
        recs = searchlog.load(root)
    except Exception:  # noqa: BLE001
        recs = []
    import datetime
    year_now = datetime.date.today().year
    langs = collections.Counter((r.get("language") or ("ja" if re.search(r"[぀-ヿ㐀-鿿]", r.get("title") or "") else "en" if r.get("title") else "?")) for r in rows)
    kinds = collections.Counter(r.get("medium") or "?" for r in rows)
    decades = collections.Counter(((int(r["year"]) // 10) * 10 if (r.get("year") or "").isdigit() else "?") for r in rows)
    dbs = collections.Counter(r.get("db") for r in recs)
    purposes = collections.Counter(r.get("purpose") or "?" for r in recs)
    verified = sum(1 for r in rows if (r.get("human_status") or "") == "VERIFIED")
    old = sum(1 for r in rows if (r.get("year") or "").isdigit() and year_now - int(r["year"]) > 10)
    q = QUESTIONS.get(lang, QUESTIONS["ja"])
    asks = []
    if recs and not purposes.get("counter"):
        asks.append(q["counter"])
    if rows and len([k for k in langs if k != "?"]) <= 1:
        asks.append(q["one_lang"])
    if rows and old * 2 > len(rows):
        asks.append(q["old"])
    if recs and len(dbs) <= 1:
        asks.append(q["one_db"])
    if rows and verified * 2 < len(rows):
        asks.append(q["unread"])
    asks.append(q["ai"])
    return {"sources": len(rows), "languages": dict(langs), "kinds": dict(kinds),
            "decades": {str(k): v for k, v in decades.items()}, "searches": len(recs), "databases": dict(dbs),
            "purposes": dict(purposes), "verified": verified, "questions": asks}


