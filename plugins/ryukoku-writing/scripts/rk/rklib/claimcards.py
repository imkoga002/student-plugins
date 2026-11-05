"""Claim cards: claims/C001.md, one claim of the student per file.

The AI may draft a card from what the student said (idea-intake), but the claim stays the student's: the card
keeps the student's own words verbatim, separately from the AI's paraphrase, and every element the AI added
(a candidate warrant, a candidate objection) carries the mark [ai_suggested]. A card is `draft` until the student
confirms "this is my claim" on the evidence notebook (one button) or with `./rk confirm` in their terminal. That
confirmation is a record in .ryukoku/signoffs.jsonl (kind "card"), bound to the digest of the student-owned parts
(claim, scope, the student's words and every element without the [ai_suggested] mark). Editing those parts
afterwards makes the confirmation stale. A card file that says `status: confirmed` without such a record is an
error in `rk check` (the status is not something the AI can set by writing the file).

Format (Markdown, sections may be in Japanese or English):
  ---
  id: C001
  status: draft
  created: YYYY-MM-DD
  ---
  # 主張 / Claim
  ## 範囲と限定 / Scope and qualifiers
  ## 必要な根拠 / Evidence needed
  ## 論拠 / Warrant
  ## 予想される反論 / Expected objections
  ## 新規性の見込み / Novelty (tentative)
  ## 学生の言葉の原文 / Student's own words
"""
import os
import re

from .common import RkError, read_text, subject_hash, today

DIR = "claims"
SECTIONS = (
    ("claim", ("主張", "claim")),
    ("scope", ("範囲と限定", "scope and qualifiers", "scope")),
    ("evidence", ("必要な根拠", "evidence needed", "evidence")),
    ("warrant", ("論拠", "warrant")),
    ("objections", ("予想される反論", "expected objections", "objections")),
    ("novelty", ("新規性の見込み", "novelty (tentative)", "novelty")),
    ("words", ("学生の言葉の原文", "student's own words", "students own words", "own words")),
)
REQUIRED = ("claim", "scope", "words")
AI_MARK = "[ai_suggested]"
ID_RE = re.compile(r"^C\d{3,4}$")


def card_dir(proj):
    return os.path.join(proj, DIR)


def card_files(proj):
    d = card_dir(proj)
    if not os.path.isdir(d):
        return []
    return sorted(os.path.join(d, f) for f in os.listdir(d) if re.match(r"^C\d{3,4}\.md$", f))


def _key(title):
    t = title.strip().lower().rstrip(":：")
    for k, names in SECTIONS:
        if t in names:
            return k
    for k, names in SECTIONS:
        if any(t.startswith(n) for n in names):
            return k
    return None


def parse_text(text, name=""):
    meta, body = {}, text
    lines = text.split("\n")
    if lines and lines[0].strip() == "---":
        for i in range(1, len(lines)):
            if lines[i].strip() == "---":
                for ln in lines[1:i]:
                    m = re.match(r"^([A-Za-z_]+)\s*:\s*(.*)$", ln)
                    if m:
                        meta[m.group(1)] = m.group(2).strip().strip("\"'")
                body = "\n".join(lines[i + 1:])
                break
    secs, cur, unknown = {}, None, []
    for ln in body.split("\n"):
        m = re.match(r"^#{1,3}\s+(.*)$", ln)
        if m:
            cur = _key(m.group(1))
            if cur is None:
                unknown.append(m.group(1).strip())
            else:
                secs.setdefault(cur, [])
            continue
        if cur:
            secs[cur].append(ln)
    out = {"id": meta.get("id") or os.path.splitext(name)[0], "status": (meta.get("status") or "draft").strip(),
           "created": meta.get("created", ""), "meta": meta, "unknown_sections": unknown, "sections": {}, "items": {}}
    for k, ls in secs.items():
        txt = "\n".join(ls).strip()
        out["sections"][k] = txt
        items = []
        for ln in ls:
            s = ln.strip()
            if not s:
                continue
            s = re.sub(r"^([-*+]|\d+[.)])\s+", "", s)
            if s.startswith(">"):
                s = s.lstrip("> ").strip()
            ai = s.startswith(AI_MARK)
            items.append({"text": s[len(AI_MARK):].strip() if ai else s, "ai": ai})
        out["items"][k] = items
    return out


def load(path):
    return parse_text(read_text(path), os.path.basename(path))


def student_part(card):
    """What the student's confirmation covers: the claim, the scope, the student's words and every element that
    is not marked [ai_suggested]."""
    obj = {"kind": "card", "id": card["id"]}
    for k, _n in SECTIONS:
        obj[k] = [it["text"] for it in card["items"].get(k, []) if not it["ai"]]
    return obj


def digest(card):
    return subject_hash(student_part(card))


def problems(card, lang="ja"):
    from .common import tr
    out = []
    if not ID_RE.match(card["id"] or ""):
        out.append(tr(lang, "id は C001 の形にする", "the id must look like C001"))
    for k in REQUIRED:
        if not card["sections"].get(k):
            name = dict(SECTIONS)[k]
            out.append(tr(lang, "「%s」の節がないか、空" % name[0], "section '%s' is missing or empty" % name[1]))
    if any(it["ai"] for it in card["items"].get("words", [])):
        out.append(tr(lang, "学生の言葉の原文に [ai_suggested] がある(原文は学生の言葉だけ)", "the student's own words contain [ai_suggested] (only the student's words go there)"))
    if any(it["ai"] for it in card["items"].get("claim", [])):
        out.append(tr(lang, "主張そのものに [ai_suggested] がある。主張は学生のもの。AI の言い換えの案は『範囲と限定』などの節で候補として示す",
                      "the claim itself is marked [ai_suggested]; the claim is the student's. Offer paraphrases as candidates elsewhere"))
    if card["status"] not in ("draft", "confirmed"):
        out.append(tr(lang, "status は draft か confirmed(confirmed は学生の確認の記録があるときだけ)", "status must be draft or confirmed"))
    if card["unknown_sections"]:
        out.append(tr(lang, "知らない節: %s" % ", ".join(card["unknown_sections"][:4]), "unknown sections: %s" % ", ".join(card["unknown_sections"][:4])))
    return out


def next_id(proj):
    n = 0
    for p in card_files(proj):
        n = max(n, int(re.findall(r"\d+", os.path.basename(p))[0]))
    return "C%03d" % (n + 1)


def new_card(proj, words, lang="ja"):
    """Create claims/C00N.md with the student's words verbatim and empty sections for the AI to fill from the
    conversation (the claim itself must come from the student's words)."""
    if not (words or "").strip():
        raise RkError("学生の言葉の原文が空 / the student's own words are empty")
    os.makedirs(card_dir(proj), exist_ok=True)
    cid = next_id(proj)
    quoted = "\n".join("> " + ln for ln in words.strip().split("\n"))
    if lang == "en":
        body = ("---\nid: %s\nstatus: draft\ncreated: %s\n---\n# Claim\n\n## Scope and qualifiers\n\n## Evidence needed\n\n## Warrant\n\n"
                "## Expected objections\n\n## Novelty (tentative)\n\n## Student's own words\n%s\n" % (cid, today(), quoted))
    else:
        body = ("---\nid: %s\nstatus: draft\ncreated: %s\n---\n# 主張\n\n## 範囲と限定\n\n## 必要な根拠\n\n## 論拠\n\n## 予想される反論\n\n"
                "## 新規性の見込み\n\n## 学生の言葉の原文\n%s\n" % (cid, today(), quoted))
    p = os.path.join(card_dir(proj), cid + ".md")
    with open(p, "w", encoding="utf-8") as f:
        f.write(body)
    return cid, p


def cards(proj):
    out = []
    for p in card_files(proj):
        try:
            out.append(load(p))
        except (OSError, UnicodeDecodeError):
            continue
    return out


def find(proj, cid):
    p = os.path.join(card_dir(proj), "%s.md" % cid)
    return load(p) if os.path.isfile(p) else None
