"""Reproducible search log research/search-log.jsonl.

One line per search: id, date, db, query, filters, hits, question_ref, purpose, selected, reason, by, auto,
endpoint, note
  hits          the count the database reported (null when unknown; never guessed)
  question_ref  id of the student's own sub-question in research/questions.md (the AI does not invent it)
  auto          true for records written by the PostToolUse hook (WebSearch); question_ref/reason are
                completed later with `searchlog annotate`
`rk.py search ...` writes a record automatically for every API search. `export` gives the table for the
thesis section on how prior work was searched, or for the advisor.
"""
import json
import os
import re

from .common import RkError, read_jsonl, today, tr

REQUIRED = ("id", "date", "db", "query", "question_ref", "by")


def path(proj):
    return os.path.join(proj, "research", "search-log.jsonl")


def load(proj):
    return read_jsonl(path(proj))


def save(proj, recs):
    p = path(proj)
    tmp = p + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        for r in recs:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    os.replace(tmp, p)


def next_id(recs):
    n = 0
    for r in recs:
        m = re.match(r"^S(\d+)$", str(r.get("id", "")))
        if m:
            n = max(n, int(m.group(1)))
    return "S%03d" % (n + 1)


def add(proj, db, query, question_ref, hits=None, filters="", selected=None, reason="", by="agent",
        endpoint="", date=None, purpose="main", note="", auto=True):
    """Append one record. `auto` is true for records the tools and hooks write by themselves (every search)."""
    from .common import FileLock
    with FileLock(path(proj) + ".lock"):
        return _add(proj, db, query, question_ref, hits, filters, selected, reason, by, endpoint, date, purpose, note, auto)


def _add(proj, db, query, question_ref, hits, filters, selected, reason, by, endpoint, date, purpose, note, auto):
    recs = load(proj)
    rec = {"id": next_id(recs), "date": date or today(), "db": db, "query": query, "filters": filters,
           "hits": hits, "question_ref": question_ref, "purpose": purpose or "main", "selected": selected or [],
           "reason": reason, "by": by, "auto": bool(auto)}
    if endpoint:
        rec["endpoint"] = endpoint
    if note:
        rec["note"] = note
    errs, _ = validate([rec])
    if errs:
        raise RkError("\n".join(errs))
    os.makedirs(os.path.dirname(path(proj)), exist_ok=True)
    with open(path(proj), "a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    return rec


def annotate(proj, rid, question_ref=None, selected=None, reason=None, hits=None):
    recs = load(proj)
    for r in recs:
        if r.get("id") == rid:
            if question_ref is not None:
                r["question_ref"] = question_ref
            if selected is not None:
                r["selected"] = [s for s in selected.split(",") if s]
            if reason is not None:
                r["reason"] = reason
            if hits is not None:
                r["hits"] = hits
            errs, _ = validate([r])
            if errs and not r.get("auto"):
                raise RkError("\n".join(errs))
            save(proj, recs)
            return r
    raise RkError("検索記録 %s がない" % rid)


def validate(recs, lang="ja"):
    errs, warns, seen = [], [], set()
    for r in recs:
        rid = r.get("id", "?")
        if rid in seen:
            errs.append(tr(lang, "%s: id が重複", "%s: duplicate id") % rid)
        seen.add(rid)
        auto = bool(r.get("auto"))
        for k in REQUIRED:
            if not str(r.get(k, "") if r.get(k) is not None else "").strip():
                (warns if auto and k == "question_ref" else errs).append(
                    tr(lang, "%s: '%s' が空%s", "%s: '%s' is empty%s") % (rid, k, tr(lang, "(自動記録。searchlog annotate で補う)", " (automatic record; complete it with searchlog annotate)") if auto else ""))
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(r.get("date", ""))):
            errs.append(tr(lang, "%s: date が YYYY-MM-DD でない", "%s: date is not YYYY-MM-DD") % rid)
        if r.get("by") not in ("human", "agent"):
            errs.append(tr(lang, "%s: by は human か agent", "%s: by must be human or agent") % rid)
        hits = r.get("hits")
        if hits is not None and not isinstance(hits, int):
            errs.append(tr(lang, "%s: hits は整数か null", "%s: hits must be an integer or null") % rid)
        if r.get("selected") and not str(r.get("reason", "")).strip():
            errs.append(tr(lang, "%s: 選んだ資料があるのに reason(選んだ理由)が空", "%s: items are selected but the reason is empty") % rid)
        if r.get("purpose", "main") not in ("main", "counter"):
            errs.append(tr(lang, "%s: purpose は main か counter", "%s: purpose must be main or counter") % rid)
    return errs, warns


def to_markdown(recs):
    lines = ["| id | 日付 | DB | 検索式 | 絞り込み | 件数 | 小問い | 目的 | 選んだもの | 選んだ理由 | 実施 |",
             "|---|---|---|---|---|---|---|---|---|---|---|"]
    esc = lambda s: str(s if s is not None else "").replace("|", "\\|").replace("\n", " ")
    for r in recs:
        lines.append("| " + " | ".join(esc(x) for x in (
            r.get("id"), r.get("date"), r.get("db"), r.get("query"), r.get("filters"),
            "不明" if r.get("hits") is None else r.get("hits"), r.get("question_ref") or "(要記入)",
            "反証・対抗" if r.get("purpose") == "counter" else "主",
            ", ".join(r.get("selected") or []), r.get("reason"), str(r.get("by")) + ("(自動)" if r.get("auto") else ""))) + " |")
    return "\n".join(lines) + "\n"
