"""Test helpers: temporary projects with their own HOME and state folder, the hook runner, the "AI tool call"
reproduction (PreToolUse -> run if allowed -> PostToolUse), and a
pseudo-terminal driver that plays the student at the terminal (tests only; the plugin itself never does this and
the hooks deny pty use by the AI).
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile

sys.dont_write_bytecode = True
PLUGIN = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Code that the tests call inside this process (decide, msguard, the notebook App, ...) must never touch the real
# home: a per-run temporary HOME and state folder (a test left an empty ~/.ryukoku-writing/state/<id>/ behind once).
_TEST_HOME = tempfile.mkdtemp(prefix="rkw-testhome-")
os.environ["HOME"] = _TEST_HOME
os.environ["RK_STATE_HOME"] = os.path.join(_TEST_HOME, ".ryukoku-writing")
import atexit  # noqa: E402
atexit.register(lambda: shutil.rmtree(_TEST_HOME, ignore_errors=True))
HOOKS = os.path.join(PLUGIN, "scripts", "hooks")
RKPY = os.path.join(PLUGIN, "scripts", "rk", "rk.py")
PASS = "correct horse battery 42"


class Env(object):
    """A sandbox: BASE/home is HOME, BASE/home/.ryukoku-writing the state folder, BASE/thesis the project."""

    def __init__(self, lang="ja", init=True, name="thesis"):
        self.base = tempfile.mkdtemp(prefix="rkw-test-")
        self.home = os.path.join(self.base, "home")
        os.makedirs(self.home)
        self.state = os.path.join(self.home, ".ryukoku-writing")
        self.proj = os.path.join(self.base, name)
        if init:
            r = self.run(["bash", os.path.join(PLUGIN, "scripts", "init-project.sh"), "--dir", self.proj, "--lang", lang])
            if r.returncode != 0:
                raise RuntimeError(r.stderr + r.stdout)

    def env(self, extra=None):
        e = dict(os.environ, HOME=self.home, RK_STATE_HOME=self.state, NO_COLOR="1", PYTHONDONTWRITEBYTECODE="1",
                 CLAUDE_PLUGIN_ROOT=PLUGIN, LC_ALL="C.UTF-8", GIT_AUTHOR_NAME="student", GIT_AUTHOR_EMAIL="student@example.test",
                 GIT_COMMITTER_NAME="student", GIT_COMMITTER_EMAIL="student@example.test", GIT_CONFIG_NOSYSTEM="1")
        e.pop("CLAUDE_PROJECT_DIR", None)
        if extra:
            e.update(extra)
        return e

    def run(self, argv, cwd=None, extra=None, timeout=180, input_text=None):
        return subprocess.run(argv, capture_output=True, text=True, cwd=cwd or self.base, env=self.env(extra), timeout=timeout,
                              input=input_text)

    def rk(self, *args, plugin=False, extra=None):
        """Machine command: the project copy (as the AI runs it) unless PLUGIN is true."""
        script = RKPY if plugin else os.path.join(self.proj, "tools", "rk", "rk.py")
        return self.run([sys.executable, "-B", script, "--project", self.proj] + list(args), cwd=self.proj, extra=extra)

    def hook(self, script, payload, project_dir=None, raw=None, cwd=None):
        data = raw if raw is not None else json.dumps(payload, ensure_ascii=False)
        extra = {"CLAUDE_PROJECT_DIR": project_dir or self.proj}
        run_cwd = cwd or project_dir or self.proj
        if not os.path.isdir(run_cwd):  # a Windows-style cwd in the JSON: run from a real folder
            run_cwd = project_dir if project_dir and os.path.isdir(project_dir) else self.base
        return subprocess.run(["bash", os.path.join(HOOKS, script)], input=data.encode("utf-8"), capture_output=True,
                              cwd=run_cwd, env=self.env(extra), timeout=90)

    def pre(self, tool, tool_input, cwd=None, project_dir=None, tuid="t1"):
        c = cwd or project_dir or self.proj
        return self.hook("pre-guard.sh", {"hook_event_name": "PreToolUse", "cwd": c, "tool_name": tool, "tool_input": tool_input,
                                          "session_id": "t", "tool_use_id": tuid}, project_dir=project_dir, cwd=c)

    def post(self, tool, tool_input, cwd=None, project_dir=None, tuid="t1"):
        c = cwd or project_dir or self.proj
        return self.hook("post-log.sh", {"hook_event_name": "PostToolUse", "cwd": c, "tool_name": tool, "tool_input": tool_input,
                                         "tool_response": {}, "session_id": "t", "tool_use_id": tuid}, project_dir=project_dir, cwd=c)

    def prompt(self, text, project_dir=None):
        return self.hook("prompt-guard.sh", {"hook_event_name": "UserPromptSubmit", "cwd": project_dir or self.proj,
                                             "prompt": text, "session_id": "t"}, project_dir=project_dir)

    def ai_bash(self, cmd, cwd=None, tuid="b1", background=False, allow_ask=False):
        """PreToolUse -> run when not denied/asked -> PostToolUse, like an AI Bash call. Returns (decision, post_ctx).
        ALLOW_ASK: an "ask" is treated as the student pressing allow (the call runs inside its window)."""
        c = cwd or self.proj
        ti = {"command": cmd}
        r = self.pre("Bash", ti, cwd=c, tuid=tuid)
        d = decision(r)
        if d == "deny" or (d == "ask" and not allow_ask):
            return d, ""
        p = subprocess.Popen(["bash", "-c", cmd], cwd=c, env=self.env(), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        p.wait(timeout=120)
        rp = self.post("Bash", ti, cwd=c, tuid=tuid)
        return d, reason(rp)

    def ai_write(self, path, content, tuid="w1"):
        r = self.pre("Write", {"file_path": path, "content": content}, tuid=tuid)
        d = decision(r)
        if d in ("deny", "ask"):
            return d
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)
        self.post("Write", {"file_path": path, "content": content}, tuid=tuid)
        return d

    def cleanup(self):
        shutil.rmtree(self.base, ignore_errors=True)

    def path(self, *p):
        return os.path.join(self.proj, *p)

    def read(self, *p):
        with open(self.path(*p), encoding="utf-8") as f:
            return f.read()

    def write(self, rel, text):
        p = self.path(rel)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "w", encoding="utf-8") as f:
            f.write(text)

    # --------------------------------------------------------------- the student at a terminal
    def tty(self, args, answers, timeout=120, script=None):
        return rk_tty(self, args, answers, timeout, script)

    def setup(self, policy="a", optout="y", git="n", passphrase=PASS):
        answers = ["", passphrase, passphrase, "", policy] + (["research,verify"] if policy == "l" else []) + ["", ""] + [optout]
        if optout == "y" or True:
            answers += [passphrase]
        answers += [git]
        rc, out = self.tty(["setup"], answers)
        if rc != 0:
            raise RuntimeError(out[-3000:])
        return out


def decision(r):
    out = r.stdout.decode("utf-8") if isinstance(r.stdout, bytes) else r.stdout
    out = out.strip()
    if not out:
        return "-"
    j = json.loads(out.splitlines()[-1])
    h = j.get("hookSpecificOutput", {})
    if "permissionDecision" in h:
        return h["permissionDecision"]
    if j.get("decision") == "block":
        return "block"
    if "additionalContext" in h:
        return "ctx"
    return "?"


def reason(r):
    out = r.stdout.decode("utf-8") if isinstance(r.stdout, bytes) else r.stdout
    out = out.strip()
    if not out:
        return ""
    j = json.loads(out.splitlines()[-1])
    h = j.get("hookSpecificOutput", {})
    return h.get("permissionDecisionReason") or h.get("additionalContext") or j.get("reason", "")


def rk_tty(env, args, answers, timeout=120, script=None):
    """Run ./rk ARGS (the installed plugin's code, as the launcher does) on a pseudo-terminal and answer prompts in
    order. A prompt is recognised when the output ends with '>', ':', '?' or '：'. Returns (exit code, transcript)."""
    import pty
    import select
    import time
    e = env.env()
    pid, fd = pty.fork()
    if pid == 0:
        os.chdir(env.proj)
        argv = [sys.executable, "-I", "-B", script or RKPY, "--project", env.proj] + list(args)
        os.execve(sys.executable, argv, e)
    buf = b""
    queue = list(answers)
    t0 = time.time()
    status = None
    last_pos = 0
    last_ans = ""
    while True:
        if time.time() - t0 > timeout:
            os.kill(pid, 9)
            raise TimeoutError(buf.decode("utf-8", "replace")[-3000:])
        r, _, _ = select.select([fd], [], [], 0.15)
        if r:
            try:
                chunk = os.read(fd, 65536)
            except OSError:
                chunk = b""
            if not chunk:
                break
            buf += chunk
            continue
        tail = buf[last_pos:].decode("utf-8", "replace").strip()
        if last_ans and tail.startswith(last_ans):
            tail = tail[len(last_ans):].strip()  # the terminal's echo of our own answer
        if queue and tail and (tail.endswith(">") or tail.endswith(":") or tail.endswith("?") or tail.endswith("：")):
            ans = queue.pop(0)
            last_pos = len(buf)
            last_ans = ans
            os.write(fd, (ans + "\n").encode("utf-8"))
            continue
        done, st = os.waitpid(pid, os.WNOHANG)
        if done:
            status = st
            try:
                while True:
                    r, _, _ = select.select([fd], [], [], 0.1)
                    if not r:
                        break
                    chunk = os.read(fd, 65536)
                    if not chunk:
                        break
                    buf += chunk
            except OSError:
                pass
            break
    if status is None:
        _, status = os.waitpid(pid, 0)
    code = os.waitstatus_to_exitcode(status) if hasattr(os, "waitstatus_to_exitcode") else status >> 8
    return code, buf.decode("utf-8", "replace")
