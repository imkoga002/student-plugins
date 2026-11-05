"""Recording a batch of human decisions and applying them (shared by the terminal commands and the notebook screen).

Only VERIFIED and the final pre-submission confirmation are signed with the passphrase (sign.NEEDS_SIGNATURE);
every other decision becomes a light confirmation. A batch with no item that needs a signature asks for no
passphrase; a batch that has one derives the key once and signs only those items.

sign_batch(proj, items, passphrase, method)
  items: [{"kind", "id", "decision", "note"?, "digest"?, "where_how"?}] - one entry per item the person looked at.
  1. every item is looked up again (subjects.find); if the caller passes the digest it saw, it must still match
     (the screen sends the digest of what it displayed, so a change after display is refused, not signed)
  2. the passphrase is turned into the signing key once (trusted signers only), every item is signed with its own
     content digest, and the key is dropped when the batch ends - nothing stays able to sign
  3. the decision is applied: ledger human columns, style.yml, annotations, accepting/rejecting proposal hunks
     (the manuscript is written only here, for hunks the person accepted), restoring a detected change
There is no "accept everything" entry point: the caller must list each item (no bulk accept: each item must be
shown before it can be chosen).

Before the key is derived, every accepted hunk is applied in memory, file by
file, in the order of the batch; a hunk that can no longer be located (the manuscript changed, or an earlier hunk
in the same batch changed the same lines) and a section sign-off for a file that an accepted hunk in the same batch
changes are SKIPPED with a reason (nothing is written for them). The caller gets one result per item (signed /
skipped / failed / not processed), so the screen can drop what was signed and say exactly what was not.
"""
import os

from . import ledger, msguard, proposals, provenance, sign, style, subjects, trust
from .common import RkError, append_jsonl, load_config, now_iso, read_text, sha256_bytes, sha256_file, state_dir, today

ORDER = ("source", "card", "claim", "rule", "comment", "hunk", "change", "config", "optout", "ailog", "guarded", "import", "figure",
         "section", "presubmit")


class DecisionError(RkError):
    pass


def _check_items(proj, items, skipped):
    out = []
    for it in items:
        kind, sid, dec = it.get("kind"), str(it.get("id") or ""), it.get("decision")
        if kind not in subjects.KIND_DECISIONS:
            raise DecisionError("不明な種類: %r" % kind)
        if dec not in subjects.KIND_DECISIONS[kind]:
            raise DecisionError("%s に使える判断は %s" % (kind, "/".join(subjects.KIND_DECISIONS[kind])))
        subj = subjects.find(proj, kind, sid)
        if subj is None:
            skipped.append((it, "見つからない(もう署名済みか、消えた) / not found (already signed, or gone)"))
            continue
        if it.get("digest") and it["digest"] != subj.digest:
            skipped.append((it, "表示した後に内容が変わった。もう一度表示して確かめる / changed after it was displayed"))
            continue
        if kind == "rule" and subj.claimed == "approved":
            skipped.append((it, "承認済み / already approved"))
            continue
        out.append((it, subj))
    out.sort(key=lambda x: ORDER.index(x[1].kind))
    return out


def _plan(proj, checked, skipped):
    """Apply accepted hunks in memory (per file, in order) and drop what cannot be signed safely. Returns
    (checked, {hunk sid: text of its file after it})."""
    texts, after, touched, keep = {}, {}, set(), []
    for it, subj in checked:
        if subj.kind != "hunk":
            keep.append((it, subj))
            continue
        pid, n = subj.sid.split("#")
        meta = next((m for m in proposals.pending(proj) if m.get("id") == pid), None)
        if meta is None:
            skipped.append((it, "提案がない / proposal not found"))
            continue
        h = next((x for x in meta["hunks"] if x["n"] == int(n)), None)
        target = meta["target"]
        if target not in texts:
            try:
                texts[target] = read_text(os.path.join(proj, target))
            except OSError:
                skipped.append((it, "対象の原稿がない / target file missing"))
                continue
        cur = texts[target]
        if it["decision"] == "accepted":
            refused = proposals.recheck(dict(meta, hunks=[h]), proj, cur)
            if refused:
                skipped.append((it, "内容の不変の検査に通らない(採用できない): %s" % refused.get(h["n"])))
                continue
            base_ok = (target not in touched) and sha256_bytes(cur.encode("utf-8")) == meta.get("base_sha256")
            new_text, applied, unlocated = proposals.apply_hunks(cur, dict(meta, base_sha256=meta.get("base_sha256") if base_ok else "x"), {h["n"]})
            if unlocated or not applied:
                why = ("同じ一括の別の提案が同じ行を変えたため、位置を特定できない。片方だけ選ぶ / another hunk in this batch changed the same lines; choose one"
                       if target in touched else
                       "位置を原稿の中で特定できない(原稿が変わった)。AI に提案の作り直しを頼む / cannot be located (the manuscript changed); ask the AI to regenerate it")
                skipped.append((it, why))
                continue
            texts[target] = new_text
            touched.add(target)
            after[subj.sid] = new_text
        keep.append((it, subj))
    out = []
    for it, subj in keep:
        if subj.kind == "section" and subj.sid in touched:
            skipped.append((it, "この一括で採用する提案がこの節を変えるので、署名は採用の後にもう一度表示してから / an accepted hunk in this batch "
                                "changes this section: show it again after accepting, then sign"))
            continue
        out.append((it, subj))
    return out, after


def _require_note(it, subj):
    if subj.kind == "source" and it["decision"] == "VERIFIED" and subj.content.get("machine_status") in (
            "RETRACTED", "NOT_FOUND", "METADATA_MISMATCH") and not (it.get("note") or "").strip():
        raise DecisionError("文献 %s は機械の状態が %s。それでも使う理由をメモに書く" % (subj.sid, subj.content.get("machine_status")))
    if subj.kind == "claim" and it["decision"] == "VERIFIED" and not subj.content.get("locator"):
        raise DecisionError("主張 %s には該当箇所(頁・節)が要る。原典で確かめて、自分の端末の ./rk verify で入れる"
                            " / claim %s needs a locator (page, section): check the source and enter it with ./rk verify" % (subj.sid, subj.sid))
    if subj.kind == "claim" and it["decision"] == "CONTRADICTED" and not (it.get("note") or "").strip():
        raise DecisionError("主張 %s: 原典が主張を支えない理由をメモに書く(主張を原典に合わせて直すのは自分)" % subj.sid)
    if subj.kind == "ailog" and not (it.get("note") or "").strip():
        raise DecisionError("%s の概要(自分の言葉で)が空" % subj.sid)


def _apply(proj, it, subj, rec, signer):
    kind, dec = subj.kind, it["decision"]
    if kind in ("source", "claim"):
        path, fields = (ledger.paths(proj)[0], ledger.REGISTER) if kind == "source" else (ledger.paths(proj)[1], ledger.CLAIMS)
        key = "id" if kind == "source" else "claim_id"
        rows = ledger.read(path, fields)
        for r in rows:
            if (r.get(key) or "").strip() == subj.sid:
                r.update(human_status=dec, human_by=signer.get("name", ""), human_on=today(),
                         human_note=(it.get("note") or "").strip(), human_record=rec["id"])
        ledger.write(path, rows, fields)
    elif kind == "rule":
        _top, prop = style.load(style.proposed_path(proj))
        keep = [r for r in prop if r.get("id") != subj.sid]
        rule = next((r for r in prop if r.get("id") == subj.sid), None)
        with open(style.proposed_path(proj), "w", encoding="utf-8") as f:
            f.write("# 記法規則の提案(AI が抽出・提案。学生が承認するまで適用しない)\nversion: 1\nrules:\n")
            for r in keep:
                f.write(style.render_rule(r))
        if dec == "approved" and rule is not None:
            rule = dict(rule)
            rule.pop("status", None)
            rule["approved_record"] = rec["id"]
            ap = style.approved_path(proj)
            if not os.path.exists(ap):
                with open(ap, "w", encoding="utf-8") as f:
                    f.write("# 承認済みの記法規則。学生が署名した承認だけがここに入る(AI は .ryukoku/ に書けない)。\nversion: 1\nrules:\n")
            with open(ap, "a", encoding="utf-8") as f:
                f.write(style.render_rule(rule))
    elif kind == "card":
        # the file shows the state for readers; what counts is the record (rk check compares the two)
        import re as _re
        p = os.path.join(proj, "claims", subj.sid + ".md")
        try:
            text = read_text(p)
            new = _re.sub(r"(?m)^status:\s*\S+\s*$", "status: confirmed", text, count=1)
            if new != text:
                with open(p, "w", encoding="utf-8", newline="") as f:
                    f.write(new)
        except OSError:
            pass
    elif kind == "comment":
        from review.store import Store
        Store(proj).set_resolved(subj.sid, signer.get("role", "student"), rec["id"])
    elif kind == "change" and dec == "reverted":
        pass  # applied before signing (the after hash is part of the signed detail)
    return rec


def _apply_hunk_first(proj, it, subj, planned=None):
    """Apply (or reject) one hunk before signing; returns the detail to sign."""
    pid, n = subj.sid.split("#")
    meta = next((m for m in proposals.pending(proj) if m.get("id") == pid), None)
    if meta is None:
        raise DecisionError("提案 %s がない" % pid)
    h = next(x for x in meta["hunks"] if x["n"] == int(n))
    target = os.path.join(proj, meta["target"])
    cur = read_text(target)
    detail = {"target": meta["target"], "proposal": pid, "hunk": int(n), "pkind": meta.get("kind"),
              "before_sha256": sha256_bytes(cur.encode("utf-8"))}
    if it["decision"] == "accepted":
        refused = proposals.recheck(dict(meta, hunks=[h]), proj, cur)
        if refused:
            raise DecisionError("%s は内容の不変の検査に通らないので採用できない: %s" % (subj.sid, refused.get(h["n"])))
        new_text, applied, unlocated = proposals.apply_hunks(cur, meta, {h["n"]})
        if (unlocated or not applied) and planned is not None:
            new_text, applied, unlocated = planned, [h["n"]], []
        if unlocated or not applied:
            raise DecisionError("%s の位置を原稿の中で特定できない(原稿が変わった)。AI に提案の作り直しを頼む" % subj.sid)
        detail["after_sha256"] = sha256_bytes(new_text.encode("utf-8"))
        return detail, (target, new_text, meta, h)
    detail["after_sha256"] = detail["before_sha256"]
    return detail, (None, None, meta, h)


def _finish_hunk(proj, meta, h, decision):
    m = next((x for x in proposals.pending(proj) if x.get("id") == meta.get("id")), None)
    if m is None:
        return
    dec = proposals.decided(m)
    dec[h["n"]] = "y" if decision == "accepted" else "n"
    m["decided"] = ",".join("%d=%s" % (k, dec[k]) for k in sorted(dec))
    if {x["n"] for x in m["hunks"]} <= set(dec):
        proposals.finish(m, proj)
    else:
        proposals.write_meta(m)


def sign_batch(proj, items, passphrase, method="tty", results=None):
    """Sign and apply ITEMS with one passphrase entry. Returns the list of records written. RESULTS (a list), when
    given, receives one {"kind", "id", "status": signed|skipped|failed|not_processed, "reason"} per item."""
    if not items:
        raise DecisionError("署名する項目が選ばれていない / nothing selected")
    skipped = []
    checked = _check_items(proj, items, skipped)
    for it, subj in checked:
        _require_note(it, subj)
    checked, planned = _plan(proj, checked, skipped)
    res = results if results is not None else []
    for it, why in skipped:
        res.append({"kind": it.get("kind"), "id": str(it.get("id") or ""), "status": "skipped", "reason": why})
    if not checked:
        return []
    need = any(sign.needs_signature(subj.kind, it["decision"]) for it, subj in checked)
    signer, secret = {"name": who(proj), "role": "student", "key": ""}, None
    if need:
        if not passphrase:
            raise sign.SignError("VERIFIED と提出前の確認には合言葉の署名が要る / VERIFIED and the pre-submission confirmation need the passphrase")
        trusted, probs, _notes = trust.local_trusted(proj)
        if not trusted:
            raise DecisionError("信頼された署名者がいない。自分の端末で ./rk verify か ./rk signoff を実行すると、最初に合言葉を登録できる"
                                "(別の PC なら ./rk trust)。" + (" " + probs[0] if probs else ""))
        signer, secret = sign.unlock(trusted, passphrase)
    out = []
    done = set()
    try:
      for it, subj in checked:
        try:
            detail, note = {}, it.get("note") or ""
            pending_write = None
            if subj.kind == "hunk":
                detail, pending_write = _apply_hunk_first(proj, it, subj, planned.get(subj.sid))
            elif subj.kind == "change":
                detail = {"what": subj.content.get("what"), "target": subj.content.get("path")}
                if it["decision"] == "reverted":
                    if subj.content.get("what") != "manuscript":
                        raise DecisionError("%s は原稿の変更ではないので、戻す操作はない(git diff などで調べて自分で直し、mine か kept_ai を選ぶ)" % subj.sid)
                    src = msguard.before_copy_path(proj, subj.content)
                    if src is None:
                        raise DecisionError("%s の変更前の写しがこの PC にない。自分で元に戻してから mine を選ぶ" % subj.sid)
                    text = read_text(src)
                    detail["after_sha256"] = sha256_bytes(text.encode("utf-8"))
                    pending_write = (os.path.join(proj, subj.content["path"]), text, None, None)
            elif subj.kind == "ailog":
                detail = {"where_how": (it.get("where_how") or "").strip()[:500]}
            elif subj.kind == "presubmit":
                detail = {"checklist": list(subjects.CHECKLIST_IDS)}
            elif subj.kind == "section":
                detail = {"sha256": subj.content.get("sha256")}
            if sign.needs_signature(subj.kind, it["decision"]):
                rec = sign.make_record(signer, secret, subj.kind, subj.sid, it["decision"], subj.digest, detail, method, note)
            else:
                rec = sign.make_confirmation(subj.kind, subj.sid, it["decision"], subj.digest, detail, method, note,
                                             name=signer.get("name") or who(proj))
            if pending_write and pending_write[0]:
                before_text = read_text(pending_write[0]) if os.path.exists(pending_write[0]) else ""
                with open(pending_write[0], "w", encoding="utf-8", newline="") as f:
                    f.write(pending_write[1])
                relp = os.path.relpath(pending_write[0], proj).replace(os.sep, "/")
                if relp.startswith("manuscript/"):
                    # the AI's proposal, accepted by the student: provenance says so (purpose format)
                    provenance.sync_student(proj, relp, before_text)
                    provenance.record(proj, relp, before_text, pending_write[1], "ai" if subj.kind == "hunk" else "student",
                                      "proposal" if subj.kind == "hunk" else "revert", materials={"purpose": "format"})
            sign.append_signoffs(proj, [rec])
            _apply(proj, it, subj, rec, signer)
            if subj.kind == "hunk":
                _finish_hunk(proj, pending_write[2], pending_write[3], it["decision"])
                if it["decision"] == "accepted":
                    append_jsonl(os.path.join(proj, "disclosure", "ai-involvement.jsonl"),
                                 {"date": today(), "ts": now_iso(), "proposal": detail["proposal"], "hunk": detail["hunk"],
                                  "kind": detail["pkind"], "target": detail["target"], "record": rec["id"],
                                  "model": subj.content.get("model", ""), "by": subj.content.get("by", "")})
            if subj.kind == "optout":
                from .common import set_config_value
                set_config_value(proj, "optout_checked", "true")
                set_config_value(proj, "optout_checked_on", today())
            out.append(rec)
            done.add((subj.kind, subj.sid))
            res.append({"kind": subj.kind, "id": subj.sid, "status": "signed", "record": rec["id"], "decision": it["decision"]})
        except (DecisionError, OSError) as e:
            res.append({"kind": subj.kind, "id": subj.sid, "status": "failed", "reason": str(e)})
            for it2, subj2 in checked:
                if (subj2.kind, subj2.sid) not in done and not any(r["id"] == subj2.sid and r["kind"] == subj2.kind for r in res):
                    res.append({"kind": subj2.kind, "id": subj2.sid, "status": "not_processed",
                                "reason": "前の項目で止まったので処理していない / not processed (stopped at an earlier item)"})
            break
    finally:
        secret = None  # noqa: F841  (dropped: no session keeps the key)
    remember_signed_sections(proj, out)
    return out


def who(proj):
    """The name recorded with a light confirmation: the student's chosen name (./rk setup), else 'student'."""
    return (load_config(proj).get("student_name") or "student")[:60]


def section_diff_base(proj, relpath, idx):
    """(previous signed text or None, record) for the section sign-off screen (it shows what changed
    since the last signature)."""
    rec = sign.latest(idx, "section", relpath)
    if not rec:
        return None, None
    snap = os.path.join(state_dir(proj), "signed", (rec.get("detail") or {}).get("sha256", "x"))
    if os.path.exists(snap):
        return read_text(snap), rec
    return None, rec


def remember_signed_sections(proj, recs):
    """Keep a copy of each signed section outside the project, to show diffs at the next sign-off."""
    for r in recs:
        if r.get("kind") != "section":
            continue
        p = os.path.join(proj, r["subject"])
        try:
            h = sha256_file(p)
            d = os.path.join(state_dir(proj), "signed")
            os.makedirs(d, exist_ok=True)
            with open(os.path.join(d, h), "w", encoding="utf-8") as f:
                f.write(read_text(p))
        except OSError:
            pass
