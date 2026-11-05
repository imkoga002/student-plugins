"""The shell's directory is never followed, record lines and light confirmations count only when written outside AI
tool calls or by the plugin's own paths, the ledger files are watched, VERIFIED covers the printed entry, data
exemptions for figures must check out, the figure rules hold on methods prose, tool inputs are read as JSON, a lock
timeout fails closed, citation keys are unique, pandoc's user data is not used, and addresses are caught. Each test
reproduces a way around a safeguard that an independent adversarial review found. Example text is neutral (library
use, survey response rates); the address is fictional."""
import csv
import fcntl
import glob
import json
import os
import shutil
import sys
import time
import unittest

from helpers import PASS, PLUGIN, Env, decision, reason

sys.path.insert(0, os.path.join(PLUGIN, "scripts", "rk"))
from rklib import common, execgate, ledger, msguard, sign, subjects, verification  # noqa: E402
from test_bibliography_and_shell import ledger_row  # noqa: E402

MS = "manuscript/main.md"
HAVE_PANDOC = shutil.which("pandoc") is not None


def ng(out):
    return [l for l in out.splitlines() if l.startswith("NG")]


class UseEnvState(object):
    """In-process calls (msguard, common) must read the same per-user state as the hooks of the Env."""

    def use(self, E):
        self._old = (os.environ.get("HOME"), os.environ.get("RK_STATE_HOME"))
        os.environ["HOME"], os.environ["RK_STATE_HOME"] = E.home, E.state

    def tearDown(self):
        if getattr(self, "_old", None):
            os.environ["HOME"], os.environ["RK_STATE_HOME"] = self._old


def slip(E, tuid, fn):
    """A change that gets past the hooks during an AI tool call (as a script the student allowed would)."""
    E.pre("Bash", {"command": "python3 job.py"}, tuid=tuid)
    fn()
    E.post("Bash", {"command": "python3 job.py"}, tuid=tuid)


class NoDirectoryTracking(unittest.TestCase):
    CMDS = ["cd thinking && false && cd ..; echo 追記 >> log.md",
            "cd sources && false && cd ..; echo '{}' > identity.json",
            "cd pandoc && false && cd ..; echo 'x: y' >> defaults-ja-docx.yaml",
            "cd .github && false && cd ..; echo x >> workflows/check.yml",
            "cd m*t && false && cd ..; echo 追記 >> main.md",
            "cd .r*u && false && cd ..; echo x >> signoffs.jsonl",
            "cd research && false && cd ..; echo Q9 >> questions.md",
            "cd sources && false && cd ..; printf x >> 'regis''ter.csv'",
            "cd review && false && cd ..; printf x >> 'annot''ations.json'",
            "cd .githooks && false && cd ..; printf x >> pre-commit",
            "cd sources\nfalse &&\ncd ..\nprintf x > identity.json",
            "cd sources\ntrue ||\ncd ..\nprintf x > identity.json",
            "false &&\ncd thinking\necho x >> log.md"]

    def test_any_cd_makes_relative_targets_unknown_and_protected_names_deny(self):
        E = Env()
        try:
            for pol in ("allowed", "prohibited"):
                E.set_policy(pol)
                for cmd in self.CMDS:
                    before = (E.read("manuscript", "main.md"), E.read("thinking", "log.md"))
                    d, _ctx = E.ai_bash(cmd)
                    self.assertEqual(d, "deny", (pol, cmd))
                    self.assertEqual(before, (E.read("manuscript", "main.md"), E.read("thinking", "log.md")))
                    self.assertFalse(os.path.exists(E.path("sources", "identity.json")), cmd)
            E.set_policy("prohibited")
            self.assertEqual(decision(E.pre("Bash", {"command": "cd disclosure && false && cd ..; printf x >> notes.md"})), "deny")
            E.set_policy("allowed")
            self.assertEqual(decision(E.pre("Bash", {"command": "cd research && echo x > notes.md"})), "ask")
            self.assertEqual(decision(E.pre("Bash", {"command": "echo x > research/notes.md"})), "-")
        finally:
            E.cleanup()

    def test_a_newline_after_and_or_pipe_continues_the_list(self):
        self.assertNotIn(("op", ";"), execgate.lex("false &&\ncd x")[:3])
        self.assertIn(("op", ";"), execgate.lex("a\nb"))

    def test_a_line_continuation_inside_double_quotes_is_dropped_like_bash(self):
        self.assertEqual(execgate.lex('echo x >> "manus\\\ncript/main.md"')[-1][1], "manuscript/main.md")
        self.assertEqual(execgate.lex("echo x >> 'a\\\nb'")[-1][1], "a\\\nb")   # literal inside single quotes
        E = Env()
        try:
            for pol in ("allowed", "prohibited"):
                E.set_policy(pol)
                for cmd in ('echo x >> "manus\\\ncript/main.md"',
                            'echo x >> "thin\\\nking/log.md"',
                            'printf x > "sources/iden\\\ntity.json"',
                            'echo x | tee -a "manus\\\ncript/main.md"',
                            "printf x > 'sources/a\tb.json'"):
                    before = E.read("manuscript", "main.md")
                    d, _ctx = E.ai_bash(cmd)
                    self.assertEqual(d, "deny", (pol, cmd))
                    self.assertEqual(before, E.read("manuscript", "main.md"))
                    self.assertFalse(os.path.exists(E.path("sources", "identity.json")), cmd)
        finally:
            E.cleanup()


class LedgerAndVerified(UseEnvState, unittest.TestCase):
    def test_ledger_files_changed_during_an_ai_call_are_detected_unless_the_plugin_wrote_them(self):
        E = Env()
        self.use(E)
        try:
            E.set_policy("allowed")
            E.post("Bash", {"command": "true"}, tuid="init")
            d, ctx = E.ai_bash("python3 tools/rk/rk.py ledger add-source --doi 10.1038/s41598-023-41032-5 --title 'Library use' "
                               "--authors 'Sato, Ken' --year 2021 --citekey sato2021", tuid="ok1")
            self.assertEqual(d, "-")
            self.assertEqual(msguard.open_detections(E.proj), [])
            for rel in ("sources/register.csv", "sources/identity.json", "sources/claims.csv", "review/annotations.json"):
                slip(E, "s-" + rel.replace("/", "_"), lambda rel=rel: open(E.path(rel), "a", encoding="utf-8").write("\nforged\n"))
            parts = " ".join(" ".join(x.content.get("parts") or []) for x in subjects.changes(E.proj))
            for rel in ("sources/register.csv", "sources/identity.json", "sources/claims.csv", "review/annotations.json"):
                self.assertIn(rel, parts)
            # an undecided detection: the settings are not trusted, manuscript writes are closed
            self.assertTrue(common.config_problems(E.proj))
            self.assertEqual(decision(E.pre("Write", {"file_path": E.path(MS), "content": "x"})), "deny")
        finally:
            E.cleanup()

    def test_verified_covers_the_printed_entry(self):
        E = Env()
        try:
            E.setup(policy="a")
            row = ledger_row(E)
            E.write(MS, "---\ntitle: t\n---\n\n図書館の利用について述べる [@tanaka2020]。\n")
            rc, out = E.tty(["verify"], ["v", "", PASS, PASS])
            self.assertEqual(rc, 0, out[-800:])
            self.assertFalse(any("VERIFIED" in l and "tanaka2020" in l for l in ng(E.rk("check", "--submit").stdout)))
            # a forged identity record (registry metadata) changes the printed entry: VERIFIED no longer covers it
            fake = {row["id"]: {"digest": ledger.source_subject(row), "checked_at": "t", "source": "crossref",
                                "meta": {"title": "A FABRICATED HANDBOOK", "author": [{"family": "Invented"}], "year": 1900}}}
            json.dump(fake, open(E.path("sources", "identity.json"), "w", encoding="utf-8"))
            out = ng(E.rk("check", "--submit").stdout)
            self.assertTrue(any("tanaka2020" in l and "VERIFIED" in l for l in out), out)
            if HAVE_PANDOC:
                r = E.rk("export", "latex")
                self.assertIn("VERIFIED", r.stdout + r.stderr)
        finally:
            E.cleanup()

    def test_a_citation_key_names_one_row(self):
        E = Env()
        try:
            ledger_row(E)
            r = E.rk("ledger", "add-source", "--citekey", "tanaka2020", "--title", "Survey response rates", "--ncid", "BA12345678")
            self.assertNotEqual(r.returncode, 0)
            r = E.rk("ledger", "add-source", "--id", "tanaka2020", "--title", "Survey response rates")
            self.assertNotEqual(r.returncode, 0)
            rows = ledger.read(E.path("sources", "register.csv"), ledger.REGISTER)
            rows.append(dict(rows[0], id="S099"))
            ledger.write(E.path("sources", "register.csv"), rows, ledger.REGISTER)
            self.assertTrue(any("tanaka2020" in l and "複数" in l for l in ng(E.rk("check").stdout)))
        finally:
            E.cleanup()


class LightConfirmations(UseEnvState, unittest.TestCase):
    def test_a_confirmation_that_appeared_during_an_ai_call_does_not_count(self):
        E = Env()
        self.use(E)
        try:
            E.setup(policy="a")
            mp = E.path(MS)
            cfg = E.path(".ryukoku", "config.yml")
            text = open(cfg, encoding="utf-8").read().replace('course_name: ""', 'course_name: "x"')
            slip(E, "c1", lambda: open(cfg, "w", encoding="utf-8").write(text))
            ids = msguard.open_detections(E.proj)
            self.assertTrue(ids)
            self.assertEqual(decision(E.pre("Write", {"file_path": mp, "content": "x"})), "deny")
            # forge the student's decision (a light confirmation has no secret) during another AI call
            recs = [json.dumps(sign.make_confirmation("change", s.sid, "mine", s.digest, method="tty"), ensure_ascii=False)
                    for s in subjects.changes(E.proj)]
            slip(E, "c2", lambda: open(E.path(".ryukoku", "signoffs.jsonl"), "a", encoding="utf-8").write("\n".join(recs) + "\n"))
            self.assertTrue(set(ids) <= set(msguard.open_detections(E.proj)))
            self.assertEqual(decision(E.pre("Write", {"file_path": mp, "content": "x"})), "deny")
            # the student decides at the terminal: then it counts
            for i in msguard.open_detections(E.proj):
                rc, out = E.tty(["sign", "change", i, "--decision", "mine"], ["y"])
                self.assertEqual(rc, 0, out[-800:])
            self.assertEqual(msguard.open_detections(E.proj), [])
            r = E.pre("Write", {"file_path": mp, "content": "x"})
            self.assertEqual(decision(r), "-", (reason(r), common.config_problems(E.proj)))
        finally:
            E.cleanup()


class FigureExemptions(unittest.TestCase):
    def test_only_checked_data_exempts_a_figure(self):
        E = Env()
        try:
            E.set_policy("allowed")
            E.post("Bash", {"command": "true"}, tuid="init")
            E.write(MS, "---\ntitle: t\n---\n\n図書館の利用率は 87.5% に達した。\n\n回答者のうち 412 人が来館した(data/processed/made.csv)。\n")
            # a numeric-claims row whose data file does not exist exempts nothing, and check reports it
            os.makedirs(E.path("data"), exist_ok=True)
            with open(E.path("data", "numeric-claims.csv"), "w", encoding="utf-8") as f:
                f.write("claim_id,text_value,file,column,key_column,key,note\nN1,87.5,data/processed/none.csv,v,k,x,\n")
            # an AI-written processed file is not a source
            self.assertEqual(E.ai_write(E.path("data", "processed", "made.csv"), "k,v\nx,412\n"), "-")
            out = ng(E.rk("check", "--submit").stdout)
            self.assertTrue(any("87.5%" in l for l in out), out)
            self.assertTrue(any("412" in l for l in out), out)
            self.assertTrue(any("numeric-claims" in l for l in out), out)
            # the student's own data file (outside any AI call) does count, and a row that checks out exempts
            os.remove(E.path("data", "processed", "made.csv"))
            with open(E.path("data", "processed", "rates.csv"), "w", encoding="utf-8") as f:
                f.write("k,v\nx,87.5\n")
            with open(E.path("data", "numeric-claims.csv"), "w", encoding="utf-8") as f:
                f.write("claim_id,text_value,file,column,key_column,key,note\nN1,87.5,data/processed/rates.csv,v,k,x,\n")
            E.write(MS, "---\ntitle: t\n---\n\n図書館の利用率は 87.5% に達した。\n\n回答者のうち 412 人が来館した(data/processed/rates.csv)。\n")
            out = ng(E.rk("check", "--submit").stdout)
            self.assertFalse(any("87.5%" in l or "412" in l for l in out), out)
        finally:
            E.cleanup()


class FigureRules(unittest.TestCase):
    FOUND = ["有効回答数は 1523 であった。", "n = 2000 の回答を得た。", "Mean 3.42 (SD 0.81) on the scale.", "来館者は (1234) 人と推定された。",
             "図書館の利用率は 87.5% に達した。", "回答者のうち 412 人が毎週来館した。", "In 2020, 1200 students visited."]
    METHODS = ("本調査では、回答を 5 段階で尋ねた。質問紙は 12 問、20 項目からなり、各項目は 5 件法で答える。回答者を 2 群に分け、"
               "第2波の調査は 2 回目の配布として 2024年11月に行った。分析には Python 3.13 と R 4.3 を使った(表1、図2)。")

    def test_years_versions_and_design_counts(self):
        for t in self.FOUND:
            self.assertTrue(verification.figures(t), t)
        self.assertEqual(verification.figures(self.METHODS), [])
        self.assertEqual(verification.figures("In 2020 the library reopened."), [])


class ToolInputs(unittest.TestCase):
    def test_paths_inside_arrays_urls_and_odd_keys(self):
        E = Env(name="my thesis")
        try:
            E.set_policy("prohibited")
            ms = E.path(MS)
            for ti in ({"edits": [{"path": ms, "oldText": "a", "newText": "b"}]}, {"changes": [{"file": ms, "text": "b"}]},
                       {"url": "file://" + ms, "content": "b"}, {"from": "/tmp/a.md", "to": ms}, {"args": ["--out", ms]},
                       {"title": ms}, {"pattern": "manuscript/*.md", "replace": "y"}, {"command": "echo hi", "path": ms}):
                self.assertEqual(decision(E.pre("mcp__fs__op", ti)), "deny", ti)
            # text under a body key is not a path
            E.set_policy("allowed")
            self.assertEqual(decision(E.pre("mcp__fs__op", {"path": E.path("research", "n.md"), "content": ms})), "-")
        finally:
            E.cleanup()


class LockTimeout(unittest.TestCase):
    def test_a_window_that_cannot_be_locked_fails_closed_and_counts_as_uncertain(self):
        E = Env()
        old = (os.environ.get("HOME"), os.environ.get("RK_STATE_HOME"))
        try:
            E.set_policy("allowed")
            mp = E.path(MS)
            E.ai_edit(mp, E.read("manuscript", "main.md") + "\n図書館の利用者は増えた。\n", tuid="w0")
            os.environ["HOME"], os.environ["RK_STATE_HOME"] = E.home, E.state
            st = common.state_dir(E.proj)
            lk = open(os.path.join(st, "windows.lock"), "a+b")
            fcntl.flock(lk.fileno(), fcntl.LOCK_EX)
            try:
                d, _ctx = E.ai_edit(mp, E.read("manuscript", "main.md") + "\nロックの待ち時間に書かれた段落。\n", tuid="w1")
            finally:
                fcntl.flock(lk.fileno(), fcntl.LOCK_UN)
                lk.close()
            self.assertEqual(d, "ask")
            E.ai_bash("ls", tuid="b9")
            rows = [json.loads(l) for l in open(E.path(".ryukoku", "provenance.jsonl"), encoding="utf-8") if l.strip()]
            last = [r for r in rows if r.get("type") == "paragraph"][-1]
            self.assertIn(last.get("actor"), ("ai", "uncertain"), last)
        finally:
            os.environ["HOME"], os.environ["RK_STATE_HOME"] = old
            E.cleanup()


class PandocUserData(unittest.TestCase):
    @unittest.skipUnless(HAVE_PANDOC, "pandoc not installed")
    def test_templates_in_the_users_pandoc_data_dir_are_not_used(self):
        E = Env()
        try:
            t = os.path.join(E.home, ".local", "share", "pandoc", "templates", "default.latex")
            E.set_policy("prohibited")
            self.assertEqual(decision(E.pre("Write", {"file_path": t, "content": "x"})), "deny")
            os.makedirs(os.path.dirname(t), exist_ok=True)
            open(t, "w").write("\\documentclass{article}\\begin{document}$body$ FABRICATED-TEMPLATE \\end{document}\n")
            E.write(MS, "---\ntitle: t\n---\n\n本文。\n")
            r = E.rk("export", "latex")
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertNotIn("FABRICATED-TEMPLATE", open(E.path("build", "manuscript.tex"), encoding="utf-8").read())
        finally:
            E.cleanup()


class Addresses(unittest.TestCase):
    def test_prefecture_city_town_and_number(self):
        E = Env()
        try:
            for p in ("住所は大阪府見本市試験町12です", "送り先: 東京都見本区試作台3-4"):
                self.assertEqual(decision(E.prompt(p)), "block", p)
            for p in ("京都府の図書館の利用者は増えた", "京都府京都市の人口を調べた"):
                self.assertNotEqual(decision(E.prompt(p)), "block", p)
        finally:
            E.cleanup()


if __name__ == "__main__":
    unittest.main()
