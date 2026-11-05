"""The evidence notebook (screen): the student starts it at their terminal, which alone shows the page's key; every API
request needs that key; an item can be decided only after its content was displayed (view token bound to
its digest); most decisions are recorded with one button and no passphrase; VERIFIED and the final confirmation
need the passphrase, and one entry signs several of them, each with its own digest; there is no accept-all
request; the server runs only from the installed plugin. A headless-browser test (Playwright) runs when node and
playwright exist."""
import json
import os
import re
import shutil
import subprocess
import sys
import time
import unittest
import urllib.error
import urllib.request

from helpers import PASS, PLUGIN, RKPY, Env

HAVE_PW = shutil.which("node") is not None and subprocess.run(["node", "-e", "require('playwright')"], capture_output=True).returncode == 0


class Server(object):
    """./rk notebook as the student starts it: on a terminal (a pseudo-terminal here), where the URL with the page's
    key (#k=...) is printed. Requests carry the key in X-RK-Session unless asked not to."""

    def __init__(self, env, script=RKPY):
        import pty
        import select
        pid, fd = pty.fork()
        if pid == 0:
            os.chdir(env.proj)
            os.execve(sys.executable, [sys.executable, "-B", script, "--project", env.proj, "notebook", "--port", "0"], env.env())
        self.pid, self.fd = pid, fd
        buf, m, t0 = b"", None, time.time()
        while time.time() - t0 < 60:
            r, _, _ = select.select([fd], [], [], 0.2)
            if not r:
                continue
            try:
                chunk = os.read(fd, 65536)
            except OSError:
                break
            if not chunk:
                break
            buf += chunk
            m = re.search(rb"http://127\.0\.0\.1:(\d+)/#k=([A-Za-z0-9_-]+)", buf)
            if m:
                break
        self.output = buf.decode("utf-8", "replace")
        if not m:
            self.close()
            raise RuntimeError(self.output)
        self.port = int(m.group(1))
        self.key = m.group(2).decode()
        self.url = "http://127.0.0.1:%d" % self.port

    def req(self, path, body=None, headers=None, host=None, key=True):
        h = {"Host": host or "127.0.0.1:%d" % self.port}
        if key:
            h["X-RK-Session"] = self.key
        data = None
        if body is not None:
            data = json.dumps(body).encode("utf-8")
            h.update({"Content-Type": "application/json", "X-RK-Request": "1", "Origin": self.url})
        h.update(headers or {})
        r = urllib.request.Request(self.url + path, data=data, headers=h, method="POST" if body is not None else "GET")
        try:
            with urllib.request.urlopen(r, timeout=60) as resp:
                return resp.status, json.loads(resp.read().decode("utf-8") or "{}")
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read().decode("utf-8") or "{}")

    def page(self):
        return urllib.request.urlopen(urllib.request.Request(self.url + "/", headers={"Host": "127.0.0.1:%d" % self.port})).read().decode("utf-8")

    def close(self):
        import signal
        try:
            os.kill(self.pid, signal.SIGTERM)
            os.waitpid(self.pid, 0)
        except OSError:
            pass
        try:
            os.close(self.fd)
        except OSError:
            pass


class Notebook(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.E = Env()
        cls.E.setup()
        cls.E.write("manuscript/main.md", "# はじめに\n\n要因 A，要因 B．\n\n１２３件を見た．\n")
        cls.E.rk("ledger", "add-source", "--doi", "10.1038/s41598-023-41032-5", "--title", "A placeholder title", "--year", "2023")
        cls.E.rk("ledger", "add-claim", "--claim", "現象 X(見本)", "--source-id", "S001", "--locator", "p. 3")
        r = cls.E.rk("propose", "start", "manuscript/main.md")
        work = cls.E.path(r.stdout.splitlines()[0])
        with open(work, "w", encoding="utf-8") as f:
            f.write("# はじめに\n\n要因 A、要因 B。\n\n123件を見た。\n")
        cls.E.rk("propose", "finish", r.stdout.splitlines()[0].split("/")[2], "--kind", "format", "--why", "表記の統一(見本)")
        cls.S = Server(cls.E)

    @classmethod
    def tearDownClass(cls):
        cls.S.close()
        cls.E.cleanup()

    def view(self, kind, sid):
        code, v = self.S.req("/api/view?kind=%s&id=%s" % (kind, urllib.request.quote(sid)))
        self.assertEqual(code, 200, v)
        return v

    def test_light_decision_needs_no_passphrase(self):
        v = self.view("rule", "punct")
        code, r = self.S.req("/api/sign", {"items": [{"kind": "rule", "id": "punct", "decision": "rejected", "token": v["token"]}]})
        self.assertEqual(code, 200, r)
        self.assertFalse(r["signed"][0]["with_passphrase"])
        recs = [json.loads(l) for l in self.E.read(".ryukoku", "signoffs.jsonl").splitlines() if l.strip()]
        self.assertTrue(any(x["kind"] == "rule" and x["sig"] == "" and x["method"] == "notebook" for x in recs))

    def test_absent_passphrase_creates_no_verified(self):
        v = self.view("claim", "C001")
        code, r = self.S.req("/api/sign", {"items": [{"kind": "claim", "id": "C001", "decision": "VERIFIED", "token": v["token"]}]})
        self.assertEqual(code, 403, r)
        code, r = self.S.req("/api/sign", {"passphrase": "", "items": [{"kind": "claim", "id": "C001", "decision": "VERIFIED", "token": v["token"]}]})
        self.assertEqual(code, 403)
        self.assertNotIn('"kind": "claim"', self.E.read(".ryukoku", "signoffs.jsonl"))

    def test_item_must_be_displayed_and_unchanged(self):
        code, r = self.S.req("/api/sign", {"passphrase": PASS, "items": [{"kind": "claim", "id": "C001", "decision": "VERIFIED"}]})
        self.assertEqual(code, 409, r)
        code, r = self.S.req("/api/sign", {"passphrase": PASS, "items": [{"kind": "claim", "id": "C001", "decision": "VERIFIED", "token": "0" * 32}]})
        self.assertEqual(code, 409, r)

    def test_request_hygiene(self):
        code, _ = self.S.req("/api/state", host="evil.test:80")
        self.assertEqual(code, 403)
        code, _ = self.S.req("/api/sign", {"passphrase": PASS, "items": []}, headers={"X-RK-Request": "0"})
        self.assertEqual(code, 403)
        code, _ = self.S.req("/api/sign", {"passphrase": PASS, "items": []}, headers={"Origin": "http://evil.test"})
        self.assertEqual(code, 403)

    def test_batch_hunks_light_and_verified_signed_with_one_passphrase(self):
        st = self.S.req("/api/list?tab=proposals")[1]
        hunks = [i["id"] for i in st["items"]]
        self.assertEqual(len(hunks), 2)
        items = []
        for h in hunks:
            v = self.view("hunk", h)
            self.assertTrue(any(op[0] != "equal" for op in v["ops"]))
            items.append({"kind": "hunk", "id": h, "decision": "accepted", "token": v["token"]})
        vs = self.view("source", "S001")
        vc = self.view("claim", "C001")
        items += [{"kind": "source", "id": "S001", "decision": "VERIFIED", "token": vs["token"]},
                  {"kind": "claim", "id": "C001", "decision": "VERIFIED", "token": vc["token"]}]
        code, r = self.S.req("/api/sign", {"passphrase": PASS, "items": items})
        self.assertEqual(code, 200, r)
        self.assertEqual(len(r["signed"]), 4)
        self.assertIn("要因 A、要因 B。", self.E.read("manuscript", "main.md"))
        recs = [json.loads(l) for l in self.E.read(".ryukoku", "signoffs.jsonl").splitlines() if l.strip()]
        self.assertEqual(len({r["digest"] for r in recs if r["kind"] in ("hunk", "source", "claim")}), 4)
        self.assertTrue(all(r["method"] == "notebook" and r["sig"] == "" for r in recs if r["kind"] == "hunk"))
        self.assertTrue(all(r["sig"] for r in recs if r["kind"] in ("source", "claim")))
        self.assertIn('"purpose": "format"', self.E.read(".ryukoku", "provenance.jsonl"))
        r = self.E.rk("check")
        self.assertEqual(r.returncode, 0, r.stdout)

    def test_the_page_key_is_required_and_never_served(self):
        # without the key that only the student's terminal showed, nothing is readable or recordable (an AI's curl, a
        # script reading the view token)
        for path in ("/api/state", "/api/list?tab=cards", "/api/view?kind=config&id=course-policy"):
            self.assertEqual(self.S.req(path, key=False)[0], 403, path)
        v = self.view("config", "course-policy")
        code, r = self.S.req("/api/sign", {"items": [{"kind": "config", "id": "course-policy", "decision": "confirmed", "token": v["token"]}]}, key=False)
        self.assertEqual(code, 403, r)
        self.assertEqual(self.S.req("/api/sign", {"items": []}, headers={"X-RK-Session": "0" * 43})[0], 403)
        # the key is in no response and not on stdout-like output of the API
        blobs = [self.S.page()] + [json.dumps(self.S.req(p)[1]) for p in ("/api/state", "/api/list?tab=submit", "/api/list?tab=research")]
        blobs.append(json.dumps(v))
        self.assertFalse(any(self.S.key in b for b in blobs))
        self.assertNotIn(self.S.key, self.E.read(".ryukoku", "signoffs.jsonl"))

    def test_wrong_passphrases_lock_signing(self):
        v = self.view("source", "S001")
        item = [{"kind": "source", "id": "S001", "decision": "VERIFIED", "token": v["token"]}]
        codes = [self.S.req("/api/sign", {"passphrase": "wrong-%d-passphrase" % i, "items": item})[0] for i in range(6)]
        self.assertEqual(codes[:5], [403] * 5)
        self.assertEqual(codes[5], 429)

    def test_no_accept_all_endpoint_and_page_has_no_such_button(self):
        for path in ("/api/accept-all", "/api/sign-all", "/api/apply"):
            self.assertEqual(self.S.req(path, {"x": 1})[0], 404)
        html = self.S.page()
        self.assertNotRegex(html, r"全部(を)?採用|accept all|select all|すべて選択")
        self.assertIn("全部をまとめて採用するボタンはない", html)


class Cards(unittest.TestCase):
    """A claim card: the AI drafts it, only the student confirms it (one button); editing the student's parts makes
    the confirmation stale, and a card that claims to be confirmed without a record fails the check."""

    def test_card_confirmation_by_button(self):
        E = Env()
        try:
            E.setup()
            r = E.rk("claims", "new", "--words", "要因 A は現象 X の一因になっていると思う")
            self.assertEqual(r.returncode, 0, r.stderr)
            p = E.path("claims", "C001.md")
            t = E.read("claims", "C001.md").replace("# 主張\n", "# 主張\n要因 A は現象 X の一因となりうる。\n").replace(
                "## 範囲と限定\n", "## 範囲と限定\n2010 年代の事例に限る。\n").replace(
                "## 予想される反論\n", "## 予想される反論\n- [ai_suggested] 逆の因果(現象 X が要因 A を生む)\n")
            open(p, "w", encoding="utf-8").write(t)
            self.assertEqual(E.rk("claims", "lint").returncode, 0)
            # the AI cannot confirm it by writing the file
            open(p, "w", encoding="utf-8").write(t.replace("status: draft", "status: confirmed"))
            r = E.rk("check")
            self.assertEqual(r.returncode, 1)
            self.assertIn("学生の確認の記録がない", r.stdout)
            open(p, "w", encoding="utf-8").write(t)
            S = Server(E)
            try:
                code, v = S.req("/api/view?kind=card&id=C001")
                self.assertEqual(code, 200, v)
                code, r = S.req("/api/sign", {"items": [{"kind": "card", "id": "C001", "decision": "confirmed", "token": v["token"]}]})
                self.assertEqual(code, 200, r)
            finally:
                S.close()
            self.assertIn("status: confirmed", E.read("claims", "C001.md"))
            r = E.rk("check")
            self.assertEqual(r.returncode, 0, r.stdout)
            self.assertIn("confirmed", E.rk("claims", "list").stdout)
            # an [ai_suggested] candidate may change without touching the confirmation; the student's claim may not
            t2 = E.read("claims", "C001.md").replace("逆の因果", "逆の因果の可能性")
            open(p, "w", encoding="utf-8").write(t2)
            self.assertIn("confirmed", E.rk("claims", "list").stdout)
            open(p, "w", encoding="utf-8").write(t2.replace("一因となりうる", "主な原因である"))
            self.assertIn("stale", E.rk("claims", "list").stdout)
            self.assertIn("確認の後に", E.rk("check").stdout)
        finally:
            E.cleanup()


class Launch(unittest.TestCase):
    def test_project_copy_refuses_to_serve(self):
        E = Env()
        try:
            r = E.rk("notebook", "--once")
            self.assertNotEqual(r.returncode, 0)
            self.assertIn("インストールされた Plugin から起動する", r.stderr)
        finally:
            E.cleanup()


@unittest.skipUnless(HAVE_PW, "node + playwright not available")
class Browser(unittest.TestCase):
    def test_headless_browser_flow(self):
        E = Env()
        try:
            E.setup()
            E.write("manuscript/main.md", "# はじめに\n\n要因 A，要因 B．\n")
            r = E.rk("propose", "start", "manuscript/main.md")
            with open(E.path(r.stdout.splitlines()[0]), "w", encoding="utf-8") as f:
                f.write("# はじめに\n\n要因 A、要因 B。\n")
            E.rk("propose", "finish", r.stdout.splitlines()[0].split("/")[2], "--kind", "format", "--why", "表記の統一(見本)")
            E.rk("ledger", "add-source", "--doi", "10.1038/s41598-023-41032-5", "--title", "A placeholder title", "--year", "2023")
            S = Server(E)
            try:
                js = os.path.join(os.path.dirname(os.path.abspath(__file__)), "js", "notebook.test.js")
                r = subprocess.run(["node", js, S.url + "/#k=" + S.key, PASS], capture_output=True, text=True, timeout=180)
                self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
                self.assertIn("要因 A、要因 B。", E.read("manuscript", "main.md"))
                recs = [json.loads(l) for l in E.read(".ryukoku", "signoffs.jsonl").splitlines() if l.strip()]
                self.assertTrue(any(x["kind"] == "hunk" and x["method"] == "notebook" and x["sig"] == "" for x in recs))
                self.assertTrue(any(x["kind"] == "source" and x["decision"] == "VERIFIED" and x["sig"] for x in recs))
            finally:
                S.close()
        finally:
            E.cleanup()


if __name__ == "__main__":
    unittest.main()
