"""Regressions from the fourth and fifth rounds of independent adversarial verification: pandoc custom readers and
writers named by `from`/`to`, values that go into the LaTeX template, and external programs (pandoc, the LaTeX
engine, mmdc) running with the project as their working directory, where AI-written configuration is found; and flow-style YAML in the defaults."""
import os
import stat
import sys
import unittest

from helpers import PLUGIN, Env

sys.path.insert(0, os.path.join(PLUGIN, "scripts", "rk"))

FAKE = """#!/bin/sh
# a stand-in for %(name)s: records where it runs, then makes the output file it was asked for
pwd > "%(log)s"
out=""
prev=""
for a in "$@"; do
  [ "$prev" = "-o" ] && out="$a"
  prev="$a"
done
[ -n "$out" ] && printf 'x' > "$out"
exit 0
"""


class Base(unittest.TestCase):
    def setUp(self):
        self.E = Env()
        self.P = self.E.proj
        self._env = {k: os.environ.get(k) for k in ("RK_STATE_HOME", "HOME")}
        os.environ["RK_STATE_HOME"], os.environ["HOME"] = self.E.state, self.E.home
        self.D = self.E.path("pandoc", "defaults-ja-docx.yaml")
        with open(self.D, encoding="utf-8") as f:
            self.base = f.read()

    def tearDown(self):
        for k, v in self._env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        self.E.cleanup()

    def bad_for(self, text):
        from rklib import export
        with open(self.D, "w", encoding="utf-8") as f:
            f.write(text)
        return export.sanitize_defaults(self.D, self.P)


class CustomReadersWriters(Base):
    def test_lua_reader_or_writer_is_rejected_by_export_and_check(self):
        for old, new in (("to: docx", "to: w.lua"), ("to: docx", "to: 'w.lua'"), ("to: docx", "to: scratch/w.lua"),
                         ("to: docx", "to: ./w"), ("from: markdown+east_asian_line_breaks", "from: r.lua")):
            safe, bad = self.bad_for(self.base.replace(old, new))
            self.assertTrue(bad, new)
            self.assertNotIn(new.split(":")[0], safe, new)
            r = self.E.rk("export", "docx")
            self.assertNotEqual(r.returncode, 0, new)
            r = self.E.rk("check")
            self.assertIn("pandoc", r.stdout, new)

    def test_built_in_formats_with_extensions_pass(self):
        safe, bad = self.bad_for(self.base)
        self.assertEqual(bad, [])
        self.assertEqual(safe["from"], "markdown+east_asian_line_breaks")
        safe, bad = self.bad_for(self.base.replace("to: docx", "to: docx+styles"))
        self.assertEqual(bad, [])


class TemplateValues(Base):
    def test_tex_in_variables_or_a_project_class_is_rejected(self):
        for extra in ("variables:\n  mainfont: 'X}\\directlua{os.exit()}'\n",
                      "variables:\n  documentclass: evil\n",       # an evil.cls the AI put in the project
                      "variables:\n  fontsize: 11pt\\relax\n",
                      "metadata:\n  lang: 'ja}\\input{x}'\n"):
            _safe, bad = self.bad_for(self.base + extra)
            self.assertTrue(bad, extra)

    def test_shipped_defaults_with_inline_comments_pass(self):
        from rklib import export
        for lang in ("ja", "en"):
            for fmt in ("docx", "latex", "pdf"):
                p = os.path.join(PLUGIN, "templates", lang, "pandoc", "defaults-%s-%s.yaml" % (lang, fmt))
                _safe, bad = export.sanitize_defaults(p, self.P)
                self.assertEqual(bad, [], p)


class FlowStyle(Base):
    def test_flow_mappings_are_rejected_with_a_message_not_a_traceback(self):
        """metadata: {lang: en} / variables: {documentclass: article} are refused with a message, not a traceback."""
        for old, new in (("metadata:\n  lang: ja", "metadata: {lang: en}"),):
            text = self.base.replace(old, new) if old in self.base else self.base + new + "\n"
            _safe, bad = self.bad_for(text)
            self.assertTrue(any(b.startswith("metadata") for b in bad), bad)
        _safe, bad = self.bad_for(self.base + "variables: {documentclass: article}\n")
        self.assertTrue(any(b.startswith("variables") for b in bad), bad)
        for cmd in (("check",), ("export", "docx")):
            r = self.E.rk(*cmd)
            self.assertNotEqual(r.returncode, 0, cmd)
            self.assertNotIn("Traceback", r.stderr + r.stdout, cmd)
            self.assertIn("pandoc", r.stderr + r.stdout, cmd)


class WorkingDirectory(Base):
    def test_pandoc_and_mmdc_do_not_run_in_the_project(self):
        """pandoc (and the LaTeX engine it starts) and mmdc/puppeteer read configuration from their working
        directory; the AI can write in the project, so they must run elsewhere."""
        fb = os.path.join(self.E.base, "fakebin")
        os.makedirs(fb)
        logs = {}
        for name in ("pandoc", "mmdc"):
            logs[name] = os.path.join(self.E.base, name + "-cwd.txt")
            p = os.path.join(fb, name)
            with open(p, "w") as f:
                f.write(FAKE % {"name": name, "log": logs[name]})
            os.chmod(p, os.stat(p).st_mode | stat.S_IXUSR)
        with open(self.E.path("manuscript", "main.md"), "a", encoding="utf-8") as f:
            f.write("\n\n```mermaid\nflowchart LR\n  A --> B\n```\n")
        # files an AI tool could have planted where the tools look for configuration
        for rel in (".puppeteerrc.cjs", "hyperref.sty", "build/.puppeteerrc.cjs"):
            os.makedirs(os.path.dirname(self.E.path(rel)), exist_ok=True)
            with open(self.E.path(rel), "w") as f:
                f.write("planted\n")
        path = fb + os.pathsep + os.environ.get("PATH", "")
        r = self.E.run([sys.executable, "-B", os.path.join(self.P, "tools", "rk", "rk.py"), "--project", self.P,
                        "export", "docx"], cwd=self.P, extra={"PATH": path})
        self.assertEqual(r.returncode, 0, r.stderr + r.stdout)
        proj = os.path.realpath(self.P)
        for name, log in logs.items():
            with open(log) as f:
                where = os.path.realpath(f.read().strip())
            self.assertFalse(where == proj or where.startswith(proj + os.sep), "%s ran in the project: %s" % (name, where))
        self.assertTrue(os.path.exists(self.E.path("build", "manuscript.docx")))
        self.assertTrue(os.path.exists(self.E.path("build", "fig-1.png")))
        # the temporary folder is removed
        sd = os.path.join(self.E.state, "state")
        left = [x for d in os.listdir(sd) for x in os.listdir(os.path.join(sd, d)) if x.startswith("export-")]
        self.assertEqual(left, [])

    def test_a_planted_link_in_build_is_not_followed(self):
        os.makedirs(self.E.path("build"), exist_ok=True)
        target = self.E.path("thinking", "linked-target.md")
        os.makedirs(os.path.dirname(target), exist_ok=True)
        with open(target, "w", encoding="utf-8") as f:
            f.write("the student's own note\n")
        os.symlink(target, self.E.path("build", "fig-1.mmd"))
        with open(self.E.path("manuscript", "main.md"), "a", encoding="utf-8") as f:
            f.write("\n\n```mermaid\nflowchart LR\n  A --> B\n```\n")
        r = self.E.rk("export", "docx")
        self.assertEqual(r.returncode, 0, r.stderr + r.stdout)
        with open(target, encoding="utf-8") as f:
            self.assertEqual(f.read(), "the student's own note\n")


if __name__ == "__main__":
    unittest.main()
