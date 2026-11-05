"""The allow-list of commands that run without asking, a renamed copy of the evidence notebook, the CI trust root and
key revocation, heading numbers, and smaller cases. Each test reproduces a way around a safeguard that an independent
adversarial review found."""
import json
import os
import shutil
import subprocess
import sys
import tarfile
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

    def d(self, cmd, background=False, tool="Bash"):
        ti = {"command": cmd}
        if background:
            ti["run_in_background"] = True
        r = self.E.pre(tool, ti)
        return decision(r), reason(r)


# ------------------------------------------------------------ allow-list
PROBES = [  # ways to run code the AI wrote: every one must ask or be denied
    "python3 scratch/x.py", "bash scratch/x.sh", "find scratch -name x.py -exec python3 {} \\;",
    "find scratch -name x.sh -exec sh {} +", 'bash -c "$(cat scratch/x.sh)"', 'eval "$(cat scratch/x.sh)"',
    "cp scratch/x.py y.py && python3 y.py", "ln -s scratch/x.py z.py && python3 z.py", "env -S 'python3 scratch/x.py'",
    "nice -n 5 python3 scratch/x.py", "timeout -s KILL 10 python3 scratch/x.py", "exec -a foo python3 scratch/x.py",
    "xargs -a scratch/list.txt python3", "cat scratch/list.txt | xargs python3", "awk 'BEGIN{system(\"python3 scratch/x.py\")}'",
    "sed -n '1e python3 scratch/x.py' manuscript/main.md", "git -c alias.z='!python3 scratch/x.py' z",
    "git -c core.pager='python3 scratch/x.py' log -1", "git log --ext-diff -p", "git diff --textconv", "git log --output=x.txt",
    "make -C scratch", "npm run --prefix scratch go",
    "PYTHONPATH=scratch python3 tools/rk/rk.py status", "BASH_ENV=scratch/x.sh bash -c true", "python3 -m pytest -q scratch",
    "python3 -m unittest discover -s scratch -p 'test_*.py'", "pytest -q scratch", "sh < scratch/x.sh", "bash <(cat scratch/x.sh)",
    "source scratch/x.sh", ". scratch/x.sh", "cd scratch && python3 x.py", "cd scratch && sh ./x.sh",
    "alias go='python3 scratch/x.py'; go", "f(){ python3 scratch/x.py; }; f", "function f { ls; }", "nohup python3 scratch/x.py",
    "python3 scratch", "python3 $PWD/scratch/x.py", "python3 'scratch/x.py'", "true\npython3 scratch/x.py",
    "true # \\\npython3 scratch/x.py", "ls # comment\npython3 scratch/x.py", "ls; python3 scratch/x.py", "(python3 scratch/x.py)",
    "{ python3 scratch/x.py; }", "X=python3; $X scratch/x.py", "ls `python3 scratch/x.py`", "cat <<EOF | python3\nprint(1)\nEOF",
    "rg --pre scratch/x.sh x", "sort --compress-program=scratch/x.sh a", "find . -delete", "env python3 scratch/x.py",
    "command python3 scratch/x.py", "PATH=scratch:$PATH ls", "ls > ~/x.txt", "echo x > .githooks/pre-commit",
]
ALLOWED = [  # read-only commands and the plugin's own code run without asking
    "ls -la", "cat research/questions.md", "head -20 manuscript/main.md", "wc -l manuscript/main.md",
    "sed -n '1,40p' manuscript/main.md", "sed -n '5p' manuscript/main.md", "python3 --version", "pandoc --version",
    "python3 tools/rk/rk.py --version", "grep -rn 要因 manuscript | head -20",
    "rg -n 要因 manuscript", "find . -name '*.md'", "sort a.txt | uniq -c", "pwd", "mkdir -p scratch/a", "echo ok",
    "diff a.txt b.txt", "stat manuscript/main.md", "cut -d, -f1 sources/register.csv",
    "python3 tools/rk/rk.py check", "python3 -B tools/rk/rk.py status", "./rk check",
    "python3 tools/rk/rk.py search crossref 'x' --question-ref Q1 2>&1 | tail -5", "python3 tools/rk/rk.py annot list --open",
    "ls > review/files.txt", "cat a 2>/dev/null",
]


class AllowList(Base):
    def setUp(self):
        super().setUp()
        X = self.P + "/scratch"
        # sitecustomize.py is Python configuration: the AI's Write is denied (it is placed directly here)
        self.assertEqual(self.E.pre("Write", {"file_path": os.path.join(X, "sitecustomize.py"), "content": "x = 1\n"}).returncode, 0)
        os.makedirs(X, exist_ok=True)
        with open(os.path.join(X, "sitecustomize.py"), "w") as f:
            f.write("x = 1\n")
        for f, c in [("x.py", "open('pwned.txt','a').write('x\\n')\n"), ("x.sh", "echo pwned >> pwned.txt\n"),
                     ("test_x.py", "def test_a():\n    pass\n"),
                     ("Makefile", "all:\n\tpython3 x.py\n"), ("package.json", '{"scripts": {"go": "python3 x.py"}}\n'),
                     ("list.txt", "scratch/x.py\n")]:
            self.assertEqual(self.E.ai_write(os.path.join(X, f), c), "-")

    def test_every_probe_asks_or_is_denied(self):
        for c in PROBES:
            with self.subTest(c=c):
                d, _r = self.d(c)
                self.assertIn(d, ("ask", "deny"), c)
        self.assertFalse(os.path.exists(self.E.path("pwned.txt")))

    def test_allow_list_runs_without_asking(self):
        for c in ALLOWED:
            with self.subTest(c=c):
                self.assertEqual(self.d(c)[0], "-", c)
        # the shell's directory is not followed: after a cd, a relative script path is unknown and asks
        self.assertEqual(self.d("cd %s && python3 tools/rk/rk.py status" % self.P)[0], "ask")
        self.assertEqual(self.d("cd %s && python3 %s/tools/rk/rk.py status" % (self.P, self.P))[0], "-")

    def test_reasons_name_the_command(self):
        d, r = self.d("make -C scratch")
        self.assertEqual(d, "ask")
        self.assertIn("make", r)
        self.assertIn("Plugin の外のコードやコマンドを実行しうる", r)
        d, r = self.d("python3 scratch/x.py")
        self.assertIn("AI が書いた・変えたファイル", r)  # the stronger wording for AI-written files

    def test_assignments_before_the_plugin_code_ask(self):
        for c in ["PYTHONPATH=scratch python3 tools/rk/rk.py check", "RK_STATE_HOME=/tmp/x ./rk check",
                  "PYTHONSTARTUP=x python3 tools/rk/rk.py check"]:
            with self.subTest(c=c):
                self.assertEqual(self.d(c)[0], "ask")

    def test_a_tampered_tools_copy_is_not_plugin_code(self):
        p = self.E.path("tools", "rk", "rklib", "extra.py")
        with open(p, "w") as f:
            f.write("x = 1\n")
        self.assertEqual(self.d("python3 tools/rk/rk.py check")[0], "ask")
        os.remove(p)
        self.assertEqual(self.d("python3 tools/rk/rk.py check")[0], "-")

    def test_git_and_python_configuration_is_denied(self):
        for tool, ti in [("Write", {"file_path": self.E.path(".git", "config"), "content": "[core]\npager = x\n"}),
                         ("Write", {"file_path": os.path.join(self.E.home, ".gitconfig"), "content": "[diff]\nexternal = x\n"}),
                         ("Write", {"file_path": os.path.join(self.E.home, ".config", "git", "config"), "content": "x"}),
                         ("Write", {"file_path": os.path.join(self.E.home, ".local", "lib", "python3.13", "site-packages", "a.pth"), "content": "x"}),
                         ("Write", {"file_path": self.E.path("scratch", "usercustomize.py"), "content": "x"}),
                         ("Bash", {"command": "echo x > .git/hooks/pre-commit"}), ("Bash", {"command": "printf x >> ~/.gitconfig"})]:
            with self.subTest(tool=tool, ti=str(ti)[:70]):
                self.assertEqual(decision(self.E.pre(tool, ti)), "deny")

    def test_ai_written_files_are_known_by_content(self):
        """touch -d, mv and a tar round trip do not hide a file the AI wrote (by content hash and change time)."""
        out = os.path.join(self.E.base, "outside")
        os.makedirs(out)
        # 1. created and back-dated in one call, run in the next
        self.assertEqual(self.E.ai_bash("printf 'print(1)\\n' > %s/z.py && touch -d 2020-01-01 %s/z.py" % (out, out), tuid="t1",
                                        allow_ask=True)[0], "ask")
        d, r = self.d("python3 %s/z.py" % out)
        self.assertEqual(d, "ask")
        self.assertIn("AI が書いた・変えたファイル", r)
        # 2. mv + touch -d of an AI-written file
        self.E.ai_bash("mv scratch/x.py scratch/q.py && touch -d 2020-01-01 scratch/q.py", tuid="t2", allow_ask=True)
        self.assertIn("AI が書いた・変えたファイル", self.d("python3 scratch/q.py")[1])
        # 3. a tar with old modification times, extracted in a later call
        src = os.path.join(out, "w.py")
        with open(src, "w") as f:
            f.write("print(2)\n")
        os.utime(src, (1, 1))
        with tarfile.open(os.path.join(out, "w.tar"), "w") as tf:
            tf.add(src, arcname="w.py")
        os.remove(src)
        self.E.ai_bash("tar -xf %s/w.tar -C scratch" % out, tuid="t3", allow_ask=True)
        self.assertIn("AI が書いた・変えたファイル", self.d("python3 scratch/w.py")[1])


# ------------------------------------------------------------ fake evidence notebook
class FakeNotebook(Base):
    def test_renamed_and_backdated_copy(self):
        cp = os.path.join(self.E.home, ".cache", "pyc-tmp")
        shutil.copytree(PLUGIN, cp, ignore=shutil.ignore_patterns("tests", "evals", "__pycache__"))
        main = os.path.join(cp, "scripts", "rk", "main.py")
        shutil.copy(os.path.join(cp, "scripts", "rk", "rk.py"), main)
        for dp, _dns, fns in os.walk(cp):
            for fn in fns:
                os.utime(os.path.join(dp, fn), (1, 1))
        for bg in (False, True):
            with self.subTest(bg=bg):
                self.assertEqual(self.d('python3 %s --project "%s" notebook' % (main, self.P), background=bg)[0], "deny")
                d, r = self.d("python3 %s --project %s status" % (main, self.P), background=bg)
                self.assertEqual(d, "ask")
                self.assertIn("合言葉を入れる画面や端末を偽れる", r)
        d, r = self.d("python3 -m http.server 8000", background=True)
        self.assertEqual(d, "ask")
        self.assertIn("Plugin の外のコード", r)


# ------------------------------------------------------------ CI trust root and revocation
@unittest.skipUnless(shutil.which("git"), "git not installed")
class TrustRootAndRevocation(unittest.TestCase):
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
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        self.E.cleanup()

    def git(self, *a, cwd=None, **kw):
        r = subprocess.run(["git"] + list(a), cwd=cwd or self.P, env=dict(self.E.env(), **kw), capture_output=True, text=True)
        if r.returncode:
            raise AssertionError(" ".join(a) + ": " + r.stderr)
        return r.stdout

    def ci(self):
        self.git("fetch", "-q", "origin")
        return self.E.rk("check", "--ci", "--stage", "pr", "--base-ref", "origin/main", plugin=True)

    def _orphan_with(self, signers_text):
        self.git("checkout", "-q", "--orphan", "old")
        self.git("rm", "-rq", "--cached", ".")
        with open(self.E.path(".ryukoku", "signers.json"), "w", encoding="utf-8") as f:
            f.write(signers_text)
        self.git("add", ".ryukoku/signers.json")
        old = dict(GIT_AUTHOR_DATE="2020-01-01T00:00:00", GIT_COMMITTER_DATE="2020-01-01T00:00:00")
        self.git("commit", "-qm", "initial", "--no-verify", **old)

    def test_orphan_history_merged_in_both_directions(self):
        from rklib import sign
        sign.register(self.P, "student", "student", "ai chosen pass phrase violet 99")
        both = open(self.E.path(".ryukoku", "signers.json"), encoding="utf-8").read()
        self.git("stash", "-q")
        self._orphan_with(both)
        # (a) the orphan merged into main
        self.git("checkout", "-q", "-f", "main")
        self.git("merge", "-q", "--no-verify", "--allow-unrelated-histories", "-s", "ours", "--no-edit", "old")
        self.git("push", "-q", "--no-verify", "origin", "main")
        r = self.ci()
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("根の commit が 2 個", r.stdout)
        # (b) main merged into the orphan, and main moved there; the working tree keeps the full project
        self.git("reset", "-q", "--hard", "HEAD~1")
        self.git("branch", "-q", "oldmerge", "old")
        self.git("merge", "-q", "--no-verify", "--allow-unrelated-histories", "-s", "ours", "--no-edit", "oldmerge")
        self.git("push", "-q", "--no-verify", "-f", "origin", "main")
        r = self.ci()
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("根の commit が 2 個", r.stdout)

    def test_root_fingerprint_is_printed_first(self):
        r = self.ci()
        self.assertTrue(r.stdout.splitlines()[0].startswith("【信頼の起点】"), r.stdout[:300])

    def _rotate(self, leaked, current):
        from rklib import setup, sign, trust

        class T(object):
            lang = "ja"

            def t(self, ja, en):
                return ja

            def say(self, m=""):
                pass

            def ask(self, p):
                return ""

            def key(self, p, allowed):
                return allowed[0]
        answers = [current, "new passphrase handed over 77", "new passphrase handed over 77"]
        orig = sign.read_passphrase
        sign.read_passphrase = lambda prompt="": answers.pop(0)
        try:
            trusted = trust.local_trusted(self.P)[0]
            active = {k: s for k, s in trusted.items() if s.get("status", "active") == "active"}
            return setup.rotate(self.P, T(), sign.load_signers(self.P), trusted, active, leaked)
        finally:
            sign.read_passphrase = orig

    def test_leaked_hand_over_keeps_ci_trust_and_revoked_key_cannot_endorse(self):
        from rklib import sign, trust
        old_key = list(sign.load_signers(self.P))[0]
        self._rotate(True, PASS)
        signers = sign.load_signers(self.P)
        self.assertEqual(signers[old_key]["status"], "revoked")
        new_key = [k for k in signers if k != old_key][0]
        # the attacker who knows the leaked passphrase endorses their own key with the revoked one
        old_signer, old_secret = None, None
        for s in signers.values():
            if s["key"] == old_key:
                kdf = s["kdf"]
                old_secret = sign.derive_secret(PASS, kdf["salt"], kdf["iter"])
                old_signer = s
        evil, _sec = sign.register(self.P, "student", "student", "evil passphrase from the leak 55",
                                   endorser=old_signer, endorser_secret=old_secret)
        trusted, probs, _n = trust.local_trusted(self.P)
        self.assertIn(new_key, trusted)
        self.assertNotIn(evil["key"], trusted)
        self.assertTrue(any("未承認" in p for p in probs))
        # CI: commit the hand-over (without the evil key) on main; the new key stays trusted
        signers = sign.load_signers(self.P)
        signers.pop(evil["key"])
        sign.save_signers(self.P, signers)
        self.git("add", ".ryukoku/signers.json")
        self.git("commit", "-qm", "hand over", "--no-verify")
        self.git("push", "-q", "--no-verify", "origin", "main")
        self.git("fetch", "-q", "origin")
        t, p, _n = trust.ci_trusted(self.P, "origin/main")
        self.assertIn(new_key, t)
        self.assertEqual(p, [])

    def test_forgotten_passphrase_root_change_is_announced(self):
        from rklib import sign
        self._rotate(False, "")
        self.assertTrue(os.path.exists(self.E.path(".ryukoku", "root-changes.jsonl")))
        self.git("add", ".ryukoku")
        self.git("commit", "-qm", "new root", "--no-verify")
        self.git("push", "-q", "--no-verify", "origin", "main")
        r = self.ci()
        head = r.stdout.splitlines()[:3]
        self.assertTrue(any("起点が変わった" in h for h in head), r.stdout[:500])
        new_key = [k for k in sign.load_signers(self.P) if sign.load_signers(self.P)[k].get("status", "active") == "active"][-1]
        self.assertIn(sign.fingerprint(new_key), "\n".join(head))


# ------------------------------------------------------------ heading numbers
class HeadingNumbers(unittest.TestCase):
    def H(self, old, new):
        from rklib.proposals import check_hunk
        o, n = old.split("\n"), new.split("\n")
        idx = [i for i, (a, b) in enumerate(zip(o, n)) if a != b]
        return check_hunk("heading", [o[i] for i in idx], [n[i] for i in idx], o, n, idx, idx)[0]

    def test_numbers_with_units_are_content(self):
        self.assertFalse(self.H("# 1990 年代の状況\n本文", "# 2010 年代の状況\n本文"))
        self.assertFalse(self.H("## 3 つの要因", "## 5 つの要因"))
        self.assertFalse(self.H("# 1.5 倍の差", "# 2.5 倍の差"))
        self.assertFalse(self.H("# 50 % の学生", "# 60 % の学生"))

    def test_the_tool_computes_the_numbers(self):
        self.assertTrue(self.H("# はじめに\n# 方法\n## 手順", "# 1 はじめに\n# 2 方法\n## 2.1 手順"))
        self.assertTrue(self.H("# 1 はじめに\n# 3 方法", "# 1 はじめに\n# 2 方法"))
        self.assertFalse(self.H("# 1 はじめに\n# 3 方法", "# 1 はじめに\n# 7 方法"))
        self.assertTrue(self.H("# 題目\n## 第1章 序論\n## 第3章 方法", "# 題目\n## 第1章 序論\n## 第2章 方法"))
        self.assertFalse(self.H("# 方法", "## 方法"))


# ------------------------------------------------------------ smaller cases
class Misc(Base):
    def test_screen_comments_are_the_students_only(self):
        from notebook.server import make_server
        import http.client
        self.E.write(MS, "# はじめに\n\n要因 A がある。\n")
        srv = make_server(self.P, 0)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        try:
            port = srv.server_address[1]
            for actor, want in (("advisor", 403), ("student", 201)):
                c = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
                c.request("POST", "/api/annotations", body=json.dumps({"doc": MS, "quote": "要因 A", "code": "W1", "comment": "根拠は?",
                                                                       "actor": actor}),
                          headers={"Content-Type": "application/json", "X-RK-Request": "1", "Host": "127.0.0.1:%d" % port,
                                   "X-RK-Session": srv.app.session})
                self.assertEqual(c.getresponse().status, want, actor)
        finally:
            srv.shutdown()
        from review.store import Store
        with self.assertRaises(PermissionError):
            Store(self.P).create(MS, "# はじめに\n\n要因 A がある。\n", 7, 11, "W1", "x", "advisor", channel="notebook")
        out = self.E.rk("annot", "list").stdout
        self.assertIn("本人確認なし", out)

    def test_claude_plugin_and_config_commands_are_denied(self):
        for c in ["claude plugin disable ryukoku-writing@student-plugins", "claude plugin uninstall ryukoku-writing",
                  "claude config set disableAllHooks true", "claude mcp add x -- python3 y.py"]:
            with self.subTest(c=c):
                self.assertEqual(self.d(c)[0], "deny")

    def test_unknown_tools_paths_are_matched_like_write(self):
        for tool, ti in [("mcp__fs__write_file", {"path": self.E.path(MS), "content": "AI"}),
                         ("SomeNewTool", {"file_path": self.E.path(".ryukoku", "signoffs.jsonl"), "content": "x"}),
                         ("mcp__nb__edit", {"notebook_path": self.E.path("thinking", "log.md")})]:
            with self.subTest(tool=tool):
                self.assertEqual(decision(self.E.pre(tool, ti)), "deny")
        self.assertEqual(decision(self.E.pre("mcp__fs__write_file", {"path": self.E.path("research", "notes.md"), "content": "x"})), "-")

    def test_full_width_symbols(self):
        from rklib.proposals import check_hunk
        ok = [("値は１２．５％。", "値は12.5%。"), ("（注）参照", "(注)参照"), ("10：00", "10:00"), ("である！", "である!"),
              ("比（1：2）", "比(1:2)"), ("a；b", "a;b")]
        bad = [("50％", "50‰"), ("[リンク]（https://x）", "[リンク](https://x)"), ("！[図]", "![図]"), ("である。", "である？"),
               ("[^1]：注", "[^1]:注"), ("１０．５", "10。5"), ("（注）", "(注")]
        for o, n in ok:
            with self.subTest(o=o, n=n):
                self.assertTrue(check_hunk("format", [o], [n])[0])
        for o, n in bad:
            with self.subTest(o=o, n=n):
                self.assertFalse(check_hunk("format", [o], [n])[0])


class SessionRecord(Base):
    def test_check_reports_the_last_recorded_session(self):
        self.E.hook("session-start.sh", {"cwd": self.P, "session_id": "s1"})
        self.assertIn("Plugin のフックが最後に記録した", self.E.rk("check", plugin=True).stdout)


if __name__ == "__main__":
    unittest.main()
