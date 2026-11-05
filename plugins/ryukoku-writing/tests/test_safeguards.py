"""Safeguards against the AI posing as the student or erasing what it did: the human-only commands and the notebook,
the command allow-list (execgate), where the passphrase may be typed, the change-detection layer, every tool going
through the hooks, Claude Code's own settings, the CI trust root, portability of the hooks, comments and logs, and
batch signing. Each test reproduces a way around a safeguard that independent adversarial reviews found, the way
those probes were built (a script the AI writes and runs, a fake notebook, CI and API calls). The proposal allow-list
is in test_proposals.AllowList."""
import json
import os
import shlex
import shutil
import subprocess
import sys
import unittest

from helpers import PASS, PLUGIN, RKPY, Env, decision, reason

sys.path.insert(0, os.path.join(PLUGIN, "scripts", "rk"))
MS = "manuscript/main.md"


def ailog_lines(E):
    p = E.path(".ryukoku", "ai-use-log.jsonl")
    return [json.loads(x) for x in open(p, encoding="utf-8") if x.strip()] if os.path.exists(p) else []


def detections(E):
    return [e for e in ailog_lines(E) if e.get("type") == "detection"]


def run_in_window(E, cmd_or_fn, tuid, tool="Bash", ti=None):
    """PreToolUse (opens the window) -> run as the AI's command would -> PostToolUse."""
    ti = ti or {"command": cmd_or_fn if isinstance(cmd_or_fn, str) else "true"}
    d = decision(E.pre(tool, ti, tuid=tuid))
    if d == "deny":  # an "ask" models the student allowing the call (the allow-list asks for these probes)
        raise AssertionError("the probe was stopped before it ran (%s): %r" % (d, ti))
    if isinstance(cmd_or_fn, str):
        subprocess.run(["bash", "-c", cmd_or_fn], cwd=E.proj, env=E.env(), capture_output=True, timeout=60)
    else:
        cmd_or_fn()
    return E.post(tool, ti, tuid=tuid)


class Base(unittest.TestCase):
    def setUp(self):
        self.E = Env()
        self.E.setup()
        self.P = self.E.proj
        # code called inside this test process (decide, msguard, the notebook App) uses the sandbox state folder
        self._env = {k: os.environ.get(k) for k in ("RK_STATE_HOME", "HOME")}
        os.environ["RK_STATE_HOME"], os.environ["HOME"] = self.E.state, self.E.home

    def tearDown(self):
        for k, v in self._env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        self.E.cleanup()

    def d(self, tool, ti, **kw):
        return decision(self.E.pre(tool, ti, **kw))


# ------------------------------------------------------------ notebook command
class NotebookCommand(Base):
    def _run_advised(self, cmd):
        argv = shlex.split(cmd) + ["--once"]
        argv[0] = sys.executable
        return self.E.run(argv + [], cwd=self.P)

    def test_advised_commands_really_run(self):
        """SessionStart, the deny reason and the skill all send the student to ./rk notebook at their terminal; the
        command runs (the --once probe), and without a terminal the server refuses to start (no key would reach anyone)."""
        txt = reason(self.E.hook("session-start.sh", {"cwd": self.P, "session_id": "s1"}))
        self.assertIn("./rk notebook", txt)
        self.assertIn("./rk notebook", reason(self.E.pre("Bash", {"command": "./rk notebook"})))
        sk = open(os.path.join(PLUGIN, "skills", "notebook", "SKILL.md"), encoding="utf-8").read()
        self.assertIn("./rk notebook", sk)
        for argv in ([RKPY, "--project", self.P, "notebook", "--once"], [RKPY, "notebook", "--project", self.P, "--once"]):
            res = self.E.run([sys.executable] + argv, cwd=self.P)
            self.assertEqual(res.returncode, 0, res.stdout + res.stderr)
            self.assertIn("http://127.0.0.1:", res.stdout)
            self.assertNotIn("#k=", res.stdout)
        res = self.E.run([sys.executable, RKPY, "--project", self.P, "notebook", "--port", "0"], cwd=self.P, timeout=60)
        self.assertEqual(res.returncode, 3, res.stdout + res.stderr)
        self.assertNotIn("#k=", res.stdout + res.stderr)

    def test_notebook_prints_running_code_and_version(self):
        res = self.E.run([sys.executable, RKPY, "--project", self.P, "notebook", "--once"], cwd=self.P)
        self.assertIn(os.path.realpath(PLUGIN), res.stdout)
        self.assertIn("版 2.", res.stdout)


# ------------------------------------------------------------ running code the AI wrote
class ExecGate(Base):
    def test_running_a_script_the_ai_wrote_asks(self):
        """Write scratch/x.py then python3 scratch/x.py -> ask, naming the file."""
        self.assertEqual(self.E.ai_write(self.P + "/scratch/x.py", "print(1)\n"), "-")
        # (with a cd the directory is not followed: "cd scratch && python3 x.py" asks too, for an unknown file)
        self.assertEqual(decision(self.E.pre("Bash", {"command": "cd scratch && python3 x.py"})), "ask")
        for c in ["python3 scratch/x.py", "python3 -I -B scratch/x.py",
                  "echo $(python3 scratch/x.py)", "env python3 scratch/x.py"]:
            with self.subTest(c=c):
                r = self.E.pre("Bash", {"command": c})
                self.assertEqual(decision(r), "ask")
                self.assertIn("AI が書いたコードは学生の権限で何でもできる", reason(r))
                self.assertIn(os.path.join(self.P, "scratch", "x.py"), reason(r))
        self.assertEqual(decision(self.E.pre("Bash", {"command": "sh -c 'python3 scratch/x.py'"})), "ask")

    def test_inline_and_created_and_bash_written_code_asks(self):
        for c in ["python3 - <<'EOF'\nprint(1)\nEOF", "python3 -c 'print(1)'", "node -e 'x'", "perl -e 'print 1'",
                  "printf 'print(1)' > scratch/y.py; python3 scratch/y.py", "cat x.py | python3", "bash scratch/new.sh",
                  'python3 "$D/x.py"']:
            with self.subTest(c=c):
                self.assertEqual(self.d("Bash", {"command": c}), "ask")
        # a file written by an earlier AI Bash call (not by Write) is on the AI-written list too
        self.E.ai_bash("mkdir -p scratch && printf 'print(2)' > scratch/z.py", tuid="b-z")
        self.assertEqual(self.d("Bash", {"command": "python3 scratch/z.py"}), "ask")

    def test_plugin_tools_run_without_asking(self):
        for c in ["python3 tools/rk/rk.py check", "./rk check", "python3 tools/rk/rk.py status", "ls -la",
                  'bash "%s/scripts/init-project.sh" --help' % PLUGIN]:
            with self.subTest(c=c):
                self.assertEqual(self.d("Bash", {"command": c}), "-")

    def test_notebook_check_parses_the_command(self):
        """Quotes, argument order and cd do not get a copy past the check."""
        cp = os.path.join(self.E.home, ".cache", "pyc-tmp")
        shutil.copytree(PLUGIN, cp, ignore=shutil.ignore_patterns("tests", "evals", "__pycache__"))
        for c in ['python3 "%s/scripts/rk/rk.py" --project "%s" notebook' % (cp, self.P),
                  "cd %s/scripts/rk && python3 rk.py --project %s notebook" % (cp, self.P),
                  "python3 '%s/scripts/rk/rk.py' notebook --project ." % cp,
                  'python3 "%s/scripts/rk/rk.py" "notebook"' % cp]:
            with self.subTest(c=c):
                self.assertEqual(self.d("Bash", {"command": c, "run_in_background": True}), "deny")
        ok = 'python3 "%s/scripts/rk/rk.py" --project "%s" notebook' % (PLUGIN, self.P)
        self.assertEqual(self.d("Bash", {"command": ok, "run_in_background": True}), "deny")  # v2: the student starts it

    def test_state_home_and_claude_settings_are_denied(self):
        for tool, ti in [("Write", {"file_path": os.path.join(self.E.state, "plugin-root"), "content": "/x"}),
                         ("Edit", {"file_path": os.path.join(self.E.state, "plugin-root.log"), "old_string": "a", "new_string": "b"}),
                         ("Write", {"file_path": os.path.join(self.E.home, ".claude", "settings.json"), "content": "{}"}),
                         ("Write", {"file_path": self.P + "/.claude/settings.local.json", "content": '{"disableAllHooks": true}'}),
                         ("Bash", {"command": "echo /x > ~/.ryukoku-writing/plugin-root"}),
                         ("Bash", {"command": "printf '{\"disableAllHooks\":true}' > .claude/settings.local.json"}),
                         ("Bash", {"command": "cp a.json ~/.claude/settings.json"})]:
            with self.subTest(tool=tool, ti=str(ti)[:60]):
                self.assertEqual(self.d(tool, ti), "deny")

    def test_human_command_with_quotes_is_denied(self):
        for c in ['python3 "%s/scripts/rk/rk.py" "optout"' % PLUGIN, "python3 tools/rk/rk.py 'apply'", "./rk 'setup'"]:
            with self.subTest(c=c):
                self.assertEqual(self.d("Bash", {"command": c}), "deny")


class PassphraseLocation(Base):
    def test_copy_of_the_plugin_does_not_ask_for_the_passphrase(self):
        """plugin-root points at a copy (even an unmodified one with a matching MANIFEST): the human command
        stops before any passphrase prompt, because the code is not where Claude Code last recorded the plugin."""
        cp = os.path.join(self.E.home, ".cache", "pyc-tmp")
        shutil.copytree(PLUGIN, cp, ignore=shutil.ignore_patterns("tests", "evals", "__pycache__"))
        with open(os.path.join(self.E.state, "plugin-root"), "w") as f:
            f.write(cp + "\n")
        rc, out = self.E.tty(["optout"], [PASS], script=os.path.join(cp, "scripts", "rk", "rk.py"))
        self.assertNotEqual(rc, 0)
        self.assertIn("合言葉を求めずに止めた", out)
        self.assertNotIn("合言葉(入力は表示されない)", out)
        self.assertIn(os.path.realpath(cp), out)  # the running code's location is shown
        # the next SessionStart notices the rewritten launcher target, logs it and points it back
        r = self.E.hook("session-start.sh", {"cwd": self.P, "session_id": "s2"})
        self.assertIn("plugin-root", reason(r))
        self.assertTrue(any("plugin-root" in " ".join(d.get("parts") or []) for d in detections(self.E)))
        self.assertEqual(open(os.path.join(self.E.state, "plugin-root")).read().strip(), os.path.realpath(PLUGIN))

    def test_rewriting_plugin_root_during_an_ai_call_is_detected(self):
        r = run_in_window(self.E, 'D=$HOME/.ryukoku-wr; printf /tmp/x > "${D}iting/plugin-root"', "t-root")
        self.assertIn("plugin-root", reason(r))
        self.assertNotEqual(self.E.rk("check", plugin=True).returncode, 0)

    def test_terminal_shows_location_and_version_before_the_passphrase(self):
        self.E.rk("ledger", "add-source", "--doi", "10.1038/s41598-023-41032-5", "--title", "A placeholder title", "--year", "2023")
        rc, out = self.E.tty(["sign", "source", "S001", "--decision", "VERIFIED"], ["y", PASS])
        self.assertIn("動いているコード: %s(版 " % os.path.realpath(PLUGIN), out)
        self.assertLess(out.index("動いているコード"), out.index("合言葉(入力は表示されない)"))


class DetectionLayer(Base):
    def test_rebaseline_inside_the_call_does_not_hide_the_change(self):
        def evil():
            code = ("import sys; sys.path.insert(0, %r)\nfrom rklib import msguard, common\n"
                    "open(%r, 'a').write('AI\\n')\nmsguard._baseline(%r, common.state_dir(%r))\n"
                    % (os.path.join(self.P, "tools", "rk"), self.E.path(MS), self.P, self.P))
            subprocess.run([sys.executable, "-c", code], env=self.E.env(), check=True)
        r = run_in_window(self.E, evil, "t-m15")
        self.assertIn(MS, reason(r))
        # v2: the AI's manuscript write is recorded as provenance even though the shared baseline was rebuilt
        self.assertIn('"actor": "ai"', self.E.read(".ryukoku", "provenance.jsonl"))

    def test_moving_the_marker_away_keeps_the_guard(self):
        cfg = self.E.path(".ryukoku", "config.yml")
        tmp = os.path.join(self.E.base, "config.yml.away")
        run_in_window(self.E, "python3 -c \"import shutil; shutil.move('.ryu'+'koku/config.yml', %r)\"" % tmp, "t-m16a")
        # with the marker gone the folder is still guarded (registered project)
        self.assertEqual(self.d("Write", {"file_path": self.E.path(MS), "content": "AI"}), "deny")
        self.assertEqual(self.d("Bash", {"command": "printf AI >> manuscript/main.md"}), "deny")
        # a variable target is denied too while the settings are gone; a route the hook cannot see is still recorded
        self.assertEqual(self.d("Bash", {"command": 'D=manu; printf AI >> "${D}script/main.md"'}), "deny")
        run_in_window(self.E, "python3 -c \"open('manu'+'script/main.md','a').write('AI')\"", "t-m16b")
        shutil.move(tmp, cfg)
        self.assertTrue(any(".ryukoku/config.yml" in " ".join(d.get("parts") or []) for d in detections(self.E)))
        self.assertIn('"file": "%s"' % MS, self.E.read(".ryukoku", "provenance.jsonl"))

    def test_removing_a_detection_and_rebuilding_the_chain_is_caught(self):
        run_in_window(self.E, "Q=ques; printf '| Q9 | x | y | z |\\n' >> \"research/${Q}tions.md\"", "t-e1")
        from rklib import ailog
        rows = [o for o in ailog_lines(self.E) if o.get("type") != "detection"]
        p = self.E.path(".ryukoku", "ai-use-log.jsonl")
        prev, out = ailog.GENESIS, []
        for o in rows:
            o["prev"] = prev
            line = json.dumps(o, ensure_ascii=False, sort_keys=True)
            out.append(line)
            prev = ailog.line_hash(line)
        open(p, "w", encoding="utf-8").write("\n".join(out) + "\n")
        st = [d for d in os.listdir(os.path.join(self.E.state, "state"))][0]
        json.dump({"lines": len(out), "head": prev}, open(os.path.join(self.E.state, "state", st, "log-head.json"), "w"))
        r = self.E.rk("check", plugin=True)
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("AI 利用記録に無い", r.stdout)

    def test_glob_from_another_folder_is_detected(self):
        other = os.path.join(self.E.base, "elsewhere", "deep")
        os.makedirs(other)
        cmd = "cd ../../the* && printf AI >> manu*/main.md"
        ti = {"command": cmd}
        self.E.pre("Bash", ti, cwd=other, project_dir=other, tuid="t-o5")
        subprocess.run(["bash", "-c", cmd], cwd=other, env=self.E.env(), capture_output=True)
        self.E.post("Bash", ti, cwd=other, project_dir=other, tuid="t-o5")
        self.assertIn('"file": "%s"' % MS, self.E.read(".ryukoku", "provenance.jsonl"))

    def test_declined_ask_leaves_no_window(self):
        """An asked call the student declines (no PostToolUse) must not turn the student's later edit into
        an 'AI change'."""
        self.assertEqual(self.d("Bash", {"command": "python3 -c 'print(1)'"}, tuid="t-ask"), "ask")
        with open(self.E.path(MS), "a", encoding="utf-8") as f:
            f.write("学生が自分で書いた。\n")
        r = run_in_window(self.E, "true", "t-next")
        self.assertEqual(reason(r), "")
        self.assertEqual(detections(self.E), [])

    def test_protected_detection_has_a_diff(self):
        run_in_window(self.E, "D=too; printf '# x\\n' >> \"${D}ls/rk/rklib/check.py\"", "t-p23")
        det = [d for d in detections(self.E) if d.get("what") == "protected"][-1]
        from rklib import msguard
        diffs = msguard.protected_diffs(self.P, det)
        self.assertTrue(any(k == "tools/rk/rklib/check.py" and before and cur and cur != before for k, before, cur in diffs))
        from notebook.server import App
        v = App(self.P, 0).view("change", det["id"])
        self.assertTrue(any(ln.startswith("+# x") for ln in v["diff"]))


# ------------------------------------------------------------ every tool goes through the hooks
class EveryTool(Base):
    def test_matcher_is_every_tool(self):
        hj = json.load(open(os.path.join(PLUGIN, "hooks", "hooks.json")))
        self.assertEqual(hj["hooks"]["PreToolUse"][0]["matcher"], "*")
        self.assertEqual(hj["hooks"]["PostToolUse"][0]["matcher"], "*")

    def test_monitor_powershell_and_unknown_tools(self):
        self.assertEqual(self.d("Monitor", {"command": "printf AI >> manuscript/main.md", "description": "x", "timeout_ms": 1000}), "deny")
        self.assertEqual(self.d("Monitor", {"command": "tail -f research/plan.md", "description": "x", "timeout_ms": 1000}), "ask")
        self.assertEqual(self.d("PowerShell", {"command": "Set-Content -Path manuscript/main.md -Value AI"}), "deny")
        self.assertEqual(self.d("PowerShell", {"command": "Add-Content .ryukoku/signoffs.jsonl x"}), "deny")
        # an unknown tool opens a window: a change it makes is detected
        r = run_in_window(self.E, "printf AI >> manuscript/main.md", "t-mcp", tool="mcp__fs__write_file", ti={"path": "x"})
        self.assertIn(MS, reason(r))


# ------------------------------------------------------------ Claude Code settings
class ClaudeCodeSettings(Base):
    def test_disable_all_hooks_and_disabled_plugin_fail_the_check(self):
        os.makedirs(self.E.path(".claude"), exist_ok=True)
        json.dump({"disableAllHooks": True}, open(self.E.path(".claude", "settings.local.json"), "w"))
        r = self.E.rk("check", plugin=True)
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("disableAllHooks", r.stdout)
        os.remove(self.E.path(".claude", "settings.local.json"))
        os.makedirs(os.path.join(self.E.home, ".claude"), exist_ok=True)
        json.dump({"enabledPlugins": {"ryukoku-writing@student-plugins": False}},
                  open(os.path.join(self.E.home, ".claude", "settings.json"), "w"))
        r = self.E.rk("check", plugin=True)
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("ryukoku-writing@student-plugins", r.stdout)
        # SessionStart tells the student
        self.assertIn("disableAllHooks / enabledPlugins", reason(self.E.hook("session-start.sh", {"cwd": self.P})))

    def test_settings_written_during_an_ai_call_are_blocked(self):
        # since the allow-list, a Bash redirect into .claude/ is denied up front; the write
        # never happens, so there is nothing to detect afterwards
        self.assertEqual(decision(self.E.pre("Bash", {"command": "printf '{\"disableAllHooks\":true}' > .cl''aude/settings.local.json"})), "deny")


# ------------------------------------------------------------ CI trust root
@unittest.skipUnless(shutil.which("git"), "git not installed")
class TrustRoot(unittest.TestCase):
    def setUp(self):
        self.E = Env()
        self.E.setup(git="g")
        self.P = self.E.proj

    def tearDown(self):
        self.E.cleanup()

    def git(self, *a):
        return subprocess.run(["git", "-C", self.P] + list(a), capture_output=True, text=True, env=self.E.env())

    def test_signer_pushed_to_main_without_endorsement_is_not_trusted(self):
        code = ("import sys; sys.path.insert(0, %r)\nfrom rklib import sign\n"
                "sign.register(%r, 'student', 'student', 'evil passphrase from a script 77')\n" % (os.path.join(PLUGIN, "scripts", "rk"), self.P))
        subprocess.run([sys.executable, "-c", code], env=self.E.env(), check=True)
        self.git("add", ".ryukoku/signers.json")
        self.git("commit", "-q", "--no-verify", "-m", "chore: tidy")
        r = self.E.rk("check", "--ci", "--stage", "pr", "--base-ref", "main", plugin=True)
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("最初の署名者からの承認", r.stdout)

    def test_pre_push_has_no_environment_bypass(self):
        hook = self.E.path(".githooks", "pre-push")
        self.assertNotIn("RK_ALLOW_MAIN", open(hook).read())
        r = subprocess.run(["setsid", "bash", hook] if shutil.which("setsid") else ["bash", hook],
                           input="refs/heads/main a refs/heads/main b\n", capture_output=True, text=True,
                           cwd=self.P, env=dict(self.E.env(), RK_ALLOW_MAIN="1"))
        self.assertNotEqual(r.returncode, 0)

    def test_tools_or_ci_changes_need_a_human_confirmation(self):
        p = self.E.path(".github", "workflows", "check.yml")
        open(p, "a").write("# changed\n")
        r = self.E.rk("check", plugin=True)
        self.assertNotEqual(r.returncode, 0)
        self.assertIn(".github/workflows/check.yml", r.stdout)
        rc, out = self.E.tty(["sign", "guarded", "tools", "--decision", "confirmed"], ["y", PASS])
        self.assertEqual(rc, 0, out[-1500:])
        r = self.E.rk("check", plugin=True)
        self.assertNotIn(".github/workflows/check.yml", "\n".join(l for l in r.stdout.splitlines() if l.startswith("NG")))


# ------------------------------------------------------------ Windows launchers and Python discovery
class Portability(unittest.TestCase):
    def test_launchers(self):
        cmd = open(os.path.join(PLUGIN, "scripts", "rk", "launchers", "rk.cmd")).read()
        self.assertNotIn("%ERRORLEVEL%", cmd)  # expanded when the block is read
        self.assertIn("exit /b", cmd)
        self.assertIn("py -3", cmd)
        ps = open(os.path.join(PLUGIN, "scripts", "rk", "launchers", "rk.ps1")).read()
        self.assertIn("if ($root)", ps)  # no Join-Path with an empty root
        sh = open(os.path.join(PLUGIN, "scripts", "rk", "launchers", "rk")).read()
        self.assertIn("py -3", sh)

    def test_hooks_find_a_python_that_really_runs(self):
        E = Env(init=False)
        try:
            b = os.path.join(E.base, "bin")
            os.makedirs(b)
            with open(os.path.join(b, "python3"), "w") as f:
                f.write("#!/bin/sh\nexit 9009\n")  # like the Windows store stub: exists, does not run
            os.chmod(os.path.join(b, "python3"), 0o755)
            os.symlink(sys.executable, os.path.join(b, "python"))
            r = subprocess.run(["bash", "-c", '. "%s"; have_python && echo "$RK_PY"' % os.path.join(PLUGIN, "scripts", "hooks", "lib.sh")],
                               capture_output=True, text=True, env=dict(os.environ, PATH=b + os.pathsep + "/usr/bin:/bin"))
            self.assertEqual(r.stdout.strip(), "python")
        finally:
            E.cleanup()

    def test_init_writes_a_windows_path_under_git_bash(self):
        E = Env(init=False)
        try:
            b = os.path.join(E.base, "bin")
            os.makedirs(b)
            for name, body in (("uname", "echo MINGW64_NT-10.0"), ("cygpath", "echo 'C:\\Users\\s\\plugin'")):
                with open(os.path.join(b, name), "w") as f:
                    f.write("#!/bin/sh\n%s\n" % body)
                os.chmod(os.path.join(b, name), 0o755)
            r = E.run(["bash", os.path.join(PLUGIN, "scripts", "init-project.sh"), "--dir", E.proj],
                      extra={"PATH": b + os.pathsep + os.environ.get("PATH", "")})
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertEqual(open(os.path.join(E.state, "plugin-root")).read().strip(), "C:\\Users\\s\\plugin")
        finally:
            E.cleanup()


# ------------------------------------------------------------ comment channels and append-only logs
class CommentsAndLogs(Base):
    def _api(self, app_srv, method, path, body=None):
        import http.client
        port = app_srv.server_address[1]
        c = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
        c.request(method, path, body=json.dumps(body) if body is not None else None,
                  headers={"Content-Type": "application/json", "X-RK-Request": "1", "Host": "127.0.0.1:%d" % port,
                           "X-RK-Session": app_srv.app.session})
        r = c.getresponse()
        return r.status, json.loads(r.read() or b"{}")

    def test_channel_is_recorded_and_deleted_comments_fail_the_check(self):
        import threading
        from notebook.server import make_server
        self.E.write(MS, "# はじめに\n\n要因 A がある。\n")
        srv = make_server(self.P, 0)
        th = threading.Thread(target=srv.serve_forever, daemon=True)
        th.start()
        try:
            code, a = self._api(srv, "POST", "/api/annotations", {"doc": MS, "quote": "要因 A", "code": "W1", "comment": "根拠は?",
                                                                    "actor": "student"})
            self.assertEqual(code, 201, a)
            self.assertEqual(a["review"]["channel"], "notebook")  # shown as typed on the screen, not signed
        finally:
            srv.shutdown()
        from rklib import subjects
        c = [s for s in subjects.comments(self.P)][0]
        self.assertEqual(c.content["channel"], "notebook")
        r = self.E.rk("annot", "flag", "--doc", MS, "--quote", "要因 A", "--code", "W1", "--comment", "どの資料で確かめた?")
        self.assertEqual(r.returncode, 0, r.stderr)
        data = json.load(open(self.E.path("review", "annotations.json")))
        self.assertTrue(any((x["review"].get("channel") == "agent-cli" and x["creator"]["name"] == "agent") for x in data["items"]))
        # a script deletes the open comments
        data["items"] = []
        json.dump(data, open(self.E.path("review", "annotations.json"), "w"))
        r = self.E.rk("check")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("annotations-log.jsonl", r.stdout)

    def test_search_log_and_references_are_watched(self):
        self.E.write("research/search-log.jsonl", '{"id": "S001"}\n')
        json.dump([{"id": "walters2023", "author": [{"family": "Walters"}], "issued": {"date-parts": [[2023]]}}],
                  open(self.E.path("sources", "references.json"), "w"))
        run_in_window(self.E, "true", "t-base")
        # the shell form is denied up front (the lexer reads search-lo''g.jsonl as search-log.jsonl) ...
        self.assertEqual(self.d("Bash", {"command": ": > research/search-lo''g.jsonl"}), "deny")
        # ... and a route the hook cannot see is detected
        r = run_in_window(self.E, "Q=search-lo; python3 -c \"open('research/'+'$Q'+'g.jsonl','w').close()\"", "t-sl")
        self.assertIn("search-log.jsonl", reason(r))
        # (after that detection the settings are not trusted until the student decides, so a recognised shell write
        # to references.json is now denied up front; a route the hook cannot see is still detected)
        r = run_in_window(self.E, "python3 -c \"p='sources/'+'references.json'; t=open(p).read().replace('Walters','Other'); open(p,'w').write(t)\"", "t-ref")
        self.assertIn("references.json", reason(r))


# ------------------------------------------------------------ batch signing
class BatchSigning(Base):
    def _proposal(self, pid, old, new, kind="format"):
        from rklib import proposals
        text = open(self.E.path(MS), encoding="utf-8").read()
        meta = {"id": pid, "status": "pending", "kind": kind, "target": MS, "base_sha256": proposals.sha256_bytes(text.encode()),
                "created": "x", "by": "ai", "model": "m", "why": "句読点"}
        lines = text.split("\n")
        i = lines.index(old)
        h = {"old_start": i + 1, "old": [old], "new": [new], "before": lines[max(0, i - 1):i], "after": lines[i + 1:i + 2], "note": ""}
        self.E.write("proposals/%s-format-main.diff" % pid, proposals.render(meta, [h]))

    def test_partial_failure_reports_each_item_and_retry_does_not_stop(self):
        from rklib import decide, subjects
        self.E.write(MS, "# はじめに\n\n要因 A，要因 B．\n\nもう一つ．\n")
        self._proposal("P0001", "要因 A，要因 B．", "要因 A、要因 B．")
        self._proposal("P0002", "要因 A，要因 B．", "要因 A，要因 B。")  # the same line: conflicts with P0001
        self._proposal("P0003", "もう一つ．", "もう一つ。")
        items = [{"kind": "hunk", "id": s.sid, "decision": "accepted", "digest": s.digest} for s in subjects.hunks(self.P)]
        res = []
        recs = decide.sign_batch(self.P, items, PASS, "tty", results=res)
        st = {r["id"]: r["status"] for r in res}
        self.assertEqual(st, {"P0001#1": "signed", "P0002#1": "skipped", "P0003#1": "signed"})
        self.assertEqual(len(recs), 2)
        self.assertIn("同じ行", [r for r in res if r["id"] == "P0002#1"][0]["reason"])
        res2 = []
        decide.sign_batch(self.P, items[:1] + items[2:], PASS, "tty", results=res2)  # retrying signed items: skipped, no error
        self.assertTrue(all(r["status"] == "skipped" for r in res2))

    def test_section_signed_in_the_same_batch_as_a_hunk_is_skipped(self):
        from rklib import decide, subjects
        self.E.write(MS, "# はじめに\n\n要因 A，要因 B．\n")
        self._proposal("P0001", "要因 A，要因 B．", "要因 A、要因 B。")
        h = subjects.hunks(self.P)[0]
        sec = [s for s in subjects.sections(self.P) if s.sid == MS][0]
        res = []
        decide.sign_batch(self.P, [{"kind": "hunk", "id": h.sid, "decision": "accepted", "digest": h.digest},
                                   {"kind": "section", "id": sec.sid, "decision": "reviewed", "digest": sec.digest}], PASS, results=res)
        st = {r["id"]: r["status"] for r in res}
        self.assertEqual(st[h.sid], "signed")
        self.assertEqual(st[MS], "skipped")

    def test_stale_hunk_can_only_be_rejected(self):
        from rklib import subjects
        self.E.write(MS, "# はじめに\n\n要因 A，要因 B．\n")
        self._proposal("P0001", "要因 A，要因 B．", "要因 A、要因 B。")
        self.E.write(MS, "# はじめに\n\n学生が書き直した。\n")
        h = subjects.hunks(self.P)[0]
        self.assertTrue(h.content["stale"])
        from notebook.server import App
        self.assertEqual(App(self.P, 0).view("hunk", h.sid)["decisions"], ["rejected"])


# ------------------------------------------------------------ smaller cases
class Misc(Base):
    def test_prohibited_course_allows_reading_but_not_writing(self):
        # v2: a prohibited course still allows verification and format checks, which need reading; writing the
        # manuscript, drafting claim cards and proposals are denied
        from rklib.common import set_config_value
        set_config_value(self.P, "ai_policy", "prohibited")
        for tool, ti in [("Grep", {"pattern": "要因"}), ("Glob", {"pattern": "**/*.md"}), ("Read", {"file_path": self.E.path("research", "plan.md")})]:
            with self.subTest(tool=tool, ti=str(ti)):
                self.assertEqual(self.d(tool, ti), "-")
        self.assertEqual(self.d("Bash", {"command": "grep -r 要因 ."}), "-")
        self.assertEqual(self.d("Bash", {"command": "python3 -c 'print(open(\"manuscript/main.md\").read())'"}), "deny")  # inline code naming the manuscript
        self.assertEqual(self.d("Bash", {"command": "python3 tools/rk/rk.py check"}), "-")
        self.assertEqual(self.d("Write", {"file_path": self.E.path("manuscript", "main.md"), "content": "x"}), "deny")
        self.assertEqual(self.d("Write", {"file_path": self.E.path("claims", "C001.md"), "content": "x"}), "deny")
        self.assertEqual(self.d("Bash", {"command": "python3 tools/rk/rk.py propose start manuscript/main.md"}), "deny")
        self.assertEqual(self.d("Bash", {"command": "python3 tools/rk/rk.py claims new --words x"}), "deny")

    def test_pandoc_export_is_not_a_manuscript_write(self):
        # not a manuscript write (no deny); pandoc is not on the allow-list (Lua filters run code), so it asks
        self.assertEqual(self.d("Bash", {"command": "pandoc manuscript/main.md -o build/x.docx"}), "ask")
        self.assertEqual(self.d("Bash", {"command": "pandoc build/x.md -o manuscript/main.md"}), "deny")

    def test_phone_formats_and_address_mask(self):
        for t in ["電話は (075)000-0000 です", "連絡先 090.0000.0000"]:
            with self.subTest(t=t):
                self.assertEqual(decision(self.E.prompt(t)), "block")
        r = reason(self.E.prompt("住所は架空県架空市架空町1丁目2番3号です"))
        self.assertNotIn("架空市", r)

    def test_passphrase_alone_is_stopped(self):
        self.assertEqual(decision(self.E.prompt(PASS)), "block")
        self.assertEqual(decision(self.E.prompt("ｃｏｒｒｅｃｔ ｈｏｒｓｅ ｂａｔｔｅｒｙ ４２")), "block")  # full-width form
        self.assertEqual(decision(self.E.prompt("この段落の論証の弱いところを教えて")), "-")

    def test_more_ghostwrite_and_rq_requests_get_the_reason(self):
        for t in ["この段落をもっと学術的にしてもらえますか", "おわりにを考えるのを手伝って、文案を3つ出して",
                  "Give me a better version of this sentence", "Can you rewrite this so it flows?",
                  "Fill in the gaps in my reasoning", "Help me expand this into 500 words"]:
            with self.subTest(t=t):
                self.assertIn("代筆", reason(self.E.prompt(t)))
        for t in ["結論はどうすればいい？", "何について書けばよいか教えて", "テーマのアイデアある？", "この結果から言えることを教えて"]:
            with self.subTest(t=t):
                self.assertIn("テーマ・RQ", reason(self.E.prompt(t)))
        for t in ["J-STAGE の検索式の書き方を教えて", "この文献の DOI を確認して", "締切までの予定を整理したい"]:
            with self.subTest(t=t):
                self.assertNotIn("代筆", reason(self.E.prompt(t)))
                self.assertNotIn("テーマ・RQ", reason(self.E.prompt(t)))

    def test_disclosure_suggestion_states_only_facts(self):
        from rklib import disclosure
        import collections
        day = {"cats": collections.Counter({"research": 1}), "flags": collections.Counter({"ghostwrite": 2})}
        s = disclosure.suggested_summary(day, "ja")
        self.assertNotIn("断り", s)
        self.assertIn("記録していない", s)
        src = open(os.path.join(PLUGIN, "scripts", "rk", "rklib", "human.py"), encoding="utf-8").read()
        self.assertNotIn("[a]案のまま確認", src)

    def test_expired_search_cache_is_removed_at_session_start(self):
        d = self.E.path(".ryukoku", "cache", "search")
        os.makedirs(d, exist_ok=True)
        p = os.path.join(d, "old.json")
        open(p, "w").write("{}")
        os.utime(p, (1, 1))
        self.E.hook("session-start.sh", {"cwd": self.P})
        self.assertFalse(os.path.exists(p))

    def test_machine_commands_follow_english(self):
        E = Env(lang="en")
        try:
            r = E.rk("status")
            self.assertIn("undecided proposal hunks", r.stdout)
            r = E.rk("propose", "start", MS)
            self.assertIn("Edit this copy", r.stdout)
            self.assertIn("phone number", reason(E.prompt("call 090-0000-0000")))
        finally:
            E.cleanup()

    def test_pdf_without_lualatex_gives_guidance(self):
        if shutil.which("lualatex") or not shutil.which("pandoc"):
            self.skipTest("lualatex present or pandoc missing")
        r = self.E.rk("export", "pdf")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("collection-langjapanese", r.stderr)

    def test_skill_does_not_let_the_ai_enter_pages(self):
        sk = open(os.path.join(PLUGIN, "skills", "verify-sources", "SKILL.md"), encoding="utf-8").read()
        self.assertNotIn('--locator "p.', sk)

    def test_weak_passphrases_are_refused(self):
        from rklib import sign
        for p in ("aaaaaaaaaaaa", "1234567890", "password12345"):
            self.assertTrue(sign.weak_reason(p))
        self.assertEqual(sign.weak_reason(PASS), "")


@unittest.skipUnless(shutil.which("git"), "git not installed")
class GitIdentity(unittest.TestCase):
    def test_setup_asks_for_a_name_and_email_when_git_has_none(self):
        E = Env()
        try:
            base_env = E.env

            def env(extra=None):
                e = base_env(extra)
                for k in ("GIT_AUTHOR_NAME", "GIT_AUTHOR_EMAIL", "GIT_COMMITTER_NAME", "GIT_COMMITTER_EMAIL"):
                    e.pop(k, None)
                e["GIT_CONFIG_GLOBAL"] = os.path.join(E.base, "no-gitconfig")
                return e
            E.env = env
            answers = ["", "", "a", "", "", "y", "y", PASS, PASS, "g", "student-x", "s@example.test"]
            rc, out = E.tty(["setup"], answers)
            self.assertEqual(rc, 0, out[-2000:])
            r = subprocess.run(["git", "-C", E.proj, "log", "--format=%an <%ae>"], capture_output=True, text=True, env=env())
            self.assertIn("student-x <s@example.test>", r.stdout)
        finally:
            E.cleanup()


if __name__ == "__main__":
    unittest.main()
