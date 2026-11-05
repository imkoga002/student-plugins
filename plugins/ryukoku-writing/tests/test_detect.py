"""Routes that write the manuscript or a protected file past the pattern guard (variable concatenation, base64, a
script file, a symlink, patch, cd, find -exec, a here-document, tar) and attempts to hide what happened.

v2: a manuscript change made inside an AI tool window is the AI's writing and is recorded as provenance (paragraph
by paragraph, .ryukoku/provenance.jsonl), not raised as an alarm. These routes run in a course recorded as
prohibited, so the record shows up in `rk check` as AI paragraphs that the course does not allow (and as an
error at the pr and submit stages). A change to a protected file (the student's questions, the records) is still
a detection that fails the check until the student decides. Deleting provenance lines breaks the chain. All text
is placeholder ("要因 A")."""
import json
import os
import subprocess
import sys
import time
import unittest

from helpers import Env

MS = "manuscript/main.md"
AI_IN_PROHIBITED = "AI が書いた・直した段落が原稿に"


def prov(E):
    p = E.path(".ryukoku", "provenance.jsonl")
    if not os.path.exists(p):
        return []
    return [json.loads(l) for l in open(p, encoding="utf-8") if l.strip()]


class ShellRoutes(unittest.TestCase):
    def setUp(self):
        self.E = Env()
        self.E.setup(policy="p")
        self.E.post("Bash", {"command": "true"}, tuid="init")  # baseline

    def tearDown(self):
        self.E.cleanup()

    def check(self, *extra):
        r = self.E.rk("check", *extra)
        return r.returncode, r.stdout

    def assertRecorded(self, label):
        ents = [e for e in prov(self.E) if e.get("actor") == "ai"]
        self.assertTrue(ents, label + ": no AI provenance entry")
        self.assertTrue(all(e.get("policy") == "prohibited" for e in ents), label)
        rc, out = self.check()
        self.assertIn(AI_IN_PROHIBITED, out, label + "\n" + out)
        self.assertNotIn("検知した変更が未判断", out, label)
        rc, out = self.check("--submit")
        self.assertEqual(rc, 1, label)
        self.assertTrue(any(AI_IN_PROHIBITED in l for l in out.splitlines() if l.startswith("NG")), label + "\n" + out)

    def run_ai(self, cmd, tuid, allow_ask=True):
        return self.E.ai_bash(cmd, tuid=tuid, allow_ask=allow_ask)

    def slip(self, py, tuid):
        """A route the hooks cannot see through: a script the AI wrote, run after the student allowed it."""
        self.E.ai_write(self.E.path("scratch", tuid + ".py"), py, tuid=tuid + "w")
        d, ctx = self.run_ai("python3 scratch/%s.py" % tuid, tuid)
        self.assertEqual(d, "ask")
        return ctx

    def test_variable_concatenation(self):
        # a write whose target is a variable is denied outright in a prohibited course (its target is unknown)
        d, _ctx = self.run_ai('D=manu; D="${D}script"; printf "\\n要因 A について。\\n" >> "$D/main.md"', "m1")
        self.assertEqual(d, "deny")
        # a script the student allowed still gets through; then it is recorded
        ctx = self.slip("p='manu'+'script/main.md'\nopen(p,'a').write('\\n要因 A について。\\n')\n", "m1b")
        self.assertIn("由来の記録", ctx)
        self.assertRecorded("variable concatenation")
        self.assertTrue(any(e["tool"] == "Bash" for e in prov(self.E)))

    def test_base64_path(self):
        self.run_ai('P=$(printf bWFudXNjcmlwdC9tYWluLm1k | base64 -d); printf "\\nx\\n" >> "$P"', "m2")
        self.assertRecorded("base64 path")

    def test_script_file(self):
        self.assertEqual(self.E.ai_write(self.E.path("scratch", "w.py"), "p='manu'+'script/main.md'\nopen(p,'a').write('\\nx\\n')\n"), "-")
        d, _ = self.run_ai("python3 scratch/w.py", "m3", allow_ask=True)
        self.assertEqual(d, "ask")  # running a script the AI wrote asks the student first
        self.assertRecorded("script file")  # and if the student allows it, the write is still recorded

    def test_symlink_then_write(self):
        self.assertEqual(self.run_ai('ln -s "man""uscript" mlink', "m4a")[0], "deny")  # the link names the manuscript
        os.symlink("manuscript", self.E.path("mlink"))  # made some other way
        d = self.E.ai_write(self.E.path("mlink", "main.md"), "x")
        self.assertEqual(d, "deny")  # resolved before matching; the course prohibits AI writing
        rc, out = self.check()
        self.assertEqual(rc, 0, out)
        self.assertNotIn(AI_IN_PROHIBITED, out)

    def test_patch_routes(self):
        diff = "--- a/manuscript/main.md\n+++ b/manuscript/main.md\n@@ -1,1 +1,2 @@\n ---\n+要因 A\n"
        self.E.ai_write(self.E.path("scratch", "p.diff"), diff)
        d, _ = self.run_ai("git apply --unidiff-zero scratch/p.diff || patch -p1 < scratch/p.diff", "m5")
        if d in ("-", "ask") and prov(self.E):
            self.assertRecorded("git apply / patch")
        else:
            self.assertIn(d, ("deny", "ask", "-"))

    def test_cd_find_exec_heredoc_and_tar(self):
        cmds = ['cd manu* && printf "\\nx1\\n" >> main.md',
                "find . -name main.md -path '*nuscr*' -exec sh -c 'printf \"\\nx2\\n\" >> \"$1\"' _ {} \\;",
                "python3 - <<'EOF'\nopen('manu'+'script/main.md','a').write('\\nx3\\n')\nEOF"]
        for i, c in enumerate(cmds):
            with self.subTest(c=c):
                d, _ = self.run_ai(c, "m7-%d" % i)
                if d in ("-", "ask"):
                    self.assertRecorded(c)
        tmpd = os.path.join(self.E.base, "t")
        os.makedirs(os.path.join(tmpd, "manuscript"))
        with open(os.path.join(tmpd, "manuscript", "main.md"), "w") as f:
            f.write("x\n")
        subprocess.run(["tar", "-cf", self.E.path("scratch.tar"), "-C", tmpd, "manuscript"], check=True)
        d, _ = self.run_ai("tar -xf scratch.tar", "m9")
        if d in ("-", "ask"):
            self.assertRecorded("tar")

    def test_student_edit_of_an_ai_paragraph_is_recorded_as_estimated(self):
        self.slip("open('manu'+'script/main.md','a').write('\\nAI の段落(要因 A)。\\n')\n", "l1a")
        t = self.E.read(MS).replace("AI の段落(要因 A)。", "AI の段落を自分で直した(要因 A と B)。")
        with open(self.E.path(MS), "w", encoding="utf-8") as f:  # the student edits in their editor
            f.write(t)
        self.run_ai("ls", "l1b")
        self.E.rk("provenance", "sync")
        st = [e for e in prov(self.E) if e["actor"] == "student"]
        self.assertTrue(st and all(e["estimated"] for e in st), prov(self.E))
        r = self.E.rk("provenance", "show")
        self.assertIn("student_after_ai", r.stdout)

    def test_deleting_provenance_breaks_the_chain(self):
        self.slip("open('manu'+'script/main.md','a').write('\\nx\\n')\n", "e1a")
        self.slip("open('manu'+'script/main.md','a').write('\\ny\\n')\n", "e1c")
        script = ("p='.ryu'+'koku/provenance.jsonl'\nL=open(p).readlines()\nopen(p,'w').writelines(L[1:])\n")
        self.E.ai_write(self.E.path("scratch", "c.py"), script)
        d, _ = self.run_ai("python3 scratch/c.py", "e1b", allow_ask=True)
        self.assertEqual(d, "ask")  # the student is asked first; here they allow it
        rc, out = self.check()
        self.assertEqual(rc, 1, out)
        self.assertTrue("連鎖" in out or "続きになっていない" in out, out)
        self.assertIn("検知した変更が未判断", out)  # rewriting an append-only record is a detection too
        rc2, out2 = self.check("--ci")
        self.assertEqual(rc2, 1, out2)


class Protected(unittest.TestCase):
    def setUp(self):
        self.E = Env()
        self.E.setup()
        self.E.post("Bash", {"command": "true"}, tuid="init")

    def tearDown(self):
        self.E.cleanup()

    def test_protected_files_are_watched_and_a_light_decision_clears_it(self):
        d, _ = self.E.ai_bash("python3 -c \"import os;open(os.path.join('research','ques'+'tions.md'),'a').write('| Q9 | 問い | x | y |\\n')\"", tuid="pq",
                              allow_ask=True)
        self.assertEqual(d, "ask")  # inline code asks first
        r = self.E.rk("check")
        self.assertEqual(r.returncode, 1)
        self.assertIn("検知した変更が未判断", r.stdout)
        self.assertIn("protected", r.stdout)
        rc, out = self.E.tty(["changes"], ["m"])  # "it was my own action": a key press, no passphrase
        self.assertEqual(rc, 0, out[-1500:])
        self.assertNotIn("合言葉(入力は表示されない)", out)
        r = self.E.rk("check")
        self.assertEqual(r.returncode, 0, r.stdout)

    def test_student_edit_between_tool_calls_is_recorded_as_estimated(self):
        self.E.hook("session-start.sh", {"cwd": self.E.proj, "hook_event_name": "SessionStart"})  # remembers the text
        with open(self.E.path(MS), "a", encoding="utf-8") as f:
            f.write("\n自分で書いた段落(要因 A)。\n")
        self.E.ai_bash("ls", tuid="s1")
        r = self.E.rk("check")
        self.assertEqual(r.returncode, 0, r.stdout)
        st = [e for e in prov(self.E) if e["actor"] == "student"]
        self.assertTrue(st and all(e["estimated"] for e in st), prov(self.E))

    def test_machine_work_is_not_flagged(self):
        self.E.ai_bash("python3 tools/rk/rk.py ledger add-source --doi 10.1038/s41598-023-41032-5 --title T", tuid="mw")
        self.E.ai_bash("python3 tools/rk/rk.py annot flag --doc manuscript/main.md --quote 'はじめに' --code C1 --comment 'この節で読者に受け入れてほしい一文はどれか？'", tuid="mw2")
        r = self.E.rk("check")
        self.assertEqual(r.returncode, 0, r.stdout)

    def test_unsigned_confirmation_appearing_in_an_ai_call_is_detected(self):
        # a light confirmation needs no signature, so one written during an AI tool call (here: a script the student
        # allowed) is reported instead of being trusted
        code = ("import sys\nsys.path.insert(0,'tools/rk')\nfrom rklib import sign, subjects\n"
                "s=subjects.find('.', 'config', 'course-policy')\n"
                "sign.append_signoffs('.', [sign.make_confirmation('config','course-policy','confirmed',s.digest)])\n")
        self.E.ai_write(self.E.path("scratch", "f.py"), code)
        d, _ = self.E.ai_bash("python3 scratch/f.py", tuid="f1", allow_ask=True)
        self.assertEqual(d, "ask")
        r = self.E.rk("check")
        self.assertEqual(r.returncode, 1, r.stdout)
        self.assertIn("署名のない確認", r.stdout)


class DelayedWrite(unittest.TestCase):
    """A detached process writes after the tool call returned. It cannot be attributed: provenance records it as the
    student's edit (estimated) - the documented limit - and the section view shows the diff since the last
    confirmation."""

    def test_delayed_write_is_estimated_as_the_students_and_shown_as_a_diff(self):
        E = Env()
        try:
            E.setup()
            rc, out = E.tty(["sign", "section", MS, "--decision", "reviewed"], ["y"])
            self.assertEqual(rc, 0, out[-1500:])
            code = ("import os,time\nif os.fork()==0:\n    os.setsid()\n    time.sleep(2)\n"
                    "    open('manu'+'script/main.md','a').write('\\n遅れて入った行(要因 Z)\\n')\n    os._exit(0)\n")
            E.ai_write(E.path("scratch", "d.py"), code)
            self.assertEqual(E.ai_bash("python3 scratch/d.py", tuid="m11", allow_ask=True)[0], "ask")
            time.sleep(3)
            E.ai_bash("ls", tuid="m11b")
            st = [e for e in prov(E) if e["actor"] == "student" and e["estimated"]]
            self.assertTrue(st, prov(E))
            snippet = ("import sys,json;sys.path.insert(0,%r);from notebook.server import App;"
                       "a=App(%r,0);v=a.view('section','manuscript/main.md');print(json.dumps(v['diff'],ensure_ascii=False))"
                       % (os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts", "rk"), E.proj))
            r = E.run([sys.executable, "-B", "-c", snippet])
            diff = json.loads(r.stdout)
            self.assertTrue(any("遅れて入った行" in l and l.startswith("+") for l in diff), diff)
        finally:
            E.cleanup()


if __name__ == "__main__":
    unittest.main()
