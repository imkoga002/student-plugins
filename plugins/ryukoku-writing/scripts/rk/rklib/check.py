"""`rk check` - the structural checks. The same code runs on the student's computer and in CI.

Stages
  draft   (default) structural breakage, human states without their record (or a VERIFIED without its signature),
          undecided change detections, a broken AI-use log or provenance log are errors; citations whose source is
          not in the ledger or below IDENTITY_CONFIRMED, figures without a source and claim-card problems are
          warnings; everything still to do is a note
  pr      + every manuscript file changed against --base-ref needs a current section confirmation (a key press);
          AI-written paragraphs in a course recorded as prohibited are errors
  submit  + the final pre-submission confirmation current (passphrase signature), cited sources VERIFIED by a
          person (signature) and at least IDENTITY_CONFIRMED by the machine, course policy known and confirmed,
          CriticMarkup removed, AI-written paragraphs absent when the course prohibits AI
CI (`--ci --base-ref origin/<base>`, run with the BASE branch's copy of this code, so a PR cannot
switch off the check that judges it): trusted signers come from
the base branch (trust.py), the sign-off record and the AI-use log must extend the base versions, and changes to
tools/, the launchers, .github/ or .githooks/ in the PR are errors (the base code is what checks them).
Locally the project's tools/ copy is compared with its MANIFEST.sha256 and, when this code runs from the plugin
itself, with the plugin's own manifest (the checking code the AI could rewrite is verified, not trusted).
"""
import json
import os
import re
import subprocess

from . import (ailog, claimcards, criticmarkup, datacheck, ledger, msguard, proposals, provenance, searchlog, sign, style,
               subjects, trust, verification)
from .common import feedback_lang, load_config, manuscript_files, read_text, rel, sha256_file, tr

HERE = os.path.dirname(os.path.abspath(__file__))
TOOLS_ROOT = os.path.dirname(HERE)  # .../scripts/rk (plugin) or .../tools/rk (project copy)
MANIFEST = "MANIFEST.sha256"
GUARDED_IN_PR = ("tools", "rk", "rk.cmd", "rk.ps1", ".github", ".githooks")


class Report(object):
    """Messages follow the feedback language of the project: t(ja, en)."""

    def __init__(self, lang="ja"):
        self.lang = lang
        self.errors, self.warns, self.notes, self.head = [], [], [], []

    def t(self, ja, en):
        return tr(self.lang, ja, en)

    def err(self, m):
        self.errors.append(m)

    def warn(self, m):
        self.warns.append(m)

    def note(self, m):
        self.notes.append(m)


def manuscript_digest(proj):
    return subjects.presubmit_subject(proj).digest


def git(proj, *args):
    from .common import run_git
    r = run_git(proj, list(args))
    return r.stdout if (r is not None and r.returncode == 0) else None


# ------------------------------------------------------------------------------------------- tools integrity
def read_manifest(path):
    out = {}
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                m = re.match(r"^([0-9a-f]{64})\s+\*?(.+)$", line.strip())
                if m:
                    out[m.group(2)] = m.group(1)
    except OSError:
        return None
    return out


def build_manifest(root):
    lines = []
    for dp, dns, fns in os.walk(root):
        dns[:] = sorted(d for d in dns if d != "__pycache__")
        for fn in sorted(fns):
            if fn == MANIFEST or fn.endswith(".pyc"):
                continue
            full = os.path.join(dp, fn)
            lines.append("%s  %s" % (sha256_file(full), os.path.relpath(full, root).replace(os.sep, "/")))
    return "\n".join(sorted(lines, key=lambda x: x[66:])) + "\n"


def check_tools(proj, rep):
    troot = os.path.join(proj, "tools", "rk")
    man = read_manifest(os.path.join(troot, MANIFEST))
    if man is None:
        rep.err(rep.t("tools/rk/%s がない(道具の複製を確かめられない)。./rk update-tools で Plugin から入れ直す" % MANIFEST,
                      "tools/rk/%s is missing (the tool copy cannot be checked). Reinstall it with ./rk update-tools" % MANIFEST))
        return
    actual = read_manifest_from_text(build_manifest(troot)) if os.path.isdir(troot) else {}
    diff = sorted(set(man) ^ set(actual)) + sorted(k for k in man if k in actual and man[k] != actual[k])
    if diff:
        rep.err(rep.t("tools/rk/ の中身が MANIFEST.sha256 と違う(検査・記録の道具が書き換えられた可能性): %s",
                      "tools/rk/ differs from MANIFEST.sha256 (the checking tools may have been modified): %s") % ", ".join(diff[:8]))
    here_is_plugin = not os.path.realpath(TOOLS_ROOT).startswith(os.path.realpath(proj) + os.sep)
    plugin_man = read_manifest(os.path.join(TOOLS_ROOT, MANIFEST))
    if here_is_plugin and plugin_man is not None and plugin_man != man:
        rep.err(rep.t("プロジェクトの tools/rk/ が、いま動いている Plugin(%s)の道具と違う。Plugin を更新したなら自分の端末で ./rk update-tools、"
                      "心当たりがなければ git diff tools/ で調べる", "The project's tools/rk/ differ from the running plugin (%s). After a plugin update run "
                      "./rk update-tools in your terminal; otherwise investigate with git diff tools/") % TOOLS_ROOT)


def read_manifest_from_text(text):
    out = {}
    for line in text.splitlines():
        m = re.match(r"^([0-9a-f]{64})\s+\*?(.+)$", line.strip())
        if m:
            out[m.group(2)] = m.group(1)
    return out


# ------------------------------------------------------------------------------------------- human states
def check_human_states(proj, idx, rep):
    n_ok = 0
    pools = [subjects.sources(proj), subjects.claims(proj), [s for s in subjects.rules(proj) if s.claimed],
             subjects.comments(proj), subjects.cards(proj)]
    for pool in pools:
        for s in pool:
            if not s.claimed:
                continue
            if s.kind == "source" and s.claimed not in subjects.KIND_DECISIONS["source"]:
                rep.err(rep.t("register %s: human_status %r は使えない(VERIFIED / REJECTED か空)", "register %s: human_status %r is not allowed (VERIFIED / REJECTED or empty)") % (s.sid, s.claimed))
                continue
            if s.kind == "claim" and s.claimed not in subjects.KIND_DECISIONS["claim"]:
                rep.err(rep.t("claim %s: human_status %r は使えない", "claim %s: human_status %r is not allowed") % (s.sid, s.claimed))
                continue
            if sign.current(idx, s.kind, s.sid, s.digest, (s.claimed,)):
                n_ok += 1
                continue
            old = sign.latest(idx, s.kind, s.sid)
            where = {"source": "sources/register.csv", "claim": "sources/claims.csv", "rule": ".ryukoku/style.yml",
                     "comment": "review/annotations.json", "card": "claims/%s.md" % s.sid}[s.kind]
            signed = sign.needs_signature(s.kind, s.claimed)
            if s.kind == "card" and old:
                rep.warn(rep.t("%s: 学生の確認の後に、主張・範囲・学生の言葉などが変わった。読み直して、もう一度確認する(証拠ノートの「主張カード」か ./rk confirm)",
                               "%s: the claim, scope or the student's words changed after your confirmation. Re-read and confirm again (notebook 'Claim cards' or ./rk confirm)") % where)
            elif old:
                rep.err(rep.t("%s %s の「%s」は、記録の後に内容が変わった(記録が古い)。読み直して%sし直す",
                              "%s %s: '%s' was recorded for different content (stale record). Re-read and %s again")
                        % (where, s.sid, s.claimed, rep.t("署名" if signed else "確認", "sign" if signed else "confirm")))
            elif signed:
                rep.err(rep.t("%s %s に「%s」とあるが、人間の署名がない(VERIFIED は合言葉の署名つきでしか成立しない。AI やスクリプトが書いた可能性)",
                              "%s %s says '%s' but has no human signature (VERIFIED exists only as a passphrase signature; an AI or a script may have written it)")
                        % (where, s.sid, s.claimed))
            else:
                rep.err(rep.t("%s %s に「%s」とあるが、学生の確認の記録がない(AI やスクリプトが書いた可能性。証拠ノートか端末で確認する)",
                              "%s %s says '%s' but there is no record of your confirmation (an AI or a script may have written it)")
                        % (where, s.sid, s.claimed))
    rep.note(rep.t("記録で裏づけられた人間の判断: %d 件", "human decisions backed by records: %d") % n_ok)


def changed_manuscripts(proj, base_ref):
    out = git(proj, "diff", "--name-only", "%s...HEAD" % base_ref, "--", "manuscript")
    if out is None:
        return None
    return [l.strip() for l in out.splitlines() if l.strip() and os.path.exists(os.path.join(proj, l.strip()))]


def check_sections(proj, idx, rep, stage, base_ref):
    secs = {s.sid: s for s in subjects.sections(proj)}
    targets = []
    if stage == "pr":
        if not base_ref:
            rep.err(rep.t("--stage pr には --base-ref が要る", "--stage pr needs --base-ref"))
            return
        targets = changed_manuscripts(proj, base_ref)
        if targets is None:
            rep.err(rep.t("git diff で変更された原稿を求められなかった(--base-ref %s)", "git diff could not list the changed manuscript files (--base-ref %s)") % base_ref)
            return
    unsigned = 0
    for r, s in sorted(secs.items()):
        ok = sign.current(idx, "section", r, s.digest, ("reviewed",))
        if not ok:
            if r in targets:
                old = sign.latest(idx, "section", r)
                rep.err(rep.t("%s の現在の内容を読んだ確認がない%s。差分を読んでから確認する(証拠ノートの「提出前」か ./rk signoff)",
                              "%s: no confirmation that you read its current content%s. Read the diff, then confirm (notebook 'Before submission' or ./rk signoff)")
                        % (r, rep.t("(前回の確認の後に変わった)", " (changed since your last confirmation)") if old else ""))
            else:
                unsigned += 1
    if unsigned and stage == "draft":
        rep.note(rep.t("読んだ確認の記録がない原稿ファイル: %d 件(任意。提出前の確認でまとめて読む)", "manuscript files without a reading confirmation: %d (optional; the pre-submission confirmation covers them)") % unsigned)


def check_config(proj, idx, rep, stage):
    cfg = load_config(proj)
    pol = cfg.get("ai_policy") or "unknown"
    if pol not in ("allowed", "limited", "prohibited", "unknown"):
        rep.err(rep.t(".ryukoku/config.yml の ai_policy が不正: %r(allowed / limited / prohibited / unknown)", "invalid ai_policy in .ryukoku/config.yml: %r (allowed / limited / prohibited / unknown)") % pol)
    if pol == "unknown":
        (rep.err if stage == "submit" else rep.warn)(rep.t(
            "科目の AI 利用条件が未確認(ai_policy: unknown)。シラバスを確かめ、迷ったら担当教員に相談する(ガイドラインⅢ-3)。確かめたら自分の端末で ./rk setup",
            "The course AI policy is not confirmed (ai_policy: unknown). Check the syllabus and ask your instructor if unsure (guideline III-3); then run ./rk setup"))
    subj = subjects.config_subject(proj)
    if not sign.current(idx, "config", subj.sid, subj.digest):
        (rep.err if stage == "submit" else rep.warn)(rep.t("科目の AI 利用条件の記録に本人の確認がない、または確認の後に変わった(./rk setup)",
                                                            "The course AI policy record is not confirmed by you, or changed after you confirmed it (./rk setup)"))
    if not sign.latest(idx, "optout", "optout"):
        rep.warn(rep.t("入力を学習に使わない設定(オプトアウト)の確認が記録されていない(ガイドラインⅡ-2(1))。./rk setup で記録する",
                       "No record that you checked the training opt-out (guideline II-2(1)); record it with ./rk setup"))


def check_ledger_shape(proj, rep):
    reg, cl = ledger.paths(proj)
    for path, fields in ((reg, ledger.REGISTER), (cl, ledger.CLAIMS)):
        if os.path.exists(path):
            with open(path, encoding="utf-8") as f:
                head = f.readline().strip().split(",")
            if head != fields:
                rep.err(rep.t("%s の見出し行が想定と違う: %s", "%s: unexpected header; expected %s") % (rel(proj, path), ",".join(fields)))
    for s in ledger.read(reg, ledger.REGISTER):
        ms = s.get("machine_status", "")
        if ms and ms not in ledger.MACHINE_STATUSES:
            rep.err(rep.t("register %s: machine_status %r は機械の状態ではない(VERIFIED は人間の列だけ)", "register %s: machine_status %r is not a machine status (VERIFIED belongs to the human column only)") % (s.get("id"), ms))
    for c in ledger.read(cl, ledger.CLAIMS):
        ms = c.get("machine_status", "")
        if ms and ms not in ledger.MACHINE_STATUSES:
            rep.err(rep.t("claim %s: machine_status %r は機械の状態ではない", "claim %s: machine_status %r is not a machine status") % (c.get("claim_id"), ms))


def question_ids(proj):
    from .search import question_ids as q
    return q(proj)


def check_searchlog(proj, rep):
    try:
        recs = searchlog.load(proj)
    except Exception as e:  # noqa: BLE001
        rep.err(rep.t("検索記録: %s", "search log: %s") % e)
        return
    se, sw = searchlog.validate(recs, rep.lang)
    for x in se:
        rep.err(rep.t("検索記録: ", "search log: ") + x)
    for x in sw:
        rep.warn(rep.t("検索記録: ", "search log: ") + x)
    qs = question_ids(proj)
    for r in recs:
        q = (r.get("question_ref") or "").strip()
        if q and q not in qs:
            rep.warn(rep.t("検索記録 %s: 問い %s が research/questions.md にない(調査の問いは学生の問いから導く)",
                           "search record %s: question %s is not in research/questions.md (research derives from your own questions)") % (r.get("id"), q))


def check_citations(proj, idx, rep, stage):
    keys = set()
    for p in manuscript_files(proj):
        text = read_text(p)
        if criticmarkup.has_markup(text):
            (rep.err if stage == "submit" else rep.warn)(rep.t("CriticMarkup の記号が原稿に残っている: %s", "CriticMarkup marks remain in the manuscript: %s") % rel(proj, p))
        keys |= set(re.findall(r"(?<![\w.])-?@([A-Za-z0-9_][A-Za-z0-9_:.#$%&+?<>~/-]*)", re.sub(r"`[^`]*`", "", text)))
    keys = {k.rstrip(".:,;") for k in keys if not k.startswith(("fig:", "tbl:", "sec:", "eq:", "lst:"))}
    reg = ledger.read(ledger.paths(proj)[0], ledger.REGISTER)
    by_key = {}
    for r in reg:
        for k in (r.get("citekey"), r.get("id")):
            if k:
                by_key[k] = r
    known = set(by_key)
    try:
        with open(os.path.join(proj, "sources", "references.json"), encoding="utf-8") as f:
            known |= {str(x.get("id")) for x in json.load(f) if isinstance(x, dict)}
    except (OSError, ValueError):
        pass
    unknown = sorted(k for k in keys if k not in by_key)
    bad = (rep.err if stage == "submit" else rep.warn)
    if unknown:
        bad(rep.t("原稿の引用キーが台帳(register.csv)にない(実在を確かめていない文献は原稿に入れない): %s",
                  "citation keys not in the ledger (register.csv); unchecked sources do not go into the manuscript: %s") % ", ".join(unknown[:10]))
    srcs = {s.sid: s for s in subjects.sources(proj)}
    for k in sorted(keys):
        r = by_key.get(k)
        if not r:
            continue
        ms = (r.get("machine_status") or "CANDIDATE").strip()
        s = srcs.get(r.get("id"))
        human_ok = bool(s and s.claimed == "VERIFIED" and sign.current(idx, "source", s.sid, s.digest, ("VERIFIED",)))
        if ms != "IDENTITY_CONFIRMED":
            note = (r.get("human_note") or "").strip()
            if human_ok and note:
                rep.warn(rep.t("引用 %s(%s)は機械の確認が %s。原典を確かめた署名とメモ(%s)があるので注意にとどめる",
                               "%s (%s) is %s by the machine; your signed VERIFIED with a note (%s) keeps it a warning") % (k, r.get("id"), ms, note[:60]))
            else:
                bad(rep.t("引用 %s(%s)の台帳の状態が %s(IDENTITY_CONFIRMED 未満)。rk.py refcheck check で識別子を確かめるか、使わない"
                          "(識別子で確かめられない資料は、原典を読んで VERIFIED にするとき理由をメモに書く)",
                          "%s (%s) has ledger state %s (below IDENTITY_CONFIRMED). Check its identifier with rk.py refcheck check, or do not "
                          "cite it (for a work without an identifier, write the reason in the note when you mark it VERIFIED)") % (k, r.get("id"), ms))
        if stage == "submit" and not human_ok:
            rep.err(rep.t("原稿が引く %s は、本人が原典を確かめた署名(source VERIFIED)がない", "%s is cited but has no signed source VERIFIED by you") % k)


def check_numbers(proj, rep):
    n = 0
    for p in manuscript_files(proj):
        relp = rel(proj, p)
        for ln, tok in verification.numbers_without_source(proj, read_text(p), relp):
            n += 1
            if n <= 8:
                rep.warn(rep.t("%s:%d の数字「%s」に、出典の引用もデータファイルへの参照(data/...・data/numeric-claims.csv)もない",
                               "%s:%d: the figure \"%s\" has neither a citation nor a data reference (data/..., data/numeric-claims.csv)") % (relp, ln, tok))
    if n > 8:
        rep.warn(rep.t("出典のない数字がほかに %d 件(rk.py lint で全部)", "%d more figures without a source (rk.py lint lists them all)") % (n - 8))


def check_cards(proj, rep):
    for c in claimcards.cards(proj):
        for x in claimcards.problems(c, rep.lang):
            rep.warn(rep.t("主張カード %s: ", "claim card %s: ") % c["id"] + x)


def check_provenance(proj, rep, stage, ci):
    if not ci:
        try:
            provenance.sync_student(proj)
        except OSError:
            pass
    for p in provenance.verify(proj, local=not ci, lang=rep.lang):
        rep.err(p)
    s = provenance.summary(proj)
    ai_n = s["by_origin"]["ai_wrote"][0] + s["by_origin"]["ai_edited"][0]
    if s["paragraphs"]:
        rep.note(rep.t("由来: 段落 %d のうち、AI が書いた %d・AI が直した %d・AI の段落を学生が直した(推定)%d・学生(推定)%d・記録なし %d",
                       "provenance: of %d paragraphs, AI-written %d, AI-revised %d, AI paragraphs revised by you (estimated) %d, yours (estimated) %d, unrecorded %d")
                 % (s["paragraphs"], s["by_origin"]["ai_wrote"][0], s["by_origin"]["ai_edited"][0], s["by_origin"]["student_after_ai"][0],
                    s["by_origin"]["student"][0], s["by_origin"]["unrecorded"][0]))
    pol = load_config(proj).get("ai_policy") or "unknown"
    if pol == "prohibited" and ai_n:
        (rep.err if stage in ("pr", "submit") else rep.warn)(rep.t(
            "科目は AI 利用禁止(prohibited)と記録されているのに、AI が書いた・直した段落が原稿に %d 段落ある(.ryukoku/provenance.jsonl)。"
            "その段落を自分で書き直すか、科目の条件の記録が誤りなら ./rk setup で直す",
            "The course is recorded as AI-prohibited, but %d paragraph(s) in the manuscript were written or revised by the AI "
            "(.ryukoku/provenance.jsonl). Rewrite them yourself, or correct the policy record with ./rk setup if it is wrong") % ai_n)


# ------------------------------------------------------------------------------- Claude Code settings
PLUGIN_NAME = "ryukoku-writing"


def settings_files(proj, ci=False):
    out = [os.path.join(proj, ".claude", "settings.json"), os.path.join(proj, ".claude", "settings.local.json")]
    if not ci:
        home = os.path.expanduser("~")
        out += [os.path.join(home, ".claude", "settings.json"), os.path.join(home, ".claude", "settings.local.json")]
    return out


def check_claude_settings(proj, rep, ci=False):
    """disableAllHooks: true, or this plugin set to false in enabledPlugins, stops every hook of the plugin: nothing
    is denied, recorded or detected while it is off (observed during development with Claude Code 2.1.318:
    disableAllHooks in .claude/settings.local.json stopped the hooks in a `claude -p` run, and `claude plugin
    disable` wrote "enabledPlugins": {"ryukoku-writing@<marketplace>": false} to ~/.claude/settings.json)."""
    for p in settings_files(proj, ci):
        if not os.path.exists(p):
            continue
        try:
            with open(p, encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, ValueError):
            rep.warn(rep.t("%s を JSON として読めない", "%s is not readable JSON") % p)
            continue
        if not isinstance(data, dict):
            continue
        if data.get("disableAllHooks") is True:
            rep.err(rep.t("%s に disableAllHooks: true がある。この間、Plugin のフックは全部止まり、AI の書き込みを止めることも、"
                          "記録や検知もできない。自分で設定を消してから Claude Code を開き直す(AI は設定を書き換えない)",
                          "%s has disableAllHooks: true. While it is set, every hook of the plugin is off: nothing blocks AI writes, "
                          "and nothing is recorded or detected. Remove it yourself and reopen Claude Code (the AI does not edit settings)") % p)
        ep = data.get("enabledPlugins")
        if isinstance(ep, dict):
            for k, v in ep.items():
                if (k == PLUGIN_NAME or str(k).startswith(PLUGIN_NAME + "@")) and v is False:
                    rep.err(rep.t("%s で %s が無効(false)。無効の間はフックが動かず、記録も検知もない。有効に戻す(/plugin)",
                                  "%s disables %s (false). While disabled no hook runs: nothing is recorded or detected. "
                                  "Enable it again (/plugin)") % (p, k))


# --------------------------------------------------------------------- tools and CI files changed
def guarded_problems(proj, idx, rep, ci=False, base_ref=None):
    """tools/, the launchers, .github/ and .githooks/ differ from what the plugin ships (locally) or from the base
    branch (CI): the check does not pass until the student signs a 'guarded' confirmation of exactly this content."""
    s = subjects.guarded_subject(proj, base_ref if ci else None)
    if not s.content.get("files"):
        return
    if sign.current(idx, "guarded", s.sid, s.digest):
        rep.note(rep.t("検査・記録の道具か CI の設定の変更(%s)は、学生が確認済み", "changes to the tools or CI settings (%s) were confirmed with a signature")
                 % ", ".join(s.content["files"][:6]))
        return
    rep.err(rep.t("検査・記録の道具か CI の設定が、%s と違う(%s)。AI のスクリプトが検査を弱めた可能性がある。差分を読み、"
                  "意図した変更なら自分の端末で ./rk sign guarded tools --decision confirmed(または ./rk update-tools)で確認する。"
                  "PR が .github/ を変えるときは、その PR の CI の結果を信用しない(差分を読む)",
                  "The checking tools or CI settings differ from %s (%s). An AI script may have weakened the checks. Read the diff; "
                  "if it is intended, confirm it in your terminal with ./rk sign guarded tools --decision confirmed (or ./rk update-tools). "
                  "When a PR changes .github/, do not trust that PR's CI result: read the diff")
            % (rep.t("基準ブランチ", "the base branch") if ci else rep.t("Plugin の同梱版", "the plugin's copy"), ", ".join(s.content["files"][:6])))


def check_ci_extras(proj, rep, base_ref):
    for relp in (ailog.LOG_REL, sign.SIGNOFFS_REL, provenance.PROV_REL, os.path.join("research", "search-log.jsonl"),
                 os.path.join("review", "annotations-log.jsonl")):
        base = git(proj, "show", "%s:%s" % (base_ref, relp.replace(os.sep, "/")))
        if base is None:
            continue
        p = ailog.base_prefix_problem(proj, base, relp)
        if p:
            rep.err(p)
    out = git(proj, "diff", "--name-only", "%s...HEAD" % base_ref, "--", *GUARDED_IN_PR)
    if out is None:
        rep.err(rep.t("git diff で道具の変更を確かめられなかった(--base-ref %s)", "git diff could not check the tools (--base-ref %s)") % base_ref)
    check_claude_settings(proj, rep, ci=True)


def run(proj, stage="draft", ci=False, base_ref=None):
    rep = Report(feedback_lang(proj))
    trusted, tprobs, tnotes = trust.trusted_signers(proj, ci=ci, base_ref=base_ref, lang=rep.lang)
    for p in tprobs:
        rep.err(p)
    for n in tnotes:
        if n.startswith(("【信頼の起点】", "[trust root]")):
            rep.head.append(n)  # printed first, for the advisor
        else:
            rep.note(n)
    idx, rprobs = sign.valid_index(proj, trusted)
    for p in rprobs:
        rep.err(p)
    entries, lprobs = ailog.verify(proj, local=not ci, lang=rep.lang)
    for p in lprobs:
        rep.err(p)
    if not ci:
        # the plugin's hooks leave a 'session' line at every SessionStart; a long gap can mean the plugin was disabled
        # or removed (an uninstall leaves no setting behind to check)
        sess = [e.get("date") for e in entries if e.get("type") == "session" and e.get("date")]
        if sess:
            rep.note(rep.t("Plugin のフックが最後に記録した Claude Code の開始: %s(この後に Claude Code を使った覚えがあるのに記録が無ければ、"
                           "Plugin が無効か削除されていた可能性)", "last Claude Code start recorded by the plugin's hooks: %s (if you used Claude "
                           "Code after that and nothing was recorded, the plugin may have been disabled or removed)") % max(sess))
    if ci and base_ref:
        check_ci_extras(proj, rep, base_ref)
    else:
        check_tools(proj, rep)
        check_claude_settings(proj, rep)
    guarded_problems(proj, idx, rep, ci=bool(ci and base_ref), base_ref=base_ref)
    if not ci:
        from .search import purge_expired_cache
        try:
            purge_expired_cache(proj)
        except OSError:
            pass
    from review.store import log_problems
    for p in log_problems(proj, rep.lang):
        rep.err(p)
    from .export import defaults_problems
    for fn, bad in defaults_problems(proj, rep.lang):
        rep.err(rep.t("pandoc の設定 pandoc/%s に、許可していない項目がある(外部のプログラムを動かしうる): %s。消すか、許可された項目だけにする",
                      "the pandoc defaults pandoc/%s has items that are not allowed (they could run external programs): %s; remove them")
                % (fn, ", ".join(str(b) for b in bad)))
    for s in msguard.pending(proj, idx):
        rep.err(rep.t("AI のツール実行中に検知した変更が未判断: %s %s(%s)。差分を見て、残す・自分の編集だった・戻すを選んで署名する"
                      "(証拠ノートの「変更の検知」か ./rk changes)",
                      "undecided change detected during an AI tool call: %s %s (%s). Review the diff and sign keep / mine / revert "
                      "(notebook 'Detected changes' or ./rk changes)") % (s.content.get("what"), s.content.get("path") or ", ".join(s.content.get("parts") or []), s.sid))
    check_human_states(proj, idx, rep)
    check_ledger_shape(proj, rep)
    lang = "en" if (load_config(proj).get("manuscript_lang", "ja").startswith("en")) else "ja"
    _rules, sp = style.approved_rules(proj, idx, lang, rep.lang)
    for p in sp:
        rep.err(p)
    _t, prop_rules = style.load(style.proposed_path(proj))
    for x in style.validate_proposed(prop_rules):
        rep.warn(rep.t("記法の提案: ", "proposed style rule: ") + x)
    if prop_rules:
        rep.note(rep.t("承認を待つ記法規則の提案: %d 件", "proposed style rules waiting for approval: %d") % len(prop_rules))
    pend = proposals.pending(proj)
    if pend:
        rep.note(rep.t("判断を待つ提案: %d 件(証拠ノートの「提案」か ./rk apply で一件ずつ)", "proposals waiting for your decision: %d (notebook 'Proposals' or ./rk apply)") % len(pend))
    for m in pend:
        try:
            bad = proposals.recheck(m, proj, read_text(os.path.join(proj, m["target"])))
            if bad:
                rep.warn(rep.t("提案 %s: 内容の不変の検査に通らない箇所 %d(採用できない)", "proposal %s: %d hunk(s) fail the invariance check (cannot be accepted)") % (m.get("id"), len(bad)))
        except OSError:
            rep.warn(rep.t("提案 %s: 対象 %s がない", "proposal %s: target %s is missing") % (m.get("id"), m.get("target")))
    if os.path.isdir(os.path.join(proj, "data")):
        for x in datacheck.verify(os.path.join(proj, "data")):
            rep.err(rep.t("データ: ", "data: ") + x)
    check_searchlog(proj, rep)
    check_provenance(proj, rep, stage, ci)
    check_sections(proj, idx, rep, stage, base_ref)
    check_config(proj, idx, rep, stage)
    check_citations(proj, idx, rep, stage)
    check_numbers(proj, rep)
    check_cards(proj, rep)
    if stage == "submit":
        ps = subjects.presubmit_subject(proj)
        if not sign.current(idx, "presubmit", ps.sid, ps.digest):
            rep.err(rep.t("提出前の最終確認の署名がない、または署名の後に原稿・台帳・記法・主張カード・由来・開示文が変わった(証拠ノートの「提出前」か ./rk signoff)",
                          "No signed pre-submission confirmation, or the manuscript, ledgers, style rules, claim cards, provenance or disclosure statement changed since (notebook 'Before submission' or ./rk signoff)"))
        days = [d for d in subjects.ailog_days(proj) if not sign.latest(idx, "ailog", d.sid)]
        if days and not subjects.disclosure_statements(proj):
            rep.warn(rep.t("AI 利用の開示文(disclosure/statement.md)がなく、概要を本人が確認していない日が %d 日ある(./rk facts の事実から開示文を作る。disclosure スキル)",
                           "no AI-use disclosure statement (disclosure/statement.md) and %d day(s) without your summary (draft it from ./rk facts; disclosure skill)") % len(days))
        unv = [c for c in subjects.claims(proj) if c.claimed != "VERIFIED"]
        if unv:
            rep.warn(rep.t("本人が原典で確認していない主張: %s", "claims you have not verified in the source: %s") % ", ".join(c.sid for c in unv[:15]))
    return rep
