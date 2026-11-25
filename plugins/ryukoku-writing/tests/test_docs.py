"""The Claude Docs guard (3.0): the hooks for the Claude Docs tools (scripts/hooks/docs-guard.sh, rklib/docsguard.py).

The tool inputs and server answers below follow what the Claude Docs tools sent and answered on 2026-11-25
(SELF-ASSESSMENT.md): an AI comment carries actor.via "mcp", a comment the person typed in the page carries
actor.via "frame", both with the same principal and actor.self true.
"""
import json
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from helpers import Env, decision, reason  # noqa: E402

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts", "rk"))
from rklib import common, docsguard  # noqa: E402

DOC = "8c3b0e34-6ad9-41c9-a1fa-f1afafe7d482"
TABS = [("原稿", "f-man", "b-man"), ("主張カード", "f-clm", "b-clm"), ("文献台帳", "f-src", "b-src"),
        ("問いと思考の記録", "f-thk", "b-thk"), ("検証", "f-ver", "b-ver"), ("設定", "f-set", "b-set"),
        ("開示と提出前", "f-dis", "b-dis")]
T = "mcp__Claude_Docs__"
C = {"kind": "project", "id": DOC}


def project_read(tabs=TABS, slug=DOC):
    files = [{"id": f, "name": "Tab", "mime": "application/vnd.claude.page", "content": {"id": b, "kind": "node", "engine": "prose"}}
             for _n, f, b in tabs]
    value = {"name": "卒業論文", "artifact": {"slug": slug}, "tabs": {f: {"name": n, "order": "a%d" % i} for i, (n, f, _b) in enumerate(tabs)}}
    return [{"type": "text", "text": json.dumps({"verdict": "allow", "value": value, "files": files,
                                                  "frame": {"url": "https://claude.ai/artifact/X"}}) + "\n\nprose after the JSON"}]


def row(cid, body, via, parent="b-clm", seq=1):
    return {"seq": seq, "at": "2026-11-25T10:39:55Z", "verb": "create", "id": cid,
            "actor": {"principal": "u_x", "channel": "external", "via": via, "self": True, "name": "s"},
            "payload": {"value": {"body": body, "parent": {"object": "node", "id": parent}}}}


class DocsBase(unittest.TestCase):
    def setUp(self):
        self.e = Env()

    def tearDown(self):
        self.e.cleanup()

    def call(self, event, short, ti, resp=None, tuid="d1"):
        payload = {"hook_event_name": "PreToolUse" if event == "pre" else "PostToolUse", "cwd": self.e.proj,
                   "tool_name": T + short, "tool_input": ti, "session_id": "t", "tool_use_id": tuid}
        if event == "post":
            payload["tool_response"] = resp if resp is not None else [{"type": "text", "text": '{"verdict":"allow"}'}]
        import subprocess
        return subprocess.run(["bash", os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts", "hooks",
                                                    "docs-guard.sh"), event],
                              input=json.dumps(payload, ensure_ascii=False).encode("utf-8"), capture_output=True,
                              cwd=self.e.proj, env=self.e.env({"CLAUDE_PROJECT_DIR": self.e.proj}), timeout=60)

    def register(self):
        r = self.call("post", "read", {"ref": {"object": "project", "id": DOC}}, project_read())
        self.assertIn("登録", r.stdout.decode("utf-8"))
        return docsguard.load(self.e.proj)

    def upd(self, body, ops, suggest=None):
        p = {"ops": ops}
        if suggest is not None:
            p["suggest"] = suggest
        return {"ref": {"object": "node", "id": body}, "engine": "prose", "container": C, "payload": p}

    def d(self, r):
        x = decision(r)
        return "allow" if x in ("-", "ctx") else x


INS = [{"op": "insert", "target": {"kind": "root"}, "side": "end", "source": {"markdown": "新しい段落。"}}]


class Registration(DocsBase):
    def test_registers_once_from_the_server_answer(self):
        reg = self.register()
        self.assertEqual(reg["doc"], DOC)
        self.assertEqual(reg["tabs"]["thinking"]["body"], "b-thk")
        # a second document with the same tab names does not replace it
        self.call("post", "read", {"ref": {"object": "project", "id": "other"}}, project_read(slug="other"))
        self.assertEqual(docsguard.load(self.e.proj)["doc"], DOC)

    def test_other_tab_sets_do_not_register(self):
        self.call("post", "read", {"ref": {"object": "project", "id": DOC}}, project_read(TABS[:3]))
        self.assertIsNone(docsguard.load(self.e.proj))

    def test_the_ai_cannot_write_the_registration(self):
        self.assertEqual(decision(self.e.pre("Write", {"file_path": self.e.path(".ryukoku", "docs.json"), "content": "{}"})), "deny")


class PreGuard(DocsBase):
    def setUp(self):
        super().setUp()
        self.register()

    def test_ai_never_accepts_or_rejects(self):
        for v in ("accept", "reject"):
            r = self.call("pre", "update", self.upd("b-man", [{"op": "decide", "suggestId": "sg_1", "verdict": v, "asOf": "x"}]))
            self.assertEqual(self.d(r), "deny", v)
        r = self.call("pre", "update", self.upd("b-man", [{"op": "decide", "suggestId": "sg_1", "verdict": "withdraw", "asOf": "x"}]))
        self.assertEqual(self.d(r), "allow")

    def test_decide_inside_a_batch_is_denied(self):
        ti = {"container": C, "batch": [{"verb": "update", "ref": {"object": "node", "id": "b-man"}, "engine": "prose",
                                          "payload": {"ops": [{"op": "decide", "suggestId": "sg_1", "verdict": "accept", "asOf": "x"}]}}]}
        self.assertEqual(self.d(self.call("pre", "batch", ti)), "deny")

    def test_thinking_tab_is_closed(self):
        self.assertEqual(self.d(self.call("pre", "update", self.upd("b-thk", INS, suggest=True))), "deny")
        self.assertEqual(self.d(self.call("pre", "update", self.upd("b-thk", INS))), "deny")

    def test_claims_and_settings_take_suggestions_only(self):
        for body in ("b-clm", "b-set"):
            self.assertEqual(self.d(self.call("pre", "update", self.upd(body, INS))), "deny", body)
            self.assertEqual(self.d(self.call("pre", "update", self.upd(body, INS, suggest=True))), "allow", body)

    def test_manuscript_follows_the_course_policy(self):
        # unknown (the default) -> suggestions only
        self.assertEqual(self.d(self.call("pre", "update", self.upd("b-man", INS))), "deny")
        self.assertEqual(self.d(self.call("pre", "update", self.upd("b-man", INS, suggest=True))), "allow")
        self.e.set_policy("allowed")
        self.assertEqual(self.d(self.call("pre", "update", self.upd("b-man", INS))), "allow")
        self.e.set_policy("prohibited")
        self.assertEqual(self.d(self.call("pre", "update", self.upd("b-man", INS, suggest=True))), "deny")
        self.e.set_policy("limited")
        self.assertEqual(self.d(self.call("pre", "update", self.upd("b-man", INS))), "deny")

    def test_untrusted_settings_stop_manuscript_writes(self):
        self.e.set_policy("allowed")
        with open(self.e.path(".ryukoku", "config.yml"), "a", encoding="utf-8") as f:
            f.write("ai_policy: allowed\n")
        self.assertEqual(self.d(self.call("pre", "update", self.upd("b-man", INS))), "deny")

    def test_comments(self):
        def com(body, parent="b-man"):
            return {"container": C, "batch": [{"verb": "create", "object": "utterance",
                                               "payload": {"value": {"parent": {"object": "node", "id": parent}, "body": body}}}]}
        self.assertEqual(self.d(self.call("pre", "batch", com("この段落の根拠は台帳の S002 だけで足りるか。"))), "allow")
        self.assertEqual(self.d(self.call("pre", "batch", com("C001 を確認", "b-clm"))), "deny")
        self.assertEqual(self.d(self.call("pre", "batch", com("S001 VERIFIED p.12", "b-src"))), "deny")
        self.assertEqual(self.d(self.call("pre", "batch", com("提出を確認", "b-dis"))), "deny")
        delete = {"container": C, "batch": [{"verb": "delete", "object": "utterance", "ref": {"object": "utterance", "id": "u1"}}]}
        self.assertEqual(self.d(self.call("pre", "batch", delete)), "deny")
        resolve = {"container": C, "batch": [{"verb": "create", "object": "utterance",
                                              "payload": {"value": {"parent": {"object": "utterance", "id": "u1"}, "kind": "resolve"}}}]}
        self.assertEqual(self.d(self.call("pre", "batch", resolve)), "deny")

    def test_tabs_and_rewind_and_unknown_ops(self):
        patch = {"ref": {"object": "project", "id": DOC}, "payload": {"kind": "patch", "patch": [{"op": "set", "path": ["tabs", "f-thk", "name"], "value": "x"}]}}
        self.assertEqual(self.d(self.call("pre", "update", patch)), "deny")
        tab = {"container": C, "batch": [{"verb": "create", "object": "file", "payload": {"value": {"birthName": "x.ldoc"}}}]}
        self.assertEqual(self.d(self.call("pre", "batch", tab)), "deny")
        self.e.set_policy("allowed")
        self.assertEqual(self.d(self.call("pre", "update", self.upd("b-man", [{"op": "restore", "rev": 3}]))), "deny")
        self.assertEqual(self.d(self.call("pre", "update", self.upd("unknown-body", INS))), "deny")
        self.assertEqual(self.d(self.call("pre", "batch", {"container": C, "batch": [{"verb": "frobnicate", "object": "node"}]})), "deny")

    def test_other_documents_and_reads_pass(self):
        other = {"ref": {"object": "node", "id": "zzz"}, "engine": "prose", "container": {"kind": "project", "id": "another"},
                 "payload": {"ops": INS}}
        self.assertEqual(self.d(self.call("pre", "update", other)), "allow")
        for short in ("read", "query", "export", "guide"):
            self.assertEqual(self.d(self.call("pre", short, {"ref": {"object": "node", "id": "b-thk"}, "container": C})), "allow", short)

    def test_browser_tools_may_not_open_claude_ai(self):
        import subprocess
        payload = {"hook_event_name": "PreToolUse", "cwd": self.e.proj, "tool_name": "mcp__claude-in-chrome__navigate",
                   "tool_input": {"url": "https://claude.ai/artifact/JKLyax"}, "session_id": "t", "tool_use_id": "b1"}
        script = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts", "hooks", "docs-guard.sh")
        r = subprocess.run(["bash", script, "pre"], input=json.dumps(payload).encode(), capture_output=True, cwd=self.e.proj,
                           env=self.e.env(), timeout=60)
        self.assertEqual(decision(r), "deny")
        payload["tool_input"] = {"url": "https://ci.nii.ac.jp/"}
        r = subprocess.run(["bash", script, "pre"], input=json.dumps(payload).encode(), capture_output=True, cwd=self.e.proj,
                           env=self.e.env(), timeout=60)
        self.assertEqual(self.d(r), "allow")

    def test_the_general_guard_does_not_block_docs_calls(self):
        self.e.set_policy("allowed")
        ti = self.upd("b-man", INS)
        ti["payload"]["ops"][0]["source"]["markdown"] = "https://claude.ai/artifact/X と data/raw/a.csv を見る。"
        self.assertEqual(self.d(self.e.pre(T + "update", ti)), "allow", reason(self.e.pre(T + "update", ti)))


class Decisions(DocsBase):
    def setUp(self):
        super().setUp()
        self.register()

    def query(self, under, rows):
        return self.call("post", "query", {"object": "utterance", "container": C, "payload": {"under": {"object": "node", "id": under}}},
                         [{"type": "text", "text": json.dumps({"verdict": "allow", "rows": rows})}])

    def test_only_the_students_page_comments_count(self):
        self.query("b-clm", [row("a1", "C001 を確認", "mcp"), row("a2", "C002 を確認", "frame", seq=2)])
        d = docsguard.decisions(self.e.proj)
        self.assertNotIn(("claim", "C001"), d)
        self.assertEqual(d[("claim", "C002")]["comment"], "a2")
        # the same listing again records nothing new
        self.query("b-clm", [row("a2", "C002 を確認", "frame", seq=2)])
        with open(self.e.path(".ryukoku", "decisions.jsonl"), encoding="utf-8") as f:
            self.assertEqual(len(f.read().splitlines()), 1)

    def test_a_decision_counts_only_on_its_tab(self):
        self.query("b-man", [row("m1", "C003 を確認", "frame", parent="b-man")])
        self.assertNotIn(("claim", "C003"), docsguard.decisions(self.e.proj))

    def test_replies_inherit_the_tab_of_their_thread(self):
        r = row("r1", "C004 を確認", "frame")
        r["payload"]["value"]["parent"] = {"object": "utterance", "id": "a9"}
        self.query("b-clm", [row("a9", "この主張の範囲は?", "mcp"), r])
        self.assertIn(("claim", "C004"), docsguard.decisions(self.e.proj))

    def test_verified_needs_a_page(self):
        r = self.query("b-src", [row("s1", "S001 VERIFIED", "frame", parent="b-src"),
                                 row("s2", "S002 原典で確認 p.12-13", "frame", parent="b-src", seq=2)])
        d = docsguard.decisions(self.e.proj)
        self.assertEqual(d[("verified_incomplete", "S001")]["why"], "頁が無い / no page")
        self.assertNotIn(("verified", "S001"), d)
        self.assertEqual(d[("verified", "S002")]["locator"], "p.12-13")
        self.assertIn("頁が無い", r.stdout.decode("utf-8"))

    def test_policy_comment_sets_the_course_policy(self):
        self.query("b-set", [row("p1", "科目の条件: 許可\n根拠: シラバス第3回「生成AIの利用を認める」", "frame", parent="b-set")])
        self.assertEqual(common.course_policy(self.e.proj), "allowed")
        self.assertIn("シラバス", self.e.read(".ryukoku", "config.yml"))
        # an AI comment with the same words changes nothing
        self.query("b-set", [row("p2", "科目の条件: 禁止", "mcp", parent="b-set", seq=2)])
        self.assertEqual(common.course_policy(self.e.proj), "allowed")

    def test_signoff(self):
        self.query("b-dis", [row("x1", "提出を確認", "frame", parent="b-dis")])
        self.assertIn(("signoff", ""), docsguard.decisions(self.e.proj))

    def test_the_hook_writes_are_not_detections(self):
        """The general hooks open a detection window around every tool call; the Docs hook's own writes to
        .ryukoku/ inside that window must not be reported as a change of a protected file."""
        ti = {"object": "utterance", "container": C, "payload": {"under": {"object": "node", "id": "b-set"}}}
        self.e.pre(T + "query", ti, tuid="q1")
        self.call("post", "query", ti, [{"type": "text", "text": json.dumps({"verdict": "allow", "rows": [
            row("p1", "科目の条件: 限定", "frame", parent="b-set")]})}], tuid="q1")
        self.e.post(T + "query", ti, tuid="q1")
        self.assertEqual(common.config_problems(self.e.proj), [])
        self.assertEqual(common.course_policy(self.e.proj), "limited")


class Provenance(DocsBase):
    def test_manuscript_writes_are_recorded(self):
        self.register()
        self.e.set_policy("allowed")
        ti = self.upd("b-man", [{"op": "insert", "target": {"kind": "root"}, "side": "end",
                                 "source": {"markdown": "第一段落。\n\n第二段落。"}}])
        self.call("post", "update", ti, [{"type": "text", "text": json.dumps({"verdict": "allow", "rev": 9, "session": "meq17q999ek"})}])
        ti2 = self.upd("b-man", [{"op": "replace", "target": {"kind": "find", "text": "第一"},
                                  "with": {"from": {"kind": "inline", "content": "最初の"}, "as": "text"}}], suggest=True)
        self.call("post", "update", ti2, [{"type": "text", "text": json.dumps({"verdict": "allow", "rev": 11, "suggestId": "sg_9"})}])
        with open(self.e.path(".ryukoku", "docs-provenance.jsonl"), encoding="utf-8") as f:
            recs = [json.loads(x) for x in f]
        self.assertEqual(len(recs), 2)
        self.assertEqual(recs[0]["session"], "meq17q999ek")
        self.assertEqual(recs[0]["paragraphs"], docsguard.paragraph_hashes("第一段落。\n\n第二段落。"))
        self.assertTrue(recs[1]["suggest"])
        self.assertEqual(recs[1]["suggestId"], "sg_9")

    def test_other_tabs_are_not_manuscript_provenance(self):
        self.register()
        self.call("post", "update", self.upd("b-ver", INS), [{"type": "text", "text": '{"verdict":"allow","rev":2}'}])
        self.assertFalse(os.path.exists(self.e.path(".ryukoku", "docs-provenance.jsonl")))


if __name__ == "__main__":
    unittest.main()
