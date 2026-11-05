"""A proposal can only unify notation/format; anything that changes the student's words, the marks
that carry meaning, or what a citation points at is refused when the proposal is made AND when it is applied.
Plus the decision flow: one hunk at a time, no accept-all key, signed records, the disclosure line."""
import json
import os
import sys
import unittest

from helpers import PASS, PLUGIN, Env

sys.path.insert(0, os.path.join(PLUGIN, "scripts", "rk"))
from rklib.proposals import check_hunk  # noqa: E402

REFS = [{"id": "walters2023", "author": [{"family": "Walters", "given": "W. H."}], "issued": {"date-parts": [[2023]]}},
        {"id": "other2023", "author": [{"family": "Other", "given": "A."}], "issued": {"date-parts": [[2023]]}},
        {"id": "yamada2020", "author": [{"family": "山田"}], "issued": {"date-parts": [[2020]]}}]


class Invariance(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.E = Env()
        with open(cls.E.path("sources", "references.json"), "w", encoding="utf-8") as f:
            json.dump(REFS, f)

    @classmethod
    def tearDownClass(cls):
        cls.E.cleanup()

    def ok(self, kind, old, new):
        return check_hunk(kind, [old], [new], proj=self.E.proj)[0]

    def test_quote_marks(self):
        self.assertFalse(self.ok("format", "「X」と述べる。", "Xと述べる。"))
        self.assertFalse(self.ok("format", 'He said "X".', "He said X."))

    def test_block_quote(self):
        self.assertFalse(self.ok("format", "> 要因 A が先にある。", "要因 A が先にある。"))

    def test_hidden_text(self):
        self.assertFalse(self.ok("format", "要因 A がある。", "<!-- 要因 A がある。 -->"))
        self.assertFalse(self.ok("format", "<!-- 要因 A がある。 -->", "要因 A がある。"))

    def test_sentence_end(self):
        self.assertFalse(self.ok("format", "原因である。", "原因である？"))
        self.assertFalse(self.ok("format", "原因である。", "原因である！"))
        self.assertFalse(self.ok("format", "Is it the cause?", "It is the cause."))

    def test_strike_through(self):
        self.assertFalse(self.ok("format", "効果はない。", "効果は~~ない~~。"))

    def test_new_citation(self):
        self.assertFalse(self.ok("citation", "現象 X は増えた。", "現象 X は増えた[@walters2023]。"))

    def test_other_work_same_year(self):
        self.assertFalse(self.ok("citation", "現象 X は増えた(Walters 2023)。", "現象 X は増えた[@other2023]。"))
        self.assertTrue(self.ok("citation", "現象 X は増えた(Walters 2023)。", "現象 X は増えた[@walters2023]。"))
        self.assertTrue(self.ok("citation", "現象 X は増えた(山田 2020)。", "現象 X は増えた[@yamada2020]。"))
        self.assertFalse(self.ok("citation", "現象 X は増えた(山田 2021)。", "現象 X は増えた[@yamada2020]。"))

    def test_format_only_is_accepted(self):
        self.assertTrue(self.ok("format", "要因 A，要因 B．", "要因 A、要因 B。"))
        self.assertTrue(self.ok("format", "１２３件", "123件"))
        self.assertTrue(self.ok("format", "Ａ社のＸＹ", "A社のXY"))
        self.assertTrue(self.ok("format", "Python を使う", "Pythonを使う"))
        self.assertTrue(self.ok("format", "値は１０．５であった．", "値は10.5であった。"))
        self.assertTrue(self.ok("format", "\u3000本文を書く。", "本文を書く。"))
        self.assertTrue(check_hunk("heading", ["# はじめに"], ["# 1 はじめに"], ["# はじめに"], ["# 1 はじめに"], [0], [0])[0])
        old = ["```mermaid", "flowchart LR", "  A --> B", "```"]
        new = ["```mermaid", "---", "config:", "  theme: default", "  look: classic", "  layout: dagre", "---", "flowchart LR", "  A --> B", "```"]
        self.assertTrue(check_hunk("diagram", old[1:2], new[1:8], old, new, [1], list(range(1, 8)))[0])

    def test_words_and_digits(self):
        self.assertFalse(self.ok("format", "検討する。", "詳しく検討する。"))
        self.assertFalse(self.ok("format", "123 件", "124 件"))
        self.assertFalse(self.ok("format", "本文", "# 本文"))
        self.assertFalse(check_hunk("heading", ["# はじめに"], ["# 1 序論"])[0])


# Every counterexample found in the independent adversarial verification, as (kind, old, new). Each must be
# REFUSED. The allow-list canonical form makes "a proposal cannot change a word, a number or a mark" true.
REFUSED = [
    ("format", "差は 10.5 ポイント", "差は 105 ポイント"),  # decimal point removed
    ("format", "変化は -5% であった", "変化は 5% であった"),  # minus sign
    ("format", "A = B ではない", "A ≠ B ではない"),
    ("format", "要因 A → 現象 X", "要因 A ← 現象 X"),  # direction of causation
    ("format", "| 条件 A | ○ |", "| 条件 A | × |"),
    ("format", "10²人", "102人"),
    ("format", "It is a part of it.", "It is apart of it."),
    ("format", "It was not able to work.", "It was notable to work."),
    ("format", "$y = a + b x$", "$y = a - b x$"),
    ("format", "$x^2$", "$x_2$"),
    ("format", "p < 0.05", "p > 0.05"),
    ("format", "50%", "50‰"),
    ("format", "1〜3 回", "13 回"),
    ("format", "彼は、急いで走る犬を追った。", "彼は急いで、走る犬を追った。"),  # a comma moved
    ("format", "例外がある。", "^[例外がある。]"),  # into a footnote
    ("format", "本文の一文。", "    本文の一文。"),  # indented into a code block
    ("format", "a", "\u0430"),  # Cyrillic look-alike
    ("format", "増える", "増\u200bえる"),  # zero-width space
    ("format", "増える", "増\u2060える"),                            # word joiner
    ("format", "増える。", "増える\u202e。"),                         # bidi override
    ("format", "増える。減る。", "増える、減る。"),  # two sentences into one
    ("format", "| 10 | 5 |", "| 105 | |"),  # a table cell boundary
    ("format", "㍻", "平成"),
    ("format", "½", "12"),
    ("format", "値は 10.5 である", "値は 10。5 である"),               # a decimal point is not a full stop
    ("format", "1,000 件", "1、000 件"),
    ("format", "1 000", "1000"),
    ("format", "A, B", "A B"),
    ("format", "「X」", "『X』"),
    ("format", 'He said "X".', "He said “X”."),
    ("format", "# 方法", "＃ 方法"),
    ("format", "> 引用", "＞ 引用"),
    ("format", "<!-- メモ -->", "＜!-- メモ --＞"),
    ("format", "1〜3", "1～3"),
    ("format", "ﬁnal", "final"),
    ("format", "①", "1"),
    ("heading", "# 方法", "## 方法"),  # level
    ("citation", "である[@walters2023]。", "である[@walters2023, p. 99]。"),  # a page invented
    ("citation", "である[@walters2023, p. 12]。", "である[@walters2023, p. 21]。"),
    ("citation", "である[@walters2023]。", "である[contra @walters2023]。"),
    ("citation", "(2023年の調査では増加)", "(2023年の調査では減少)"),
    ("citation", "A である。B である[@walters2023]。", "A である[@walters2023]。B である。"),  # moved
    ("citation", "増えた(Walters 2023)。", "増えた[@walters2023, p. 4]。"),
    ("citation", "増えた(Walters 2023, p. 4)。", "増えた[@walters2023, p. 5]。"),
    ("citation", "増えた(Walters 2023)。", "増えた[-@other2023]。"),
    ("citation", "増えた[@walters2023]。", "増えない[@walters2023]。"),
]
MULTI_REFUSED = [
    ("format", ["本文の一文"], ["本文の一文", "==="]),  # a paragraph into a heading
    ("format", ["一行目", "二行目"], ["一行目二行目"]),
    ("diagram", ["  A --> B"], ["  A <-- B"]),
]


class AllowList(unittest.TestCase):
    """The allow-list: every counterexample from the independent verification, a randomised check, and an end-to-end case."""
    @classmethod
    def setUpClass(cls):
        cls.E = Env()
        with open(cls.E.path("sources", "references.json"), "w", encoding="utf-8") as f:
            json.dump(REFS, f)

    @classmethod
    def tearDownClass(cls):
        cls.E.cleanup()

    def test_every_counterexample_is_refused(self):
        for kind, old, new in REFUSED:
            with self.subTest(old=old, new=new):
                ok, why = check_hunk(kind, [old], [new], proj=self.E.proj)
                self.assertFalse(ok, "%s: %r -> %r was accepted" % (kind, old, new))
                self.assertTrue(why)
        for kind, old, new in MULTI_REFUSED:
            with self.subTest(old=old, new=new):
                full_o, full_n = ["```mermaid"] + old + ["```"], ["```mermaid"] + new + ["```"]
                ok, _ = check_hunk(kind, old, new, full_o, full_n, list(range(1, 1 + len(old))),
                                   list(range(1, 1 + len(new))), proj=self.E.proj)
                self.assertFalse(ok, "%r -> %r was accepted" % (old, new))

    def test_any_other_character_change_is_refused(self):
        """Random single-character insertions, deletions and substitutions that are not one of the allowed
        transforms are always refused (the claim 'a proposal cannot change a word, a number or a mark')."""
        import random
        rnd = random.Random(20261104)
        base = ["要因 A は現象 X の 10.5% を説明する(Walters 2023)。", "It is a part of the 2nd model, p < 0.05.",
                "| 条件 | ○ | -5 |", "$y = a + b x^2$ と書く。"]
        pool = list("0123456789.,-+=<>≠→←○×%‰^_$|*~#>「」『』()[]@!?、。，．abcXYZ要因現象ア\u200b\u0430 ")
        allowed_pairs = {("、", "，"), ("，", "、"), ("。", "．"), ("．", "。")}
        tried = 0
        for _ in range(3000):
            line = rnd.choice(base)
            i = rnd.randrange(len(line) + 1)
            op = rnd.choice(("ins", "del", "sub"))
            c = rnd.choice(pool)
            if op == "ins":
                new = line[:i] + c + line[i:]
            elif op == "del" and i < len(line):
                new = line[:i] + line[i + 1:]
            elif i < len(line) and line[i] != c and (line[i], c) not in allowed_pairs:
                new = line[:i] + c + line[i + 1:]
            else:
                continue
            removed = line[i:i + 1] if op != "ins" else ""
            added = c if op != "del" else ""
            # skip changes that ARE allowed: a space next to Japanese text, or nothing at all
            if (removed + added).strip() == "" :
                continue
            tried += 1
            ok, _ = check_hunk("format", [line], [new])
            self.assertFalse(ok, "accepted: %r -> %r" % (line, new))
        self.assertGreater(tried, 1500)

    def test_mixed_hunk_is_refused_end_to_end(self):
        """A hunk mixing allowed width/punctuation changes with 10.5%→105%, =→≠ and →→← cannot be made."""
        E = Env()
        try:
            E.setup()
            E.write("manuscript/main.md", "# はじめに\n\n値は１０．５％で，A = B，要因 A → 現象 X．\n\n増えた[@walters2023]。\n")
            with open(E.path("sources", "references.json"), "w", encoding="utf-8") as f:
                json.dump(REFS, f)
            E.post("Bash", {"command": "true"}, tuid="i")
            r = E.rk("propose", "start", "manuscript/main.md")
            self.assertEqual(r.returncode, 0, r.stderr)
            tok = r.stdout.splitlines()[0].split("/")[2]
            with open(E.path(r.stdout.splitlines()[0]), "w", encoding="utf-8") as f:
                f.write("# はじめに\n\n値は105%で、A ≠ B、要因 A ← 現象 X。\n\n増えた[@walters2023]。\n")
            r = E.rk("propose", "finish", tok, "--kind", "format", "--why", "全角半角と句読点の統一")
            self.assertNotEqual(r.returncode, 0)
            self.assertIn("提案にできない", r.stderr)
            r = E.rk("propose", "start", "manuscript/main.md")
            tok = r.stdout.splitlines()[0].split("/")[2]
            with open(E.path(r.stdout.splitlines()[0]), "w", encoding="utf-8") as f:
                f.write("# はじめに\n\n値は１０．５％で，A = B，要因 A → 現象 X．\n\n増えた[@walters2023, p. 99]。\n")
            r = E.rk("propose", "finish", tok, "--kind", "citation", "--why", "引用の書式の統一")
            self.assertNotEqual(r.returncode, 0)
            # a hand-written proposal file that slips the change in is refused again at apply time
            E.write("proposals/P0099-format-main.diff", "\n".join([
                "# rk-proposal: 1", "# id: P0099", "# status: pending", "# kind: format", "# target: manuscript/main.md",
                "# by: ai", "# why: 表記の統一", "--- a/manuscript/main.md", "+++ b/manuscript/main.md",
                "@@ -3,1 +3,1 @@ 句読点", "-値は１０．５％で，A = B，要因 A → 現象 X．", "+値は105%で、A ≠ B、要因 A ← 現象 X。", ""]))
            rc, out = E.tty(["apply"], [PASS])
            self.assertIn("採用できない", out)
            self.assertNotIn("値は105%", E.read("manuscript", "main.md"))
        finally:
            E.cleanup()

    def test_claim_in_docs_matches_the_check(self):
        """The README and the disclosure say a proposal cannot change words or numbers; that must stay true."""
        readme = open(os.path.join(PLUGIN, "README.md"), encoding="utf-8").read()
        self.assertIn("語・数字", readme)
        for kind, old, new in REFUSED[:10]:
            self.assertFalse(check_hunk(kind, [old], [new], proj=self.E.proj)[0])


class Flow(unittest.TestCase):
    def setUp(self):
        self.E = Env()
        self.E.setup()
        self.E.write("manuscript/main.md", "# はじめに\n\n要因 A，要因 B．\n\n１２３件を見た．\n\n「X」と述べる．\n")
        self.E.post("Bash", {"command": "true"}, tuid="i")

    def tearDown(self):
        self.E.cleanup()

    def propose(self, new_text, kind="format"):
        r = self.E.rk("propose", "start", "manuscript/main.md")
        self.assertEqual(r.returncode, 0, r.stderr)
        work = self.E.path(r.stdout.splitlines()[0])
        with open(work, "w", encoding="utf-8") as f:
            f.write(new_text)
        tok = r.stdout.splitlines()[0].split("/")[2]
        return self.E.rk("propose", "finish", tok, "--kind", kind, "--why", "句読点と数字の表記の統一(見本)")

    def test_content_change_cannot_be_proposed(self):
        r = self.propose("# はじめに\n\n要因 A，要因 B，要因 C．\n\n１２３件を見た．\n\n「X」と述べる．\n")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("提案にできない", r.stderr)
        r = self.propose("# はじめに\n\n要因 A，要因 B．\n\n１２３件を見た．\n\nXと述べる．\n")
        self.assertNotEqual(r.returncode, 0)

    def test_one_by_one_no_accept_all_and_signed(self):
        r = self.propose("# はじめに\n\n要因 A、要因 B。\n\n123件を見た。\n\n「X」と述べる。\n")
        self.assertEqual(r.returncode, 0, r.stderr)
        rc, out = self.E.tty(["apply"], ["a", "y", "n", "y", PASS])  # "a" is not a key: the prompt repeats
        self.assertEqual(rc, 0, out[-2000:])
        self.assertNotIn("[a]", out)
        ms = self.E.read("manuscript", "main.md")
        self.assertIn("要因 A、要因 B。", ms)
        self.assertIn("１２３件を見た．", ms)  # the rejected hunk
        recs = [json.loads(l) for l in self.E.read(".ryukoku", "signoffs.jsonl").splitlines() if l.strip()]
        hunks = [r for r in recs if r["kind"] == "hunk"]
        self.assertEqual(sorted(r["decision"] for r in hunks), ["accepted", "accepted", "rejected"])
        inv = self.E.read("disclosure", "ai-involvement.jsonl")
        self.assertEqual(inv.count('"proposal"'), 2)
        r = self.E.rk("check")
        self.assertEqual(r.returncode, 0, r.stdout)  # the accepted change is not reported as an AI change
        facts = self.E.rk("facts").stdout
        self.assertIn("形式の提案のうち自分が採用した箇所: 2", facts)

    def test_hand_edited_proposal_refused_at_apply(self):
        r = self.propose("# はじめに\n\n要因 A、要因 B。\n\n１２３件を見た．\n\n「X」と述べる．\n")
        self.assertEqual(r.returncode, 0, r.stderr)
        pdir = self.E.path("proposals")
        f = [x for x in os.listdir(pdir) if x.endswith(".diff")][0]
        p = os.path.join(pdir, f)
        s = open(p, encoding="utf-8").read().replace("+要因 A、要因 B。", "+要因 A、要因 B、要因 C。")
        with open(p, "w", encoding="utf-8") as fh:
            fh.write(s)
        rc, out = self.E.tty(["apply"], [PASS])
        self.assertIn("採用できない", out)
        self.assertNotIn("要因 C", self.E.read("manuscript", "main.md"))


if __name__ == "__main__":
    unittest.main()


class StyleExtraction(unittest.TestCase):
    """A rule extracted from a guide stays a proposal until the student approves and signs it."""

    def test_extracted_rule_applies_only_after_signed_approval(self):
        E = Env()
        try:
            E.setup()
            fixture = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures", "econ-guide-summary.md")
            self.assertIn("rishu.ryukoku.ac.jp", open(fixture, encoding="utf-8").read())
            E.write("proposals/style-rules.yml", 'version: 1\nrules:\n  - id: "ending"\n    kind: "ending_style"\n    value: "である"\n'
                    '    lang: "ja"\n    source: "tests/fixtures/econ-guide-summary.md(公開資料の要約)"\n    page: "要約 2 行目"\n'
                    '    quote: "文体は「である体」"\n    confidence: "high"\n    status: "proposed"\n')
            E.write("manuscript/main.md", "# はじめに\n\n現象 X を検討します。\n")
            self.assertEqual(E.rk("rules", "validate").returncode, 0)
            before = E.rk("lint").stdout
            self.assertNotIn("[ending]", before)
            self.assertIn("未承認のため適用していない規則: ending", before)
            rc, out = E.tty(["style"], ["a", PASS])
            self.assertEqual(rc, 0, out[-1500:])
            self.assertIn("文体は「である体」", out)  # the evidence is shown before the decision
            after = E.rk("lint").stdout
            self.assertIn("[ending]", after)
            self.assertEqual(E.rk("check").returncode, 0)
            # an approved rule edited afterwards is no longer applied, and check reports it
            p = E.path(".ryukoku", "style.yml")
            s = open(p, encoding="utf-8").read().replace('value: "である"', 'value: "です・ます"')
            with open(p, "w", encoding="utf-8") as f:
                f.write(s)
            r = E.rk("check")
            self.assertEqual(r.returncode, 1)
            self.assertIn("署名つきの承認がない", r.stdout)
        finally:
            E.cleanup()
