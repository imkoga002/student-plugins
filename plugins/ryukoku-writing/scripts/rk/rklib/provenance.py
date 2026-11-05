"""Provenance of the manuscript, paragraph by paragraph: .ryukoku/provenance.jsonl (append-only, committed).

Each line is one paragraph (or heading) that someone wrote, changed or deleted:
  {"type": "paragraph", "file", "kind", "actor": "ai"|"student", "estimated", "lines": [start, end], "sha",
   "from_sha", "section", "chars", "block", "materials": {"claims", "sources", "data", "purpose"}, "tool",
   "policy", "date", "ts", "prev"}
  kind: ai_wrote / ai_edited / ai_deleted / student_wrote / student_edited / student_deleted
Every line carries "prev" = SHA-256 of the previous line ("GENESIS" for the first), like the AI-use log, so a
deleted or rewritten line breaks the chain; `rk check` verifies it, locally against the head remembered outside
the project and in CI by requiring the file to extend the base branch's version.

Who wrote what:
  * AI: the PostToolUse hook compares the manuscript before and after every AI tool call (msguard) and records
    each changed paragraph with actor "ai" (estimated: false). The materials come from the citations in the
    paragraph and from what the draft-writer declared beforehand (`rk.py provenance materials`).
  * Student: what changed between AI tool calls is assumed to be the student's own editing and recorded at the
    next AI tool call, at SessionStart and at `rk check` with actor "student" and estimated: true. It is an
    inference (another program could have written it), and the record says so.
The last recorded text of every manuscript file is kept outside the project (state_dir/prov/files/), so the
comparison does not depend on anything the AI could rewrite in the project.
"""
import json
import os
import re
import time

from . import paragraphs as P
from .common import (FileLock, load_config, note_written, manuscript_files, read_text, rel, sha256_bytes, state_dir, today,
                     now_iso, tr)

PROV_REL = os.path.join(".ryukoku", "provenance.jsonl")
GENESIS = "GENESIS"
MATERIALS_TTL = 2 * 3600
AI_KINDS = ("ai_wrote", "ai_edited")
CITE = re.compile(r"(?<![\w.])-?@([A-Za-z0-9_][A-Za-z0-9_:.#$%&+?<>~/-]*)")
NONCITE = ("fig:", "tbl:", "sec:", "eq:", "lst:")


def path(proj):
    return os.path.join(proj, PROV_REL)


def line_hash(line):
    return sha256_bytes(line.rstrip("\r\n").encode("utf-8"))


def _pdir(proj, *p):
    d = os.path.join(state_dir(proj), "prov", *p)
    return d


def _head_path(proj):
    return _pdir(proj, "head.json")


# ------------------------------------------------------------------------------------------------ the log
def read(proj):
    p = path(proj)
    out = []
    if not os.path.exists(p):
        return out
    with open(p, encoding="utf-8") as f:
        for ln, line in enumerate(f, 1):
            if line.strip():
                try:
                    out.append((ln, line.rstrip("\r\n"), json.loads(line)))
                except ValueError:
                    out.append((ln, line.rstrip("\r\n"), None))
    return out


def entries(proj):
    return [o for _l, _r, o in read(proj) if o]


def _append(proj, objs):
    if not objs:
        return []
    p = path(proj)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    out = []
    with FileLock(p + ".lock"):
        last = None
        try:
            with open(p, "rb") as f:
                f.seek(0, 2)
                size = f.tell()
                f.seek(max(0, size - 65536))
                chunk = [x for x in f.read().decode("utf-8", "replace").split("\n") if x.strip()]
                last = chunk[-1] if chunk else None
        except OSError:
            last = None
        prev = line_hash(last) if last else GENESIS
        with open(p, "a", encoding="utf-8", newline="") as f:
            for o in objs:
                o = dict(o, prev=prev)
                o.setdefault("date", today())
                o.setdefault("ts", now_iso())
                line = json.dumps(o, ensure_ascii=False, sort_keys=True)
                f.write(line + "\n")
                note_written(proj, PROV_REL, [line])
                prev = line_hash(line)
                out.append(o)
        try:
            n = sum(1 for x in open(p, encoding="utf-8") if x.strip())
            os.makedirs(_pdir(proj), exist_ok=True)
            with open(_head_path(proj), "w", encoding="utf-8") as f:
                json.dump({"lines": n, "head": prev}, f)
        except OSError:
            pass
    return out


def verify(proj, local=True, lang="ja"):
    """Problems of the provenance log: unreadable lines, a broken chain, and (locally) a truncated or rebuilt log."""
    rows = read(proj)
    probs = []
    prev = GENESIS
    for ln, raw, obj in rows:
        if obj is None:
            probs.append(tr(lang, "由来の記録 %d 行目が JSON でない(改変の可能性)", "provenance log line %d is not JSON (possibly altered)") % ln)
        elif obj.get("prev") != prev:
            probs.append(tr(lang, "由来の記録(.ryukoku/provenance.jsonl)の連鎖が %d 行目で切れている(行の削除・書き換えの可能性。記録はフックと道具だけが追記する)",
                            "the provenance log (.ryukoku/provenance.jsonl) chain breaks at line %d (lines deleted or rewritten)") % ln)
        prev = line_hash(raw)
    if local:
        try:
            with open(_head_path(proj), encoding="utf-8") as f:
                head = json.load(f)
        except (OSError, ValueError):
            head = None
        if head and head.get("lines"):
            n = int(head["lines"])
            if len(rows) < n or line_hash(rows[n - 1][1]) != head.get("head"):
                probs.append(tr(lang, "由来の記録が、この PC で最後に記録した内容(%d 行)の続きになっていない。切り詰め・作り直しの可能性",
                                "the provenance log does not continue what this computer last recorded (%d lines): truncated or rebuilt?") % n)
    return probs


# ------------------------------------------------------------------------------------------------ last known text
def _known_path(proj, relp):
    return _pdir(proj, "files", relp.replace("/", os.sep))


def known_text(proj, relp):
    try:
        return read_text(_known_path(proj, relp))
    except OSError:
        return None


def set_known(proj, relp, text):
    p = _known_path(proj, relp)
    if text is None:
        try:
            os.remove(p)
        except OSError:
            pass
        return
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w", encoding="utf-8", newline="") as f:
        f.write(text)


# ------------------------------------------------------------------------------------------------ materials
def _mat_path(proj):
    return _pdir(proj, "materials.json")


def set_materials(proj, relp, claims=(), sources=(), data=(), purpose="draft"):
    """What the next AI write to RELP is based on (declared by the draft-writer before writing)."""
    p = _mat_path(proj)
    try:
        with open(p, encoding="utf-8") as f:
            cur = json.load(f)
    except (OSError, ValueError):
        cur = {}
    cur[relp] = {"claims": [c for c in claims if c], "sources": [s for s in sources if s], "data": [d for d in data if d],
                 "purpose": purpose or "draft", "at": time.time()}
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w", encoding="utf-8") as f:
        json.dump(cur, f, ensure_ascii=False)
    return cur[relp]


def peek_materials(proj, relp):
    try:
        with open(_mat_path(proj), encoding="utf-8") as f:
            m = json.load(f).get(relp)
    except (OSError, ValueError, AttributeError):
        return None
    if m and time.time() - float(m.get("at", 0)) < MATERIALS_TTL:
        return m
    return None


def citekeys(text):
    t = re.sub(r"`[^`]*`", "", text or "")
    return sorted({k.rstrip(".:,;") for k in CITE.findall(t) if not k.startswith(NONCITE)})


def _source_ids(proj, keys):
    from . import ledger
    by = {}
    for r in ledger.read(ledger.paths(proj)[0], ledger.REGISTER):
        for k in (r.get("citekey"), r.get("id")):
            if k:
                by[k] = r.get("id")
    return sorted({by.get(k, k) for k in keys})


# ------------------------------------------------------------------------------------------------ recording
def record(proj, relp, old_text, new_text, actor, tool="", materials=None, estimated=False, uncertain=False):
    """Record every block that differs between OLD_TEXT and NEW_TEXT of RELP, then remember NEW_TEXT."""
    pol = load_config(proj).get("ai_policy") or "unknown"
    objs = []
    seen = set()
    if estimated:
        # a paragraph that already has a record (a git pull or a branch switch brought it back, or it was pasted
        # back) is not re-attributed to the student
        seen = {(e.get("file"), e.get("sha")) for e in entries(proj) if e.get("type") == "paragraph" and e.get("sha")}
    for d in P.diff(old_text or "", new_text or ""):
        o, w = d["old"], d["new"]
        b = w or o
        if estimated and w is not None and (relp, w["sha"]) in seen:
            continue
        if d["op"] == "insert":
            kind = actor + "_wrote"
        elif d["op"] == "delete":
            kind = actor + "_deleted"
        else:
            kind = actor + ("_wrote" if P.similarity(o["text"], w["text"]) < 0.25 else "_edited")
        mats = {"claims": [], "sources": [], "data": [], "purpose": ""}
        if materials:
            mats.update({k: list(materials.get(k) or []) for k in ("claims", "sources", "data")})
            mats["purpose"] = materials.get("purpose") or ""
        if w is not None:
            mats["sources"] = sorted(set(mats["sources"]) | set(_source_ids(proj, citekeys(w["text"]))))
        if actor == "ai" and not mats["purpose"]:
            mats["purpose"] = "revise" if kind == "ai_edited" else ("draft" if kind == "ai_wrote" else "delete")
        objs.append({"type": "paragraph", "file": relp, "kind": kind, "actor": actor, "estimated": bool(estimated),
                     "lines": [b["start"], b["end"]], "sha": w["sha"] if w else "", "from_sha": o["sha"] if o else "",
                     "section": b["section"], "chars": len(P.norm(w["text"])) if w else 0, "block": b["kind"],
                     "materials": mats, "tool": tool or "", "policy": pol})
        if uncertain:
            objs[-1]["uncertain"] = True
    out = _append(proj, objs)
    set_known(proj, relp, new_text)
    return out


def sync_student(proj, relp=None, before=None, uncertain=False):
    """Record what changed since the last recorded text as the student's (estimated). With RELP and BEFORE (the
    text at the start of an AI tool call) only that file is compared with BEFORE. Returns the new entries."""
    out = []
    if relp is not None:
        known = known_text(proj, relp)
        if known is None:
            set_known(proj, relp, before)
            return out
        if (before or "") != known:
            out += record(proj, relp, known, before or "", "student", "editor", estimated=True, uncertain=uncertain)
        return out
    files = {rel(proj, p): p for p in manuscript_files(proj)}
    kdir = _pdir(proj, "files")
    for dp, _dns, fns in os.walk(kdir):
        for fn in fns:
            r = os.path.relpath(os.path.join(dp, fn), kdir).replace(os.sep, "/")
            files.setdefault(r, None)
    for r, p in sorted(files.items()):
        cur = read_text(p) if p and os.path.exists(p) else None
        known = known_text(proj, r)
        if known is None:
            if cur is not None:
                set_known(proj, r, cur)  # first sight: nothing to compare with (paragraphs stay "unrecorded")
            continue
        if cur != known:
            out += record(proj, r, known, cur or "", "student", "editor", estimated=True, uncertain=uncertain)
            if cur is None:
                set_known(proj, r, None)
    return out


def ensure_known(proj):
    """Remember the current text of every manuscript file that has no remembered text yet (nothing is recorded:
    what was written before this point stays 'unrecorded')."""
    for p in manuscript_files(proj):
        r = rel(proj, p)
        if known_text(proj, r) is None:
            try:
                set_known(proj, r, read_text(p))
            except (OSError, UnicodeDecodeError):
                pass


def record_ai(proj, relp, before, after, tool):
    """An AI tool call changed RELP from BEFORE to AFTER: first the student's edits since the last record (estimated),
    then the AI's change, with the materials the draft-writer declared for this file."""
    out = sync_student(proj, relp, before)
    out += record(proj, relp, before, after, "ai", tool, materials=peek_materials(proj, relp))
    return out


# ------------------------------------------------------------------------------------------------ reading it back
def attribution(proj, texts=None):
    """{file: [{"start", "end", "sha", "section", "chars", "origin", "entry"}]} for the current paragraphs.
    origin: ai_wrote / ai_edited / student_after_ai (the student changed an AI paragraph; estimated) / student
    (estimated) / uncertain (changed while an AI tool call was open but never finished; counted with the AI's) /
    unrecorded (written before recording started, or by a way that left no record)."""
    ents = entries(proj)
    by_sha = {}
    for i, e in enumerate(ents):
        if e.get("type") == "paragraph" and e.get("sha"):
            by_sha.setdefault((e.get("file"), e["sha"]), []).append(i)

    def latest(f, sha, before=None):
        idxs = [i for i in by_sha.get((f, sha), []) if before is None or i < before]
        return idxs[-1] if idxs else None

    def ai_in_chain(f, i, depth=0):
        e = ents[i]
        if e.get("actor") == "ai" and e.get("kind") in AI_KINDS:
            return True
        if depth > 60 or not e.get("from_sha"):
            return False
        j = latest(f, e["from_sha"], i)
        return j is not None and ai_in_chain(f, j, depth + 1)

    out = {}
    files = texts if texts is not None else {rel(proj, p): read_text(p) for p in manuscript_files(proj)}
    for f, text in sorted(files.items()):
        rows = []
        for b in P.blocks(text):
            if b["kind"] not in ("paragraph", "heading", "code"):
                continue
            i = latest(f, b["sha"])
            if i is None:
                origin = "unrecorded"
            else:
                e = ents[i]
                if e.get("actor") == "ai":
                    origin = e.get("kind") if e.get("kind") in AI_KINDS else "ai_wrote"
                elif e.get("uncertain"):
                    origin = "uncertain"
                else:
                    origin = "student_after_ai" if ai_in_chain(f, i) else "student"
            rows.append({"start": b["start"], "end": b["end"], "sha": b["sha"], "section": b["section"], "block": b["kind"],
                         "chars": len(P.norm(b["text"])), "origin": origin, "entry": ents[i] if i is not None else None,
                         "text": b["text"]})
        out[f] = rows
    return out


ORIGINS = ("ai_wrote", "ai_edited", "uncertain", "student_after_ai", "student", "unrecorded")
AI_SIDE = ("ai_wrote", "ai_edited", "uncertain")  # counted as the AI's in the facts and the policy check


def summary(proj):
    """Facts for the disclosure: paragraphs and characters by origin, per file and section, and the purposes and
    materials of the AI's writing."""
    att = attribution(proj)
    tot = {o: [0, 0] for o in ORIGINS}
    per = {}
    purposes, claims, sources = {}, set(), set()
    for f, rows in att.items():
        for r in rows:
            if r["block"] != "paragraph":
                continue
            tot[r["origin"]][0] += 1
            tot[r["origin"]][1] += r["chars"]
            key = (f, r["section"] or "-")
            per.setdefault(key, {o: 0 for o in ORIGINS})[r["origin"]] += 1
    for e in entries(proj):
        if e.get("type") == "paragraph" and e.get("actor") == "ai" and e.get("kind") in AI_KINDS:
            m = e.get("materials") or {}
            purposes[m.get("purpose") or "draft"] = purposes.get(m.get("purpose") or "draft", 0) + 1
            claims |= set(m.get("claims") or [])
            sources |= set(m.get("sources") or [])
    n = sum(v[0] for v in tot.values())
    c = sum(v[1] for v in tot.values())
    return {"paragraphs": n, "chars": c, "by_origin": tot, "per_section": per, "purposes": purposes,
            "claims": sorted(claims), "sources": sorted(sources)}


def digest(proj):
    """Hash of the current attribution (what the final confirmation covers)."""
    s = summary(proj)
    obj = {"by_origin": s["by_origin"], "per_section": sorted([list(k), v] for k, v in s["per_section"].items())}
    return sha256_bytes(json.dumps(obj, sort_keys=True, ensure_ascii=False).encode("utf-8"))


def ai_paragraphs(proj, relp=None):
    """Current paragraphs whose latest record is the AI's (written or edited), with their entries."""
    out = []
    for f, rows in attribution(proj).items():
        if relp and f != relp:
            continue
        for r in rows:
            if r["block"] == "paragraph" and r["origin"] in AI_KINDS:
                out.append(dict(r, file=f))
    return out
