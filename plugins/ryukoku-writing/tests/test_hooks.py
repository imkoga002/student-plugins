"""The hooks: the pre-tool guard (writes to the manuscript by the course AI policy, ledgers and protected files, human-only commands,
pushes to main), where the session is opened, silence outside a project, the prompt guard (ghostwriting and
question-delegation requests, personal data), the course AI policy and the search records. Hooks are fed Claude
Code's hook JSON on stdin; an "AI tool call" is PreToolUse -> run if allowed -> PostToolUse (helpers.Env.ai_bash). All values are fictitious."""
import os
import re
import subprocess
import time
import unittest

from helpers import Env, decision, reason

MS = "manuscript/main.md"
LEDGER = "sources/claims.csv"


class PreToolUse(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.E = Env()
        cls.P = cls.E.proj
        os.makedirs(cls.E.path("data", "raw"), exist_ok=True)
        open(cls.E.path("data", "raw", "a.csv"), "w").write("x\n")

    @classmethod
    def tearDownClass(cls):
        cls.E.cleanup()

    def d(self, tool, ti, cwd=None, project_dir=None):
        return decision(self.E.pre(tool, ti, cwd=cwd, project_dir=project_dir))

    # ---- direct writes to the ledgers, the manuscript and protected files; pushes to main ----
    def test_direct_writes_and_pushes_to_main(self):
        P = self.P
        cases = [
            ("Edit", {"file_path": f"{P}/{LEDGER}", "old_string": "a", "new_string": "VERIFIED"}, "deny"),
            ("Write", {"file_path": f"{P}/{LEDGER}", "content": "id,claim,status\nc1,foo,VERIFIED\n"}, "deny"),
            ("Bash", {"command": f"sed -i s/CANDIDATE/VERIFIED/ {LEDGER}"}, "deny"),
            ("Bash", {"command": f"python3 -c \"open('{LEDGER}','a').write('c9,x,VERIFIED\\n')\""}, "deny"),
            ("Bash", {"command": f"sed -i s/CANDIDATE/VERIFIED/ {LEDGER} && cat {LEDGER}"}, "deny"),
            ("Bash", {"command": f'V=VERI; sed -i "s/CANDIDATE/${{V}}FIED/" {LEDGER}'}, "deny"),
            ("Write", {"file_path": f"{P}/{MS}", "content": "# 序論\n本稿では..."}, "ask"),  # policy unknown: asks
            ("Bash", {"command": f"cat > {MS} <<EOF\n本稿では\nEOF"}, "deny"),
            ("Bash", {"command": "git push --force origin main"}, "deny"),
            ("Bash", {"command": "git push origin main"}, "deny"),
            ("Bash", {"command": "git push origin sec-2"}, "ask"),
            ("Write", {"file_path": f"{P}/review/annotations.json", "content": '{"items":[]}'}, "deny"),
            ("Bash", {"command": "curl -s -X POST http://127.0.0.1:8765/api/sign"}, "deny"),
            ("Write", {"file_path": f"{P}/data/raw/a.csv", "content": "z"}, "deny"),
            ("Edit", {"file_path": f"{P}/.ryukoku/style.yml", "old_string": "a", "new_string": "approved"}, "deny"),
            ("Bash", {"command": f"echo 本稿では | tee {MS}"}, "deny"),
            ("Bash", {"command": f"python3 -c \"open('{MS}','w').write('x')\""}, "deny"),
            ("Bash", {"command": f"cp /tmp/draft.md {MS}"}, "deny"),
            ("Bash", {"command": "git push -f origin HEAD:main"}, "deny"),
            ("Bash", {"command": "git push origin +main"}, "deny"),
            ("Write", {"file_path": f"{P}/.claude/settings.json", "content": '{"enabledPlugins":{}}'}, "deny"),
            ("Write", {"file_path": f"{P}/.ryukoku/ai-use-log.jsonl", "content": ""}, "deny"),
            ("Bash", {"command": "rm .ryukoku/ai-use-log.jsonl"}, "deny"),
            ("Write", {"file_path": MS, "content": "x"}, "ask"),
            ("Write", {"file_path": f"{P}/.ryukoku/signoffs.jsonl", "content": "{}"}, "deny"),
            ("Edit", {"file_path": f"{P}/.ryukoku/config.yml", "old_string": "ai_policy: unknown", "new_string": "ai_policy: allowed"}, "deny"),
        ]
        for tool, ti, want in cases:
            with self.subTest(tool=tool, ti=str(ti)[:80]):
                self.assertEqual(self.d(tool, ti), want)

    def test_malformed_input_is_silent(self):
        for raw in ['{"tool_name":"Write","tool_input":{"file_path":', ""]:
            r = self.E.hook("pre-guard.sh", None, raw=raw)
            self.assertEqual((decision(r), r.returncode), ("-", 0))

    def ms(self, tool, ti, cwd=None, project_dir=None):
        """A manuscript write under the default policy (unknown): it asks, with the manuscript reason."""
        r = self.E.pre(tool, ti, cwd=cwd, project_dir=project_dir)
        self.assertEqual(decision(r), "ask", str(ti))
        self.assertIn("ai_policy: unknown", reason(r))

    def test_paths_windows_case_symlink_normalisation(self):
        w = "C:\\Users\\student\\thesis"
        self.ms("Write", {"file_path": w + "\\manuscript\\main.md", "content": "x"}, cwd=w, project_dir=self.P)
        self.ms("Write", {"file_path": "C:/Users/student/thesis/manuscript/main.md", "content": "x"}, cwd=w, project_dir=self.P)
        self.ms("Write", {"file_path": f"{self.P}/Manuscript/main.md", "content": "x"})
        self.ms("NotebookEdit", {"notebook_path": f"{self.P}/{MS}", "new_source": "x"})
        self.assertEqual(self.d("Bash", {"command": "copy draft.md Manuscript\\main.md & cp x MANUSCRIPT\\main.md"}), "deny")

    def test_dot_segments_in_the_path(self):
        self.ms("Edit", {"file_path": f"{self.P}/manuscript//./main.md", "old_string": "a", "new_string": "b"})

    def test_symlink_target_is_resolved(self):
        link = self.E.path("mlink")
        if not os.path.islink(link):
            os.symlink("manuscript", link)
        self.ms("Write", {"file_path": f"{link}/main.md", "content": "x"})

    def test_write_operations_on_the_manuscript(self):
        cmds = [f"dd if=/tmp/x of={MS}", f"install -m 644 /tmp/x {MS}", f"rsync /tmp/x {MS}", f"ln -sf /tmp/x {MS}",
                f"perl -pi -e 's/a/b/' {MS}", f"ruby -e 'File.write(\"{MS}\",1)'", f"node -e \"require('fs').writeFileSync('{MS}','x')\"",
                f"truncate -s 0 {MS}", f"rm {MS}", f"mv /tmp/x {MS}", f"sed --in-place s/a/b/ {MS}", f"python3 - <<EOF\nopen('{MS}','w')\nEOF",
                f"echo x >> {MS}", f"echo x >{MS}", "cd manuscript && echo x > main.md", f"git checkout -- {MS}", f"bash -c 'echo x > {MS}'",
                f"pandoc a.md -o {MS}", f"patch -p1 < scratch/p.diff {MS}"]
        for c in cmds:
            with self.subTest(c=c):
                self.assertEqual(self.d("Bash", {"command": c}), "deny")

    def test_reads_and_machine_commands_pass(self):
        for c in [f"cat {MS}", f"grep -n 本稿 {MS}", f"wc -m {MS}", "python3 tools/rk/rk.py propose start manuscript/main.md",
                  "python3 tools/rk/rk.py refcheck check --id S001", "python3 tools/rk/rk.py check", "./rk check",
                  f"python3 tools/rk/rk.py lint {MS} > review/lint.txt", "python3 tools/rk/rk.py annot list --open"]:
            with self.subTest(c=c):
                self.assertEqual(self.d("Bash", {"command": c}), "-")
        self.assertEqual(self.d("Write", {"file_path": f"{self.P}/proposals/.work/W1/main.md", "content": "x"}), "-")
        self.assertEqual(self.d("Write", {"file_path": f"{self.P}/research/plan.md", "content": "x"}), "-")
        self.assertEqual(self.d("Read", {"file_path": f"{self.P}/{MS}"}), "-")

    def test_human_only_commands_denied(self):
        for c in ["./rk apply", "./rk confirm", "./rk confirm C001", "./rk verify C001", "python3 tools/rk/rk.py style", "./rk resolve", "./rk signoff",
                  "./rk changes", "./rk optout", "./rk setup", "./rk sign claim C001 --decision VERIFIED", "rk.cmd apply",
                  "tools\\rk\\rk.py apply", "./rk trust", "./rk update-tools", "./rk notebook", "python3 tools/rk/rk.py notebook --project ."]:
            with self.subTest(c=c):
                self.assertEqual(self.d("Bash", {"command": c}), "deny")

    def test_notebook_only_from_plugin_root(self):
        from helpers import PLUGIN
        ok = 'python3 "%s/scripts/rk/rk.py" --project "%s" notebook' % (PLUGIN, self.P)
        r = self.E.pre("Bash", {"command": ok, "run_in_background": True})
        self.assertEqual(decision(r), "-")
        self.assertEqual(self.d("Bash", {"command": "python3 /tmp/elsewhere/scripts/rk/rk.py notebook --project ."}), "deny")

    def test_tty_emulation_detached_and_msguard(self):
        for c in ["script -qc './rk apply' /dev/null", "python3 -c 'import pty; pty.spawn([\"./rk\",\"apply\"])'",
                  "expect run.exp", "unbuffer ./x", "nohup python3 x.py", "setsid python3 x.py",
                  "python3 tools/rk/hookcore.py pre .", "python3 -c 'import rklib.msguard'"]:
            with self.subTest(c=c):
                self.assertEqual(self.d("Bash", {"command": c}), "deny")
        self.assertEqual(self.d("Bash", {"command": "sleep 5 &"}), "ask")
        self.assertEqual(decision(self.E.pre("Bash", {"command": "python3 x.py", "run_in_background": True})), "ask")

    def test_protected_files_all_tools(self):
        for fp in [".ryukoku/signers.json", ".ryukoku/config.yml", "disclosure/ai-involvement.jsonl", "thinking/log.md",
                   "tools/rk/rk.py", "tools/rk/rklib/check.py", "rk", "rk.cmd", "rk.ps1", "research/questions.md",
                   "research/search-log.jsonl"]:
            with self.subTest(fp=fp):
                self.assertEqual(self.d("Write", {"file_path": f"{self.P}/{fp}", "content": "x"}), "deny")
        for c in ["sed -i s/a/b/ tools/rk/rklib/check.py", "echo x >> research/questions.md", "cp x thinking/log.md",
                  "sed -i s/a/b/ .ryukoku/signers.json", "echo '{}' >> .ryukoku/signoffs.jsonl", "cp /tmp/x rk",
                  "echo x > ~/.ryukoku-writing/trust/p1.json"]:
            with self.subTest(c=c):
                self.assertEqual(self.d("Bash", {"command": c}), "deny")

    def test_passphrase_code_is_not_writable(self):
        from helpers import PLUGIN
        self.assertEqual(self.d("Write", {"file_path": f"{PLUGIN}/scripts/rk/notebook/server.py", "content": "x"}), "deny")
        self.assertEqual(self.d("Bash", {"command": f"sed -i s/a/b/ {PLUGIN}/scripts/rk/rklib/sign.py"}), "deny")
        self.assertEqual(self.d("Bash", {"command": "sed -i s/a/b/ ~/.claude/plugins/*/ryukoku*/scripts/rk/notebook/server.py"}), "deny")
        self.assertEqual(self.d("Bash", {"command": "perl -pi -e s/a/b/ */rklib/human.py"}), "deny")

    def test_reason_explains_and_offers_alternative(self):
        r = reason(self.E.pre("Write", {"file_path": f"{self.P}/{MS}", "content": "x"}))
        self.assertIn("Ⅲ-3", r)
        self.assertIn("./rk setup", r)
        r = reason(self.E.pre("Bash", {"command": f"echo x >> {MS}"}))
        self.assertIn("Write・Edit", r)
        r = reason(self.E.pre("Write", {"file_path": f"{self.P}/research/questions.md", "content": "Q1: x"}))
        self.assertIn("rq-dialogue", r)


class Locations(unittest.TestCase):
    """A session opened in the parent folder of the project, and one opened in a child folder."""

    def setUp(self):
        self.E = Env()

    def tearDown(self):
        self.E.cleanup()

    def test_parent_folder_session(self):
        parent = self.E.base
        r = self.E.pre("Write", {"file_path": f"{self.E.proj}/manuscript/main.md", "content": "x"}, cwd=parent, project_dir=parent)
        self.assertEqual(decision(r), "ask")  # found as this project's manuscript: the course policy (unknown) asks
        self.assertIn("開き直す", reason(r))
        r = self.E.pre("Bash", {"command": "echo x >> thesis/manuscript/main.md"}, cwd=parent, project_dir=parent)
        self.assertEqual(decision(r), "deny")
        r = self.E.hook("session-start.sh", {"cwd": parent, "hook_event_name": "SessionStart"}, project_dir=parent)
        self.assertIn("開き直す", reason(r))

    def test_child_folder_session(self):
        child = self.E.path("manuscript")
        r = self.E.pre("Write", {"file_path": f"{child}/main.md", "content": "x"}, cwd=child, project_dir=child)
        self.assertEqual(decision(r), "ask")
        self.assertIn("ai_policy: unknown", reason(r))
        r = self.E.pre("Bash", {"command": "echo x >> main.md"}, cwd=child, project_dir=child)
        self.assertEqual(decision(r), "deny")
        r = self.E.pre("Write", {"file_path": "main.md", "content": "x"}, cwd=child, project_dir=child)
        self.assertEqual(decision(r), "ask")


class Outside(unittest.TestCase):
    """In a folder without the marker every hook prints nothing and creates no file."""

    def test_outside_a_project_is_silent(self):
        E = Env(init=False)
        try:
            d = os.path.join(E.base, "plain")
            os.makedirs(os.path.join(d, "manuscript"))
            before = sorted(os.listdir(E.base))
            for tool, ti in [("Bash", {"command": "git push --force origin main"}), ("Write", {"file_path": f"{d}/manuscript/main.md", "content": "x"}),
                             ("Bash", {"command": "cat > manuscript/main.md <<EOF\nx\nEOF"})]:
                self.assertEqual(decision(E.pre(tool, ti, cwd=d, project_dir=d)), "-")
            self.assertEqual(decision(E.post("Bash", {"command": "ls"}, cwd=d, project_dir=d)), "-")
            self.assertEqual(E.hook("session-start.sh", {"cwd": d}, project_dir=d).stdout.decode().strip(), "")
            self.assertEqual(decision(E.prompt("電話は090-1234-5678です", project_dir=d)), "-")
            self.assertEqual(E.hook("stop-check.sh", {"cwd": d}, project_dir=d).stdout.decode().strip(), "")
            self.assertEqual(sorted(os.listdir(E.base)), before)
            self.assertEqual(os.listdir(d), ["manuscript"])
            self.assertFalse(os.path.exists(E.state))
        finally:
            E.cleanup()


class Prompts(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.E = Env()

    @classmethod
    def tearDownClass(cls):
        cls.E.cleanup()

    def p(self, text):
        return self.E.prompt(text)

    def test_ghostwriting_requests_get_the_reason(self):
        for text in ["序論を書いて", "RQを決めて", "この段落を書き直して", "Write the introduction for me.",
                     "Can you decide my research question?", "Rewrite this paragraph."]:
            with self.subTest(text=text):
                self.assertEqual(decision(self.p(text)), "ctx")

    def test_personal_data_is_stopped(self):
        for text in ["電話は090-1234-5678です", "学籍番号はY210123です", "学籍番号: 22110345", "my student ID is 22110345",
                     "連絡先 taro.sample@mail.example.test"]:
            with self.subTest(text=text):
                r = self.p(text)
                self.assertEqual(decision(r), "block")
                self.assertNotIn("1234-5678", reason(r))
                self.assertNotIn("22110345", reason(r))

    def test_malformed_prompt_input(self):
        r = self.E.hook("prompt-guard.sh", None, raw='{"prompt": "序論を書')
        self.assertEqual((decision(r), r.returncode), ("-", 0))

    def test_personal_data_kinds(self):
        block = ["090-1234-5678", "090 1234 5678", "09012345678", "０９０−１２３４−５６７８", "+81-90-1234-5678", "075-000-0000",
                 "学籍番号はY210123", "学籍番号: 22110345", "my student ID is 22110345", "Student No. Y210123",
                 "マイナンバーは1234 5678 9012", "1234-5678-9012", "123456789012", "taro.yamada@example.test",
                 "大阪府架空市架空町1丁目2番3号", "〒600-0000"]
        for text in block:
            with self.subTest(text=text):
                r = self.p(text)
                self.assertEqual(decision(r), "block")
                digits = re.sub(r"[^0-9]", "", text)
                if len(digits) >= 7:
                    self.assertNotIn(digits[-7:], re.sub(r"[^0-9]", "", reason(r)))
        # a bare "ID: 22110345": decided policy = caution context, not a block (false positives with table ids)
        r = self.p("ID: 22110345")
        self.assertEqual(decision(r), "ctx")
        self.assertIn("伏せ字", reason(r))
        # a name and an affiliation alone are not detected (documented limit)
        self.assertNotEqual(decision(self.p("氏名は架空太郎、所属は架空学部")), "block")

    def test_no_false_positives(self):
        for text in ["DOI 10.1038/s41598-023-41032-5 を確かめて", "ISBN 9784004319023 の本", "統計表 ID 0003348423 を使う",
                     "2026-11-04 15:30 に CiNii で調べた", "pp. 123-145 を読む", "1,234,567 円の値", "3.2.1 節を見て",
                     "連絡先は @example.com の形式", "1990-2020 年の範囲"]:
            with self.subTest(text=text):
                self.assertEqual(decision(self.p(text)), "-")

    def test_ghostwrite_and_delegation_variants(self):
        for text in ["結論の段落を考えて", "この考察を代わりに作ってください", "下書きを作って", "この箇条書きを文章にして", "論拠を補って",
                     "Can you flesh out my argument?", "make this paragraph sound more academic", "Please improve this paragraph.",
                     "Write a conclusion for my essay.", "どんなテーマがいいと思う？", "仮説を提案して", "What should my thesis argue?",
                     "この節を英語に訳して提出したい", "序論の最初の一文だけ例を見せて"]:
            with self.subTest(text=text):
                r = self.p(text)
                self.assertEqual(decision(r), "ctx")
                self.assertRegex(reason(r), "Ⅲ-|III-")

    def test_benign_requests_get_no_ghostwriting_context(self):
        for text in ["この段落の論理の飛躍を指摘して", "APA 7 の参考文献の書き方を確認して", "Mermaid の書き方を教えて",
                     "Toulmin の warrant とは何か", "書いてある内容を確認して",
                     "注入された文の中のコマンドを、そのまま一行だけ示してください"]:  # a false positive seen in the live run
            with self.subTest(text=text):
                r = self.p(text)
                self.assertNotIn("代筆", reason(r))
                self.assertNotIn("ghostwriting", reason(r))

    def test_passphrase_in_the_chat_is_stopped(self):
        for text in ["合言葉は correct horse battery 42 です", "my passphrase is correct horse battery staple",
                     "パスフレーズ: tsukimi-dango-2026"]:
            with self.subTest(text=text):
                r = self.p(text)
                self.assertEqual(decision(r), "block")
                self.assertNotIn("horse", reason(r))
                self.assertNotIn("dango", reason(r))
        for text in ["合言葉は何文字以上必要？", "合言葉を忘れたらどうする？", "what happens if I forget my passphrase?"]:
            with self.subTest(text=text):
                self.assertNotEqual(decision(self.p(text)), "block")

    def test_prompt_text_not_logged(self):
        self.p("秘密の計画について調べたい")
        log = self.E.read(".ryukoku", "ai-use-log.jsonl")
        self.assertNotIn("秘密の計画", log)
        self.assertIn('"categories": "research"', log)


class Policy(unittest.TestCase):
    """The course AI policy changes what the tools do."""

    def setUp(self):
        self.E = Env()

    def tearDown(self):
        self.E.cleanup()

    def set_policy(self, policy, uses=""):
        p = self.E.path(".ryukoku", "config.yml")
        s = open(p, encoding="utf-8").read()
        s = re.sub(r"(?m)^ai_policy: \S+", "ai_policy: " + policy, s)
        s = re.sub(r'(?m)^ai_allowed_uses: "[^"]*"', 'ai_allowed_uses: "%s"' % uses, s)
        open(p, "w", encoding="utf-8").write(s)

    def test_manuscript_writes_follow_the_course_policy(self):
        P = self.E.proj
        w = ("Write", {"file_path": f"{P}/{MS}", "content": "x"})
        e = ("Edit", {"file_path": f"{P}/{MS}", "old_string": "a", "new_string": "b"})
        sh = ("Bash", {"command": f"echo x >> {MS}"})
        for pol, want in (("allowed", "-"), ("limited", "ask"), ("unknown", "ask"), ("prohibited", "deny")):
            self.set_policy(pol, "research")
            with self.subTest(policy=pol):
                self.assertEqual(decision(self.E.pre(*w)), want)
                self.assertEqual(decision(self.E.pre(*e)), want)
                self.assertEqual(decision(self.E.pre(*sh)), "deny")  # never from the shell
        self.set_policy("limited", "research")
        r = reason(self.E.pre(*w))
        self.assertIn("limited", r)
        self.assertIn("シラバス", r)

    def test_allowed_write_is_recorded_as_provenance(self):
        self.set_policy("allowed")
        self.E.post("Bash", {"command": "true"}, tuid="i0")
        p = self.E.path(MS)
        d, ctx = self.E.ai_edit(p, self.E.read(MS) + "\n要因 A は現象 X の一因となりうる。\n", tuid="w1")
        self.assertEqual(d, "-")
        self.assertIn("由来の記録", ctx)
        log = self.E.read(".ryukoku", "provenance.jsonl")
        self.assertIn('"kind": "ai_wrote"', log)
        self.assertIn('"policy": "allowed"', log)
        self.assertNotIn('"type": "detection"', self.E.read(".ryukoku", "ai-use-log.jsonl"))
        r = self.E.rk("check")
        self.assertEqual(r.returncode, 0, r.stdout)
        self.assertIn("AI が書いた 1", r.stdout)

    def test_prohibited_blocks_writing_but_not_research_or_verification(self):
        self.set_policy("prohibited")
        P = self.E.proj
        deny = [("Write", {"file_path": f"{P}/{MS}", "content": "x"}), ("Write", {"file_path": f"{P}/claims/C001.md", "content": "x"}),
                ("Bash", {"command": "python3 tools/rk/rk.py propose start manuscript/main.md"}),
                ("Bash", {"command": "python3 tools/rk/rk.py claims new --words x"}),
                ("Bash", {"command": "python3 tools/rk/rk.py provenance materials --file manuscript/main.md"}),
                ("Write", {"file_path": f"{P}/proposals/.work/W1/main.md", "content": "x"})]
        for tool, ti in deny:
            with self.subTest(tool=tool, ti=str(ti)[:60]):
                self.assertEqual(decision(self.E.pre(tool, ti)), "deny")
        allow = [("Read", {"file_path": f"{P}/{MS}"}), ("Grep", {"pattern": "x", "path": f"{P}/manuscript"}),
                 ("Edit", {"file_path": f"{P}/research/plan.md", "old_string": "a", "new_string": "b"}),
                 ("WebSearch", {"query": "現象 X"}), ("Task", {"subagent_type": "research-scout"}), ("Task", {"subagent_type": "claim-verifier"}),
                 ("Bash", {"command": f"cat {MS}"}), ("Bash", {"command": "python3 tools/rk/rk.py search crossref x --question-ref Q1"}),
                 ("Bash", {"command": "python3 tools/rk/rk.py verification scaffold manuscript/main.md"}),
                 ("Write", {"file_path": f"{P}/review/verification/x.md", "content": "x"}),
                 ("Bash", {"command": "python3 tools/rk/rk.py argmap review/a.json"}), ("Bash", {"command": "python3 tools/rk/rk.py check"})]
        for tool, ti in allow:
            with self.subTest(tool=tool, ti=str(ti)[:60]):
                self.assertEqual(decision(self.E.pre(tool, ti)), "-")

    def test_limited_asks_outside_the_allowed_uses(self):
        self.set_policy("limited", "research")
        for tool, ti in [("Bash", {"command": "python3 tools/rk/rk.py propose start manuscript/main.md"}),
                         ("Bash", {"command": "python3 tools/rk/rk.py refcheck check"}), ("Task", {"subagent_type": "argument-reviewer"}),
                         ("Task", {"subagent_type": "source-verifier"})]:
            with self.subTest(ti=str(ti)):
                self.assertEqual(decision(self.E.pre(tool, ti)), "ask")
        self.assertEqual(decision(self.E.pre("WebSearch", {"query": "x"})), "-")

    def test_unknown_policy_asks_for_the_instructor(self):
        r = self.E.hook("session-start.sh", {"cwd": self.E.proj})
        self.assertIn("担当教員", reason(r))
        out = self.E.rk("check").stdout
        self.assertIn("ai_policy: unknown", out)


class Research(unittest.TestCase):
    """The student's questions and thinking log are not written by the AI; web searches are recorded automatically."""

    def setUp(self):
        self.E = Env()

    def tearDown(self):
        self.E.cleanup()

    def test_questions_and_thinking_are_the_students(self):
        P = self.E.proj
        self.assertEqual(decision(self.E.pre("Write", {"file_path": f"{P}/research/questions.md", "content": "| Q1 | x | y | z |"})), "deny")
        self.assertEqual(decision(self.E.pre("Edit", {"file_path": f"{P}/thinking/log.md", "old_string": "a", "new_string": "b"})), "deny")

    def test_websearch_and_db_webfetch_are_logged(self):
        self.E.post("WebSearch", {"query": "現象 X 要因 A"})
        self.E.post("WebFetch", {"url": "https://api.crossref.org/works?query.bibliographic=%E7%8F%BE%E8%B1%A1+X&rows=5", "prompt": "list"})
        self.E.post("WebFetch", {"url": "https://example.test/page", "prompt": "x"})
        lines = [l for l in self.E.read("research", "search-log.jsonl").splitlines() if l.strip()]
        self.assertEqual(len(lines), 2)
        self.assertIn('"db": "WebSearch"', lines[0])
        self.assertIn('"auto": true', lines[0])
        self.assertIn("api.crossref.org", lines[1])
        self.assertIn("現象 X", lines[1])


class Hooks(unittest.TestCase):
    def test_session_start_language_and_notebook_path(self):
        E = Env(lang="en")
        try:
            r = E.hook("session-start.sh", {"cwd": E.proj, "model": "claude-test-model"})
            txt = reason(r)
            self.assertIn("Write all feedback", txt)
            self.assertIn("Working constitution, key points", txt)  # CONSTITUTION.md digest (decision 11)
            self.assertIn('--project "%s" notebook' % E.proj, txt)
            self.assertIn("scripts/rk/rk.py", txt)
            self.assertIn("ryukoku-writing", txt)
            self.assertIn('"model": "claude-test-model"', E.read(".ryukoku", "ai-use-log.jsonl"))
            with open(os.path.join(E.state, "plugin-root")) as f:
                from helpers import PLUGIN
                self.assertEqual(f.read().strip(), os.path.realpath(PLUGIN))
        finally:
            E.cleanup()

    def test_hook_timing(self):
        E = Env()
        try:
            t = time.time()
            for _ in range(3):
                E.pre("Bash", {"command": "ls"})
            self.assertLess((time.time() - t) / 3, 2.0)
        finally:
            E.cleanup()


if __name__ == "__main__":
    unittest.main()
