"""Citation keys in any script and the bibliography pandoc would print, figures in Japanese prose, the one decision on
the settings file, CI and export settings closed to the AI, overlapping and unfinished tool calls, hosts that reach
this computer, directory changes the command scanner follows, commands that write in other ways, and abbreviated
options. Each test reproduces a way around a safeguard that an independent adversarial review found. All example
text is neutral (library use, survey response rates)."""
import csv
import json
import os
import re
import shutil
import subprocess
import sys
import unittest

from helpers import PASS, PLUGIN, Env, decision

sys.path.insert(0, os.path.join(PLUGIN, "scripts", "rk"))
from rklib import citations, common, execgate, verification  # noqa: E402

MS = "manuscript/main.md"
HAVE_PANDOC = shutil.which("pandoc") is not None


def prov(E):
    p = E.path(".ryukoku", "provenance.jsonl")
    return [json.loads(l) for l in open(p, encoding="utf-8") if l.strip()] if os.path.exists(p) else []


def confirm_source(E, key, title, year, authors, doi="10.1038/s41598-023-41032-5"):
    """A ledger row for KEY at IDENTITY_CONFIRMED (what refcheck would leave after a matched identifier check)."""
    E.rk("ledger", "add-source", "--doi", doi, "--title", title, "--year", year, "--authors", authors, "--citekey", key)
    p = E.path("sources", "register.csv")
    rows = list(csv.DictReader(open(p, encoding="utf-8")))
    fields = open(p, encoding="utf-8").readline().strip().split(",")
    for r in rows:
        if r["citekey"] == key:
            r["machine_status"] = "IDENTITY_CONFIRMED"
    with open(p, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)


def write_refs(E, entries):
    with open(E.path("sources", "references.json"), "w", encoding="utf-8") as f:
        json.dump(entries, f, ensure_ascii=False)


def append_ms(E, text):
    with open(E.path(MS), "a", encoding="utf-8") as f:
        f.write(text)


def ng(out):
    return [l for l in out.splitlines() if l.startswith("NG")]


class CitationKeys(unittest.TestCase):
    def test_keys_follow_pandocs_rule_in_any_script(self):
        cases = {
            "利用者調査 [@図書館2021] による。": {"図書館2021"},
            "x [@lib利用2020] y": {"lib利用2020"},
            "[@ü2019; @survey_2022, p. 3]": {"ü2019", "survey_2022"},
            "末尾の句読点 @key-end-. と @a.b.c.": {"key-end", "a.b.c"},
            "連絡は office@example.org まで": set(),
            "`[@code2020]` はコード": set(),
            "```\n[@fenced2020]\n```\n": set(),
            "(@ex) 例の項目\n\n(@ex) を参照。(@undefined2020) は引用。": {"undefined2020"},
            "図 @fig:rate を見よ。": set(),
        }
        for text, want in cases.items():
            self.assertEqual(citations.extract(text)[0], want, text)

    @unittest.skipUnless(HAVE_PANDOC, "pandoc not installed")
    def test_the_reader_agrees_with_pandoc(self):
        text = ("---\nnocite: |\n  @nc1\n---\n本文 [@図書館2021]、@回答率_2019 と [-@survey.2020a]。"
                "メール office@example.org。(@)\n\n(@lbl) 例\n\n(@lbl) と (@cited9)。\n")
        pk = citations._pandoc_keys(text)
        self.assertIsNotNone(pk)
        self.assertEqual(citations.extract(text)[0], pk[0])

    def test_a_key_in_kanji_that_is_not_in_the_ledger_stops_submission_and_export(self):
        E = Env()
        try:
            E.setup()
            append_ms(E, "\n図書館の利用は増えた [@図書館2021]。\n")
            out = E.rk("check", "--submit").stdout
            self.assertTrue(any("図書館2021" in l for l in ng(out)), out)
            if HAVE_PANDOC:
                r = E.rk("export", "latex")
                self.assertNotEqual(r.returncode, 0)
                self.assertIn("図書館2021", r.stderr)
        finally:
            E.cleanup()


class Figures(unittest.TestCase):
    def test_figures_next_to_kana_and_kanji_are_found(self):
        found = {
            "回答率は38.5%だった。": "38.5%",
            "利用者は約三割増えた。": "三割",
            "全国で12位だった。": "12位",
            "15か国で調べた。": "15か国",
            "来館者は約百万人だった。": "百万",
            "貸出は1,200件に達した。": "1,200件",
            "回答率は３８．５％だった。": "38.5%",
            "about 45000 visitors": "45000",
            "the rate rose by 3 points": "3 points",
        }
        for text, tok in found.items():
            self.assertIn(tok, verification.figures(text), text)
        for text in ("図 2.1 に示す。", "表 3 のとおり。", "式 (2.3) を用いる。", "Python 3.13 で集計した。", "2020 年から 1990 年代に",
                     "3.2 節と第 2 章", "v1.2 の版", "一人ひとりに聞いた。", "第3回の調査", "2024年4月1日"):
            self.assertEqual(verification.figures(text), [], text)

    def test_a_data_reference_counts_only_when_the_file_exists(self):
        E = Env()
        try:
            text = "回答率は38.5%だった(data/processed/response-rate.csv)。\n"
            self.assertTrue(verification.numbers_without_source(E.proj, text))
            os.makedirs(E.path("data", "processed"), exist_ok=True)
            open(E.path("data", "processed", "response-rate.csv"), "w").write("year,rate\n2024,38.5\n")
            self.assertEqual(verification.numbers_without_source(E.proj, text), [])
        finally:
            E.cleanup()


class BibliographyContent(unittest.TestCase):
    def setUp(self):
        self.E = Env()
        self.E.setup()
        confirm_source(self.E, "lib2021", "Library use in rural towns", "2021", "Tanaka, Hana")
        append_ms(self.E, "\n利用は増えた [@lib2021]。\n")

    def tearDown(self):
        self.E.cleanup()

    def mismatch_lines(self):
        return [l for l in ng(self.E.rk("check", "--submit").stdout) if "lib2021" in l and "台帳と違う" in l]

    def test_the_printed_entry_must_say_what_the_ledger_says(self):
        good = {"id": "lib2021", "type": "article-journal", "title": "Library use in rural towns",
                "author": [{"family": "Tanaka", "given": "Hana"}], "issued": {"date-parts": [[2021]]},
                "DOI": "10.1038/s41598-023-41032-5"}
        write_refs(self.E, [good])
        self.assertEqual(self.mismatch_lines(), [])
        for bad in ({"title": "A different study"}, {"issued": {"date-parts": [[2018]]}},
                    {"author": [{"family": "Tanaka", "given": "Hana"}, {"family": "Invented", "given": "X"}]},
                    {"DOI": "10.1000/other"}):
            write_refs(self.E, [dict(good, **bad)])
            self.assertTrue(self.mismatch_lines(), bad)
            if HAVE_PANDOC:
                r = self.E.rk("export", "latex")
                self.assertNotEqual(r.returncode, 0, bad)
                self.assertIn("mismatch", r.stderr, bad)

    def test_only_sources_references_json_is_printed(self):
        from rklib import export
        d = self.E.path("pandoc", "defaults-ja-latex.yaml")
        base = open(d, encoding="utf-8").read()
        open(d, "w", encoding="utf-8").write(base.replace("bibliography: sources/references.json", "bibliography: sources/alt.json"))
        open(self.E.path("sources", "alt.json"), "w").write("[]")
        _safe, bad = export.sanitize_defaults(d, self.E.proj)
        self.assertTrue(any(b.startswith("bibliography") for b in bad), bad)
        open(d, "w", encoding="utf-8").write(base.replace("pdf-engine", "csl: sources/style.csl\npdf-engine") if "pdf-engine" in base
                                              else base + "csl: sources/style.csl\n")
        open(self.E.path("sources", "style.csl"), "w").write("<style/>")
        _safe, bad = export.sanitize_defaults(d, self.E.proj)
        self.assertTrue(any(b.startswith("csl") for b in bad), bad)
        open(d, "w", encoding="utf-8").write(base)
        t = open(self.E.path(MS), encoding="utf-8").read()
        open(self.E.path(MS), "w", encoding="utf-8").write(t.replace("---\n", "---\nbibliography: sources/alt.json\n", 1))
        self.assertTrue(any("bibliography" in l for l in ng(self.E.rk("check", "--submit").stdout)))
        if HAVE_PANDOC:
            r = self.E.rk("export", "latex")
            self.assertNotEqual(r.returncode, 0)
            self.assertIn("front matter", r.stderr)

    def test_export_settings_are_closed_to_the_ai_and_a_change_needs_the_student(self):
        E = self.E
        for pol in ("allowed", "prohibited"):
            E.set_policy(pol)
            for rel in ("pandoc/defaults-ja-latex.yaml", "pandoc/style.csl", "pandoc/template.latex"):
                self.assertEqual(decision(E.pre("Write", {"file_path": E.path(rel), "content": "x\n"})), "deny", (pol, rel))
            self.assertEqual(decision(E.pre("Bash", {"command": "echo 'csl: pandoc/x.csl' >> pandoc/defaults-ja-latex.yaml"})), "deny", pol)
        E.set_policy("allowed")
        if not HAVE_PANDOC:
            return
        write_refs(E, [{"id": "lib2021", "type": "article-journal", "title": "Library use in rural towns",
                        "author": [{"family": "Tanaka", "given": "Hana"}], "issued": {"date-parts": [[2021]]}}])
        d = E.path("pandoc", "defaults-ja-latex.yaml")
        with open(d, "a", encoding="utf-8") as f:
            f.write("# the student's own note\n")
        r = E.rk("export", "latex")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("guarded", r.stderr)
        rc, out = E.tty(["sign", "guarded", "tools", "--decision", "confirmed"], ["y", PASS])
        self.assertEqual(rc, 0, out[-1500:])
        r = E.rk("export", "latex")
        self.assertNotIn("guarded", r.stderr)


class SettingsFile(unittest.TestCase):
    def setUp(self):
        self.E = Env()
        self.cfg = self.E.path(".ryukoku", "config.yml")
        self.E.set_policy("allowed")
        self.orig = open(self.cfg, "rb").read()

    def tearDown(self):
        self.E.cleanup()

    def variant(self, data):
        open(self.cfg, "wb").write(data)
        d = decision(self.E.pre("Write", {"file_path": self.E.path(MS), "content": "x\n"}))
        r = subprocess.run(["bash", "-c", '. "$1"; PROJ="$2"; cfg_check_bash', "x", os.path.join(PLUGIN, "scripts", "hooks", "lib.sh"),
                            self.E.proj], capture_output=True, text=True)
        return d, common.config_problems(self.E.proj), common.course_policy(self.E.proj), r.stdout

    def test_hook_and_tools_make_one_decision(self):
        line = re.compile(rb"(?m)^ai_policy:[^\n]*")
        cases = {
            "plain": (self.orig, False),
            "crlf": (self.orig.replace(b"\n", b"\r\n"), False),
            "quoted, comment": (line.sub(b"ai_policy: 'allowed' # checked", self.orig, count=1), False),
            "tab before value": (line.sub(b"ai_policy:\tallowed", self.orig, count=1), False),
            "saved as cp932": (self.orig.decode("utf-8").encode("cp932", "replace"), True),
            "no-break space": (line.sub("ai_policy: allowed ".encode("utf-8"), self.orig, count=1), True),
            "vertical tab": (line.sub(b"ai_policy: allowed\x0b", self.orig, count=1), True),
            "upper case": (line.sub(b"ai_policy: Allowed", self.orig, count=1), True),
            "two words": (line.sub(b"ai_policy: allowed prohibited", self.orig, count=1), True),
            "indented second line": (self.orig + b"\n  ai_policy: prohibited\n", True),
            "byte order mark": (b"\xef\xbb\xbf" + self.orig, None),
        }
        for name, (data, bad) in cases.items():
            d, probs, pol, bash = self.variant(data)
            if bad is None:   # a BOM before a comment line is harmless, before the key line it is not; just agree
                bad = bool(probs)
            self.assertEqual(bool(probs), bad, (name, probs))
            self.assertEqual(d, "deny" if bad else "-", (name, d, probs))
            self.assertEqual(pol, "unreadable" if bad else "allowed", name)
            self.assertEqual(bash.startswith("bad"), bad, (name, bash))

    def test_a_cp932_settings_file_is_named_by_check(self):
        E = self.E
        s = open(self.cfg, encoding="utf-8").read()
        open(self.cfg, "wb").write(s.encode("cp932", "replace"))
        mp = E.path(MS)
        d, _ctx = E.ai_edit(mp, open(mp, encoding="utf-8").read() + "\n\n回答率の段落。\n")
        self.assertEqual(d, "deny")
        self.assertTrue(any("UTF-8" in l for l in ng(E.rk("check").stdout)))


class CiAndTools(unittest.TestCase):
    def test_the_ai_never_writes_ci_or_git_hooks(self):
        E = Env()
        try:
            for pol in ("allowed", "unknown", "prohibited"):
                E.set_policy(pol)
                for rel in (".github/workflows/check.yml", ".github/workflows/new.yml", ".githooks/pre-commit", "tools/rk/rk.py"):
                    self.assertEqual(decision(E.pre("Write", {"file_path": E.path(rel), "content": "x\n"})), "deny", (pol, rel))
                for cmd in ("echo x >> .github/workflows/check.yml", "cp /dev/null .githooks/pre-push", "cd .gith?oks && echo x > pre-commit"):
                    self.assertEqual(decision(E.pre("Bash", {"command": cmd})), "deny", (pol, cmd))
        finally:
            E.cleanup()


class ToolWindows(unittest.TestCase):
    def setUp(self):
        self.E = Env()
        self.E.set_policy("unknown")
        self.E.rk("check")
        self.mp = self.E.path(MS)

    def tearDown(self):
        self.E.cleanup()

    def last_for(self, text):
        rows = [r for r in prov(self.E) if r.get("type") == "paragraph"]
        cur = open(self.mp, encoding="utf-8").read()
        self.assertIn(text, cur)
        return rows[-1] if rows else {}

    def test_an_allowed_call_overlapped_by_the_next_one_stays_the_ais(self):
        E = self.E
        ti = {"file_path": self.mp, "content": "x"}
        self.assertEqual(decision(E.pre("Write", ti, tuid="t1")), "ask")      # the student allows it
        append_ms(E, "\n\n図書館の利用者は増えた(許可された書き込み)。\n")
        notes = {"file_path": E.path("research", "notes.md"), "content": "y"}
        E.pre("Write", notes, tuid="t2")                                          # before t1's PostToolUse
        E.post("Write", ti, tuid="t1")
        E.post("Write", notes, tuid="t2")
        r = self.last_for("許可された書き込み")
        self.assertEqual(r.get("actor"), "ai", r)

    def test_a_call_that_never_finished_counts_with_the_ais_at_the_end_of_the_turn(self):
        E = self.E
        self.assertEqual(decision(E.pre("Write", {"file_path": self.mp, "content": "x"}, tuid="t1")), "ask")
        append_ms(E, "\n\n回答率の段落(PostToolUse の来なかった呼び出しの間)。\n")
        E.hook("stop-check.sh", {"hook_event_name": "Stop", "cwd": E.proj, "session_id": "t"})
        r = self.last_for("来なかった呼び出し")
        self.assertEqual((r.get("actor"), r.get("uncertain")), ("uncertain", True), r)
        facts = E.rk("facts").stdout
        self.assertIn("AI の可能性", facts)
        # after the turn, the student's own edit is the student's again
        append_ms(E, "\n\n学生が自分で足した段落。\n")
        E.rk("check")
        r = self.last_for("学生が自分で")
        self.assertEqual(r.get("actor"), "student", r)

    def test_a_command_outside_the_allow_list_asks_and_its_writes_are_recorded_as_the_ais(self):
        E = self.E
        E.set_policy("allowed")
        for cmd in ("tar -xf a.tar", "unzip a.zip", "xargs rm < list.txt", "find . -name '*.md' -exec sed -i s/a/b/ {} +",
                    "python3 -c 'print(1)'", "perl -e 1", "node -e 1", "git apply p.diff", "patch -p1 < p.diff"):
            self.assertIn(decision(E.pre("Bash", {"command": cmd})), ("ask", "deny"), cmd)
        code = "import os; p = os.path.join('manu' + 'script', 'main.md'); open(p, 'a').write('\\n\\n調査の回答率の段落(シェル)。\\n')"
        d, _ctx = E.ai_bash("python3 -c \"%s\"" % code, allow_ask=True)
        self.assertEqual(d, "ask")
        r = self.last_for("調査の回答率の段落(シェル)")
        self.assertEqual(r.get("actor"), "ai", r)


class LocalHosts(unittest.TestCase):
    def test_every_spelling_of_this_computer_is_denied(self):
        E = Env()
        try:
            for host in ("127.0.0.1:8765", "127.1:8765", "0x7f.1:8765", "2130706433:8765", "0177.0.0.1:8765", "[::1]:8765",
                         "[::ffff:7f00:1]:8765", "[::ffff:127.0.0.1]:8765", "[0:0:0:0:0:0:0:1]:8765", "localhost.localdomain:8765",
                         "app.localhost:8765", "0.0.0.0:8765"):
                self.assertEqual(decision(E.pre("Bash", {"command": "curl -s http://%s/api/view" % host})), "deny", host)
            self.assertEqual(decision(E.pre("Bash", {"command": "curl --resolve x:8765:127.0.0.1 http://x:8765/api/view"})), "deny")
            self.assertEqual(decision(E.pre("Bash", {"command": "nc 127.1 8765"})), "deny")
            self.assertEqual(execgate.loopback_targets("curl https://api.crossref.org/works?rows=1"), [])
            self.assertEqual(execgate.loopback_targets("head -n 0 manuscript/main.md"), [])
        finally:
            E.cleanup()


class DirectoryChanges(unittest.TestCase):
    def test_pushd_popd_cd_options_and_cdpath(self):
        E = Env()
        try:
            E.set_policy("allowed")
            for cmd in ("cd -P manuscript && echo x >> main.md", "pushd manuscript && echo x >> main.md",
                        "pushd /tmp && popd && echo x >> manuscript/main.md", "popd && echo x >> main.md",
                        "cd manuscript; pushd ..; echo x > manuscript/main.md", "cd -- manuscript && echo x >> main.md"):
                self.assertEqual(decision(E.pre("Bash", {"command": cmd})), "deny", cmd)
            f = execgate.scan("export CDPATH=/x; cd manuscript; echo a > notes.md", E.proj, PLUGIN, E.proj)
            self.assertIn("unknown_target", [k for k, _w in f])
            os.environ["CDPATH"] = E.base
            try:
                f = execgate.scan("cd thesis && echo a > notes.md", E.base, PLUGIN, E.proj)
            finally:
                os.environ.pop("CDPATH")
            self.assertIn("unknown_target", [k for k, _w in f])
        finally:
            E.cleanup()


class HumanCommandOptions(unittest.TestCase):
    def test_abbreviated_options_before_a_human_only_command(self):
        E = Env()
        try:
            for cmd in ("python3 tools/rk/rk.py --proj . confirm", "python3 tools/rk/rk.py --pro=. confirm",
                        "./rk --project . verify"):
                self.assertEqual(decision(E.pre("Bash", {"command": cmd})), "deny", cmd)
            r = E.run([sys.executable, "-B", os.path.join(E.proj, "tools", "rk", "rk.py"), "--proj", E.proj, "status"], cwd=E.proj)
            self.assertNotEqual(r.returncode, 0)   # no abbreviations: argparse refuses --proj
        finally:
            E.cleanup()


class ConsoleOnly(unittest.TestCase):
    def test_the_notebook_key_is_never_printed_when_there_is_no_console(self):
        from rklib import sign
        from notebook import server
        E = Env()
        old = (sign.TTY_OUT, sign.tty_available)
        try:
            sign.TTY_OUT = os.path.join(E.base, "no", "console")
            sign.tty_available = lambda: True
            with self.assertRaises(sign.SignError):
                sign.tty_print("secret")
            import io
            from contextlib import redirect_stdout, redirect_stderr
            out, err = io.StringIO(), io.StringIO()
            with redirect_stdout(out), redirect_stderr(err):
                rc = server.serve(E.proj, 0)
            self.assertEqual(rc, 3)
            self.assertNotIn("#k=", out.getvalue() + err.getvalue())
        finally:
            sign.TTY_OUT, sign.tty_available = old
            E.cleanup()


if __name__ == "__main__":
    unittest.main()
