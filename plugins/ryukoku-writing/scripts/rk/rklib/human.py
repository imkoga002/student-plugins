"""Terminal flows for the human-only commands (./rk confirm, apply, verify, style, resolve, changes, disclose, signoff,
optout, import-docx, sign, trust). Each flow shows every item and collects the person's decision item by item.
Most decisions are then recorded as light confirmations at once (no passphrase). Only VERIFIED and the final
pre-submission confirmation ask for the passphrase, once per batch (decide.sign_batch); the first time one is
needed and no passphrase is registered yet, the flow registers it first (setup.step_passphrase).

Speed bumps that do not depend on secrecy: the commands run only from the installed plugin (never from the project
copy in tools/, which an AI tool could have rewritten), only at a real terminal (/dev/tty), and there is no key
that accepts the remaining items in bulk (no bulk accept: each item must be shown before it can be chosen).
"""
import difflib
import os
import sys

from . import claimcards, decide, ledger, msguard, proposals, sign, style, subjects, trust
from .common import RkError, feedback_lang, is_inside, read_text, tr, trust_path

HERE = os.path.dirname(os.path.abspath(__file__))
CODE_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(HERE)))  # plugin root when run from the plugin

CHECKLIST = {
    "claims_mine": ("問い・主張・結論は自分のもの。AI が書いた・直した文は読んで、自分の主張(主張カード)どおりであることを確かめた",
                    "The questions, claims and conclusions are mine. I read every passage the AI wrote or revised and checked it says what my claim cards say"),
    "disclosure_true": ("AI 利用の開示(./rk facts の事実と開示文)は由来の記録のとおりで正しく、科目の指示どおりに書いた(ガイドラインⅢ-3・Ⅲ-4)",
                        "The AI-use disclosure (./rk facts and the statement) matches the provenance record and follows the course's instructions (guideline III-3, III-4)"),
    "facts_verified": ("引用・数値・ページ番号は自分で原典を読んで確かめた(主張の台帳で VERIFIED)",
                       "I checked quotations, figures and page numbers in the sources myself (claims VERIFIED)"),
    "quotes_marked": ("引用は「」かブロックで区別し、出典を示した(著作権法32条・48条)",
                      "Quotations are marked and sourced (Copyright Act arts. 32 and 48)"),
    "integrity": ("捏造・改ざん・盗用・二重投稿・不適切なオーサーシップに当たるものがない(龍谷大学の研究不正の定義)",
                  "Nothing amounts to fabrication, falsification, plagiarism, duplicate submission or improper authorship"),
    "course_policy": ("科目の AI 利用条件と、開示の形式・置き場所に従った(ガイドラインⅢ-3)",
                      "I followed the course AI policy and the disclosure format (guideline III-3)"),
    "no_personal_data": ("個人情報・機密情報を含めていない。人を対象とする調査は指導教員に確認した",
                         "No personal or confidential data; research on people was cleared with my advisor"),
    "faculty_rules": ("学部・科目の執筆要項(字数・書式・提出方法)を確認した",
                      "I checked the faculty/course writing rules (length, format, submission)"),
}


class Term(object):
    def __init__(self, lang):
        self.lang = lang
        self.color = not os.environ.get("NO_COLOR") and os.name != "nt"

    def t(self, ja, en):
        return tr(self.lang, ja, en)

    def say(self, msg=""):
        sign.tty_print(msg)

    def c(self, s, code):
        return "\033[%sm%s\033[0m" % (code, s) if self.color else s

    def key(self, prompt, allowed):
        return sign.tty_key(prompt, allowed)

    def ask(self, prompt):
        return sign.tty_input(prompt)


def start(proj, purpose_ja, purpose_en):
    """Common entry: refuse project-copy code and non-terminals; print where the code runs from."""
    lang = feedback_lang(proj)
    if is_inside(HERE, proj):
        raise RkError(tr(lang,
            "この操作は人間専用で、インストールされた Plugin のコードから動かす(プロジェクトの中の tools/ は AI が書き換えうるので使わない)。"
            "./rk(Windows は rk.cmd / rk.ps1)から実行する。Plugin の場所が分からないときは Claude Code でこのフォルダを一度開く。",
            "Human-only commands run from the installed plugin, never from the project copy in tools/ (an AI tool could have "
            "rewritten it). Use ./rk (Windows: rk.cmd / rk.ps1). If the plugin location is unknown, open this folder in Claude Code once."))
    sign.require_tty(lang)
    term = Term(lang)
    term.say(term.c(tr(lang, "[ryukoku-writing・非公式] ", "[ryukoku-writing, unofficial] ") + tr(lang, purpose_ja, purpose_en), "1"))
    for ln in running_code_lines(lang):
        term.say(ln)
    problem = plugin_integrity(proj) or code_location_problem(lang)
    if problem:
        raise RkError(problem)
    from . import check as _check
    rep = _check.Report(lang)
    _check.check_claude_settings(proj, rep)
    for e in rep.errors:
        term.say(term.c("NG  " + e, "31"))
    return term


def running_code_lines(lang):
    from .common import plugin_version
    return [tr(lang, "  動いているコード: %s(版 %s)" % (CODE_ROOT, plugin_version(CODE_ROOT)),
               "  running code: %s (version %s)" % (CODE_ROOT, plugin_version(CODE_ROOT))),
            tr(lang, "  合言葉を入れる前に、この場所が Claude Code の Plugin の場所(/plugin で確かめられる)であることを確かめる。",
               "  Before typing the passphrase, check that this is where Claude Code keeps the plugin (see /plugin).")]


def code_location_problem(lang):
    """The running code must be the plugin Claude Code last recorded (SessionStart / init), with the same
    MANIFEST. Otherwise no passphrase is asked for."""
    from .common import check_running_code
    if os.environ.get("RK_DEV_NO_MANIFEST"):
        return None
    ok, lines = check_running_code(CODE_ROOT)
    if ok:
        return None
    body = "\n".join("  - " + tr(lang, ja, en) for ja, en in lines)
    return tr(lang, "合言葉を求めずに止めた。理由:\n%s\n心当たりがなければ、この PC のファイルが書き換えられた可能性がある。"
                    "Claude Code をこのプロジェクトのフォルダで開き直し(Plugin の場所が記録し直される)、それでも止まるなら"
                    "Plugin を入れ直し、AI 利用記録の検知を確かめる。" % body,
              "Stopped without asking for the passphrase:\n%s\nIf you did not expect this, files on this computer may have been "
              "rewritten. Reopen Claude Code in the project folder (it records the plugin location again); if it still "
              "stops, reinstall the plugin and review the detections in the AI-use log." % body)


def plugin_integrity(proj):
    """The passphrase is typed into this code, so check it against the manifest shipped with the plugin.
    Returns a message when a file differs (then nothing asks for the passphrase)."""
    from . import check
    rk_root = os.path.dirname(HERE)
    man = check.read_manifest(os.path.join(rk_root, check.MANIFEST))
    if man is None:
        return None if os.environ.get("RK_DEV_NO_MANIFEST") else tr(feedback_lang(proj),
            "Plugin の道具の一覧(MANIFEST.sha256)がない。Plugin を入れ直す。", "The plugin's MANIFEST.sha256 is missing; reinstall the plugin.")
    actual = check.read_manifest_from_text(check.build_manifest(rk_root))
    bad = sorted(set(man) ^ set(actual)) + sorted(k for k in man if k in actual and man[k] != actual[k])
    if bad:
        return tr(feedback_lang(proj),
                  "合言葉を受け取る Plugin のコードが、同梱の一覧と違う(%s)。書き換えられた可能性があるので、合言葉を入れずに Plugin を入れ直す。" % ", ".join(bad[:5]),
                  "The plugin code that receives your passphrase differs from its manifest (%s). Do not enter the passphrase; reinstall the plugin." % ", ".join(bad[:5]))
    return None


def ensure_signer(proj, term):
    """VERIFIED and the final confirmation need a passphrase. If none is registered (or trusted on this computer)
    yet, register it now: the deferred first step of ./rk setup."""
    trusted, _p, _n = trust.local_trusted(proj)
    if trusted:
        return trusted
    from . import setup
    term.say("")
    term.say(term.t("VERIFIED(原典を読んだという宣言)と提出前の最終確認には、合言葉の署名が要る。まだ登録していないので、ここで登録する。",
                    "VERIFIED (\"I read the original\") and the final pre-submission confirmation need a passphrase signature. None is registered yet, so register it now."))
    return setup.step_passphrase(proj, term)


def finish(proj, term, items, method="tty"):
    """Record ITEMS: light confirmations at once; VERIFIED and the final confirmation with one passphrase entry."""
    if not items:
        term.say(term.t("記録する項目がない(何も変えていない)。", "Nothing to record (nothing changed)."))
        return []
    need = [it for it in items if sign.needs_signature(it["kind"], it["decision"])]
    term.say("")
    term.say(term.t("記録する %d 件:" % len(items), "%d item(s) to record:" % len(items)))
    for it in items:
        term.say("  - %s %s → %s%s" % (it["kind"], it["id"], it["decision"],
                                        term.t("(合言葉の署名)", " (passphrase signature)") if it in need else ""))
    if not need:
        results = []
        recs = decide.sign_batch(proj, items, None, method, results=results)
        term.say(term.t("%d 件を記録した(合言葉は要らない判断)。" % len(recs), "Recorded %d item(s) (decisions that need no passphrase)." % len(recs)))
        for r in results:
            if r["status"] != "signed":
                term.say(term.t("  記録しなかった: %s %s(%s)" % (r["kind"], r["id"], r.get("reason")),
                                "  not recorded: %s %s (%s)" % (r["kind"], r["id"], r.get("reason"))))
        return recs
    ensure_signer(proj, term)
    term.say(term.t("合言葉は、この画面(端末)にだけ入れる。チャットや AI には決して入れない。",
                    "Type the passphrase only here, in your terminal. Never into the chat or to the AI."))
    for attempt in range(3):
        pw = sign.read_passphrase(term.t("合言葉(入力は表示されない): ", "passphrase (not shown): "))
        results = []
        try:
            recs = decide.sign_batch(proj, items, pw, method, results=results)
        except sign.SignError as e:
            pw = None
            term.say(str(e))
            continue
        finally:
            pw = None
        term.say(term.t("%d 件を記録した(うち署名 %d 件)。" % (len(recs), sum(1 for r in recs if r.get("sig"))),
                        "Recorded %d item(s) (%d signed)." % (len(recs), sum(1 for r in recs if r.get("sig")))))
        for r in results:
            if r["status"] != "signed":
                term.say(term.t("  記録しなかった: %s %s(%s)" % (r["kind"], r["id"], r.get("reason")),
                                "  not recorded: %s %s (%s)" % (r["kind"], r["id"], r.get("reason"))))
        return recs
    raise RkError(term.t("合言葉が 3 回合わなかったので記録しなかった。", "Passphrase did not match three times; nothing recorded."))


finish_with_passphrase = finish  # the v1 name


def _show_hunk(term, s):
    c = s.content
    for x in c.get("before", []):
        term.say("    " + term.c(x, "2"))
    co, cn = proposals.char_diff("\n".join(c.get("old", [])), "\n".join(c.get("new", [])), term.color)
    if c.get("old"):
        for ln in co.split("\n"):
            term.say("  - " + ln)
    if c.get("new"):
        for ln in cn.split("\n"):
            term.say("  + " + ln)
    for x in c.get("after", []):
        term.say("    " + term.c(x, "2"))


def why_proposals(lang):
    return tr(lang,
        "提案ファイルは、表記・書式の直しを一か所ずつ見て決めたいときの選択肢(科目が許せば、AI が原稿を直接直してもよく、その場合も由来は記録される)。"
        "道具が通すのは、全角半角(英数字・カナ)、句読点の組(、と，/。と．)、日本語の周りの空白、見出しの番号、同じ文献の引用の書式の変更だけ。"
        "それ以外の文字(語・数字・小数点・符号・記号・頁)が一字でも変わる提案は、作るときと採用するときに拒否する。採用した変更は由来の記録に"
        "『AI の提案(書式)』として残る。差分を読んでから選ぶ。",
        "Proposal files are an option for when you want to see each notation/format fix (if the course allows, the AI may also edit "
        "the manuscript directly; provenance is recorded either way). The tool lets through only full/half-width forms of letters, "
        "digits and kana, the punctuation system (、/， and 。/．), spaces next to Japanese text, heading numbers and the form of a "
        "citation of the same work. A proposal that changes any other character is refused when made and when applied. Accepted "
        "changes are recorded as provenance (AI proposal, format). Read each diff before choosing.")


def cmd_apply(proj, ids=None):
    hs = [s for s in subjects.hunks(proj) if not ids or s.sid.split("#")[0] in ids]
    term = start(proj, "提案(表記・書式の統一)を一か所ずつ見て決める", "Decide on proposals (notation/format), one hunk at a time")
    if not hs:
        term.say(term.t("判断を待つ提案はない。", "No proposals waiting."))
        return 0
    term.say(why_proposals(term.lang))
    items = []
    by_pid = {}
    for m in proposals.pending(proj):
        by_pid[m["id"]] = m
    for i, s in enumerate(hs, 1):
        m = by_pid.get(s.sid.split("#")[0], {})
        term.say("")
        term.say(term.c("[%d/%d] %s  %s  %s" % (i, len(hs), s.sid, s.content.get("target"),
                                              term.t("%s 行目" % s.content.get("line"), "line %s" % s.content.get("line"))), "1")
                 + "  " + s.content.get("note", ""))
        if s.content.get("stale"):
            term.say(term.c("  " + term.t("原稿が変わって位置を特定できない(作り直しが要る)。採用はできない。[n]不採用 [s]保留",
                                          "The manuscript changed and this hunk cannot be located (needs regenerating); it cannot be "
                                          "accepted. [n]o [s]kip"), "33"))
            _show_hunk(term, s)
            k = term.key("  [n]/[s] > ", "ns")
            if k == "n":
                items.append({"kind": "hunk", "id": s.sid, "decision": "rejected", "digest": s.digest})
            continue
        term.say("  " + term.t("理由: ", "why: ") + (m.get("why") or "") + ("  " + term.t("規則: ", "rule: ") + m["rule"] if m.get("rule") else ""))
        _show_hunk(term, s)
        bad = proposals.recheck(dict(m, hunks=[h for h in m.get("hunks", []) if "%s#%d" % (m["id"], h["n"]) == s.sid]),
                                proj, read_text(os.path.join(proj, m["target"]))) if m else {}
        if bad:
            term.say(term.c("  " + term.t("内容の不変の検査に通らないので採用できない(不採用として記録する): ", "fails the invariance check; recorded as rejected: ") + list(bad.values())[0], "31"))
            items.append({"kind": "hunk", "id": s.sid, "decision": "rejected"})
            continue
        k = term.key(term.t("  採用? [y]はい [n]いいえ [s]保留 [?]説明 [q]ここまで > ", "  accept? [y]es [n]o [s]kip [?]why [q]stop here > "), "ynsq?")
        while k == "?":
            term.say(why_proposals(term.lang))
            k = term.key("  [y]/[n]/[s]/[q] > ", "ynsq")
        if k == "q":
            break
        if k in ("y", "n"):
            items.append({"kind": "hunk", "id": s.sid, "decision": "accepted" if k == "y" else "rejected", "digest": s.digest})
    finish(proj, term, items)
    return 0


def cmd_confirm(proj, ids=None):
    """Claim cards: the student confirms 'this is my claim' (a light confirmation; no passphrase)."""
    term = start(proj, "主張カードを読み、自分の主張かどうかを確かめる", "Read the claim cards and confirm which are your claims")
    trusted, _p, _n = trust.local_trusted(proj)
    idx, _b = sign.valid_index(proj, trusted)
    cs = [s for s in subjects.cards(proj) if (not ids or s.sid in ids) and not sign.current(idx, "card", s.sid, s.digest)]
    if not cs:
        term.say(term.t("確認を待っている主張カードはない。", "No claim cards waiting."))
        return 0
    term.say(term.t("主張カードは、あなたの言葉を AI が聞き取って整理したもの。[ai_suggested] の印は AI が足した候補で、確認の対象に入らない。"
                    "主張・範囲・あなたの言葉の原文が、あなたの考えと同じときだけ y を押す。違えば n にして、カードを直す(自分で、または AI に頼む)。",
                    "A claim card is what the AI organised from your words. Items marked [ai_suggested] are the AI's candidates and are not "
                    "part of what you confirm. Press y only if the claim, the scope and your own words say what you think; otherwise n, "
                    "and fix the card (yourself or by asking the AI)."))
    items = []
    for s in cs:
        c = s.content
        term.say("\n" + term.c(s.sid, "1") + (term.t("(確認の後に変わった)", " (changed after your confirmation)") if sign.latest(idx, "card", s.sid) else ""))
        names = dict(claimcards.SECTIONS)
        for k in ("claim", "scope", "evidence", "warrant", "objections", "novelty", "words"):
            its = c["items"].get(k) or []
            if not its:
                continue
            term.say("  " + term.c(names[k][0] if term.lang != "en" else names[k][1], "1"))
            for it in its:
                term.say("    " + (term.c("[ai_suggested] ", "33") if it["ai"] else "") + it["text"])
        k = term.key(term.t("  これは自分の主張か? [y]はい [n]違う(直す) [s]保留 [q]ここまで > ", "  is this your claim? [y]es [n]o (fix it) [s]kip [q]stop > "), "ynsq")
        if k == "q":
            break
        if k == "y":
            items.append({"kind": "card", "id": s.sid, "decision": "confirmed", "digest": s.digest})
        elif k == "n":
            term.say(term.t("  確認しなかった。どこが違うかを AI に伝えるか、claims/%s.md を自分で直す。" % s.sid,
                            "  Not confirmed. Tell the AI what is wrong, or edit claims/%s.md yourself." % s.sid))
    finish(proj, term, items)
    return 0


def cmd_verify(proj, ids=None):
    term = start(proj, "原典を読んで確かめた結果を記録する", "Record what you confirmed in the sources")
    srcs = [s for s in subjects.sources(proj) if (not ids or s.sid in ids) and s.claimed != "VERIFIED"]
    cls = [s for s in subjects.claims(proj) if (not ids or s.sid in ids) and s.claimed in ("",)]
    if not srcs and not cls:
        term.say(term.t("確認を待っている文献・主張はない。", "Nothing waiting for verification."))
        return 0
    term.say(term.t("VERIFIED は『自分で原典(現物)を読み、該当箇所が主張を支えると確かめた』ときだけ付ける。AI の要約や機械の状態だけでは付けない。",
                    "Mark VERIFIED only if you read the source yourself and the passage supports the claim; never on an AI summary or a machine status alone."))
    items = []
    for s in srcs:
        c = s.content
        term.say("\n" + term.c(term.t("文献 ", "source ") + s.sid, "1") + "  %s / %s / %s" % (c.get("title"), c.get("authors"), c.get("year")))
        term.say("  ids: doi=%s isbn=%s ncid=%s crid=%s ndl=%s url=%s" % tuple(c.get(k, "") for k in ("doi", "isbn", "ncid", "crid", "ndl_id", "url")))
        term.say("  " + term.t("機械の状態: ", "machine: ") + "%s  %s" % (c.get("machine_status"), (c.get("machine_note") or "")[:200]))
        k = term.key(term.t("  現物(または公式の画面)で書誌を確かめたか? [v]VERIFIED [x]使わない(REJECTED) [s]保留 [q]ここまで > ",
                            "  checked the bibliographic data on the item itself? [v]erified [x] not used (REJECTED) [s]kip [q]stop > "), "vxsq")
        if k == "q":
            break
        if k == "s":
            continue
        note = ""
        if k == "v" and c.get("machine_status") in ("RETRACTED", "NOT_FOUND", "METADATA_MISMATCH"):
            note = term.ask(term.t("  機械の状態が %s。それでも使う理由(必須): " % c.get("machine_status"), "  machine status is %s; why use it anyway (required): " % c.get("machine_status"))).strip()
            if not note:
                term.say(term.t("  理由がないので保留にした。", "  No reason; kept pending."))
                continue
        items.append({"kind": "source", "id": s.sid, "decision": "VERIFIED" if k == "v" else "REJECTED", "note": note, "digest": s.digest})
    for s in cls:
        c = s.content
        term.say("\n" + term.c(term.t("主張 ", "claim ") + s.sid, "1") + "  " + c.get("claim", ""))
        term.say("  " + term.t("出典: ", "source: ") + "%s %s(%s)  " % (c.get("source_id"), c["source"].get("title", ""), c["source"].get("year", "")) +
                 term.t("機械の状態: ", "machine: ") + (c.get("source_machine_status") or "-"))
        if not c.get("locator"):
            loc = term.ask(term.t("  該当箇所(頁・節など。空なら保留): ", "  locator (page, section; empty to skip): ")).strip()
            if not loc:
                continue
            rows = ledger.read(ledger.paths(proj)[1], ledger.CLAIMS)
            for r in rows:
                if r["claim_id"] == s.sid:
                    r["locator"] = loc
            ledger.write(ledger.paths(proj)[1], rows, ledger.CLAIMS)
            c["locator"] = loc
        term.say("  " + term.t("該当箇所: ", "locator: ") + c["locator"])
        k = term.key(term.t("  その箇所を読んだ結果は? [v]支える(VERIFIED) [c]矛盾する(CONTRADICTED) [f]見つからない(NOT_FOUND) [s]保留 [q]ここまで > ",
                            "  after reading that passage: [v]supports [c]ontradicts [f] not found [s]kip [q]stop > "), "vcfsq")
        if k == "q":
            break
        if k == "s":
            continue
        status = {"v": "VERIFIED", "c": "CONTRADICTED", "f": "NOT_FOUND"}[k]
        if status == "CONTRADICTED":
            term.say(term.t("  原典と主張が矛盾するときは、主張を原典に合わせて直す(原典の読み方を主張に合わせない)。",
                            "  When source and claim conflict, revise the claim to match the source (never the reverse)."))
        note = term.ask(term.t("  メモ(CONTRADICTED のときは必須): ", "  note (required for CONTRADICTED): ")).strip()
        items.append({"kind": "claim", "id": s.sid, "decision": status, "note": note})
    finish(proj, term, items)
    return 0


def cmd_style(proj):
    term = start(proj, "記法規則の提案を一件ずつ承認・却下する", "Approve or reject proposed style rules one by one")
    rs = [s for s in subjects.rules(proj) if not s.claimed]
    if not rs:
        term.say(term.t("承認を待っている規則はない(proposals/style-rules.yml)。", "No proposed rules waiting."))
        return 0
    term.say(term.t("承認した規則だけが検査と機械的な提案に使われる。根拠の資料(要項・シラバス・見本)の該当箇所と照らして決める。",
                    "Only approved rules are used. Compare each with the cited source (handbook, syllabus, sample)."))
    items = []
    for s in rs:
        r = s.content
        term.say("\n" + term.c("%s  (%s)" % (s.sid, r.get("kind")), "1") + "  value: %s  lang: %s" % (r.get("value", ""), r.get("lang", "any")))
        term.say("  " + term.t("根拠: ", "source: ") + "%s %s" % (r.get("source", ""), r.get("page", "")))
        if r.get("quote"):
            term.say("  " + term.t("該当箇所: ", "passage: ") + r["quote"])
        term.say("  " + term.t("確信度: ", "confidence: ") + (r.get("confidence") or "?") + ("  " + r.get("note", "") if r.get("note") else ""))
        k = term.key(term.t("  [a]承認 [r]却下 [s]保留 [q]ここまで > ", "  [a]pprove [r]eject [s]kip [q]stop > "), "arsq")
        if k == "q":
            break
        if k in ("a", "r"):
            items.append({"kind": "rule", "id": s.sid, "decision": "approved" if k == "a" else "rejected", "digest": s.digest})
    finish(proj, term, items)
    return 0


def cmd_resolve(proj, ids=None):
    term = start(proj, "コメントの解決を決める", "Decide on open comments")
    cs = [s for s in subjects.comments(proj) if not s.claimed and (not ids or s.sid in ids)]
    if not cs:
        term.say(term.t("未解決のコメントはない。", "No open comments."))
        return 0
    items = []
    for s in cs:
        c = s.content
        term.say("\n" + term.c("%s %s" % (c.get("code"), c.get("creator")), "1") + "  「%s」" % (c.get("exact") or "")[:100])
        term.say("  " + (c.get("comment") or ""))
        for a, k_, t_ in c.get("replies") or []:
            term.say("  └ %s(%s): %s" % (a, k_, t_))
        k = term.key(term.t("  自分で対応した(または対応しない理由を決めた)? [r]解決 [s]保留 [q]ここまで > ", "  handled it yourself? [r]esolve [s]kip [q]stop > "), "rsq")
        if k == "q":
            break
        if k == "r":
            items.append({"kind": "comment", "id": s.sid, "decision": "resolved", "digest": s.digest})
    finish(proj, term, items)
    return 0


def cmd_changes(proj):
    term = start(proj, "AI のツール実行中に検知した変更を判断する", "Decide on changes detected during AI tool calls")
    trusted, _p, _n = trust.local_trusted(proj)
    idx, _b = sign.valid_index(proj, trusted)
    pend = msguard.pending(proj, idx)
    if not pend:
        term.say(term.t("判断を待っている変更はない。", "No detected changes waiting."))
        return 0
    items = []
    for s in pend:
        d = s.content
        term.say("\n" + term.c(s.sid, "1") + "  %s  tool=%s  %s" % (d.get("path") or ", ".join(d.get("parts") or []), d.get("tool"), d.get("ts")))
        if d.get("summary"):
            term.say("  " + term.t("そのときの操作: ", "operation: ") + d["summary"][:200])
        if d.get("what") == "manuscript":
            src = msguard.before_copy_path(proj, d)
            before = read_text(src) if src else ""
            cur_p = os.path.join(proj, d["path"])
            cur = read_text(cur_p) if os.path.exists(cur_p) else ""
            if not src:
                term.say(term.t("  (変更前の写しがこの PC にない。git diff などで確かめる)", "  (no pre-change copy on this computer; use git diff)"))
            for ln in list(difflib.unified_diff(before.split("\n"), cur.split("\n"), "before", "now", lineterm="", n=1))[:80]:
                term.say("  " + (term.c(ln, "31") if ln.startswith("-") else term.c(ln, "32") if ln.startswith("+") else ln))
            k = term.key(term.t("  [k]残す(AI の関与として記録) [m]自分のエディタでの編集だった [r]元に戻す [s]保留 > ",
                                "  [k]eep (record as AI involvement) [m]ine (my own edit) [r]evert [s]kip > "), "kmrs")
        else:
            term.say(term.t("  守られている場所が変わった: ", "  protected files changed: ") + ", ".join(d.get("parts") or []))
            for k, before, cur in msguard.protected_diffs(proj, d):  # show what changed
                if before is None and cur is None:
                    continue
                for ln in list(difflib.unified_diff((before or "").split("\n"), (cur or "").split("\n"), "before/" + k, "now/" + k,
                                                    lineterm="", n=1))[:60]:
                    term.say("  " + (term.c(ln, "31") if ln.startswith("-") else term.c(ln, "32") if ln.startswith("+") else ln))
            term.say(term.t("  自分の操作(同時に ./rk や画面を使っていた)なら [m]。心当たりがなければ [s] のまま git diff などで調べる。",
                            "  [m] if it was your own action at the same time; otherwise keep it pending [s] and investigate."))
            k = term.key("  [m]/[k]/[s] > ", "mks")
        if k == "s":
            continue
        items.append({"kind": "change", "id": s.sid, "decision": {"k": "kept_ai", "m": "mine", "r": "reverted"}[k], "digest": s.digest})
    finish(proj, term, items)
    return 0


def cmd_disclose(proj):
    from . import disclosure
    term = start(proj, "AI 利用の概要を日ごとに自分の言葉で書いて確認する", "Write and confirm the AI-use summary per day")
    trusted, _p, _n = trust.local_trusted(proj)
    idx, _b = sign.valid_index(proj, trusted)
    days = disclosure.by_day(proj)
    todo = [s for s in subjects.ailog_days(proj) if not sign.latest(idx, "ailog", s.sid)]
    if not todo:
        term.say(term.t("確認を待っている日はない。./rk facts で一覧を見る。", "No days waiting. See ./rk facts."))
        return 0
    term.say(term.t("記録にプロンプトの本文はない(機密の混入を避けるため種類だけを自動で記録した)。概要は自分の言葉で書く。",
                    "The log holds no prompt text (only categories). Write the summary in your own words."))
    items = []
    for s in todo:
        x = days.get(s.sid)
        if not x:
            continue
        sug = disclosure.suggested_summary(x, term.lang)
        term.say("\n" + term.c(s.sid, "1") + "  model: %s  prompts: %d" % (", ".join(sorted(x["models"])) or "unknown", x["prompts"]))
        term.say("  " + term.t("操作: ", "actions: ") + ", ".join("%s×%d" % kv for kv in x["areas"].most_common(8)))
        term.say("  " + term.t("記録された種類(参考。概要ではない): ", "recorded categories (for reference; not a summary): ") + sug)
        # the summary is the student's own words: there is no key that signs the category list as it is
        k = term.key(term.t("  [w]自分で書く [s]保留 [q]ここまで > ", "  [w]rite my own [s]kip [q]stop > "), "wsq")
        if k == "q":
            break
        if k == "s":
            continue
        summary = term.ask(term.t("  概要(自分の言葉で): ", "  summary (your own words): ")).strip()
        if summary and summary == sug:
            term.say(term.t("  記録された種類をそのまま写しただけになっている。自分の言葉で書く。", "  That is the category list copied; write it in your own words."))
            continue
        where = term.ask(term.t("  どの部分でどのように(任意。例: 第2章の文献探し): ", "  where and how (optional): ")).strip()
        if summary:
            items.append({"kind": "ailog", "id": s.sid, "decision": "confirmed", "note": summary, "where_how": where, "digest": s.digest})
    finish(proj, term, items)
    return 0


def section_diff_lines(proj, s, idx):
    prev, rec = decide.section_diff_base(proj, s.sid, idx)
    cur = read_text(os.path.join(proj, s.sid))
    if rec is None:
        return None, cur
    if prev is None:
        return [], cur
    return list(difflib.unified_diff(prev.split("\n"), cur.split("\n"), "signed", "now", lineterm="", n=1)), cur


def cmd_signoff(proj):
    from . import check
    term = start(proj, "提出前: 原稿を節ごとに読んで署名し、チェックリストを確かめる", "Before submission: sign each section and go through the checklist")
    rep = check.run(proj, stage="draft")
    if rep.errors:
        for e in rep.errors:
            term.say("NG  " + e)
        term.say(term.t("先に上のエラーを解消する(./rk check)。", "Fix the errors above first (./rk check)."))
        return 1
    trusted, _p, _n = trust.local_trusted(proj)
    idx, _b = sign.valid_index(proj, trusted)
    from . import disclosure, provenance
    sm = provenance.summary(proj)
    term.say(term.t("由来の記録: 段落 %d のうち AI が書いた %d・AI が直した %d・AI の段落を自分が直した(推定)%d・自分(推定)%d・記録なし %d"
                    % (sm["paragraphs"], sm["by_origin"]["ai_wrote"][0], sm["by_origin"]["ai_edited"][0], sm["by_origin"]["student_after_ai"][0],
                       sm["by_origin"]["student"][0], sm["by_origin"]["unrecorded"][0]),
                    "Provenance: of %d paragraphs, AI-written %d, AI-revised %d, AI paragraphs you revised (estimated) %d, yours (estimated) %d, unrecorded %d"
                    % (sm["paragraphs"], sm["by_origin"]["ai_wrote"][0], sm["by_origin"]["ai_edited"][0], sm["by_origin"]["student_after_ai"][0],
                       sm["by_origin"]["student"][0], sm["by_origin"]["unrecorded"][0])))
    st = subjects.disclosure_statements(proj)
    term.say(term.t("開示文: %s" % (", ".join(st) or "なし(disclosure/statement.md。./rk facts の事実から作る)"),
                    "Disclosure statement: %s" % (", ".join(st) or "none (disclosure/statement.md; draft it from ./rk facts)")))
    for relp in st:
        term.say("  ----- %s" % relp)
        for ln in read_text(os.path.join(proj, relp)).split("\n")[:60]:
            term.say("  " + ln)
    del disclosure
    items = []
    for s in subjects.sections(proj):
        if sign.current(idx, "section", s.sid, s.digest):
            continue
        diff, cur = section_diff_lines(proj, s, idx)
        term.say("\n" + term.c(s.sid, "1"))
        if diff is None:
            term.say(term.t("  初めての署名。全文を読んでから答える(%d 字)。" % len(cur), "  First sign-off: read the whole file (%d chars)." % len(cur)))
        elif not diff:
            term.say(term.t("  前回の署名時の内容がこの PC にない。全文を読み直してから答える。", "  The previously signed text is not on this computer; reread the whole file."))
        else:
            term.say(term.t("  前回の署名からの差分(AI のツールの外で変わった箇所も含む):", "  Diff since your last sign-off (including changes made outside AI tool calls):"))
            for ln in diff[:120]:
                term.say("  " + (term.c(ln, "31") if ln.startswith("-") else term.c(ln, "32") if ln.startswith("+") else ln))
        k = term.key(term.t("  この内容を読み、提出物として責任を持てる?(AI が書いた・直した段落も含めて) [y]はい [n]いいえ > ",
                            "  read it and take responsibility for it as your submission (including what the AI wrote or revised)? [y]/[n] > "), "yn")
        if k != "y":
            term.say(term.t("  記録しない。読み直してから、もう一度 ./rk signoff。", "  Not recorded. Reread, then run ./rk signoff again."))
            return 1
        items.append({"kind": "section", "id": s.sid, "decision": "reviewed", "digest": s.digest})
    for cid in subjects.CHECKLIST_IDS:
        ja, en = CHECKLIST[cid]
        k = term.key("  [ ] %s  [y]/[n] > " % term.t(ja, en), "yn")
        if k != "y":
            term.say(term.t("  この項目が満たせるまで提出前の確認はしない(節を読んだ確認だけ記録する)。", "  Not signing the pre-submission record until this holds (section confirmations only)."))
            finish(proj, term, items)
            return 1
    items.append({"kind": "presubmit", "id": "submission", "decision": "ready"})
    finish(proj, term, items)
    return 0


def cmd_optout(proj):
    term = start(proj, "学習へのオプトアウトの確認を記録する(ガイドラインⅡ-2(1))", "Record the training opt-out check (guideline II-2(1))")
    k = term.key(term.t("使っている AI サービスで、入力を学習に使わせない設定を確認したか? [y]/[n] > ",
                        "Did you check the setting that keeps your input out of training? [y]/[n] > "), "yn")
    if k != "y":
        term.say(term.t("設定の場所は使っているサービスの公式の案内で確かめる。確認できたら、もう一度 ./rk optout。",
                        "Check your service's official help, then run ./rk optout again."))
        return 1
    finish(proj, term, [{"kind": "optout", "id": "optout", "decision": "checked"}])
    return 0


def cmd_sign(proj, kind, sid, decision, note=""):
    term = start(proj, "一件を署名する(%s %s)" % (kind, sid), "Sign one item (%s %s)" % (kind, sid))
    s = subjects.find(proj, kind, sid)
    if s is None:
        raise RkError("見つからない: %s %s" % (kind, sid))
    import json
    term.say(json.dumps(s.content, ensure_ascii=False, indent=1)[:4000])
    k = term.key(term.t("  上の内容を確かめたうえで「%s」と記録する? [y]/[n] > " % decision, "  record '%s' for the content above? [y]/[n] > " % decision), "yn")
    if k != "y":
        return 1
    finish(proj, term, [{"kind": kind, "id": sid, "decision": decision, "note": note, "digest": s.digest}])
    return 0


def cmd_trust(proj):
    term = start(proj, "この PC で、プロジェクトの署名者を信頼の起点に登録する", "Register this project's signers as trusted on this computer")
    signers = sign.load_signers(proj)
    if not signers:
        term.say(term.t("署名者がいない。./rk setup で登録する。", "No signers; run ./rk setup."))
        return 1
    current = trust.read_trust_copy(proj) or {}
    ok = {}
    for k, s in sorted(signers.items(), key=lambda x: x[1].get("added", "")):
        if not sign.self_sig_ok(s):
            term.say(term.t("  %s は自己署名が合わないので信頼しない" % sign.fingerprint(k), "  %s: bad self-signature, not trusted" % sign.fingerprint(k)))
            continue
        term.say("\n  %s  %s(%s、登録 %s)%s" % (sign.fingerprint(k), s.get("name"), s.get("role"), (s.get("added") or "")[:10],
                                          term.t("  [登録済み]", "  [already trusted]") if k in current else ""))
        a = term.key(term.t("  この指紋は、最初に控えた自分(または指導教員)の指紋と同じか? [y]/[n] > ",
                            "  is this the fingerprint you noted when it was registered? [y]/[n] > "), "yn")
        if a == "y":
            ok[k] = s
    if not ok:
        term.say(term.t("何も登録しなかった。", "Nothing registered."))
        return 1
    trust.write_trust_copy(proj, ok)
    term.say(term.t("登録した: %d 名。この PC の信頼の起点: %s" % (len(ok), trust_path(proj)),
                    "Registered %d signer(s): %s" % (len(ok), trust_path(proj))))
    return 0


def cmd_import_docx(proj, docx_path, doc):
    from review.store import Store
    from . import docx_comments
    from .common import safe_rel
    term = start(proj, "指導教員が Word に入れたコメントを取り込む", "Import the comments your advisor put into a Word file")
    items = docx_comments.extract(docx_path)
    full, r = safe_rel(proj, doc, "manuscript/")
    text = read_text(full)
    term.say(term.t("コメント %d 件。取り込むと、指導教員のコメント(T0・T1)として残る。変更履歴は原稿に反映しない。" % len(items),
                    "%d comment(s). They become advisor comments (T0/T1); tracked changes are not applied." % len(items)))
    for it in items[:30]:
        term.say("  [%s] %s: %s" % (it["kind"], it.get("author"), (it.get("comment") or "")[:80]))
    if term.key(term.t("  取り込む? [y]/[n] > ", "  import? [y]/[n] > "), "yn") != "y":
        return 1
    subj = subjects.import_subject(docx_path)
    rec = sign.make_confirmation("import", subj.sid, "imported", subj.digest, {"doc": r, "count": len(items)}, "tty",
                                 name=decide.who(proj))
    st = Store(proj)
    n = orphan = 0
    for it in items:
        pos = docx_comments.locate(text, it.get("anchor") or "") or docx_comments.locate(text, (it.get("paragraph") or "")[:40])
        if pos is None:
            orphan += 1
            continue
        code = "T0" if it["kind"] == "comment" else "T1"
        body = "%s(%s): %s" % (it.get("author") or "advisor", (it.get("date") or "")[:10], it.get("comment"))
        st.create(r, text, pos[0], pos[1], code, body, "advisor", "推奨", channel="tty")
        n += 1
    sign.append_signoffs(proj, [rec])
    term.say(term.t("取り込んだ: %d / 位置不明: %d" % (n, orphan), "Imported %d, not located %d" % (n, orphan)))
    return 0


def run_human(cmd, proj, a):
    try:
        if cmd == "confirm":
            return cmd_confirm(proj, a.ids)
        if cmd == "apply":
            return cmd_apply(proj, a.ids)
        if cmd == "verify":
            return cmd_verify(proj, a.ids)
        if cmd == "style":
            return cmd_style(proj)
        if cmd == "resolve":
            return cmd_resolve(proj, a.ids)
        if cmd == "changes":
            return cmd_changes(proj)
        if cmd == "disclose":
            return cmd_disclose(proj)
        if cmd == "signoff":
            return cmd_signoff(proj)
        if cmd == "optout":
            return cmd_optout(proj)
        if cmd == "sign":
            return cmd_sign(proj, a.kind, a.id, a.decision, a.note or "")
        if cmd == "trust":
            return cmd_trust(proj)
        if cmd == "import-docx":
            return cmd_import_docx(proj, a.file, a.doc)
    except (sign.SignError, decide.DecisionError) as e:
        sys.stderr.write(str(e) + "\n")
        return 3
    raise RkError("unknown human command %s" % cmd)
