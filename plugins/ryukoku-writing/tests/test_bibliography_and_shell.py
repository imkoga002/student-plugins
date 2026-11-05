"""The bibliography the export prints comes from the ledger (never from a file the AI can edit), metadata anywhere in
the manuscript cannot redirect it, a cd the shell may not take leaves the directory unknown, the window store holds
under parallel tool calls, every string in a tool's JSON input is checked, and every number in body prose is a
candidate figure. Each test reproduces a way around a safeguard that an independent adversarial review found. All
example text is neutral (library use, survey response rates)."""
import csv
import glob
import json
import os
import shutil
import subprocess
import sys
import unittest

from helpers import PASS, PLUGIN, Env, decision, reason

sys.path.insert(0, os.path.join(PLUGIN, "scripts", "rk"))
from rklib import citations, common, execgate, ledger, verification  # noqa: E402

MS = "manuscript/main.md"
HAVE_PANDOC = shutil.which("pandoc") is not None
TITLE = "Library usage patterns among first-year undergraduate students"
HC = os.path.join(PLUGIN, "scripts", "rk", "hookcore.py")


def ledger_row(E, key="tanaka2020", title=TITLE, authors="Tanaka, Hanako", year="2020", status="IDENTITY_CONFIRMED", rid="S001",
               doi="10.1038/s41598-023-41032-5"):
    p = E.path("sources", "register.csv")
    rows = ledger.read(p, ledger.REGISTER)
    rows = [r for r in rows if r.get("id") != rid]
    rows.append({"id": rid, "citekey": key, "title": title, "authors": authors, "year": year, "doi": doi,
                 "container": "Journal of Library Studies", "machine_status": status})
    ledger.write(p, rows, ledger.REGISTER)
    return rows[-1]


def body(E, text):
    E.write(MS, "---\ntitle: t\n---\n\n" + text)


def ng(out):
    return [l for l in out.splitlines() if l.startswith("NG")]


def export_text(E, fmt="latex"):
    r = E.rk("export", fmt)
    p = E.path("build", "manuscript.tex")
    txt = open(p, encoding="utf-8").read() if os.path.exists(p) else ""
    if os.path.exists(p):
        os.remove(p)
    return r, txt.lower()   # the style may change the case of titles


FAKE_REFS = [{"id": "tanaka2020", "type": "book", "title": "A FABRICATED HANDBOOK", "author": [{"family": "Invented"}],
              "issued": {"date-parts": [[1900]]}}]


class Bibliography(unittest.TestCase):
    def setUp(self):
        self.E = Env()
        ledger_row(self.E)
        with open(self.E.path("sources", "references.json"), "w", encoding="utf-8") as f:
            json.dump(FAKE_REFS, f)

    def tearDown(self):
        self.E.cleanup()

    @unittest.skipUnless(HAVE_PANDOC, "pandoc not installed")
    def test_the_printed_bibliography_is_the_ledgers_not_references_json(self):
        body(self.E, "本文は図書館の利用について述べる [@tanaka2020]。\n")
        r, tex = export_text(self.E)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("library usage patterns", tex)
        self.assertNotIn("fabricated", tex)
        self.assertNotIn("invented", tex)
        # the informational comparison names the difference
        self.assertIn("references.json", self.E.rk("check").stdout)

    @unittest.skipUnless(HAVE_PANDOC, "pandoc not installed")
    def test_nocite_star_renders_the_qualifying_ledger_rows_only(self):
        ledger_row(self.E, key="candidate2019", title="Survey response rates in small libraries", rid="S002", status="CANDIDATE")
        body(self.E, "---\nnocite: '@*'\n...\n\n本文。\n")
        r, tex = export_text(self.E)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("library usage patterns", tex)
        self.assertNotIn("survey response rates", tex)

    def test_metadata_anywhere_in_the_body_cannot_redirect_the_bibliography(self):
        base = "本文は図書館の利用について述べる [@tanaka2020]。\n\n"
        cases = {
            "references": base + "---\nreferences:\n- id: tanaka2020\n  type: book\n  title: OVERRIDDEN\n...\n",
            "star and fake": base + "---\nnocite: |\n  @*\nreferences:\n- id: fake1999\n  type: book\n  title: Fabricated\n...\n",
            "csl": base + "---\ncsl: /nonexistent/x.csl\n...\n",
            "bibliography": base + "---\nbibliography: sources/alt.json\n...\n",
            "citation-abbreviations": base + "---\ncitation-abbreviations: x.json\n...\n",
            "raw tex": base + "\\begin{thebibliography}{9}\n\\bibitem{x} Fabricated.\n\\end{thebibliography}\n",
            "raw openxml": base + "```{=openxml}\n<w:fldSimple w:instr=\"BIBLIOGRAPHY\"/>\n```\n",
        }
        for name, text in cases.items():
            body(self.E, text)
            self.assertTrue(any("差し替え" in l for l in ng(self.E.rk("check", "--submit").stdout)), name)
            if HAVE_PANDOC:
                r, tex = export_text(self.E)
                self.assertNotEqual(r.returncode, 0, name)
                self.assertNotIn("overridden", tex)
        body(self.E, base + "---\nlink-citations: true\n...\n")
        self.assertFalse(any("差し替え" in l for l in ng(self.E.rk("check", "--submit").stdout)))

    def test_rows_that_cannot_be_printed_or_do_not_qualify_are_errors(self):
        ledger_row(self.E, key="noauthor2021", title="Reading rooms", authors="", rid="S003")
        ledger_row(self.E, key="notitle2021", title="", authors="Sato, Ken", rid="S004")
        body(self.E, "利用者は増えた [@noauthor2021]。回答も得た [@notitle2021]。未登録の [@fake1999]。\n")
        out = ng(self.E.rk("check", "--submit").stdout)
        self.assertTrue(any("noauthor2021" in l and "作れない" in l for l in out), out)
        self.assertTrue(any("notitle2021" in l and "作れない" in l for l in out), out)
        self.assertTrue(any("fake1999" in l for l in out), out)
        if HAVE_PANDOC:
            r, _tex = export_text(self.E)
            self.assertNotEqual(r.returncode, 0)
            self.assertIn("noauthor2021", r.stderr)

    @unittest.skipUnless(HAVE_PANDOC, "pandoc not installed")
    def test_the_registry_metadata_recorded_by_the_identity_check_wins(self):
        row = ledger.read(self.E.path("sources", "register.csv"), ledger.REGISTER)[0]
        meta = {"title": "Library usage patterns among first-year undergraduates: a registry title", "author": [{"family": "Tanaka", "given": "Hanako"}],
                "year": 2020, "container-title": "Journal of Library Studies"}
        ledger.record_identity(self.E.proj, [row], [{"id": row["id"], "status": "IDENTITY_CONFIRMED", "checked_at": "t", "source": "crossref", "meta": meta}])
        body(self.E, "本文 [@tanaka2020]。\n")
        r, tex = export_text(self.E)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("a registry title", tex)
        # the identity record must be for the row as it is now
        d = json.load(open(self.E.path("sources", "identity.json"), encoding="utf-8"))
        d[row["id"]]["digest"] = "0" * 64
        json.dump(d, open(self.E.path("sources", "identity.json"), "w", encoding="utf-8"))
        self.assertTrue(any("identity_stale" in l for l in ng(self.E.rk("check", "--submit").stdout)))

    def test_the_identity_record_and_the_export_settings_are_closed_to_the_ai(self):
        for pol in ("allowed", "prohibited"):
            self.E.set_policy(pol)
            for rel in ("sources/identity.json", "sources/register.csv", "pandoc/defaults-ja-latex.yaml"):
                self.assertEqual(decision(self.E.pre("Write", {"file_path": self.E.path(rel), "content": "{}"})), "deny", (pol, rel))

    @unittest.skipUnless(HAVE_PANDOC, "pandoc not installed")
    def test_a_file_outside_the_manuscript_is_exported_as_a_sample(self):
        self.E.write("examples/sample.md", "---\ntitle: s\n---\n\n見本 [@unknown2000]。\n")
        r = self.E.rk("export", "latex", "--file", self.E.path("examples", "sample.md"))
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertTrue(os.path.exists(self.E.path("build", "sample-sample.tex")))
        self.E.write("examples/sample.md", "---\nreferences:\n- id: z\n  title: F\n---\n\n見本。\n")
        r = self.E.rk("export", "latex", "--file", self.E.path("examples", "sample.md"))
        self.assertNotEqual(r.returncode, 0)

    def test_the_comparison_with_references_json_is_exact(self):
        row = {"title": TITLE, "authors": "Tanaka, Hanako", "year": "2020", "doi": "", "isbn": ""}
        base = {"title": TITLE, "author": [{"family": "Tanaka", "given": "Hanako"}], "issued": {"date-parts": [[2020]]}}

        def v(**kw):
            e = dict(base)
            e.update(kw)
            return citations.entry_mismatches(row, e)
        self.assertEqual(v(), [])
        for kw in ({"author": [{"family": "Ta", "given": "Fake"}]}, {"author": [{"given": "Someone Else"}]},
                   {"author": [], "editor": [{"family": "Invented"}]}, {"title": TITLE + ": an added subtitle"},
                   {"DOI": "10.9999/x.1"}, {"container-title": "Another Journal"}, {"original-date": {"date-parts": [[1850]]}},
                   {"translator": [{"family": "Invented"}]}):
            self.assertTrue(v(**kw), kw)
        self.assertTrue(citations.entry_mismatches({"title": "", "authors": "", "year": ""}, {"title": "Anything", "author": [{"family": "A"}]}))


class ConditionalDirectoryChanges(unittest.TestCase):
    def test_a_cd_bash_may_not_take_leaves_the_directory_unknown(self):
        E = Env()
        try:
            cfg0 = E.read(".ryukoku", "config.yml")
            for pol in ("allowed", "prohibited"):
                E.set_policy(pol)
                cfg0 = E.read(".ryukoku", "config.yml")
                for cmd in ("cd m?nuscript || cd ../research; echo 追記 >> main.md",
                            "cd .r?ukoku || cd ../research; echo 'ai_policy: allowed' >> config.yml",
                            "cd th?nking || cd ../research; echo 追記 >> log.md",
                            "true | cd manuscript; echo 追記 >> main.md",
                            "cd manuscript & echo 追記 >> main.md",
                            "if true; then cd manuscript; fi; echo 追記 >> main.md",
                            "command cd manuscript; echo 追記 >> main.md",
                            "cd nonexistent-dir; echo 追記 >> main.md",
                            "(cd manuscript; echo 追記 >> main.md)"):
                    before = E.read("manuscript", "main.md")
                    d, _ctx = E.ai_bash(cmd)
                    self.assertEqual(d, "deny", (pol, cmd))
                    self.assertEqual(before, E.read("manuscript", "main.md"))
                    self.assertEqual(cfg0, E.read(".ryukoku", "config.yml"))
            # an unknown directory with any write form: deny under prohibited, ask otherwise
            E.set_policy("prohibited")
            self.assertEqual(decision(E.pre("Bash", {"command": "cd res?arch || cd ..; echo x > notes.md"})), "deny")
            E.set_policy("allowed")
            self.assertEqual(decision(E.pre("Bash", {"command": "cd res?arch || cd ..; echo x > notes.md"})), "ask")
            # the directory is never followed: any cd makes relative write targets unknown (ask); without one they
            # resolve against the tool's working directory
            self.assertEqual(decision(E.pre("Bash", {"command": "cd research && echo x > notes.md"})), "ask")
            self.assertEqual(decision(E.pre("Bash", {"command": "echo x > research/notes.md"})), "-")
        finally:
            E.cleanup()

    def test_any_directory_change_makes_relative_targets_unknown(self):
        E = Env()
        try:
            for cmd in ("cd research && echo x > a.md", "pushd research; echo x > a.md", "$D research; echo x > a.md",
                        "c? research; echo x > a.md", "echo cd; echo x > a.md"):
                self.assertIn("unknown_target", [k for k, _w in execgate.scan(cmd, E.proj, PLUGIN, E.proj)], cmd)
            self.assertNotIn("unknown_target", [k for k, _w in execgate.scan("echo x > research/a.md", E.proj, PLUGIN, E.proj)])
        finally:
            E.cleanup()

    def test_a_settings_change_detected_during_an_ai_call_closes_manuscript_writes(self):
        E = Env()
        try:
            E.setup(policy="a")
            mp = E.path(MS)
            self.assertEqual(decision(E.pre("Write", {"file_path": mp, "content": "x"})), "-")
            # a change to the settings that slipped through during an AI tool call
            E.pre("Bash", {"command": "python3 job.py"}, tuid="slip")
            cfg = E.path(".ryukoku", "config.yml")
            s = open(cfg, encoding="utf-8").read()
            open(cfg, "w", encoding="utf-8").write(s.replace('course_name: ""', 'course_name: "図書館学"'))
            E.post("Bash", {"command": "python3 job.py"}, tuid="slip")
            self.assertTrue(any("検知" in p for p in common.config_problems(E.proj)))
            r = E.pre("Write", {"file_path": mp, "content": "x"})
            self.assertEqual(decision(r), "deny")
            from rklib import msguard
            ids = msguard.open_detections(E.proj)
            rc, out = E.tty(["sign", "change", ids[0], "--decision", "mine"], ["y"])
            self.assertEqual(rc, 0, out[-1500:])
            self.assertEqual(common.config_problems(E.proj), [])
            self.assertEqual(decision(E.pre("Write", {"file_path": mp, "content": "x"})), "-")
        finally:
            E.cleanup()


class ParallelWindows(unittest.TestCase):
    def test_concurrent_tool_calls_do_not_lose_windows(self):
        E = Env()
        try:
            lost = 0
            for trial in range(4):
                ps = [subprocess.Popen([sys.executable, "-I", "-B", HC, "pre", E.proj, "tu%d_%d" % (trial, i), "run"], env=E.env())
                      for i in range(8)]
                for p in ps:
                    p.wait()
                oj = glob.glob(os.path.join(E.state, "**", "open.json"), recursive=True)[0]
                w = json.load(open(oj))
                lost += 8 - len([k for k in w if k.startswith("tu%d_" % trial)])
                ps = [subprocess.Popen([sys.executable, "-I", "-B", HC, "post", E.proj, "Bash", "tu%d_%d" % (trial, i), ""], env=E.env(),
                                       stdout=subprocess.DEVNULL) for i in range(8)]
                for p in ps:
                    p.wait()
            self.assertEqual(lost, 0)
        finally:
            E.cleanup()

    def test_a_window_snapshot_left_without_its_entry_makes_changes_uncertain(self):
        E = Env()
        try:
            E.set_policy("allowed")
            E.ai_bash("echo hi", tuid="b0")
            mp = E.path(MS)
            text = E.read("manuscript", "main.md") + "\n図書館の利用者アンケートの回収方法を比べる段落。\n"
            ti = {"file_path": mp, "content": text}
            E.pre("Write", ti, tuid="W1")
            E.pre("Bash", {"command": "echo a"}, tuid="B2")
            oj = glob.glob(os.path.join(E.state, "**", "open.json"), recursive=True)[0]
            w = json.load(open(oj))
            w.pop("W1")
            json.dump(w, open(oj, "w"))           # an entry lost (as an unlocked update could lose it)
            E.post("Bash", {"command": "echo a"}, tuid="B2")
            open(mp, "w", encoding="utf-8").write(text)
            E.pre("Bash", {"command": "echo b"}, tuid="B3")
            E.post("Bash", {"command": "echo b"}, tuid="B3")
            rows = [json.loads(l) for l in open(E.path(".ryukoku", "provenance.jsonl"), encoding="utf-8") if l.strip()]
            last = [r for r in rows if r.get("type") == "paragraph"][-1]
            self.assertIn(last.get("actor"), ("ai", "uncertain"), last)
        finally:
            E.cleanup()


class ToolInputs(unittest.TestCase):
    def test_every_string_in_a_tools_json_input_is_checked(self):
        E = Env()
        try:
            E.set_policy("prohibited")
            ms = E.path(MS)
            for ti in ({"path": ms, "content": "x"}, {"paths": [ms], "content": "x"}, {"directory": E.path("manuscript"), "name": "main.md"},
                       {"options": {"target": {"file": ms}}}, {"files": [{"uri": ms}]}):
                self.assertEqual(decision(E.pre("mcp__fs__write_file", ti)), "deny", ti)
            # a relative path: unknown place -> deny under prohibited, ask otherwise
            self.assertEqual(decision(E.pre("mcp__fs__write_file", {"path": "manuscript/main.md", "content": "x"})), "deny")
            E.set_policy("allowed")
            self.assertEqual(decision(E.pre("mcp__fs__write_file", {"path": "notes/a.md", "content": "x"})), "ask")
            # a tool with a command and a path field: both are checked
            self.assertEqual(decision(E.pre("PowerShell", {"command": "Get-Date", "file_path": E.path(".ryukoku", "config.yml")})), "deny")
        finally:
            E.cleanup()


class Numbers(unittest.TestCase):
    FOUND = ["調査に回答した学生は320冊を借りていた。", "回答者のうち3分の1が毎週図書館を利用した。", "利用者は百人を超えた。",
             "調査の有効回答は n=350 であった。", "回答者は32の学部に所属していた。", "平均の滞在時間は45分であった。",
             "Mean 3.4 hours were spent in the library.", "On average students borrowed 12 books.", "250 respondents completed the survey.",
             "回答率は42%であった。<!-- @tanaka2020 -->", "回答率は四二%だった。", "来館者は年間で約二千人であった。", "1/3 of the students never visited.",
             "回答者は数百人に上った。", "図書館を利用した学生は2020年に1200人であった。", "回答した学生は三十二人。"]
    EXEMPT = ["前節3.2で述べたとおり、調査票を配布した。", "(2.3) より、次の関係が得られる。", "本研究では2回目の調査を行った。",
              "ISO 27001 に準拠した管理を行った。", "調査はPython 3.13で集計した。", "第2章で方法を述べる。", "表1に結果を示す。",
              "2026年11月5日に配布した。", "1990年代以降、利用が変化した。", "Section 3.2 describes the method.", "See Table 3.1.",
              "回答者には1人ずつ面接した。", "ver 2.0.0 を使った。", "3.2.1 項で述べる。", "第1位の理由は立地だった。", "RFC 9110 に従った。",
              "午後3時に開始した。", "アンケートの問5で尋ねた。", "2019-2021 年の調査を比べる。"]

    def test_every_number_in_prose_is_a_candidate_except_the_exempt_forms(self):
        E = Env(init=False)
        try:
            os.makedirs(E.proj)
            for t in self.FOUND:
                self.assertTrue(verification.numbers_without_source(E.proj, t + "\n"), t)
            for t in self.EXEMPT:
                self.assertEqual(verification.numbers_without_source(E.proj, t + "\n"), [], t)
            # sourced per sentence: a citation in another sentence of the paragraph does not count
            self.assertTrue(verification.numbers_without_source(E.proj, "回答率は42%であった。利用は増えた [@tanaka2020]。\n"))
            self.assertEqual(verification.numbers_without_source(E.proj, "回答率は42%であった [@tanaka2020]。\n"), [])
        finally:
            E.cleanup()

    def test_the_student_can_mark_a_figure_as_needing_no_source(self):
        E = Env()
        try:
            E.setup()
            with open(E.path(MS), "a", encoding="utf-8") as f:
                f.write("\n本稿では例として 3 冊の本を挙げる。\n")
            out = ng(E.rk("check", "--submit").stdout)
            self.assertTrue(any("3 冊" in l for l in out), out)
            rc, tr = E.tty(["figures"], ["y"] * 6)
            self.assertEqual(rc, 0, tr[-1500:])
            self.assertFalse(any("出典の引用もデータ" in l for l in ng(E.rk("check", "--submit").stdout)))
            # the AI cannot write the mark; and a changed sentence drops it
            self.assertEqual(decision(E.pre("Write", {"file_path": E.path(".ryukoku", "signoffs.jsonl"), "content": "{}"})), "deny")
            t = open(E.path(MS), encoding="utf-8").read().replace("3 冊", "4 冊")
            open(E.path(MS), "w", encoding="utf-8").write(t)
            self.assertTrue(any("出典の引用もデータ" in l for l in ng(E.rk("check", "--submit").stdout)))
        finally:
            E.cleanup()


if __name__ == "__main__":
    unittest.main()
