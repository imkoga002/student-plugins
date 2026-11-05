"""Initialisation, export, language switch, workflows, validate, and the content of the public package (no word
from the private list, no guideline text copied, fictitious data only)."""
import json
import os
import re
import shutil
import subprocess
import sys
import unittest
import zipfile

from helpers import PLUGIN, Env

HAVE_PANDOC = shutil.which("pandoc") is not None
HAVE_LUALATEX = shutil.which("lualatex") is not None
# Words that must never appear in the public plugin. The list is private and is not kept in the repository, not even as hashes (short words can be found
# from their hashes by trying a dictionary). Put one word per line in a file and point RK_PRIVATE_TERMS_FILE at it,
# or place it at tests/private-terms.txt (ignored by Git). Without the file the scan is skipped and says so.
PRIVATE_TERMS_FILE = os.environ.get("RK_PRIVATE_TERMS_FILE") or os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                                                           "private-terms.txt")


def _norm(text):
    import unicodedata
    return re.sub(r"\s+", "", unicodedata.normalize("NFKC", text).lower())


def private_terms():
    try:
        with open(PRIVATE_TERMS_FILE, encoding="utf-8") as f:
            return [w for w in (_norm(x) for x in f.read().splitlines() if not x.lstrip().startswith("#")) if w]
    except OSError:
        return None


def term_hits(text, terms):
    t = _norm(text)
    return [w for w in terms if w in t]


class Init(unittest.TestCase):
    def test_fresh_project_passes_every_check(self):
        E = Env()
        try:
            r = E.rk("check")
            self.assertEqual(r.returncode, 0, r.stdout)
            self.assertIn("エラー 0 件", r.stdout)
            for args in (("lint",), ("searchlog", "validate"), ("data", "verify"), ("rules", "validate")):
                with self.subTest(args=args):
                    self.assertEqual(E.rk(*args).returncode, 0, E.rk(*args).stdout)
        finally:
            E.cleanup()

    @unittest.skipUnless(HAVE_PANDOC, "pandoc not installed")
    def test_docx_and_latex_both_languages(self):
        for lang in ("ja", "en"):
            E = Env(lang=lang)
            try:
                self.assertTrue(os.path.exists(E.path("pandoc", "reference.docx")))
                r = E.rk("export", "docx", "--file", "examples/format-examples.md")
                self.assertEqual(r.returncode, 0, r.stderr)
                with zipfile.ZipFile(E.path("build", "format-examples-sample.docx")) as z:
                    doc = z.read("word/document.xml").decode("utf-8")
                    notes = z.read("word/footnotes.xml").decode("utf-8") if "word/footnotes.xml" in z.namelist() else ""
                self.assertGreaterEqual(doc.count("<m:oMath"), 3, lang)
                self.assertIn("<w:tbl>", doc)
                self.assertIn("w:footnote", notes)
                r = E.rk("export", "latex", "--file", "examples/format-examples.md")
                self.assertEqual(r.returncode, 0, r.stderr)
                tex = open(E.path("build", "format-examples-sample.tex"), encoding="utf-8").read()
                self.assertIn("ltjsarticle" if lang == "ja" else "{article}", tex)
                self.assertNotIn("babel", tex)  # no lang in the PDF/LaTeX settings
                if not HAVE_LUALATEX:
                    r = E.rk("export", "pdf", "--file", "examples/format-examples.md")
                    self.assertNotEqual(r.returncode, 0)
            finally:
                E.cleanup()

    def test_relative_plugin_and_home_are_handled_before_creating(self):
        E = Env(init=False)
        try:
            r = E.run(["bash", os.path.join(PLUGIN, "scripts", "init-project.sh"), "--dir", "rel/thesis"], cwd=E.base)
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertTrue(os.path.isfile(os.path.join(E.base, "rel", "thesis", ".ryukoku", "config.yml")))
            r = E.run(["bash", os.path.join(PLUGIN, "scripts", "init-project.sh"), "--dir", "x"], cwd=PLUGIN)
            self.assertEqual(r.returncode, 2)
            self.assertFalse(os.path.exists(os.path.join(PLUGIN, "x")))
            r = E.run(["bash", os.path.join(PLUGIN, "scripts", "init-project.sh"), "--dir", E.home])
            self.assertEqual(r.returncode, 2)
            self.assertFalse(os.path.exists(os.path.join(E.home, ".ryukoku")))
            r = E.run(["bash", os.path.join(PLUGIN, "scripts", "init-project.sh"), "--dir", os.path.join(E.base, "rel", "thesis")])
            self.assertEqual(r.returncode, 3)
        finally:
            E.cleanup()

    @unittest.skipUnless(HAVE_PANDOC, "pandoc not installed")
    def test_language_is_one_line(self):
        E = Env(lang="ja")
        try:
            p = E.path(".ryukoku", "config.yml")
            s = open(p, encoding="utf-8").read()
            with open(p, "w", encoding="utf-8") as f:
                f.write(s.replace("manuscript_lang: ja", "manuscript_lang: en").replace("feedback_lang: ja", "feedback_lang: en"))
            r = E.rk("export", "latex", "--file", "examples/format-examples.md")
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertIn("{article}", open(E.path("build", "format-examples-sample.tex"), encoding="utf-8").read())
            self.assertIn("Once, in your own terminal", E.rk("help").stdout)
            ctx = E.hook("session-start.sh", {"cwd": E.proj}).stdout.decode()
            self.assertIn("Write all feedback", ctx)
        finally:
            E.cleanup()

    def test_workflows_parse_and_pin_only_checked_actions(self):
        try:
            import yaml
        except ImportError:
            self.skipTest("PyYAML not installed")
        allowed = {"actions/checkout@v6", "actions/upload-artifact@v6", "pandoc/actions/setup@v1"}
        wdir = os.path.join(PLUGIN, "templates", "github", ".github", "workflows")
        for fn in os.listdir(wdir):
            with open(os.path.join(wdir, fn), encoding="utf-8") as f:
                data = yaml.safe_load(f)
            self.assertIn("jobs", data)
            uses = re.findall(r"uses:\s*(\S+)", open(os.path.join(wdir, fn), encoding="utf-8").read())
            self.assertTrue(set(uses) <= allowed, (fn, uses))
        check = open(os.path.join(wdir, "check.yml"), encoding="utf-8").read()
        self.assertIn("git worktree add --detach .rk-base", check)
        self.assertIn(".rk-base/tools/rk/rk.py", check)
        self.assertNotIn("python3 tools/rk/rk.py check", check)  # never the PR's own copy

    def test_validate_strict(self):
        if not shutil.which("claude"):
            self.skipTest("claude CLI not installed")
        r = subprocess.run(["claude", "plugin", "validate", "--strict", PLUGIN], capture_output=True, text=True, timeout=120)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertNotIn("warning", (r.stdout + r.stderr).lower())

    def public_files(self):
        for dp, dns, fns in os.walk(PLUGIN):
            dns[:] = [d for d in dns if d not in ("__pycache__", ".git", "results")]
            for fn in fns:
                if fn.endswith((".pyc", ".docx", ".png")):
                    continue
                yield os.path.join(dp, fn)

    def test_no_private_terms_anywhere(self):
        terms = private_terms()
        if terms is None:
            self.skipTest("no private term list (set RK_PRIVATE_TERMS_FILE or create tests/private-terms.txt)")
        me = os.path.abspath(__file__)
        hits = []
        for p in self.public_files():
            if os.path.abspath(p) in (me, os.path.abspath(PRIVATE_TERMS_FILE)):
                continue
            txt = open(p, encoding="utf-8", errors="replace").read()
            if term_hits(txt, terms):
                hits.append(os.path.relpath(p, PLUGIN))
        self.assertEqual(hits, [])

    def test_private_term_scan_works(self):
        # the scan normalizes width, case and spaces: a planted placeholder is found, and a clean text is not
        self.assertEqual(term_hits("no term here", ["placeholderxyz"]), [])
        self.assertEqual(term_hits("a ＰＬＡＣＥ holder XYZ b", ["placeholderxyz"]), ["placeholderxyz"])

    def test_no_guideline_text_copied(self):
        phrases = ["断じてすべきではありません", "一部であっても自身の成果物とすること", "生成 AI により作成されたものを"]
        hits = [os.path.relpath(p, PLUGIN) for p in self.public_files() if os.path.abspath(p) != os.path.abspath(__file__)
                for ph in phrases if ph in open(p, encoding="utf-8", errors="replace").read()]
        self.assertEqual(hits, [])

    def test_no_real_looking_personal_data_in_package(self):
        bad = []
        for p in self.public_files():
            txt = open(p, encoding="utf-8", errors="replace").read()
            for m in re.finditer(r"[A-Za-z0-9._%+-]+@([A-Za-z0-9-]+\.)+[A-Za-z]{2,}", txt):
                dom = m.group(0).split("@", 1)[1].lower()
                if not dom.endswith(".test") and "example" not in dom:
                    bad.append("%s: %s" % (os.path.relpath(p, PLUGIN), m.group(0)))
        self.assertEqual(bad, [])

    def test_manifest_is_current(self):
        sys.path.insert(0, os.path.join(PLUGIN, "scripts", "rk"))
        from rklib import check
        root = os.path.join(PLUGIN, "scripts", "rk")
        self.assertEqual(open(os.path.join(root, check.MANIFEST), encoding="utf-8").read(), check.build_manifest(root),
                         "run: python3 scripts/update-manifest.py")


if __name__ == "__main__":
    unittest.main()


class Misc(unittest.TestCase):
    def test_model_is_read_from_the_transcript_when_session_start_has_none(self):
        E = Env()
        try:
            tr = os.path.join(E.base, "t.jsonl")
            with open(tr, "w") as f:
                f.write(json.dumps({"type": "assistant", "message": {"model": "claude-sample-model", "content": []}}) + "\n")
            E.hook("prompt-guard.sh", {"hook_event_name": "UserPromptSubmit", "cwd": E.proj, "prompt": "資料を探したい",
                                       "session_id": "t", "transcript_path": tr})
            log = E.read(".ryukoku", "ai-use-log.jsonl")
            self.assertIn('"model": "claude-sample-model"', log)
            facts = E.rk("facts").stdout
            self.assertIn("claude-sample-model", facts)
        finally:
            E.cleanup()

    def test_bundle_lists_signers_and_checks(self):
        E = Env()
        try:
            E.setup()
            r = E.rk("bundle")
            self.assertEqual(r.returncode, 0, r.stderr)
            h = E.read("HANDOFF.md")
            self.assertRegex(h, r"[0-9A-F]{4}-[0-9A-F]{4}-[0-9A-F]{4}-[0-9A-F]{4}")
            self.assertIn("署名者の数: 1", h)
            self.assertIn("エラー 0 件", h)
        finally:
            E.cleanup()

    def test_no_build_leftovers_in_the_plugin(self):
        for dp, dns, fns in os.walk(PLUGIN):
            for d in dns:
                self.assertNotIn(d, ("results", "build", ".rk-base"), os.path.join(dp, d))
            for fn in fns:
                self.assertFalse(fn.endswith((".pyc", ".log", ".tmp")), os.path.join(dp, fn))
