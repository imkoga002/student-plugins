#!/usr/bin/env python3
"""Python side of the hooks (standard library only). The bash hooks call it as
    python3 -I -B <plugin>/scripts/rk/hookcore.py <command> <project> [args...]
and treat any failure as "nothing to report" (a broken helper must never break the session).

  pre PROJ TOOL_USE_ID [run|ask]        msguard window before a tool call that may write ("ask": pending until
                                        PostToolUse shows the student allowed it)
  preall TOOL_USE_ID [run|ask]          the same for every registered project (no project in sight)
  post PROJ TOOL TOOL_USE_ID SUMMARY [COMMAND] [FILE_PATH]
                                        msguard comparison after it; prints {"entries": [...], ...}; records the
                                        files the call wrote as AI-written (execgate)
  postall TOOL TOOL_USE_ID SUMMARY [COMMAND] [FILE_PATH]
                                        post for every registered project that has a window for TOOL_USE_ID
  cmdscan PROJ PLUGIN_ROOT CWD SESSION  (stdin: a shell command) what code it would run: one finding per line,
                                        "kind<TAB>what" (execgate.scan)
  log PROJ                              append the JSON object on stdin to the chained AI-use log
  search PROJ DB QUERY                  automatic search record (WebSearch, WebFetch of a database search URL)
  session PROJ PLUGIN_ROOT              SessionStart status (pending work, tools integrity) as JSON; records the
                                        plugin location for the ./rk launcher (outside the project)
  nfkc                                  NFKC-normalise stdin (used before the personal-data scan)
"""
import json
import os
import sys
import unicodedata

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)


def _proj(p):
    p = os.path.abspath(p)
    if os.path.isfile(os.path.join(p, ".ryukoku", "config.yml")):
        return p
    from rklib.common import known_projects
    return p if os.path.realpath(p) in known_projects() and os.path.isdir(p) else None


def _registered():
    from rklib.common import known_projects
    return [p for p in known_projects() if os.path.isdir(p)]


def main(argv):
    if not argv:
        return 0
    cmd = argv[0]
    if cmd == "nfkc":
        data = sys.stdin.buffer.read().decode("utf-8", "replace")
        sys.stdout.write(unicodedata.normalize("NFKC", data).replace("−", "-").replace("‐", "-")
                         .replace("‑", "-").replace("–", "-").replace("—", "-").replace("ー", "-"))
        return 0
    if cmd == "preall":
        from rklib import msguard
        for p in _registered():
            msguard.pre(p, argv[1] if len(argv) > 1 else "", argv[2] if len(argv) > 2 else "run")
        return 0
    if cmd == "postall":
        from rklib import msguard
        from rklib.common import state_dir
        res = {"entries": [], "manuscript_changed": [], "other_changed": []}
        a = argv + [""] * 6
        a[2] = a[2] or "anon"  # pre() keys a call without tool_use_id as "anon"
        for p in _registered():
            if a[2] in msguard._windows(state_dir(p)):
                r = with_checks(p, msguard.post(p, a[1], a[3], a[2], a[4], a[5]))
                for k in ("entries", "manuscript_changed", "other_changed"):
                    res[k] += r[k]
                res.setdefault("provenance", []).extend(r.get("provenance") or [])
                res.setdefault("checks", []).extend(r.get("checks") or [])
                if r.get("note"):
                    res["note"] = (res.get("note", "") + "\n" + r["note"]).strip()
        print(json.dumps(res, ensure_ascii=False))
        return 0
    proj = _proj(argv[1]) if len(argv) > 1 else None
    if proj is None:
        return 0
    from rklib import ailog, msguard
    if cmd == "pre":
        msguard.pre(proj, argv[2] if len(argv) > 2 else "", argv[3] if len(argv) > 3 else "run")
    elif cmd == "post":
        a = argv + [""] * 7
        print(json.dumps(with_checks(proj, msguard.post(proj, a[2], a[4], a[3], a[5], a[6])), ensure_ascii=False))
    elif cmd == "cmdscan":
        from rklib import execgate
        a = argv + [""] * 5
        command = sys.stdin.read()
        try:
            found = execgate.scan(command, a[3] or proj, a[2], proj)
        except Exception as e:  # noqa: BLE001 - fail closed: an error in the scan asks the student
            found = [("unparsed", "internal error %s" % type(e).__name__)]
        for kind, what in found:
            print("%s\t%s" % (kind, str(what).replace("\t", " ").replace("\n", " ")[:200]))
        print("scanned\t1")  # without this line the hook treats the command as not analysed
    elif cmd == "log":
        try:
            obj = json.loads(sys.stdin.read() or "{}")
        except ValueError:
            return 0
        if isinstance(obj, dict):
            if obj.get("type") in ("event", "prompt", "session") and not obj.get("model"):
                m = _model(proj)
                if m == "unknown" and len(argv) > 2 and argv[2]:
                    m = _model_from_transcript(argv[2]) or m
                    if m != "unknown":
                        _set_model(proj, m)
                obj["model"] = m
            if obj.get("type") == "session" and obj.get("model"):
                _set_model(proj, obj["model"])
            ailog.append(proj, obj)
    elif cmd == "search":
        from rklib import searchlog
        db, query = argv[2], argv[3]
        searchlog.add(proj, db, query[:300], "", hits=None, filters="", by="agent", auto=True,
                      note="自動記録(PostToolUse)。question_ref と選んだ理由は rk.py searchlog annotate で補う")
    elif cmd == "pwcheck":
        print("match" if pwcheck(proj, sys.stdin.read()) else "")
    elif cmd == "stop":
        print(json.dumps(stop(proj), ensure_ascii=False))
    elif cmd == "session":
        print(json.dumps(session(proj, argv[2] if len(argv) > 2 else "", argv[3] if len(argv) > 3 else ""), ensure_ascii=False))
    return 0


def with_checks(proj, res):
    """After an AI write to the manuscript: the mechanical part of the verification for the files it changed
    (citations and their ledger state, uncited assertive sentences in AI paragraphs, numbers without a source, the
    swap candidates against the claim cards), so the agent shows the student at once what to check."""
    res.setdefault("checks", [])
    try:
        from rklib import verification
        from rklib.common import feedback_lang, read_text
        lang = feedback_lang(proj)
        for pr in res.get("provenance") or []:
            if not (pr.get("wrote") or pr.get("edited")):
                continue
            p = os.path.join(proj, pr["file"])
            if os.path.isfile(p):
                res["checks"] += verification.mechanical(proj, pr["file"], read_text(p), lang)[:12]
    except Exception as e:  # noqa: BLE001 - never break the session
        res["checks"].append("(mechanical check failed: %s)" % type(e).__name__)
    prov = [p for p in res.get("provenance") or [] if p.get("wrote") or p.get("edited") or p.get("deleted")]
    if prov:
        try:
            from rklib.common import feedback_lang
            en = feedback_lang(proj) == "en"
        except Exception:  # noqa: BLE001
            en = False
        what = "; ".join(("%s: wrote %d, revised %d, deleted %d paragraph(s)" if en else "%s: 新しく書いた段落 %d・直した段落 %d・消した段落 %d")
                         % (p["file"], p["wrote"], p["edited"], p["deleted"]) for p in prov)
        checks = " | ".join(res.get("checks") or []) or ("nothing" if en else "なし")
        res["note"] = (("[ryukoku-writing] The manuscript write was recorded as provenance (%s; .ryukoku/provenance.jsonl). "
                        "Mechanical checks (facts, not judgements): %s. Tell the student briefly what you wrote and these results. "
                        "Do not add claims, figures or sources that are not in the confirmed claim cards, the ledger or the saved data. "
                        "Check fatal or major candidates with the claim-verifier (if the text says more or something else than the "
                        "student's claim card, fix the text or ask the student; never change the student's claim to fit the text).")
                       if en else
                       ("[ryukoku-writing] 原稿への書き込みを由来の記録に残した(%s。.ryukoku/provenance.jsonl)。"
                        "機械の照合(事実であって判断ではない): %s。学生に、書いた内容とこの結果を短く示す。"
                        "確認済みの主張カード・台帳・保存したデータにない主張・数字・文献は足さない。"
                        "致命・重要の候補は claim-verifier で確かめる(文が学生の主張カードより強い・広い・別のことを言っていれば、"
                        "文を直すか学生に尋ねる。主張を文に合わせて変えない)。")) % (what, checks)
    return res


def _model_path(proj):
    from rklib.common import state_dir
    return os.path.join(state_dir(proj), "model")


def _model(proj):
    try:
        with open(_model_path(proj), encoding="utf-8") as f:
            return f.read().strip()[:80] or "unknown"
    except OSError:
        return "unknown"


def _model_from_transcript(path):
    """claude -p gives SessionStart no model; the transcript's assistant messages carry it."""
    import re
    try:
        with open(path, "rb") as f:
            f.seek(0, 2)
            n = f.tell()
            f.seek(max(0, n - 400000))
            tail = f.read().decode("utf-8", "replace")
    except OSError:
        return None
    found = re.findall(r'"model"\s*:\s*"([A-Za-z0-9._:\[\]-]{3,80})"', tail)
    found = [m for m in found if m not in ("unknown", "<synthetic>")]
    return found[-1] if found else None


def _set_model(proj, m):
    try:
        with open(_model_path(proj), "w", encoding="utf-8") as f:
            f.write(str(m)[:80])
    except OSError:
        pass


def pwcheck(proj, prompt):
    """True when the prompt (a short one-line message, or the value after a passphrase keyword) reproduces the
    public key of an active signer: the passphrase itself was typed into the chat. At most a few key
    derivations per prompt, so long messages are not tried."""
    import re
    from rklib import sign
    signers = [s for s in sign.load_signers(proj).values() if s.get("status", "active") == "active"][:3]
    if not signers:
        return False
    text = prompt.strip()
    cands = []
    if "\n" not in text and sign.MIN_PASSPHRASE <= len(text) <= 64:
        cands.append(text)
    for m in re.finditer(r"(?:合言葉|あいことば|パスフレーズ|pass ?phrase|password|パスワード)[^\n]{0,12}?(?:は|:|：|=|\bis\b)\s*[\"'「『]?([^\"'」』\n]{%d,64})"
                         % sign.MIN_PASSPHRASE, text, re.I):
        cands.append(m.group(1).strip().rstrip("。.」』"))
    seen, tried = set(), 0
    for c in cands:
        for v in (c, unicodedata.normalize("NFKC", c)):
            if v in seen or tried >= 4:
                continue
            seen.add(v)
            tried += 1
            for s in signers:
                kdf = s.get("kdf") or {}
                try:
                    sec = sign.derive_secret(v, kdf["salt"], kdf["iter"])
                except (KeyError, ValueError, TypeError):
                    continue
                if sign.ED.public_key(sec).hex() == s.get("pub"):
                    return True
    return False


def stop(proj):
    """Count what happened since the last turn marker, then append a new marker."""
    from rklib import ailog
    rows = ailog.read(proj)
    since = []
    for _ln, _raw, e in reversed(rows):
        if e and e.get("type") == "turn":
            break
        if e:
            since.append(e)
    det = sum(1 for e in since if e.get("type") == "detection")
    props = sum(1 for e in since if e.get("type") == "event" and e.get("area") == "rk:propose")
    nev = sum(1 for e in since if e.get("type") == "event")
    ms = sum(1 for e in since if e.get("type") == "event" and e.get("action") == "write" and e.get("area") == "manuscript")
    ver = sum(1 for e in since if e.get("type") == "event" and e.get("area") in ("rk:verification", "subagent") )
    ailog.append(proj, {"type": "turn", "events": nev, "detections": det, "proposal_runs": props, "manuscript_writes": ms})
    return {"detections": det, "proposal_runs": props, "manuscript_writes": ms, "verification_runs": ver}


def session(proj, plugin_root, sid=""):
    from rklib import ailog, check, common, execgate, msguard, proposals, search, sign, subjects, trust
    out = {}
    common.register_project(proj)
    if sid:
        execgate.session_start(sid)
    if plugin_root and os.path.isfile(os.path.join(plugin_root, "scripts", "rk", "rk.py")) \
            and not common.is_inside(plugin_root, proj):
        prob = common.record_plugin_root(plugin_root, sid)
        if prob:
            out["plugin_root_changed"] = prob
            ailog.append(proj, {"type": "detection", "id": "U-%s-root" % common.sha256_bytes(os.urandom(8))[:10],
                                "what": "protected", "parts": [prob], "tool": "SessionStart", "summary": "",
                                "at": __import__("time").time()})
    try:
        search.purge_expired_cache(proj)
    except Exception:  # noqa: BLE001 - never break the session
        pass
    try:
        from rklib import provenance
        out["student_edits_recorded"] = len(provenance.sync_student(proj))
    except Exception:  # noqa: BLE001
        pass
    miss = ailog.missing_witnessed(proj)
    out["missing_detections"] = len(miss)
    trusted, tprobs, _n = trust.local_trusted(proj)
    idx, _b = sign.valid_index(proj, trusted)
    out["signers"] = len(trusted)
    out["trust_problems"] = len(tprobs)
    out["pending_detections"] = len(msguard.pending(proj, idx))
    out["pending_hunks"] = len(subjects.hunks(proj))
    out["pending_proposals"] = len(proposals.pending(proj))
    out["open_comments"] = len([c for c in subjects.comments(proj) if not c.claimed])
    rep = check.Report()
    check.check_tools(proj, rep)
    out["tools_problems"] = rep.errors[:2]
    rep2 = check.Report()
    check.check_claude_settings(proj, rep2)
    out["settings_problems"] = rep2.errors[:2]
    out["optout_recorded"] = bool(sign.latest(idx, "optout", "optout"))
    cfg = subjects.config_subject(proj)
    out["config_signed"] = bool(sign.current(idx, "config", cfg.sid, cfg.digest))
    out["draft_cards"] = len([c for c in subjects.cards(proj) if not sign.current(idx, "card", c.sid, c.digest)])
    return out


if __name__ == "__main__":
    try:
        sys.exit(main(sys.argv[1:]))
    except Exception as e:  # never break the session
        sys.stderr.write("hookcore: %s\n" % type(e).__name__)
        sys.exit(0)
