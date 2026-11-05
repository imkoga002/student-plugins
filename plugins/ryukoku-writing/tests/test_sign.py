"""VERIFIED and the final pre-submission confirmation exist only as passphrase signatures by a trusted signer,
locally and in CI; the other human states are light confirmations that an AI cannot add during its tool calls.
Forgeries are made the way an AI tool call would make them (a script file, then `python3 scratch/f.py`), never by
editing the plugin. CI is reproduced as the workflow runs it: the base branch's tools from a separate worktree."""
import json
import os
import random
import shutil
import subprocess
import sys
import unittest

from helpers import PASS, PLUGIN, RKPY, Env, decision

sys.path.insert(0, os.path.join(PLUGIN, "scripts", "rk"))
from rklib import ed25519 as ED  # noqa: E402

RK = os.path.join(PLUGIN, "scripts", "rk")


def forge_script(body):
    return "import sys\nsys.path.insert(0, %r)\n%s\n" % (RK, body)


class Ed25519(unittest.TestCase):
    def test_rfc8032_vectors(self):
        sk = bytes.fromhex("9d61b19deffd5a60ba844af492ec2cc44449c5697b326919703bac031cae7f60")
        self.assertEqual(ED.public_key(sk).hex(), "d75a980182b10ab7d54bfed3c964073a0ee172f3daa62325af021a68f707511a")
        self.assertEqual(ED.sign(sk, b"").hex(), "e5564300c360ac729086e2cc806e828a84877f1eb8e5d974d873e065224901555fb8821590a33bacc61e39701cf9b46bd25bf5f0595bbe24655141438e7a100b")
        sk2 = bytes.fromhex("4ccd089b28ff96da9db6c346ec114e0f5b8a319f35aba624da8cf6ed4fb8a6fb")
        self.assertEqual(ED.public_key(sk2).hex(), "3d4017c3e843895a92b70aa74d1b7ebc9c982ccf2ec4968cc0cd55f12af4660c")
        sig = ED.sign(sk2, bytes([0x72]))
        self.assertEqual(sig.hex(), "92a009a9f0d4cab8720e820b5f642540a2b27b5416503f8fb3762223ebdb69da085ac1e43e15996e458f3613d0f11d8c387b2eaeb4302aeeb00d291612bb0c00")
        self.assertTrue(ED.verify(ED.public_key(sk2), bytes([0x72]), sig))
        self.assertFalse(ED.verify(ED.public_key(sk2), bytes([0x73]), sig))

    def test_cross_check_with_cryptography(self):
        try:
            from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
            from cryptography.hazmat.primitives import serialization
        except ImportError:
            self.skipTest("cryptography not installed")
        rnd = random.Random(7)
        for _ in range(20):
            sk = bytes(rnd.getrandbits(8) for _ in range(32))
            msg = bytes(rnd.getrandbits(8) for _ in range(rnd.randint(0, 200)))
            k = Ed25519PrivateKey.from_private_bytes(sk)
            pub = k.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
            self.assertEqual(ED.public_key(sk), pub)
            self.assertEqual(ED.sign(sk, msg), k.sign(msg))
            self.assertTrue(ED.verify(pub, msg, k.sign(msg)))
            self.assertFalse(ED.verify(pub, msg + b"x", k.sign(msg)))


class Forgery(unittest.TestCase):
    def setUp(self):
        self.E = Env()
        self.E.setup()
        r = self.E.rk("ledger", "add-source", "--doi", "10.1038/s41598-023-41032-5", "--title", "A placeholder title", "--year", "2023")
        self.assertEqual(r.returncode, 0, r.stderr)
        r = self.E.rk("ledger", "add-claim", "--claim", "現象 X は要因 A と関係する(見本)", "--source-id", "S001", "--locator", "p. 3")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.E.post("Bash", {"command": "true"}, tuid="init")

    def tearDown(self):
        self.E.cleanup()

    def run_script(self, body, tuid):
        self.assertEqual(self.E.ai_write(self.E.path("scratch", "f.py"), forge_script(body), tuid=tuid + "w"), "-")
        d, _ = self.E.ai_bash("python3 scratch/f.py", tuid=tuid, allow_ask=True)
        self.assertEqual(d, "ask")  # the student is asked first; here they allow it

    def test_scripted_verified_fails(self):
        self.run_script("from rklib import ledger\np=ledger.paths('.')[1]\nrows=ledger.read(p,ledger.CLAIMS)\n"
                        "rows[0]['human_status']='VERIFIED'\nledger.write(p,rows,ledger.CLAIMS)", "b1")
        r = self.E.rk("check")
        self.assertEqual(r.returncode, 1)
        self.assertIn("人間の署名がない", r.stdout)

    def test_scripted_new_signer_is_not_trusted(self):
        body = ("from rklib import sign, subjects\n"
                "s, sec = sign.register('.', 'student', 'student', 'ai-made-passphrase-123', iterations=100000)\n"
                "subj = subjects.find('.', 'claim', 'C001')\n"
                "rec = sign.make_record(s, sec, 'claim', 'C001', 'VERIFIED', subj.digest)\n"
                "sign.append_signoffs('.', [rec])\n"
                "from rklib import ledger\np=ledger.paths('.')[1]\nrows=ledger.read(p,ledger.CLAIMS)\n"
                "rows[0]['human_status']='VERIFIED'\nrows[0]['human_record']=rec['id']\nledger.write(p,rows,ledger.CLAIMS)")
        self.run_script(body, "b2")
        r = self.E.rk("check")
        self.assertEqual(r.returncode, 1)
        self.assertIn("未承認の署名者の追加", r.stdout)
        self.assertIn("unknown signer key", r.stdout)

    def test_signed_then_edited_is_stale(self):
        rc, out = self.E.tty(["verify"], ["v", "", "v", "", PASS])
        self.assertEqual(rc, 0, out[-1500:])
        r = self.E.rk("check")
        self.assertEqual(r.returncode, 0, r.stdout)
        self.assertIn("記録で裏づけられた人間の判断: 2 件", r.stdout)
        p = self.E.path("sources", "claims.csv")
        s = open(p, encoding="utf-8").read().replace("p. 3", "p. 4")
        with open(p, "w", encoding="utf-8") as f:
            f.write(s)
        r = self.E.rk("check")
        self.assertEqual(r.returncode, 1)
        self.assertIn("記録の後に内容が変わった", r.stdout)

    def test_no_secret_on_disk(self):
        rc, out = self.E.tty(["verify"], ["v", "", "v", "", PASS])
        self.assertEqual(rc, 0)
        hits = []
        for root in (self.E.home, self.E.proj):
            for dp, _dns, fns in os.walk(root):
                for fn in fns:
                    p = os.path.join(dp, fn)
                    try:
                        data = open(p, "rb").read()
                    except OSError:
                        continue
                    if PASS.encode() in data or fn.endswith((".key", ".pem")):
                        hits.append(p)
        self.assertEqual(hits, [])
        signers = json.loads(self.E.read(".ryukoku", "signers.json"))["signers"]
        self.assertEqual(set(signers[0]) - {"endorsed_by", "endorse_sig"},
                         {"key", "name", "role", "pub", "kdf", "added", "status", "self_sig"})

    def test_no_terminal_no_signature(self):
        r = self.E.run([sys.executable, "-B", RKPY, "--project", self.E.proj, "sign", "claim", "C001", "--decision", "VERIFIED"],
                       cwd=self.E.proj, input_text=PASS + "\ny\n")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("端末", r.stderr + r.stdout)
        self.assertEqual(self.E.read(".ryukoku", "signoffs.jsonl").count('"kind": "claim"'), 0)

    def test_new_passphrase_and_revocation(self):
        new = "a new passphrase 2026"
        # leaked: hand over with the current passphrase, then revoke
        rc, out = self.E.tty(["verify"], ["v", "", "s", PASS])  # a VERIFIED signed with the current passphrase
        self.assertEqual(rc, 0, out[-1500:])
        # leaked: hand over with the current passphrase, then revoke (course record kept, opt-out already recorded)
        rc, out = self.E.tty(["setup"], ["y", "n", "y", "", PASS, new, new, "n"])
        self.assertEqual(rc, 0, out[-2000:])
        self.assertIn("失効", out)
        self.assertEqual(self.E.rk("check").returncode, 0)  # signatures made before the revocation stay valid
        rc, out = self.E.tty(["sign", "claim", "C001", "--decision", "VERIFIED"], ["y", PASS, PASS, PASS])
        self.assertNotEqual(rc, 0)  # the old passphrase no longer signs
        rc, out = self.E.tty(["sign", "claim", "C001", "--decision", "VERIFIED"], ["y", new])
        self.assertEqual(rc, 0, out[-1500:])

    def test_project_copy_refuses_human_commands(self):
        rc, out = self.E.tty(["verify"], [], script=self.E.path("tools", "rk", "rk.py"))
        self.assertNotEqual(rc, 0)
        self.assertIn("インストールされた Plugin", out)

    def test_wrong_passphrase_signs_nothing(self):
        rc, out = self.E.tty(["verify"], ["v", "", "v", "", "wrong passphrase 1", "wrong passphrase 2", "wrong passphrase 3"])
        self.assertNotEqual(rc, 0)
        self.assertNotIn('"kind": "claim"', self.E.read(".ryukoku", "signoffs.jsonl"))


class Launch(unittest.TestCase):
    """The code that receives the passphrase is the installed plugin's, verified
    against its manifest, and no file inside the project can change where the launcher goes."""

    def test_launcher_has_no_project_indirection(self):
        E = Env()
        try:
            for name in ("rk", "rk.cmd", "rk.ps1"):
                txt = E.read(name)
                self.assertIn("plugin-root", txt)
                self.assertNotIn(".ryukoku/", txt.replace(".ryukoku-writing", ""))
                self.assertNotIn("private", txt)
            # a plugin copy planted INSIDE the project and pointed to: the human command refuses to run from it
            planted = E.path("scratch", "plug")
            shutil.copytree(PLUGIN, planted, ignore=shutil.ignore_patterns("__pycache__", "tests", "evals"))
            with open(os.path.join(E.state, "plugin-root"), "w") as f:
                f.write(planted + "\n")
            rc, out = E.tty(["verify"], [], script=os.path.join(planted, "scripts", "rk", "rk.py"))
            self.assertNotEqual(rc, 0)
            self.assertIn("インストールされた Plugin", out)
        finally:
            E.cleanup()

    def test_modified_plugin_code_is_refused_before_the_passphrase(self):
        E = Env()
        try:
            E.setup()
            copy = os.path.join(E.base, "installed-plugin")
            shutil.copytree(PLUGIN, copy, ignore=shutil.ignore_patterns("__pycache__"))
            srv = os.path.join(copy, "scripts", "rk", "notebook", "server.py")
            with open(srv, "a", encoding="utf-8") as f:  # what a script with the student's permissions could do
                f.write("\n# planted\n")
            rc, out = E.tty(["verify"], [], script=os.path.join(copy, "scripts", "rk", "rk.py"))
            self.assertNotEqual(rc, 0)
            self.assertIn("同梱の一覧と違う", out)
            self.assertNotIn("合言葉(入力は表示されない)", out)
        finally:
            E.cleanup()


def git(cwd, *args):
    r = subprocess.run(["git"] + list(args), cwd=cwd, capture_output=True, text=True,
                       env=dict(os.environ, GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@example.test", GIT_COMMITTER_NAME="t",
                                GIT_COMMITTER_EMAIL="t@example.test"))
    if r.returncode != 0:
        raise RuntimeError(r.stderr)
    return r.stdout


class CI(unittest.TestCase):
    """CI: the workflow's command, run with the base branch's tools (unknown signers, a first PR, a neutered check in the
    PR, and detections that must reach CI)."""

    def setUp(self):
        self.E = Env()

    def tearDown(self):
        self.E.cleanup()

    def ci(self):
        wt = os.path.join(self.E.base, "rk-base")
        if os.path.exists(wt):
            git(self.E.proj, "worktree", "remove", "--force", wt)
        git(self.E.proj, "worktree", "add", "--detach", wt, "main")
        r = self.E.run([sys.executable, "-I", "-B", os.path.join(wt, "tools", "rk", "rk.py"), "--project", self.E.proj,
                        "check", "--ci", "--stage", "pr", "--base-ref", "main"], cwd=self.E.proj)
        return r.returncode, r.stdout

    def branch_commit(self, msg):
        git(self.E.proj, "add", "-A")
        git(self.E.proj, "commit", "-q", "--no-verify", "-m", msg)

    def forge_signer_and_verify(self):
        body = ("import sys\nsys.path.insert(0, %r)\nfrom rklib import sign, subjects, ledger\n"
                "s, sec = sign.register('.', 'student', 'student', 'ai-made-passphrase-123', iterations=100000)\n"
                "subj = subjects.find('.', 'claim', 'C001')\nrec = sign.make_record(s, sec, 'claim', 'C001', 'VERIFIED', subj.digest)\n"
                "sign.append_signoffs('.', [rec])\np=ledger.paths('.')[1]\nrows=ledger.read(p,ledger.CLAIMS)\n"
                "rows[0]['human_status']='VERIFIED'\nledger.write(p,rows,ledger.CLAIMS)\n" % RK)
        with open(self.E.path("scratch_f.py"), "w") as f:
            f.write(body)
        subprocess.run([sys.executable, "-B", "scratch_f.py"], cwd=self.E.proj, check=True, env=self.E.env())
        os.remove(self.E.path("scratch_f.py"))

    def add_claim(self):
        self.E.rk("ledger", "add-source", "--doi", "10.1038/s41598-023-41032-5", "--title", "A placeholder title", "--year", "2023")
        self.E.rk("ledger", "add-claim", "--claim", "現象 X(見本)", "--source-id", "S001", "--locator", "p. 3")

    def test_unknown_signer_in_pr(self):
        self.E.setup(git="g")
        git(self.E.proj, "checkout", "-q", "-b", "sec1")
        self.add_claim()
        self.forge_signer_and_verify()
        self.branch_commit("forged")
        rc, out = self.ci()
        self.assertEqual(rc, 1, out)
        self.assertIn("unknown signer key", out)
        self.assertIn("承認されていない", out)

    def test_first_pr_without_base_signers(self):
        git(self.E.proj, "init", "-q")
        git(self.E.proj, "symbolic-ref", "HEAD", "refs/heads/main")
        git(self.E.proj, "add", "-A")
        git(self.E.proj, "commit", "-q", "--no-verify", "-m", "no signers yet")
        git(self.E.proj, "checkout", "-q", "-b", "sec1")
        self.add_claim()
        self.forge_signer_and_verify()
        self.branch_commit("forged")
        rc, out = self.ci()
        self.assertEqual(rc, 1, out)
        self.assertIn("作業ツリーの署名者は信頼しない", out)

    def test_neutered_check_code_in_pr(self):
        self.E.setup(git="g")
        git(self.E.proj, "checkout", "-q", "-b", "sec1")
        self.add_claim()
        tgt = "tools/rk/rklib/check.py"
        self.assertEqual(decision(self.E.pre("Bash", {"command": "sed -i 's/    check_human_states(proj, idx, rep)/    pass/' %s" % tgt})), "deny")
        p = self.E.path(tgt)
        s = open(p, encoding="utf-8").read().replace("    check_human_states(proj, idx, rep)\n", "    pass\n")
        with open(p, "w", encoding="utf-8") as f:
            f.write(s)
        snippet = ("import sys\nsys.path.insert(0, %r)\nfrom rklib import ledger\np=ledger.paths('.')[1]\n"
                   "rows=ledger.read(p,ledger.CLAIMS)\nrows[0]['human_status']='VERIFIED'\nledger.write(p,rows,ledger.CLAIMS)\n" % RK)
        subprocess.run([sys.executable, "-B", "-c", snippet], cwd=self.E.proj, check=True, env=self.E.env())
        self.branch_commit("neutered")
        rc, out = self.ci()
        self.assertEqual(rc, 1, out)
        self.assertIn("検査・記録の道具", out)
        # the PR's own (neutered) copy would have passed the human-state check: the base copy did not
        self.assertIn("人間の署名がない", out)

    def test_provenance_reaches_ci(self):
        # in a course recorded as prohibited, an AI write that slipped past the guard reaches CI as provenance
        self.E.setup(policy="p", git="g")
        git(self.E.proj, "checkout", "-q", "-b", "sec1")
        self.E.post("Bash", {"command": "true"}, tuid="i")
        self.E.ai_write(self.E.path("scratch", "s.py"), "open('manu'+'script/main.md','a').write('\\nx\\n')\n", tuid="sw")
        self.assertEqual(self.E.ai_bash("python3 scratch/s.py", tuid="m1", allow_ask=True)[0], "ask")
        self.branch_commit("bypass")
        rc, out = self.ci()
        self.assertEqual(rc, 1, out)
        self.assertIn("AI が書いた・直した段落が原稿に", out)

    def test_detection_of_a_protected_file_reaches_ci(self):
        self.E.setup(git="g")
        git(self.E.proj, "checkout", "-q", "-b", "sec1")
        self.E.post("Bash", {"command": "true"}, tuid="i")
        self.E.ai_bash("Q=ques; printf '| Q9 | x | y | z |\\n' >> \"research/${Q}tions.md\"", tuid="m1", allow_ask=True)
        self.branch_commit("bypass")
        rc, out = self.ci()
        self.assertEqual(rc, 1, out)
        self.assertIn("検知した変更が未判断", out)

    def test_clean_pr_passes_with_section_signature(self):
        self.E.setup(git="g")
        git(self.E.proj, "checkout", "-q", "-b", "sec1")
        with open(self.E.path("manuscript", "main.md"), "a", encoding="utf-8") as f:
            f.write("\n自分で書いた段落(要因 A について)。\n")
        rc, out = self.E.tty(["sign", "section", "manuscript/main.md", "--decision", "reviewed"], ["y"])  # a key press
        self.assertEqual(rc, 0, out[-1500:])
        self.assertNotIn("合言葉(入力は表示されない)", out)
        self.branch_commit("section 1")
        rc, out = self.ci()
        self.assertEqual(rc, 0, out)


if __name__ == "__main__":
    unittest.main()
