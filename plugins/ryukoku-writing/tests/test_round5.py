"""Regressions from the third round of independent adversarial verification: allow-listed commands (git, the
plugin's export) that read configuration the AI could write and so run other programs, writes outside the project
that take over the student's terminal, the CI root with several keys, line-initial Markdown marks, and common
read-only commands. Each finding's reproduction became a test here."""
import json
import os
import shutil
import subprocess
import sys
import threading
import unittest

from helpers import PASS, PLUGIN, Env, decision, reason

sys.path.insert(0, os.path.join(PLUGIN, "scripts", "rk"))
MS = "manuscript/main.md"


class Base(unittest.TestCase):
    def setUp(self):
        self.E = Env()
        self.E.setup()
        self.P = self.E.proj
        self._env = {k: os.environ.get(k) for k in ("RK_STATE_HOME", "HOME")}
        os.environ["RK_STATE_HOME"], os.environ["HOME"] = self.E.state, self.E.home

    def tearDown(self):
        for k, v in self._env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        self.E.cleanup()

    def d(self, cmd, tool="Bash"):
        return decision(self.E.pre(tool, {"command": cmd} if tool == "Bash" else cmd))


# ------------------------------------------------------------ git configuration and startup files
class GitAndStartup(Base):
    def test_planted_git_repo_config_is_not_run_without_asking(self):
        """A git read-only command used against a planted repo (with core.fsmonitor) asks; writing the repo's
        files, or a .git-named file, or a config-shaped file, is denied/asked."""
        os.makedirs(self.P + "/sub")
        self.assertIn(decision(self.E.pre("Write", {"file_path": self.E.home + "/.cache/z/HEAD", "content": "ref: refs/heads/main\n"})), ("ask", "deny"))
        self.assertEqual(self.d({"file_path": self.E.home + "/.cache/z/config", "content": "[core]\n\tfsmonitor = python3 x\n"}, tool="Write"), "ask")
        self.assertEqual(self.d({"file_path": self.P + "/sub/.git", "content": "gitdir: /x\n"}, tool="Write"), "deny")
        self.assertEqual(self.d("printf 'gitdir: /x' > sub/.git"), "deny")
        self.assertEqual(self.d("git -C %s/.cache/z status" % self.E.home), "ask")
        self.assertEqual(self.d("git -C sub status"), "ask")
        self.assertEqual(self.d("git -c core.fsmonitor=x status"), "ask")

    def test_git_read_only_in_the_project_repo_runs_without_asking(self):
        if not shutil.which("git"):
            self.skipTest("git not installed")
        E = Env()
        try:
            E.setup(git="g")
            def d(c):
                return decision(E.pre("Bash", {"command": c}))
            self.assertEqual(d("git status"), "-")
            self.assertEqual(d("git log --oneline -5"), "-")
            self.assertEqual(d("git diff"), "-")
            self.assertEqual(d("git show HEAD --stat"), "-")
            self.assertEqual(d("git -C . status"), "-")
            # a sibling repo, or a config-executing option, still asks
            self.assertEqual(d("git -C %s status" % os.path.dirname(E.proj)), "ask")
            self.assertEqual(d("git -c core.pager='python3 x' log"), "ask")
            self.assertEqual(d("git log --ext-diff -p"), "ask")
        finally:
            E.cleanup()

    def test_startup_and_path_and_boot_writes_are_denied(self):
        home = self.E.home
        for tool, ti in [("Write", {"file_path": home + "/.bashrc", "content": "x"}),
                         ("Write", {"file_path": home + "/.profile", "content": "x"}),
                         ("Write", {"file_path": home + "/.zshrc", "content": "x"}),
                         ("Write", {"file_path": home + "/.local/bin/python3", "content": "x"}),
                         ("Write", {"file_path": home + "/bin/python3", "content": "x"}),
                         ("Write", {"file_path": home + "/.config/autostart/x.desktop", "content": "x"}),
                         ("Write", {"file_path": home + "/.config/systemd/user/x.service", "content": "x"}),
                         ("Write", {"file_path": self.P + "/.envrc", "content": "x"}),
                         ("Write", {"file_path": self.P + "/.vscode/tasks.json", "content": "x"}),
                         ("Edit", {"file_path": home + "/.bashrc", "old_string": "a", "new_string": "b"}),
                         ("Bash", {"command": "printf x >> %s/.bashrc" % home}),
                         ("Bash", {"command": "echo x > %s/.local/bin/python3" % home}),
                         ("Bash", {"command": "cp manuscript/main.md %s/.zshenv" % home})]:
            with self.subTest(tool=tool, ti=str(ti)[:60]):
                self.assertEqual(decision(self.E.pre(tool, ti)), "deny")

    def test_other_outside_write_asks_but_session_tmp_is_ok(self):
        # a project under /tmp (the test sandbox) does not make /tmp a free-for-all: an outside write still asks
        self.assertEqual(self.d({"file_path": self.E.base + "/elsewhere/notes.txt", "content": "x"}, tool="Write"), "ask")

    def test_config_shaped_content_anywhere_asks(self):
        self.assertEqual(self.d({"file_path": self.P + "/scratch/c", "content": '[filter "x"]\n\tprocess = python3 y\n'}, tool="Write"), "ask")
        self.assertEqual(self.d({"file_path": self.P + "/scratch/c2", "content": "[core]\n\tsshCommand = python3 y\n"}, tool="Write"), "ask")


# ------------------------------------------------------------ pandoc defaults
class PandocDefaults(Base):
    def test_a_filter_in_defaults_is_rejected_by_export_and_check(self):
        from rklib import export
        d = self.E.path("pandoc", "defaults-ja-docx.yaml")
        with open(d, "a", encoding="utf-8") as f:
            f.write("filters:\n  - scratch/f.lua\n")
        safe, bad = export.sanitize_defaults(d, self.P)
        self.assertIn("filters", bad)
        self.assertNotIn("filters", safe)
        probs = export.defaults_problems(self.P)
        self.assertTrue(any(fn == "defaults-ja-docx.yaml" and "filters" in b for fn, b in probs))
        r = self.E.rk("check")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("pandoc", r.stdout)
        # export refuses to run with the filter present
        r = self.E.rk("export", "docx")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("許可していない", r.stderr + r.stdout)

    def test_other_dangerous_keys_are_rejected(self):
        from rklib import export
        d = self.E.path("pandoc", "defaults-ja-docx.yaml")
        base = open(d, encoding="utf-8").read()
        for extra in ("lua-filter: scratch/f.lua\n", "template: scratch/t.tex\n", "data-dir: scratch\n",
                      "pdf-engine: /tmp/evil\n", "include-in-header: scratch/h.tex\n"):
            with open(d, "w", encoding="utf-8") as f:
                f.write(base + extra)
            _safe, bad = export.sanitize_defaults(d, self.P)
            self.assertTrue(bad, extra)

    def test_a_clean_defaults_is_accepted(self):
        from rklib import export
        d = self.E.path("pandoc", "defaults-ja-docx.yaml")
        safe, bad = export.sanitize_defaults(d, self.P)
        self.assertEqual(bad, [])
        self.assertEqual(safe.get("to"), "docx")
        self.assertEqual(safe.get("metadata"), {"lang": "ja"})

    def test_pandoc_dir_is_watched(self):
        from rklib import msguard
        self.assertIn("pandoc", msguard.TREES)


# ------------------------------------------------------------ CI root with several keys
@unittest.skipUnless(shutil.which("git"), "git not installed")
class CiRootMultiKey(unittest.TestCase):
    def setUp(self):
        self.E = Env()
        self.E.setup(git="g")
        self.P = self.E.proj
        self.origin = os.path.join(self.E.base, "origin.git")
        self.git("init", "-q", "--bare", self.origin, cwd=self.E.base)
        self.git("remote", "add", "origin", self.origin)
        self.git("push", "-q", "--no-verify", "-u", "origin", "main")
        self._env = {k: os.environ.get(k) for k in ("RK_STATE_HOME", "HOME")}
        os.environ["RK_STATE_HOME"], os.environ["HOME"] = self.E.state, self.E.home

    def tearDown(self):
        for k, v in self._env.items():
            os.environ.pop(k, None) if v is None else os.environ.__setitem__(k, v)
        self.E.cleanup()

    def git(self, *a, cwd=None):
        r = subprocess.run(["git"] + list(a), cwd=cwd or self.P, env=self.E.env(), capture_output=True, text=True)
        if r.returncode:
            raise AssertionError(" ".join(a) + ": " + r.stderr)
        return r.stdout

    def test_two_root_keys_in_the_first_commit_are_rejected(self):
        from rklib import sign, trust
        sign.register(self.P, "student", "student", "ai chosen pass phrase violet 99")  # a second key in signers.json
        both = open(self.E.path(".ryukoku", "signers.json"), encoding="utf-8").read()
        self.git("stash", "-q")
        self.git("checkout", "-q", "--orphan", "newmain")
        with open(self.E.path(".ryukoku", "signers.json"), "w", encoding="utf-8") as f:
            f.write(both)
        self.git("add", "-A")
        self.git("commit", "-qm", "rk setup: initial project (signers.json is the trust root)", "--no-verify")
        self.git("push", "-q", "--no-verify", "-f", "origin", "newmain:main")
        self.git("fetch", "-q", "origin")
        t, probs, _n = trust.ci_trusted(self.P, "origin/main")
        self.assertTrue(any("起点の署名者が" in p for p in probs))
        self.assertEqual(t, {})


# ------------------------------------------------------------ line-initial Markdown marks
class LineInitialMarkers(unittest.TestCase):
    def ok(self, o, n):
        from rklib.proposals import check_hunk
        return check_hunk("format", [o], [n])[0]

    def test_full_width_to_ascii_that_makes_a_marker_is_refused(self):
        self.assertFalse(self.ok("：　定義", ":   定義"))        # definition list
        self.assertFalse(self.ok("　：定義", "  :定義"))
        self.assertFalse(self.ok("＞引用", ">引用"))                 # block quote
        self.assertFalse(self.ok("－項目", "-項目"))                 # bullet
        self.assertFalse(self.ok("＋項目", "+項目"))
        self.assertFalse(self.ok("｜表", "|表"))

    def test_percent_inside_math_is_refused(self):
        self.assertFalse(self.ok("値は $50％$", "値は $50%$"))
        self.assertFalse(self.ok("$$x=50％$$", "$$x=50%$$"))
        self.assertFalse(self.ok("\\section{50％}", "\\section{50%}"))

    def test_normal_full_width_changes_still_pass(self):
        self.assertTrue(self.ok("本文：改行", "本文:改行"))           # colon not at line start
        self.assertTrue(self.ok("割合は 50％", "割合は 50%"))     # % outside math
        self.assertTrue(self.ok("１２．５％", "12.5%"))


# ------------------------------------------------------------ common read-only commands
class AllowedReads(Base):
    def test_sed_print_and_version_only(self):
        for c in ["sed -n '1,40p' manuscript/main.md", "sed -n '5p' manuscript/main.md",
                  "python3 --version", "python3 -V", "pandoc --version", "git --version", "lualatex --version"]:
            with self.subTest(c=c):
                self.assertEqual(self.d(c), "-", c)

    def test_sed_write_and_program_and_awk_still_ask(self):
        for c in ["sed -i 's/a/b/' manuscript/main.md", "sed -n '1e python3 x' a", "sed 's/a/b/' a",
                  "awk 'NR<5' manuscript/main.md", "pandoc manuscript/main.md -o x.docx"]:
            with self.subTest(c=c):
                self.assertIn(self.d(c), ("ask", "deny"), c)


if __name__ == "__main__":
    unittest.main()
