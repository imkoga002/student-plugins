"""The evidence notebook (screen) and its batch-signing rules — nothing counts
without the passphrase; an item can be signed only after its content was displayed (view token bound to its
digest); one passphrase entry signs several items, each with its own digest; there is no accept-all request; the
server runs only from the installed plugin. A headless-browser test (Playwright) runs when node and playwright exist."""
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
    def __init__(self, env, script=RKPY):
        self.p = subprocess.Popen([sys.executable, "-B", script, "--project", env.proj, "notebook", "--port", "0"],
                                  stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=env.env(), cwd=env.proj)
        line, m = "", None
        for _ in range(8):  # the running code's location and version come first
            ln = self.p.stdout.readline()
            if not ln:
                break
            line += ln
            m = re.search(r"http://127\.0\.0\.1:(\d+)/", ln)
            if m:
                break
        if not m:
            self.p.kill()
            raise RuntimeError(line + self.p.stderr.read())
        self.port = int(m.group(1))
        self.url = "http://127.0.0.1:%d" % self.port

    def req(self, path, body=None, headers=None, host=None):
        h = {"Host": host or "127.0.0.1:%d" % self.port}
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

    def close(self):
        self.p.terminate()
        try:
            self.p.wait(timeout=10)
        except subprocess.TimeoutExpired:
            self.p.kill()
        self.p.stdout.close()
        self.p.stderr.close()


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

    def test_absent_passphrase_creates_no_state(self):
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

    def test_batch_sign_hunks_and_claim_with_one_passphrase(self):
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
        self.assertTrue(all(r["method"] == "notebook" for r in recs if r["kind"] == "hunk"))
        r = self.E.rk("check")
        self.assertEqual(r.returncode, 0, r.stdout)

    def test_wrong_passphrases_lock_signing(self):
        v = self.view("rule", "punct")
        item = [{"kind": "rule", "id": "punct", "decision": "rejected", "token": v["token"]}]
        codes = [self.S.req("/api/sign", {"passphrase": "wrong-%d-passphrase" % i, "items": item})[0] for i in range(6)]
        self.assertEqual(codes[:5], [403] * 5)
        self.assertEqual(codes[5], 429)

    def test_no_accept_all_endpoint_and_page_has_no_such_button(self):
        for path in ("/api/accept-all", "/api/sign-all", "/api/apply"):
            self.assertEqual(self.S.req(path, {"x": 1})[0], 404)
        html = urllib.request.urlopen(urllib.request.Request(self.S.url + "/", headers={"Host": "127.0.0.1:%d" % self.S.port})).read().decode("utf-8")
        self.assertNotRegex(html, r"全部(を)?採用|accept all|select all|すべて選択")
        self.assertIn("全部をまとめて採用するボタンはない", html)


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
            S = Server(E)
            try:
                js = os.path.join(os.path.dirname(os.path.abspath(__file__)), "js", "notebook.test.js")
                r = subprocess.run(["node", js, S.url, PASS], capture_output=True, text=True, timeout=180)
                self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
                self.assertIn("要因 A、要因 B。", E.read("manuscript", "main.md"))
                recs = [json.loads(l) for l in E.read(".ryukoku", "signoffs.jsonl").splitlines() if l.strip()]
                self.assertTrue(any(x["kind"] == "hunk" and x["method"] == "notebook" for x in recs))
            finally:
                S.close()
        finally:
            E.cleanup()


if __name__ == "__main__":
    unittest.main()
