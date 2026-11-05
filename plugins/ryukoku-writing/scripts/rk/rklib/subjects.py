"""What each human confirmation is bound to (kind, subject id, content digest), with a display payload for the
evidence notebook (the screen shows exactly what the digest covers before the student can choose).

Only VERIFIED (source, claim) and presubmit need the passphrase signature (sign.NEEDS_SIGNATURE); every other
decision is a light confirmation (a button or a key; recorded, bound to the digest, not signed).

  kind       subject           decisions                       digest covers
  source     register id       VERIFIED / REJECTED             identifiers + title/authors/year
  card       C001              confirmed                       the student-owned parts of the claim card
  claim      claim_id          VERIFIED / CONTRADICTED /       claim text, locator, source id and its identity
                               NOT_FOUND
  rule       rule id           approved / rejected             every rule field except status/approved_record
  comment    annotation id     resolved                        document, quoted text, code, comment, replies
  hunk       P0003#2           accepted / rejected             proposal id, target, kind, why, rule, context,
                                                               old and new lines
  section    manuscript path   reviewed                        file SHA-256
  config     course-policy     confirmed                       course, ai_policy, allowed uses, source, disclosure
  optout     optout            checked                         the statement itself (date in the record)
  ailog      YYYY-MM-DD        confirmed                       that day's AI-use log lines (summary in note)
  change     detection id      kept_ai / mine / reverted       the detection entry in the AI-use log
  presubmit  submission        ready                           every manuscript/ledger/style/claim-card hash, the
                                                               provenance attribution, the disclosure statement
                                                               and the checklist
  import     docx file name    imported                        the .docx file's SHA-256
  guarded    tools             confirmed                       every file of tools/, the launchers, .github/ and
                                                               .githooks/ that differs from the plugin's copy
                                                               (locally) or from the base branch (CI)
A state written in the project (human_status, resolved, style.yml) counts only when the latest valid record
for that subject matches the current digest; editing the subject afterwards makes the record stale.
"""
import json
import os

from . import ailog, claimcards, ledger, proposals, provenance, style
from .common import load_config, manuscript_files, project_id, rel, sha256_file, subject_hash

KIND_DECISIONS = {
    "source": ("VERIFIED", "REJECTED"),
    "card": ("confirmed",),
    "claim": ("VERIFIED", "CONTRADICTED", "NOT_FOUND"),
    "rule": ("approved", "rejected"),
    "comment": ("resolved",),
    "hunk": ("accepted", "rejected"),
    "section": ("reviewed",),
    "config": ("confirmed",),
    "optout": ("checked",),
    "ailog": ("confirmed",),
    "change": ("kept_ai", "mine", "reverted"),
    "presubmit": ("ready",),
    "import": ("imported",),
    "guarded": ("confirmed",),
}
POLICY_KEYS = ("course_name", "ai_policy", "ai_allowed_uses", "ai_policy_source", "disclosure_format")
CHECKLIST_IDS = ("claims_mine", "disclosure_true", "facts_verified", "quotes_marked", "integrity",
                 "course_policy", "no_personal_data", "faculty_rules")


class Subject(object):
    __slots__ = ("kind", "sid", "digest", "label", "content", "claimed")

    def __init__(self, kind, sid, digest, label, content=None, claimed=""):
        self.kind, self.sid, self.digest, self.label = kind, sid, digest, label
        self.content, self.claimed = content or {}, claimed or ""

    def to_json(self):
        return {"kind": self.kind, "id": self.sid, "digest": self.digest, "label": self.label,
                "content": self.content, "claimed": self.claimed, "decisions": list(KIND_DECISIONS[self.kind])}


def _d(obj):
    return subject_hash(obj)


def source_identity(row):
    return {k: (row.get(k) or "").strip() for k in ledger.SOURCE_KEYS}


def sources(proj):
    out = []
    for r in ledger.read(ledger.paths(proj)[0], ledger.REGISTER):
        ident = source_identity(r)
        c = dict(ident, machine_status=r.get("machine_status", ""), machine_note=r.get("machine_note", ""),
                 container=r.get("container", ""), medium=r.get("medium", ""), human_note=r.get("human_note", ""))
        out.append(Subject("source", ident["id"], _d(dict(kind="source", **ident)),
                           "%s %s(%s)" % (ident["id"], ident["title"][:60], ident["year"]), c,
                           (r.get("human_status") or "").strip()))
    return out


def claims(proj):
    reg = {r.get("id"): r for r in ledger.read(ledger.paths(proj)[0], ledger.REGISTER)}
    out = []
    for r in ledger.read(ledger.paths(proj)[1], ledger.CLAIMS):
        src = reg.get((r.get("source_id") or "").strip(), {})
        obj = {"kind": "claim", "claim_id": (r.get("claim_id") or "").strip(), "claim": (r.get("claim") or "").strip(),
               "source_id": (r.get("source_id") or "").strip(), "locator": (r.get("locator") or "").strip(),
               "source": source_identity(src)}
        c = dict(obj, used_in=r.get("used_in", ""), source_machine_status=src.get("machine_status", ""),
                 source_human_status=src.get("human_status", ""))
        hs = (r.get("human_status") or "").strip()
        out.append(Subject("claim", obj["claim_id"], _d(obj), "%s「%s」← %s %s" % (obj["claim_id"], obj["claim"][:50],
                           obj["source_id"], obj["locator"]), c, "" if hs == "CANDIDATE" else hs))
    return out


def cards(proj):
    out = []
    for c in claimcards.cards(proj):
        st = c["status"] if c["status"] == "confirmed" else ""
        content = {"id": c["id"], "sections": c["sections"], "items": c["items"], "student_part": claimcards.student_part(c),
                   "status_in_file": c["status"]}
        claim = " ".join(it["text"] for it in c["items"].get("claim", []) if not it["ai"])
        out.append(Subject("card", c["id"], claimcards.digest(c), "%s「%s」" % (c["id"], claim[:60]), content, st))
    return out


def rules(proj):
    out = []
    _t, prop = style.load(style.proposed_path(proj))
    for r in prop:
        if r.get("status", "proposed") == "proposed":
            out.append(Subject("rule", r.get("id", ""), style.rule_subject(r), "%s: %s = %s" % (r.get("id"), r.get("kind"), r.get("value")),
                               {k: r.get(k, "") for k in style.FIELDS if k != "approved_record"}, ""))
    _t, appr = style.load(style.approved_path(proj))
    for r in appr:
        out.append(Subject("rule", r.get("id", ""), style.rule_subject(r), "%s: %s = %s" % (r.get("id"), r.get("kind"), r.get("value")),
                           {k: r.get(k, "") for k in style.FIELDS if k != "approved_record"}, "approved"))
    return out


def _annotations(proj):
    p = os.path.join(proj, "review", "annotations.json")
    try:
        with open(p, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return []
    return data.get("items", []) if isinstance(data, dict) else []


def comment_obj(a):
    exact = ""
    for s in (a.get("target") or {}).get("selector") or []:
        if s.get("type") == "TextQuoteSelector":
            exact = s.get("exact", "")
    text = ""
    for b in a.get("body") or []:
        if b.get("purpose") == "commenting":
            text = b.get("value", "")
    rv = a.get("review") or {}
    return {"kind": "comment", "id": a.get("id"), "doc": (a.get("target") or {}).get("source"), "exact": exact,
            "code": rv.get("code"), "comment": text, "creator": (a.get("creator") or {}).get("name"),
            "replies": [[x.get("author"), x.get("kind"), x.get("text")] for x in rv.get("replies") or []]}


def comments(proj):
    out = []
    for a in _annotations(proj):
        o = comment_obj(a)
        st = (a.get("review") or {}).get("status")
        out.append(Subject("comment", a.get("id", ""), _d(o), "%s [%s]「%s」" % (o["doc"], o["code"], (o["exact"] or "")[:40]),
                           dict(o, severity=(a.get("review") or {}).get("severity"),
                                channel=(a.get("review") or {}).get("channel") or ("agent-cli" if o["creator"] == "agent" else "")),
                           "resolved" if st == "resolved" else ""))
    return out


def hunk_obj(meta, h):
    return {"kind": "hunk", "proposal": meta.get("id"), "target": meta.get("target"), "pkind": meta.get("kind"),
            "why": meta.get("why", ""), "rule": meta.get("rule", ""), "before": h["before"], "old": h["old"],
            "new": h["new"], "after": h["after"]}


def hunks(proj):
    """Pending hunks. A hunk that can no longer be located in the current manuscript is marked stale (it can
    only be rejected; the AI regenerates the proposal)."""
    from .common import feedback_lang, read_text, sha256_bytes
    en = feedback_lang(proj) == "en"
    out = []
    for m in proposals.pending(proj):
        dec = proposals.decided(m)
        try:
            text = read_text(os.path.join(proj, m.get("target") or ""))
        except OSError:
            text = None
        lines = text.split("\n") if text is not None else []
        base_ok = text is not None and sha256_bytes(text.encode("utf-8")) == m.get("base_sha256")
        for h in m["hunks"]:
            if h["n"] in dec:
                continue
            o = hunk_obj(m, h)
            stale = text is None or proposals.locate(lines, h, base_ok) is None
            label = "%s#%d %s %s %d %s" % (m["id"], h["n"], m.get("target"), "line" if en else "行", h["old_start"], h.get("note", ""))
            if stale:
                label += " [needs regenerating]" if en else " [作り直しが要る]"
            out.append(Subject("hunk", "%s#%d" % (m["id"], h["n"]), _d(o), label,
                               dict(o, line=h["old_start"], note=h.get("note", ""), stale=stale,
                                    created=m.get("created", ""), model=m.get("model", ""), by=m.get("by", "")), ""))
    return out


def sections(proj):
    out = []
    for p in manuscript_files(proj):
        r = rel(proj, p)
        h = sha256_file(p)
        out.append(Subject("section", r, _d({"kind": "section", "path": r, "sha256": h}), "%s(sha256 %s)" % (r, h[:12]),
                           {"path": r, "sha256": h}, ""))
    return out


def config_subject(proj):
    cfg = load_config(proj)
    obj = {"kind": "config"}
    obj.update({k: cfg.get(k, "") for k in POLICY_KEYS})
    return Subject("config", "course-policy", _d(obj), "科目 %s / AI 利用条件 %s / 用途 %s" % (
        obj["course_name"] or "(未記入)", obj["ai_policy"] or "unknown", obj["ai_allowed_uses"] or "-"), obj, "")


def optout_subject(proj):
    return Subject("optout", "optout", _d({"kind": "optout", "project": project_id(proj)}),
                   "学習へのオプトアウトを確認した / checked the training opt-out", {}, "")


def ailog_days(proj):
    rows = ailog.read(proj)
    days = {}
    for _ln, raw, obj in rows:
        if obj and obj.get("date"):
            days.setdefault(obj["date"], []).append(raw)
    return [Subject("ailog", d, _d({"kind": "ailog", "date": d, "lines": lines}), "%s(記録 %d 行)" % (d, len(lines)),
                    {"date": d, "lines": len(lines)}, "") for d, lines in sorted(days.items())]


def detection_obj(e):
    return {k: v for k, v in e.items() if k not in ("prev",)}


def changes(proj):
    out = []
    for _ln, _raw, e in ailog.read(proj):
        if e and e.get("type") == "detection" and e.get("id"):
            out.append(Subject("change", e["id"], _d({"kind": "change", "entry": detection_obj(e)}),
                               "%s %s %s" % (e["id"], e.get("what"), e.get("path") or ", ".join(e.get("parts") or [])),
                               detection_obj(e), ""))
    return out


def presubmit_subject(proj):
    def fh(relp):
        p = os.path.join(proj, relp)
        return sha256_file(p) if os.path.exists(p) else ""
    obj = {"kind": "presubmit", "manuscript": {rel(proj, p): sha256_file(p) for p in manuscript_files(proj)},
           "register": fh(os.path.join("sources", "register.csv")), "claims": fh(os.path.join("sources", "claims.csv")),
           "style": fh(style.APPROVED_REL), "checklist": list(CHECKLIST_IDS),
           "cards": {rel(proj, p): sha256_file(p) for p in claimcards.card_files(proj)},
           "provenance": provenance.digest(proj), "disclosure": disclosure_statements(proj)}
    return Subject("presubmit", "submission", _d(obj), "提出物一式(原稿 %d 件・台帳・記法・主張カード・由来・開示文・チェックリスト)" % len(obj["manuscript"]),
                   obj, "")


def disclosure_statements(proj):
    """{rel path: sha256} of the AI-use disclosure statement drafts (disclosure/statement*.md)."""
    d = os.path.join(proj, "disclosure")
    out = {}
    if os.path.isdir(d):
        for fn in sorted(os.listdir(d)):
            if fn.startswith("statement") and fn.endswith(".md"):
                out["disclosure/" + fn] = sha256_file(os.path.join(d, fn))
    return out


def import_subject(docx_path):
    name = os.path.basename(docx_path)
    return Subject("import", name, _d({"kind": "import", "file": name, "sha256": sha256_file(docx_path)}), name, {"file": name}, "")


def _plugin_root():
    """The plugin whose shipped copies the project's tools and CI files are compared with (None if unknown)."""
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # .../scripts/rk or .../tools/rk
    cand = os.path.dirname(os.path.dirname(here))
    if os.path.isdir(os.path.join(cand, "templates", "github")):
        return cand
    from .common import state_home
    try:
        with open(os.path.join(state_home(), "plugin-root"), encoding="utf-8") as f:
            r = f.readline().strip()
        return r if os.path.isdir(os.path.join(r, "templates", "github")) else None
    except OSError:
        return None


def guarded_files(proj, base_ref=None):
    """{rel path: sha or 'deleted'} of the guarded files that differ from the plugin (or the base branch)."""
    from .common import run_git
    out = {}
    if base_ref:
        r = run_git(proj, ["diff", "--name-only", "%s...HEAD" % base_ref, "--", "tools", "rk", "rk.cmd", "rk.ps1",
                           ".github", ".githooks"], timeout=30)
        names = [x.strip() for x in r.stdout.splitlines() if x.strip()] if (r is not None and r.returncode == 0) else []
        for n in names:
            p = os.path.join(proj, n)
            out[n] = sha256_file(p) if os.path.isfile(p) else "deleted"
        return out
    root = _plugin_root()
    if not root:
        return out
    pairs = []
    for sub, shipped in (("tools/rk", os.path.join(root, "scripts", "rk")), (".github", os.path.join(root, "templates", "github", ".github")),
                         (".githooks", os.path.join(root, "templates", "github", ".githooks"))):
        seen = set()
        for base, prefix in ((shipped, sub), (os.path.join(proj, sub), sub)):
            if not os.path.isdir(base):
                continue
            for dp, dns, fns in os.walk(base):
                dns[:] = [d for d in dns if d != "__pycache__"]
                for fn in fns:
                    if fn.endswith(".pyc"):
                        continue
                    r = os.path.relpath(os.path.join(dp, fn), base).replace(os.sep, "/")
                    if r not in seen:
                        seen.add(r)
                        pairs.append((prefix + "/" + r, os.path.join(shipped, r)))
    for name in ("rk", "rk.cmd", "rk.ps1"):
        pairs.append((name, os.path.join(root, "scripts", "rk", "launchers", name)))
    for relp, ship in pairs:
        mine = os.path.join(proj, relp)
        a = sha256_file(mine) if os.path.isfile(mine) else "deleted"
        b = sha256_file(ship) if os.path.isfile(ship) else "absent"
        if a != b and not (a == "deleted" and b == "absent"):
            out[relp] = a
    return out


def guarded_subject(proj, base_ref=None):
    """sid 'tools': differences from the plugin's copies (local check). sid 'pr': files changed against the base
    branch (CI, and `./rk sign guarded pr` before pushing a PR that changes them)."""
    files = guarded_files(proj, base_ref)
    sid = "pr" if base_ref else "tools"
    obj = {"kind": "guarded", "scope": sid, "files": sorted(files), "sha": files}
    return Subject("guarded", sid, _d(obj), "道具・CI の設定の変更 %d 件" % len(files),
                   {"scope": sid, "files": sorted(files), "sha": files, "base_ref": base_ref or ""}, "")


POOLS = {"source": sources, "card": cards, "claim": claims, "rule": rules, "comment": comments, "hunk": hunks,
         "section": sections, "ailog": ailog_days, "change": changes}


def find(proj, kind, sid):
    if kind not in KIND_DECISIONS:
        return None
    if kind == "config":
        return config_subject(proj)
    if kind == "optout":
        return optout_subject(proj)
    if kind == "presubmit":
        return presubmit_subject(proj)
    if kind == "guarded":
        if sid == "pr":
            return guarded_subject(proj, load_config(proj).get("base_ref") or "origin/main")
        return guarded_subject(proj)
    if kind == "import":
        return None
    hit = None
    for s in POOLS[kind](proj):
        if s.sid == sid:
            hit = s  # rules: the approved copy (listed last) wins
    return hit
