"""v2: claim cards, provenance, the mechanical part of the verification (format, swap candidates, citations and
numbers), the citation-key check against the ledger, the disclosure facts, the two signed decisions and the light
confirmations, the deferred passphrase, and the hooks' guidance after a manuscript write. All text is placeholder
("現象 X", "要因 A")."""
import csv
import json
import os
import sys
import unittest

from helpers import PASS, PLUGIN, Env, decision, reason

sys.path.insert(0, os.path.join(PLUGIN, "scripts", "rk"))
from rklib import claimcards, paragraphs, sign, verification  # noqa: E402

MS = "manuscript/main.md"
CARD = """---
id: C001
status: draft
created: 2026-11-05
---
# 主張
要因 A は現象 X の一因となりうる。

## 範囲と限定
2010 年代の事例に限る。

## 必要な根拠
- 年ごとの記録 @w2023

## 論拠
- 要因 A が先に起きている

## 予想される反論
- [ai_suggested] 逆の因果(現象 X が要因 A を生む)

## 新規性の見込み
未調査

## 学生の言葉の原文
> 要因 A が現象 X の原因の一つだと思う。2010 年代の話として。
"""


def set_ledger(E, status="IDENTITY_CONFIRMED", citekey="w2023"):
    p = E.path("sources", "register.csv")
    rows = list(csv.DictReader(open(p, encoding="utf-8")))
    fields = open(p, encoding="utf-8").readline().strip().split(",")
    for r in rows:
        r["machine_status"] = status
        r["citekey"] = citekey
    with open(p, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)


def prov(E):
    p = E.path(".ryukoku", "provenance.jsonl")
    return [json.loads(l) for l in open(p, encoding="utf-8") if l.strip()] if os.path.exists(p) else []


class Units(unittest.TestCase):
    def test_paragraph_blocks_and_diff(self):
        t = "---\ntitle: x\n---\n\n# はじめに {#sec-intro}\n\n段落 1。\n続き。\n\n<!-- 注釈\n二行 -->\n\n```\na\n\nb\n```\n\n段落 2。\n"
        bs = paragraphs.blocks(t)
        self.assertEqual([b["kind"] for b in bs], ["frontmatter", "heading", "paragraph", "comment", "code", "paragraph"])
        self.assertEqual(bs[2]["section"], "はじめに")
        self.assertEqual((bs[2]["start"], bs[2]["end"]), (7, 8))
        d = paragraphs.diff(t, t.replace("段落 2。", "段落 2 を直した。") + "\n段落 3。\n")
        self.assertEqual([x["op"] for x in d], ["replace", "insert"])

    def test_card_parse_digest_and_problems(self):
        c = claimcards.parse_text(CARD, "C001.md")
        self.assertEqual(claimcards.problems(c), [])
        dg = claimcards.digest(c)
        # an [ai_suggested] candidate is not part of what the student confirms
        c2 = claimcards.parse_text(CARD.replace("逆の因果", "逆の因果の可能性"), "C001.md")
        self.assertEqual(claimcards.digest(c2), dg)
        # removing the mark makes the AI's candidate look like the student's: the digest changes
        c3 = claimcards.parse_text(CARD.replace("[ai_suggested] ", ""), "C001.md")
        self.assertNotEqual(claimcards.digest(c3), dg)
        c4 = claimcards.parse_text(CARD.replace("> 要因 A が", "> [ai_suggested] 要因 A が"), "C001.md")
        self.assertTrue(claimcards.problems(c4))

    def test_swap_candidates(self):
        c = claimcards.parse_text(CARD, "C001.md")
        kinds = lambda t: {k for k, _j, _e in verification.swap_check(c, t)}  # noqa: E731
        self.assertEqual(kinds("2010 年代の事例では、要因 A は現象 X の一因となりうる。"), set())
        self.assertIn("強さ", kinds("2010 年代、要因 A は必ず現象 X を生む。"))
        self.assertIn("限定", kinds("2010 年代、要因 A は現象 X の原因である。"))
        self.assertIn("範囲", kinds("要因 A は現象 X の一因となりうる。"))
        up = claimcards.parse_text(CARD.replace("一因となりうる", "増加の一因となりうる"), "C001.md")
        self.assertTrue(any(k == "向き" for k, _j, _e in verification.swap_check(up, "2010 年代、要因 A は現象 X の減少の一因となりうる。")))

    def test_verification_lint(self):
        good = ("## 0. 機械\n- [致命] すり替え L1: 候補 / 根拠: claims/C001.md\n## 1. 論理\n- [重要] W1 L3: 論拠がない / 根拠: 本文 L3\n"
                "## 2. 根拠の対応\n- [重要] 根拠の対応 L3: 抜粋は主張を支えない(言い過ぎ) / 根拠: excerpts/s001.txt\n"
                "- [軽微] 根拠の対応 L5: 未照合 / 根拠: 抜粋なし\n## 3. 反証\n検索していない\n## 4. 新規性・位置づけ\n記録した検索の範囲では見当たらない(S001)\n"
                "## 5. すり替え\n- [致命] すり替え L1: 「必ず」が足されている / 根拠: claims/C001.md\n## 6. 修正案\n- 一因となりうる、に戻す\n")
        errs, warns = verification.lint_text(good)
        self.assertEqual(errs, [], errs)
        bad = (good.replace("[重要] W1", "[大] W1").replace(" / 根拠: 本文 L3", "")
               .replace("言い過ぎ) / 根拠: excerpts/s001.txt", "支えない) / 根拠: 抜粋なし").replace("[軽微] 根拠の対応 L5: 未照合", "[軽微] 根拠の対応 L5: 原典はこの主張を支える")
               .replace("記録した検索の範囲では見当たらない(S001)", "この主張は新規である"))
        errs, _w = verification.lint_text(bad)
        msgs = " ".join(errs)
        for want in ("重大度", "根拠(/ 根拠", "抜粋", "新規性"):
            self.assertIn(want, msgs)
        _e, warns = verification.lint_text(good.replace("- [致命] すり替え L1: 「必ず」が足されている / 根拠: claims/C001.md\n", ""))
        self.assertTrue(any("すり替え" in w for w in warns))


class Project(unittest.TestCase):
    def setUp(self):
        self.E = Env()
        self.E.setup()  # allowed, passphrase registered
        self.E.rk("ledger", "add-source", "--doi", "10.1038/s41598-023-41032-5", "--title", "A placeholder title", "--year", "2023",
                  "--citekey", "w2023")
        self.E.post("Bash", {"command": "true"}, tuid="init")

    def tearDown(self):
        self.E.cleanup()

    def confirm_card(self, text=CARD):
        os.makedirs(self.E.path("claims"), exist_ok=True)
        open(self.E.path("claims", "C001.md"), "w", encoding="utf-8").write(text)
        rc, out = self.E.tty(["confirm"], ["y"])
        self.assertEqual(rc, 0, out[-1500:])
        self.assertNotIn("合言葉(入力は表示されない)", out)

    def test_materials_must_be_confirmed_and_flow_into_provenance(self):
        os.makedirs(self.E.path("claims"), exist_ok=True)
        open(self.E.path("claims", "C001.md"), "w", encoding="utf-8").write(CARD)
        r = self.E.rk("provenance", "materials", "--file", MS, "--claims", "C001", "--sources", "S001")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("確認済みでない", r.stderr)
        r = self.E.rk("provenance", "materials", "--file", MS, "--claims", "C001", "--sources", "S999")
        self.assertNotEqual(r.returncode, 0)
        self.confirm_card()
        r = self.E.rk("provenance", "materials", "--file", MS, "--claims", "C001", "--sources", "S001")
        self.assertEqual(r.returncode, 0, r.stderr)
        d, ctx = self.E.ai_edit(self.E.path(MS), self.E.read(MS) + "\n2010 年代の事例では、要因 A は必ず現象 X の唯一の原因である [@w2023]。\n")
        self.assertEqual(d, "-")
        ai = [e for e in prov(self.E) if e["actor"] == "ai"]
        self.assertEqual(ai[-1]["materials"]["claims"], ["C001"])
        self.assertIn("S001", ai[-1]["materials"]["sources"])
        # the mechanical check right after the write shows the swap candidate as fatal and the ledger state
        self.assertIn("[致命] すり替え", ctx)
        self.assertIn("必ず", ctx)
        self.assertIn("IDENTITY_CONFIRMED 未満", ctx)
        # the scaffold carries the same facts and lints as a skeleton (sections present)
        r = self.E.rk("verification", "scaffold", MS)
        self.assertEqual(r.returncode, 0, r.stderr)
        path = [l for l in r.stdout.split() if l.startswith("review/verification/")][0].rstrip("(")
        txt = self.E.read(path.split("(")[0])
        self.assertIn("## 5.", txt)
        self.assertIn("[致命] すり替え", txt)

    def test_restored_ai_paragraph_is_not_re_attributed_to_the_student(self):
        # a branch switch or a pull brings back a paragraph the AI wrote: it stays the AI's
        before = self.E.read(MS)
        self.E.ai_edit(self.E.path(MS), before + "\nAI の段落(要因 A)。\n")
        with_ai = self.E.read(MS)
        open(self.E.path(MS), "w", encoding="utf-8").write(before)  # e.g. git switch to another branch
        self.E.rk("provenance", "sync")
        open(self.E.path(MS), "w", encoding="utf-8").write(with_ai)  # and back
        self.E.rk("provenance", "sync")
        self.assertIn("ai_wrote", self.E.rk("provenance", "show").stdout)

    def test_stop_hook_reminds_after_a_manuscript_write(self):
        self.E.ai_edit(self.E.path(MS), self.E.read(MS) + "\n要因 A の段落。\n")
        r = self.E.hook("stop-check.sh", {"cwd": self.E.proj, "hook_event_name": "Stop"})
        self.assertEqual(decision(r), "block")
        self.assertIn("由来", reason(r))
        r = self.E.hook("stop-check.sh", {"cwd": self.E.proj, "hook_event_name": "Stop", "stop_hook_active": True})
        self.assertEqual(decision(r), "-")

    def test_citation_keys_against_the_ledger(self):
        with open(self.E.path(MS), "a", encoding="utf-8") as f:
            f.write("\n現象 X は増えている [@w2023, p. 3]。未知の文献もある [@nobody1999]。\n")
        r = self.E.rk("check")
        self.assertEqual(r.returncode, 0, r.stdout)  # draft: warnings
        self.assertIn("nobody1999", r.stdout)
        set_ledger(self.E, "CANDIDATE")
        r = self.E.rk("check", "--submit")
        ng = [l for l in r.stdout.splitlines() if l.startswith("NG")]
        self.assertTrue(any("nobody1999" in l for l in ng), r.stdout)
        self.assertTrue(any("w2023" in l and "IDENTITY_CONFIRMED 未満" in l for l in ng), r.stdout)
        set_ledger(self.E, "IDENTITY_CONFIRMED")
        r = self.E.rk("check", "--submit")
        self.assertFalse(any("w2023" in l and "IDENTITY_CONFIRMED" in l for l in r.stdout.splitlines() if l.startswith("NG")), r.stdout)

    def test_numbers_without_a_source_are_warned(self):
        with open(self.E.path(MS), "a", encoding="utf-8") as f:
            f.write("\n現象 X は 45% の事例で見られた。\n\n現象 X は 12.5 倍になった [@w2023]。\n\n件数は 30 件だった[^1]。\n\n[^1]: data/processed/x.csv の集計\n")
        r = self.E.rk("check")
        self.assertIn("30 件", r.stdout)   # a data reference counts only when the file exists
        os.makedirs(self.E.path("data", "processed"), exist_ok=True)
        open(self.E.path("data", "processed", "x.csv"), "w").write("n\n30\n")
        r = self.E.rk("check")
        self.assertIn("45%", r.stdout)
        self.assertNotIn("12.5", r.stdout)
        self.assertNotIn("30 件", r.stdout)
        r = self.E.rk("lint", MS)
        self.assertIn("[数字]", r.stdout)

    def test_light_and_signed_records(self):
        self.assertTrue(sign.needs_signature("source", "VERIFIED"))
        self.assertTrue(sign.needs_signature("presubmit", "ready"))
        self.assertFalse(sign.needs_signature("card", "confirmed"))
        self.assertFalse(sign.needs_signature("hunk", "accepted"))
        # an unsigned record that claims VERIFIED is an error, even written by a person's script
        rec = {"v": 2, "kind": "source", "subject": "S001", "decision": "VERIFIED", "digest": "x", "detail": {}, "role": "student",
               "key": "", "signer": "s", "ts": "2026-11-05T00:00:00+0000", "method": "tty", "note": "", "sig": ""}
        rec["id"] = "CF-" + __import__("hashlib").sha256(sign.payload(rec)).hexdigest()[:16]
        with open(self.E.path(".ryukoku", "signoffs.jsonl"), "a", encoding="utf-8") as f:
            f.write(json.dumps(rec) + "\n")
        r = self.E.rk("check")
        self.assertEqual(r.returncode, 1)
        self.assertIn("合言葉の署名が要る", r.stdout)

    def test_tampered_light_record_is_an_error(self):
        lines = open(self.E.path(".ryukoku", "signoffs.jsonl"), encoding="utf-8").read().splitlines()
        rec = json.loads([l for l in lines if '"kind": "config"' in l][0])
        self.assertEqual(rec["sig"], "")
        rec["note"] = "changed afterwards"
        with open(self.E.path(".ryukoku", "signoffs.jsonl"), "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        r = self.E.rk("check")
        self.assertEqual(r.returncode, 1)
        self.assertIn("id が内容と合わない", r.stdout)

    def test_disclosure_facts_from_provenance_and_presubmit_covers_the_statement(self):
        self.E.ai_edit(self.E.path(MS), self.E.read(MS) + "\n# 考察\n\nAI が書いた段落(要因 A)。\n")
        with open(self.E.path(MS), "a", encoding="utf-8") as f:
            f.write("\n自分で書いた段落(要因 B)。\n")
        r = self.E.rk("facts")
        self.assertIn("5. 原稿の由来", r.stdout)
        self.assertIn("AI が新しく書いた 1", r.stdout)
        self.assertIn("考察", r.stdout)
        os.makedirs(self.E.path("disclosure"), exist_ok=True)
        st = self.E.path("disclosure", "statement.md")
        self.assertEqual(decision(self.E.pre("Write", {"file_path": st, "content": "x"})), "-")  # the AI may draft it
        open(st, "w", encoding="utf-8").write("# AI の利用\nClaude Code で考察の一段落を下書きした。\n")
        rc, out = self.E.tty(["signoff"], ["y"] + ["y"] * 8 + [PASS])
        self.assertEqual(rc, 0, out[-2500:])
        self.assertIn("開示文: disclosure/statement.md", out)
        ng = [l for l in self.E.rk("check", "--submit").stdout.splitlines() if l.startswith("NG")]
        self.assertFalse(any("提出前の最終確認" in l for l in ng), ng)
        open(st, "a", encoding="utf-8").write("追記。\n")
        ng = [l for l in self.E.rk("check", "--submit").stdout.splitlines() if l.startswith("NG")]
        self.assertTrue(any("提出前の最終確認" in l for l in ng), ng)


class Deferred(unittest.TestCase):
    def test_passphrase_is_registered_at_the_first_verified(self):
        E = Env()
        try:
            out = E.setup(register=False)
            self.assertNotIn("新しい合言葉", out)
            self.assertFalse(os.path.exists(E.path(".ryukoku", "signers.json")) and json.load(open(E.path(".ryukoku", "signers.json")))["signers"])
            self.assertEqual(E.rk("check").returncode, 0)  # course policy and opt-out are recorded without a passphrase
            E.rk("ledger", "add-source", "--doi", "10.1038/s41598-023-41032-5", "--title", "A placeholder title", "--year", "2023")
            rc, out = E.tty(["verify"], ["v", PASS, PASS, PASS])
            self.assertEqual(rc, 0, out[-2500:])
            self.assertIn("まだ登録していないので、ここで登録する", out)
            recs = [json.loads(l) for l in E.read(".ryukoku", "signoffs.jsonl").splitlines() if l.strip()]
            self.assertTrue(any(r["kind"] == "source" and r["decision"] == "VERIFIED" and r["sig"] for r in recs))
            r = E.rk("check")
            self.assertEqual(r.returncode, 0, r.stdout)
        finally:
            E.cleanup()


class Prompts(unittest.TestCase):
    def test_writing_request_follows_the_policy(self):
        E = Env()
        try:
            E.set_policy("allowed")
            r = reason(E.prompt("考察の段落を書いて"))
            self.assertIn("draft-writer", r)
            self.assertIn("材料", r)
            E.set_policy("prohibited")
            r = reason(E.prompt("考察の段落を書いて"))
            self.assertIn("prohibited", r)
            self.assertIn("原稿は書かない", r)
        finally:
            E.cleanup()


class Hardening(unittest.TestCase):
    """Regression tests of the adversarial review of v2 (shell writes past the string checks, forged provenance lines,
    symlinked files, other field names, the human-only list, the notebook key, citations, figures, the settings,
    long tool calls)."""

    REVIEW_CMDS = ["echo x >> man\\uscript/main.md",
                   "cd m?nuscript && echo 'AI paragraph under prohibited.' >> main.md",
                   "cd .r?ukoku && echo '{}' >> signoffs.jsonl",
                   "cd .[r]yukoku && echo 'ai_policy: allowed' >> config.yml",
                   "cd th?nking && echo x >> log.md",
                   "cd res?arch && echo x > q\\uestions.md",
                   "cd t?ols/rk && echo '#x' >> rk.py",
                   "cd .r?ukoku && printf '%s\\n' x >> provenance.jsonl",
                   'cd "$D" && echo x >> signoffs.jsonl',
                   "D=.ryu; echo x >> \"${D}koku/provenance.jsonl\"",
                   "cp /dev/null m?nuscript/main.md",
                   "sed -i s/a/b/ m?nuscript/main.md"]

    def test_shell_writes_to_protected_paths_are_denied_under_every_policy(self):
        E = Env()
        try:
            for pol in ("prohibited", "allowed"):
                E.set_policy(pol)
                for i, c in enumerate(self.REVIEW_CMDS):
                    with self.subTest(policy=pol, c=c):
                        self.assertEqual(decision(E.pre("Bash", {"command": c}, tuid="h%d" % i)), "deny")
            # reading stays possible, and a write whose place is unknown asks (denied when prohibited)
            self.assertEqual(decision(E.pre("Bash", {"command": "cd .r?ukoku; tail -n 1 provenance.jsonl"})), "-")
            E.set_policy("allowed")
            self.assertEqual(decision(E.pre("Bash", {"command": 'cd "$D" && echo x >> notes.txt'})), "ask")
            E.set_policy("prohibited")
            self.assertEqual(decision(E.pre("Bash", {"command": 'cd "$D" && echo x >> notes.txt'})), "deny")
        finally:
            E.cleanup()

    def test_path_classes_agree_with_the_hook(self):
        from rklib import paths
        import subprocess as sp
        sample = ["manuscript/main.md", "Manuscript/x.md", ".ryukoku/signoffs.jsonl", "tools/rk/rk.py", "rk", "rk.cmd",
                  "research/questions.md", "research/plan.md", "research/search-log.jsonl", "thinking/log.md",
                  "disclosure/statement.md", "disclosure/ai-involvement.jsonl", "review/annotations.json",
                  "review/verification/a.md", "sources/register.csv", "sources/references.json", "data/raw/a.csv",
                  ".github/workflows/check.yml", ".githooks/pre-push", "proposals/x.diff", "claims/C001.md",
                  "excerpts/a.txt", "notes.txt", ".git/config", ".claude/settings.json", "x/.bashrc", "build/a.docx"]
        lib = os.path.join(PLUGIN, "scripts", "hooks", "lib.sh")
        script = ". %s; for r in %s; do path_class \"$(norm_path \"$r\")\"; done" % (lib, " ".join(sample))
        out = sp.run(["bash", "-c", script], capture_output=True, text=True).stdout.split()
        self.assertEqual(out, [paths.classify(r) for r in sample])

    def test_forged_provenance_lines_are_detected(self):
        E = Env()
        try:
            E.set_policy("allowed")
            E.post("Bash", {"command": "true"}, tuid="i0")
            E.ai_edit(E.path(MS), E.read(MS) + "\nAI の段落(要因 A)。\n", tuid="w1")
            import hashlib
            p = E.path(".ryukoku", "provenance.jsonl")
            last = [l for l in open(p, encoding="utf-8") if l.strip()][-1].rstrip("\n")
            ai = json.loads(last)
            forged = dict(ai, kind="student_wrote", actor="student", estimated=True, tool="editor",
                          prev=hashlib.sha256(last.encode()).hexdigest())
            line = json.dumps(forged, ensure_ascii=False, sort_keys=True)
            # the prompt-less shell route is denied ...
            self.assertEqual(decision(E.pre("Bash", {"command": "cd .r?ukoku && printf '%%s\\n' '%s' >> provenance.jsonl" % line})), "deny")
            # ... and a script the student allowed, which keeps the chain intact, is still caught
            E.ai_write(E.path("scratch", "f.py"), "import sys\nopen('.ryu'+'koku/provenance.jsonl','a').write(sys.argv[1]+'\\n')\n", tuid="fw")
            import shlex
            d, ctx = E.ai_bash("python3 scratch/f.py " + shlex.quote(line), tuid="f1", allow_ask=True)
            self.assertEqual(d, "ask")
            self.assertIn("Plugin の道具が書いていない行", ctx)
            r = E.rk("check")
            self.assertEqual(r.returncode, 1, r.stdout)
            self.assertIn("検知した変更が未判断", r.stdout)
        finally:
            E.cleanup()

    def test_symlinked_file_and_other_field_names(self):
        E = Env()
        try:
            E.set_policy("prohibited")
            P = E.proj
            os.symlink(os.path.join(P, "manuscript", "main.md"), os.path.join(P, "research", "file.md"))
            self.assertEqual(decision(E.pre("Write", {"file_path": P + "/research/file.md", "content": "x"})), "deny")
            for ti in ({"filename": P + "/manuscript/main.md", "content": "x"},
                       {"source": P + "/research/a.md", "destination": P + "/manuscript/main.md"},
                       {"target_file": "manuscript/main.md", "text": "x"},
                       {"out": P + "/.ryukoku/signoffs.jsonl"}):
                with self.subTest(ti=ti):
                    self.assertEqual(decision(E.pre("mcp__fs__write_file", ti)), "deny")
            # a path-looking text in a content field is not taken for the target
            self.assertEqual(decision(E.pre("mcp__fs__write_file", {"path": P + "/notes/a.md", "content": "see manuscript/main.md"})), "-")
        finally:
            E.cleanup()

    def test_one_list_of_human_only_commands(self):
        from rklib import execgate
        from rklib.common import HUMAN_COMMANDS
        sys.path.insert(0, os.path.join(PLUGIN, "scripts", "rk"))
        import rk as rkmod
        listed = [l.strip() for l in open(os.path.join(PLUGIN, "scripts", "rk", "human-commands.txt"), encoding="utf-8")
                  if l.strip() and not l.startswith("#")]
        self.assertEqual(set(listed), set(HUMAN_COMMANDS))
        self.assertEqual(set(listed), set(execgate.HUMAN))
        self.assertEqual(set(listed), set(rkmod.HUMAN))
        self.assertTrue({"confirm", "unattributed", "review", "notebook"} <= set(listed))
        E = Env()
        try:
            for c in ['python3 "%s/scripts/rk/rk.py" --project "%s" confirm' % (PLUGIN, E.proj),
                      'python3 "%s/scripts/rk/rk.py" --project=%s confirm C001' % (PLUGIN, E.proj),
                      "./rk --project . confirm", "python3 tools/rk/rk.py --project . signoff",
                      "python3 tools/rk/rk.py unattributed", "python3 tools/rk/rk.py review"]:
                with self.subTest(c=c):
                    self.assertEqual(decision(E.pre("Bash", {"command": c})), "deny")
            # an argument that happens to be a human command's name is not a subcommand
            self.assertEqual(decision(E.pre("Bash", {"command": "python3 tools/rk/rk.py annot flag --doc manuscript/main.md --quote 'x' --code C1 --comment 'verify したか'"})), "-")
        finally:
            E.cleanup()

    def test_loopback_api_calls_are_denied_in_any_spelling(self):
        E = Env()
        try:
            for url in ("http://127.0.0.1:8765/api/sign", "http://127.1:8765/api/sign", "http://localhost:9/api/state",
                        "http://[::1]:5000/api/view", "http://0x7f000001:80/api/sign", "http://2130706433:80/api/sign",
                        "http://127.0.0.2/api/sign"):
                for tool in ("curl -s %s", "wget -q -O- %s", "python3 -c 'import urllib.request as u; u.urlopen(\"%s\")'"):
                    c = tool % url
                    with self.subTest(c=c):
                        self.assertEqual(decision(E.pre("Bash", {"command": c})), "deny")
        finally:
            E.cleanup()

    def test_rendered_bibliography_entries_must_be_confirmed(self):
        from rklib import citations
        keys, star = citations.extract("---\nnocite: |\n  @extra1, @{odd key}\n---\n本文 [@{w 2023}, p. 3] と @plain の引用。図 @fig:x。\n")
        self.assertEqual(keys, {"extra1", "odd key", "w 2023", "plain"})
        self.assertFalse(star)
        self.assertTrue(citations.extract("---\nnocite: '@*'\n---\nx\n")[1])
        self.assertEqual(citations.extract("---\nnocite:\n  - '@a'\n  - '@b'\ntitle: t\n---\n")[0], {"a", "b"})
        E = Env()
        try:
            E.setup()
            E.rk("ledger", "add-source", "--doi", "10.1038/s41598-023-41032-5", "--title", "A placeholder title", "--year", "2023",
                 "--citekey", "w2023")
            set_ledger(E, "IDENTITY_CONFIRMED")
            with open(E.path("sources", "references.json"), "w", encoding="utf-8") as f:
                json.dump([{"id": "w2023", "type": "article"}, {"id": "ghost1999", "type": "book"}], f)
            t = E.read(MS).replace("---\n\n", "---\n\n", 1)
            t = t.replace('author:', "nocite: '@*'\nauthor:", 1)
            open(E.path(MS), "w", encoding="utf-8").write(t + "\n本文 [@{w2023}]。\n")
            ng = [l for l in E.rk("check", "--submit").stdout.splitlines() if l.startswith("NG")]
            self.assertTrue(any("ghost1999" in l for l in ng), ng)
            r = E.rk("export", "docx")
            self.assertNotEqual(r.returncode, 0)
            self.assertIn("ghost1999", r.stderr)
            # the bibliography file is not the AI's to grow under a prohibited course
            E.set_policy("prohibited")
            self.assertEqual(decision(E.pre("Write", {"file_path": E.path("sources", "references.json"), "content": "[]"})), "deny")
        finally:
            E.cleanup()

    def test_figures_without_a_source_fail_at_submission_but_not_years_or_sections(self):
        E = Env()
        try:
            E.setup()
            with open(E.path(MS), "a", encoding="utf-8") as f:
                f.write("\n2020 年から 1990 年代にかけて、3.2 節と第 2 章で述べた v1.2 の版を見る(pp. 12-15)。\n")
            out = E.rk("check", "--submit").stdout
            self.assertFalse(any("出典の引用もデータ" in l for l in out.splitlines() if l.startswith("NG")), out)
            with open(E.path(MS), "a", encoding="utf-8") as f:
                f.write("\n現象 X は 45% の事例で見られた。\n")
            out = E.rk("check", "--submit").stdout
            self.assertTrue(any("45%" in l for l in out.splitlines() if l.startswith("NG")), out)
            self.assertTrue(any("45%" in l for l in E.rk("check").stdout.splitlines() if l.startswith("注意")))
        finally:
            E.cleanup()

    def test_settings_that_cannot_be_trusted_close_manuscript_writes(self):
        E = Env()
        try:
            cfg = E.path(".ryukoku", "config.yml")
            base = E.read(".ryukoku", "config.yml")
            w = ("Write", {"file_path": E.path(MS), "content": "x"})
            variants = {"duplicate": base.replace("ai_policy: unknown", "ai_policy: prohibited") + "ai_policy: allowed\n",
                        "capital": base.replace("ai_policy: unknown", "ai_policy: Allowed"),
                        "missing": "\n".join(l for l in base.split("\n") if not l.startswith("ai_policy"))}
            for name, text in variants.items():
                open(cfg, "w", encoding="utf-8").write(text)
                with self.subTest(variant=name):
                    self.assertEqual(decision(E.pre(*w)), "deny")
                    r = E.rk("check")
                    self.assertEqual(r.returncode, 1, r.stdout)
            # the hooks and the tools read the same line, with or without a space before the colon
            open(cfg, "w", encoding="utf-8").write(base.replace("ai_policy: unknown", "ai_policy : allowed"))
            self.assertEqual(decision(E.pre(*w)), "-")
            from rklib.common import load_config
            self.assertEqual(load_config(E.proj)["ai_policy"], "allowed")
        finally:
            E.cleanup()

    def test_changes_after_an_unfinished_tool_call_count_as_the_ais(self):
        E = Env()
        try:
            E.set_policy("allowed")
            E.hook("session-start.sh", {"cwd": E.proj, "hook_event_name": "SessionStart"})
            E.pre("Bash", {"command": "python3 -c 'print(1)'"}, tuid="long")  # asks; treat as allowed: make it a run window
            import glob as g
            sd = g.glob(os.path.join(E.state, "state", "*"))[0]
            op = os.path.join(sd, "open.json")
            o = json.load(open(op))
            o["long"] = {"t": 1.0, "ask": False}  # opened long ago, never finished
            json.dump(o, open(op, "w"))
            with open(E.path(MS), "a", encoding="utf-8") as f:
                f.write("\n長いツール実行の間に入った段落。\n")
            E.ai_bash("ls", tuid="next")
            ents = prov(E)
            self.assertTrue(any(e.get("uncertain") for e in ents), ents)
            out = E.rk("facts").stdout
            self.assertIn("AI の可能性", out)
        finally:
            E.cleanup()


if __name__ == "__main__":
    unittest.main()
