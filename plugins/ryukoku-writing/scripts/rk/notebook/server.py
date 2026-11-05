"""Evidence notebook (証拠ノート): one local screen for reading the evidence and making every human decision.
Python standard library only; binds 127.0.0.1; no external requests; no CDN.

Tabs, Host/Origin checks, ARIA and both languages:
  * The student opens an item (the server returns its full content, its digest and a view token = HMAC(server
    secret, kind|id|digest)) and chooses a decision. POST /api/sign re-reads every item and refuses any item whose
    content changed since it was displayed (token mismatch) or that was never displayed (no token).
  * Most decisions (a claim card is mine, accept/reject a proposal, resolve a comment, approve a rule, ...) are
    recorded at once as light confirmations, one button per item, without the passphrase.
  * VERIFIED and the final pre-submission confirmation need the passphrase: they collect in the "to sign" list and
    one passphrase entry signs each with its own digest; the key is dropped afterwards (decide.sign_batch). There
    is no "accept all" request.
  * The AI may start this server (the passphrase is needed for anything that counts); the code always runs from
    the installed plugin, never from the project (rk.py notebook refuses the project copy, which an AI tool could have rewritten).
  * Every /api/ request needs the session key (header X-RK-Session). The key is made at server start, is never
    served by an endpoint and never written to stdout or to a file: it is printed only on the student's terminal
    (/dev/tty), as the #k=... fragment of the URL, which the browser does not send to the server. That is why the
    student starts this page with ./rk notebook in their own terminal: an AI tool call has no terminal, so a page the
    AI started could not be used, and a request the AI makes with curl has no key. The page keeps the key in
    sessionStorage and drops the fragment from the address bar. Limits: a program running with the student's rights
    can read the terminal or the browser's storage, or run its own server; the key stops prompt-less requests, not
    a program the student allowed.
  * Writes that are not decisions: a new comment or reply by the student, reopening a comment, and the reason for
    selecting a search result.
  * Five wrong passphrases lock signing for a while (exponential), to stop guessing through the screen.
"""
import difflib
import hashlib
import hmac
import json
import os
import re
import secrets
import sys
import threading
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

from rklib import bias, check, decide, msguard, proposals, provenance, search, searchlog, sign, subjects, trust  # noqa: E402
from rklib.common import RkError, feedback_lang, load_config, manuscript_files, read_text, rel, safe_rel  # noqa: E402
from rklib.common import plugin_version  # noqa: E402
from rklib.human import CHECKLIST, CODE_ROOT, why_proposals  # noqa: E402
from review.store import Store, StoreError, load_taxonomy  # noqa: E402

MAX_BODY = 2_000_000
MAX_FAILS = 5


class App(object):
    def __init__(self, proj, port):
        self.proj = os.path.abspath(proj)
        self.port = port
        self.secret = secrets.token_bytes(32)
        self.session = secrets.token_urlsafe(32)
        self.lock = threading.RLock()
        self.fails = 0
        self.locked_until = 0.0
        self.store = Store(self.proj)

    # ------------------------------------------------------------------ helpers
    def lang(self):
        return feedback_lang(self.proj)

    def token(self, kind, sid, digest):
        return hmac.new(self.secret, ("%s|%s|%s" % (kind, sid, digest)).encode("utf-8"), hashlib.sha256).hexdigest()[:32]

    def idx(self):
        trusted, _p, _n = trust.local_trusted(self.proj)
        return sign.valid_index(self.proj, trusted)[0], trusted

    # ------------------------------------------------------------------ reads
    def boot(self):
        cfg = load_config(self.proj)
        tax = load_taxonomy()
        return {"lang": self.lang(), "project": os.path.basename(self.proj), "manuscript_lang": cfg.get("manuscript_lang", "ja"),
                "codes": [{"code": c["code"], "ja": c["ja"], "en": c["en"]} for c in tax["codes"] if c["layer"] != "T"],
                "checklist": [{"id": k, "ja": CHECKLIST[k][0], "en": CHECKLIST[k][1]} for k in subjects.CHECKLIST_IDS],
                "why_proposals": why_proposals(self.lang()),
                "needs_signature": sorted([k, d] for k, d in sign.NEEDS_SIGNATURE),
                "code": {"root": CODE_ROOT, "version": plugin_version(CODE_ROOT)}}

    def state(self):
        idx, trusted = self.idx()
        rep = check.run(self.proj, stage="draft")
        cfg = load_config(self.proj)
        sm = provenance.summary(self.proj)
        return {"signers": [sign.fingerprint(k) for k in trusted], "errors": rep.errors[:30], "warns": rep.warns[:30],
                "notes": rep.notes[:10], "course": cfg.get("course_name", ""), "ai_policy": cfg.get("ai_policy", "unknown"),
                "provenance": {"paragraphs": sm["paragraphs"], "by_origin": {k: v[0] for k, v in sm["by_origin"].items()}},
                "counts": {"cards": len([c for c in subjects.cards(self.proj) if not sign.current(idx, "card", c.sid, c.digest)]),
                           "hunks": len(subjects.hunks(self.proj)), "changes": len(msguard.pending(self.proj, idx)),
                           "comments": len([c for c in subjects.comments(self.proj) if not c.claimed]),
                           "rules": len([r for r in subjects.rules(self.proj) if not r.claimed]),
                           "sources": len([s for s in subjects.sources(self.proj) if not s.claimed]),
                           "claims": len([s for s in subjects.claims(self.proj) if not s.claimed])}}

    def listing(self, tab):
        idx, _t = self.idx()

        def row(s, extra=None):
            r = {"kind": s.kind, "id": s.sid, "label": s.label, "claimed": s.claimed,
                 "decisions": list(subjects.KIND_DECISIONS[s.kind])}
            if s.claimed:
                r["signed"] = bool(sign.current(idx, s.kind, s.sid, s.digest, (s.claimed,)))
            r.update(extra or {})
            return r
        if tab == "proposals":
            return {"items": [row(s, dict({"target": s.content.get("target"), "why": s.content.get("why"), "stale": s.content.get("stale")},
                                          **({"decisions": ["rejected"]} if s.content.get("stale") else {})))
                              for s in subjects.hunks(self.proj)]}
        if tab == "cards":
            return {"items": [row(s, {"confirmed": bool(sign.current(idx, "card", s.sid, s.digest)),
                                      "stale": bool(sign.latest(idx, "card", s.sid)) and not sign.current(idx, "card", s.sid, s.digest)})
                              for s in subjects.cards(self.proj)]}
        if tab == "evidence":
            return {"sources": [row(s, {"machine": s.content.get("machine_status")}) for s in subjects.sources(self.proj)],
                    "claims": [row(s, {"source_human": s.content.get("source_human_status")}) for s in subjects.claims(self.proj)]}
        if tab == "rules":
            return {"items": [row(s) for s in subjects.rules(self.proj)]}
        if tab == "comments":
            return {"items": [row(s, {"doc": s.content.get("doc"), "code": s.content.get("code"), "creator": s.content.get("creator"),
                                      "channel": s.content.get("channel"),
                                      "severity": s.content.get("severity")}) for s in subjects.comments(self.proj)],
                    "docs": [rel(self.proj, p) for p in manuscript_files(self.proj)]}
        if tab == "changes":
            return {"items": [row(s) for s in msguard.pending(self.proj, idx)]}
        if tab == "submit":
            secs = []
            for s in subjects.sections(self.proj):
                secs.append(row(s, {"current": bool(sign.current(idx, "section", s.sid, s.digest))}))
            days = [row(s, {"confirmed": bool(sign.latest(idx, "ailog", s.sid))}) for s in subjects.ailog_days(self.proj)]
            ps = subjects.presubmit_subject(self.proj)
            from rklib import disclosure
            facts, _u = disclosure.facts(self.proj, self.lang())
            return {"sections": secs, "days": days, "presubmit": {"current": bool(sign.current(idx, "presubmit", ps.sid, ps.digest))},
                    "facts": facts, "statements": {r: read_text(os.path.join(self.proj, r)) for r in subjects.disclosure_statements(self.proj)}}
        if tab == "research":
            def rd(r):
                try:
                    return read_text(os.path.join(self.proj, r))
                except OSError:
                    return ""
            try:
                recs = searchlog.load(self.proj)
                probs = searchlog.validate(recs)[0]
            except Exception as e:  # noqa: BLE001
                recs, probs = [], [str(e)]
            return {"questions": rd("research/questions.md"), "plan": rd("research/plan.md"),
                    "thinking": rd("thinking/log.md"), "searchlog": recs, "problems": probs,
                    "question_ids": sorted(search.question_ids(self.proj)), "bias": bias.report(self.proj, self.lang())}
        raise KeyError(tab)

    def view(self, kind, sid):
        s = subjects.find(self.proj, kind, sid)
        if s is None:
            raise KeyError(sid)
        out = s.to_json()
        out["token"] = self.token(kind, sid, s.digest)
        if kind == "hunk" and s.content.get("stale"):
            out["decisions"] = ["rejected"]  # cannot be located any more: only rejecting it is possible
        idx, _t = self.idx()
        if kind == "hunk":
            c = s.content
            sm = difflib.SequenceMatcher(None, "\n".join(c["old"]), "\n".join(c["new"]), autojunk=False)
            out["ops"] = [[op, "\n".join(c["old"])[i1:i2], "\n".join(c["new"])[j1:j2]] for op, i1, i2, j1, j2 in sm.get_opcodes()]
        elif kind == "section":
            prev, rec = decide.section_diff_base(self.proj, sid, idx)
            cur = read_text(os.path.join(self.proj, sid))
            out["text"] = cur
            out["first"] = rec is None
            out["diff"] = list(difflib.unified_diff(prev.split("\n"), cur.split("\n"), "signed", "now", lineterm="", n=1)) if prev is not None else None
        elif kind == "change":
            d = s.content
            if d.get("what") == "protected":
                diffs = []
                for k, before, cur in msguard.protected_diffs(self.proj, d):
                    if before is None and cur is None:
                        diffs.append("--- %s: (binary or unreadable)" % k)
                        continue
                    diffs += list(difflib.unified_diff((before or "").split("\n"), (cur or "").split("\n"), "before/" + k, "now/" + k,
                                                       lineterm="", n=1))[:200]
                out["diff"] = diffs[:400]
                out["has_before"] = bool(diffs)
            if d.get("what") == "manuscript":
                src = msguard.before_copy_path(self.proj, d)
                before = read_text(src) if src else ""
                p = os.path.join(self.proj, d["path"])
                cur = read_text(p) if os.path.exists(p) else ""
                out["has_before"] = bool(src)
                out["diff"] = list(difflib.unified_diff(before.split("\n"), cur.split("\n"), "before", "now", lineterm="", n=1))[:400]
        elif kind == "ailog":
            from rklib import disclosure
            x = disclosure.by_day(self.proj).get(sid)
            if x:
                out["suggested"] = disclosure.suggested_summary(x, self.lang())
                out["models"] = sorted(x["models"])
                out["areas"] = x["areas"].most_common(10)
                out["prompts"] = x["prompts"]
        elif kind == "presubmit":
            rep = check.run(self.proj, stage="draft")
            out["errors"] = rep.errors
        elif kind == "section":
            pass
        if kind == "section":
            att = provenance.attribution(self.proj).get(sid, [])
            out["ai_paragraphs"] = [[r["start"], r["end"], r["origin"]] for r in att if r["origin"] in ("ai_wrote", "ai_edited", "uncertain", "student_after_ai")]
        return out

    def doc(self, relp):
        try:
            full, r = safe_rel(self.proj, relp, "manuscript/")
        except RkError:
            return None
        return read_text(full) if os.path.isfile(full) and full.endswith((".md", ".markdown", ".txt", ".tex")) else None

    # ------------------------------------------------------------------ signing
    def sign_items(self, body):
        with self.lock:
            now = time.time()
            if now < self.locked_until:
                return 429, {"error": "合言葉の誤りが続いたため、%d 秒待つ / too many wrong passphrases; wait %d s"
                                      % (int(self.locked_until - now) + 1, int(self.locked_until - now) + 1)}
            pw = body.get("passphrase")
            items = body.get("items")
            if not isinstance(items, list) or not items or len(items) > 500:
                return 400, {"error": "署名する項目がない / no items"}
            clean, results = [], []
            for it in items:
                if not isinstance(it, dict):
                    return 400, {"error": "bad item"}
                kind, sid = it.get("kind"), str(it.get("id") or "")
                s = subjects.find(self.proj, kind, sid) if kind in subjects.KIND_DECISIONS else None
                if s is None:  # already signed in an earlier, partly finished batch, or gone: skip, do not stop
                    results.append({"kind": kind, "id": sid, "status": "skipped",
                                    "reason": "見つからない(署名済みか、消えた) / not found (already signed, or gone)"})
                    continue
                if not hmac.compare_digest(str(it.get("token") or ""), self.token(kind, sid, s.digest)):
                    results.append({"kind": kind, "id": sid, "status": "skipped",
                                    "reason": "画面で表示した内容と今の内容が違う(または表示していない)。もう一度「表示」して確かめる"
                                              " / changed since displayed, or never displayed"})
                    continue
                if kind == "presubmit":
                    if sorted(it.get("checklist") or []) != sorted(subjects.CHECKLIST_IDS):
                        return 400, {"error": "提出前のチェックリストの全項目を確かめる / tick every checklist item"}
                    errs = check.run(self.proj, stage="draft").errors
                    if errs:
                        return 400, {"error": "先に検査のエラーを解消する: " + errs[0]}
                clean.append({"kind": kind, "id": sid, "decision": it.get("decision"), "digest": s.digest,
                              "note": str(it.get("note") or "")[:1000], "where_how": str(it.get("where_how") or "")[:500]})
            recs = []
            if not clean and any("displayed" in (r.get("reason") or "") for r in results):
                return 409, {"error": results[0]["reason"], "results": results}
            need = any(sign.needs_signature(c["kind"], c["decision"]) for c in clean)
            if need and (not isinstance(pw, str) or not pw):
                return 403, {"error": "VERIFIED と提出前の最終確認には合言葉の署名が要る(ほかの判断は合言葉なしで記録できる) / "
                                      "VERIFIED and the final confirmation need the passphrase"}
            if not need:
                pw = None
            try:
                if clean:
                    recs = decide.sign_batch(self.proj, clean, pw, method="notebook", results=results)
            except sign.SignError as e:
                if not need:
                    return 400, {"error": str(e), "results": results}
                self.fails += 1
                if self.fails >= MAX_FAILS:
                    self.locked_until = time.time() + 30 * (2 ** (self.fails - MAX_FAILS))
                return 403, {"error": str(e)}
            except decide.DecisionError as e:
                return 400, {"error": str(e), "results": results}
            finally:
                pw = None
                body["passphrase"] = None
            if need:
                self.fails = 0
            return 200, {"signed": [{"id": r["id"], "kind": r["kind"], "subject": r["subject"], "decision": r["decision"],
                                     "with_passphrase": bool(r.get("sig"))} for r in recs], "results": results}


def make_handler(app):
    allowed_hosts = {"127.0.0.1:%d" % app.port, "localhost:%d" % app.port}
    allowed_origins = {"http://" + h for h in allowed_hosts}
    with open(os.path.join(HERE, "notebook.html"), encoding="utf-8") as f:
        html_tpl = f.read()

    class H(BaseHTTPRequestHandler):
        server_version = "rk-notebook/1.0"

        def log_message(self, *a):
            pass

        def _send(self, code, obj=None, raw=None, ctype="application/json; charset=utf-8"):
            body = raw if raw is not None else json.dumps(obj, ensure_ascii=False).encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("Content-Security-Policy", "default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; "
                             "connect-src 'self'; img-src 'self' data:; base-uri 'none'; form-action 'none'; frame-ancestors 'none'")
            self.end_headers()
            self.wfile.write(body)

        def _host_ok(self):
            if self.headers.get("Host", "") not in allowed_hosts:
                self._send(403, {"error": "bad host"})
                return False
            return True

        def _session_ok(self):
            if not hmac.compare_digest(str(self.headers.get("X-RK-Session") or ""), app.session):
                self._send(403, {"error": "この画面の鍵がない。自分の端末で ./rk notebook を実行し、その端末に表示された URL から開く"
                                          " / no session key: open the URL that ./rk notebook printed in your own terminal"})
                return False
            return True

        def _body(self):
            o = self.headers.get("Origin")
            if o is not None and o not in allowed_origins:
                self._send(403, {"error": "bad origin"})
                return None
            if self.headers.get("X-RK-Request") != "1":
                self._send(403, {"error": "X-RK-Request header required"})
                return None
            try:
                n = int(self.headers.get("Content-Length", "0"))
            except ValueError:
                n = -1
            if n < 0 or n > MAX_BODY:
                self._send(413, {"error": "too large"})
                return None
            try:
                v = json.loads(self.rfile.read(n).decode("utf-8") or "{}")
                if not isinstance(v, dict):
                    raise ValueError
                return v
            except ValueError:
                self._send(400, {"error": "invalid json"})
                return None

        def do_GET(self):
            if not self._host_ok():
                return
            u = urlparse(self.path)
            q = parse_qs(u.query)
            g = lambda k: (q.get(k) or [""])[0]
            try:
                if u.path == "/":
                    blob = json.dumps(app.boot(), ensure_ascii=False).replace("</", "<\\/")
                    return self._send(200, raw=html_tpl.replace("/*__BOOT__*/null", blob).encode("utf-8"), ctype="text/html; charset=utf-8")
                if not self._session_ok():
                    return
                if u.path == "/api/state":
                    return self._send(200, app.state())
                if u.path == "/api/list":
                    return self._send(200, app.listing(g("tab")))
                if u.path == "/api/view":
                    return self._send(200, app.view(g("kind"), g("id")))
                if u.path == "/api/doc":
                    t = app.doc(g("path"))
                    return self._send(200, {"path": g("path"), "text": t}) if t is not None else self._send(404, {"error": "not found"})
                if u.path == "/api/annotations":
                    t = app.doc(g("doc"))
                    if t is None:
                        return self._send(404, {"error": "not found"})
                    return self._send(200, {"items": app.store.reanchor(g("doc"), t)})
            except KeyError:
                return self._send(404, {"error": "not found"})
            except (ValueError, OSError, RkError) as e:
                return self._send(500, {"error": str(e)})
            return self._send(404, {"error": "not found"})

        def do_POST(self):
            if not self._host_ok():
                return
            if not self._session_ok():
                return
            body = self._body()
            if body is None:
                return
            path = urlparse(self.path).path
            try:
                if path == "/api/sign":
                    code, obj = app.sign_items(body)
                    return self._send(code, obj)
                # the screen cannot tell who is typing: comments and replies made here are the student's, unsigned. An
                # advisor's comments come only through the signed terminal import of Word comments
                actor = body.get("actor", "student")
                if actor != "student":
                    return self._send(403, {"error": "画面からは学生の名義だけ(本人確認なし)。指導教員のコメントは ./rk import-docx(署名つき)で取り込む"
                                                     " / the screen creates student comments only (identity not verified); advisor comments come "
                                                     "through ./rk import-docx (signed)"})
                with app.lock:
                    if path == "/api/annotations":
                        t = app.doc(body.get("doc", ""))
                        if t is None:
                            return self._send(404, {"error": "doc not found"})
                        start, end = body.get("start"), body.get("end")
                        if body.get("quote") and start is None:
                            n = t.count(body["quote"])
                            if n != 1:
                                return self._send(400, {"error": "引用文が原稿に %d 箇所ある(1 箇所に絞る)" % n})
                            start = t.index(body["quote"])
                            end = start + len(body["quote"])
                        a = app.store.create(body["doc"], t, int(start), int(end), body.get("code"), body.get("comment"), actor,
                                             body.get("severity", "推奨"), channel="notebook")
                        return self._send(201, a)
                    m = re.fullmatch(r"/api/annotations/([^/]+)/replies", path)
                    if m:
                        return self._send(201, app.store.add_reply(m.group(1), actor, body.get("text"), channel="notebook"))
                    m = re.fullmatch(r"/api/annotations/([^/]+)/reopen", path)
                    if m:
                        return self._send(200, app.store.reopen(m.group(1), actor, "notebook"))
                    m = re.fullmatch(r"/api/searchlog/([^/]+)/annotate", path)
                    if m:
                        qref = body.get("question_ref") or None
                        if qref and qref not in search.question_ids(app.proj):
                            return self._send(400, {"error": "問い %s が research/questions.md にない" % qref})
                        return self._send(200, searchlog.annotate(app.proj, m.group(1), qref, body.get("selected"), body.get("reason")))
            except KeyError:
                return self._send(404, {"error": "not found"})
            except PermissionError as e:
                return self._send(403, {"error": str(e)})
            except (StoreError, RkError, TypeError, ValueError) as e:
                return self._send(400, {"error": str(e)})
            return self._send(404, {"error": "not found"})

    return H


def make_server(proj, port=0):
    srv = ThreadingHTTPServer(("127.0.0.1", port), BaseHTTPRequestHandler)
    app = App(proj, srv.server_address[1])
    srv.RequestHandlerClass = make_handler(app)
    srv.app = app
    return srv


def serve(proj, port=0, open_browser=False, once=False):
    from rklib.human import code_location_problem, plugin_integrity, running_code_lines
    lang = feedback_lang(proj)
    for ln in running_code_lines(lang):
        print(ln, flush=True)
    problem = plugin_integrity(proj) or code_location_problem(lang)
    if problem:
        print(problem, file=sys.stderr)
        return 3
    from rklib import sign as _sign
    if not once and not _sign.tty_available():
        print(("証拠ノートは、自分の端末(ターミナル)で ./rk notebook を実行して開く。画面の鍵はその端末にだけ表示する"
               "(AI のツールの呼び出しには端末が無いので、ここでは起動しない)。" if lang != "en" else
               "Open the evidence notebook with ./rk notebook in your own terminal; the page's key is shown only there "
               "(an AI tool call has no terminal, so it is not started here)."), file=sys.stderr)
        return 3
    srv = make_server(proj, port)
    url = "http://127.0.0.1:%d/" % srv.server_address[1]
    print(("証拠ノート: %s(この URL だけでは開けない。鍵つきの URL は端末にだけ表示する)\n(127.0.0.1 だけ・外部通信なし。終了は Ctrl+C。合言葉が要るのは VERIFIED と提出前の最終確認だけで、この画面の署名の欄にだけ入れる。チャットには入れない)" if lang != "en" else
           "Evidence notebook: %s (this URL alone does not open it; the URL with its key is shown on the terminal only)\n(127.0.0.1 only, no external requests; Ctrl+C to stop. Only VERIFIED and the final confirmation need the passphrase; type it only into this page's sign box, never into the chat.)") % url, flush=True)
    if once:
        return 0
    keyed = url + "#k=" + srv.app.session
    try:
        _sign.tty_print(("開く URL(鍵つき。チャットに貼らない): %s" if lang != "en" else "Open this URL (it carries the key; never paste it into the chat): %s") % keyed)
    except _sign.SignError as e:  # no console to show the key on: do not start (the key never goes to stdout)
        print(str(e), file=sys.stderr)
        srv.server_close()
        return 3
    if open_browser:
        webbrowser.open(keyed)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    return 0
