"""./rk setup - the one terminal session a student needs. Resumable: every step checks what is already done and
skips it; each step explains itself and asks for confirmation.

  1 course      course name, AI policy from the syllabus (III-3) with a one-line source, allowed uses, disclosure
                format. The policy decides what the AI may do with the manuscript (allowed / limited / prohibited /
                unknown)
  2 opt-out     whether the training opt-out of the AI service was checked (II-2(1))
     -> 1 and 2 are recorded as light confirmations (no passphrase)
  3 passphrase  optional now: it is needed only for VERIFIED and the final pre-submission confirmation, and is
                registered the first time one of them is made if the student skips it here. With GitHub, registering
                now puts the signer into the first commit (the trust root for CI)
  4 Git         none / local Git / GitHub
Finally it tells the student to reopen Claude Code in this folder (the hooks act only where the project is).
"""
import os
import subprocess

from . import human, sign, subjects, trust
from .common import RkError, load_config, set_config_value, tr

POLICIES = {"a": "allowed", "l": "limited", "p": "prohibited", "u": "unknown"}
USES = ("research", "verify", "format", "review", "language", "ideas", "draft")


def _git(proj, *args):
    # setup writes (init/commit/config/push) in the student's terminal; still disable the config entries that let
    # a planted .git/config run code during these operations.
    from .common import GIT_SAFE_FLAGS
    env = dict(os.environ, GIT_CONFIG_NOSYSTEM="1", GIT_TERMINAL_PROMPT="0")
    try:
        r = subprocess.run(["git", "-C", proj] + GIT_SAFE_FLAGS + list(args), capture_output=True, text=True,
                           timeout=60, env=env)
        return r.returncode, (r.stdout + r.stderr).strip()
    except (OSError, subprocess.SubprocessError) as e:
        return 1, str(e)


def step_passphrase(proj, term):
    signers = sign.load_signers(proj)
    trusted, probs, _n = trust.local_trusted(proj)
    if trusted:
        active = {k: s for k, s in trusted.items() if s.get("status", "active") == "active"}
        term.say(term.t("   登録済み(%s)。" % ", ".join(sign.fingerprint(k) for k in active),
                        "   already registered (%s)." % ", ".join(sign.fingerprint(k) for k in active)))
        if term.key(term.t("   [k]このまま [n]新しい合言葉を登録する(忘れた・漏れたとき) > ", "   [k]eep [n]ew passphrase (forgotten or leaked) > "), "kn") == "k":
            return trusted
        leaked = term.key(term.t("   今までの合言葉が他人(チャットや AI を含む)に知られた可能性があるか? [y]はい(新しい鍵に引き継いでから、今までの鍵を失効させる) [n]いいえ > ",
                                 "   could the old passphrase be known to anyone else (including the chat or the AI)? [y]es (hand over to the new key, then revoke the old one) [n]o > "),
                          "yn") == "y"
        return rotate(proj, term, signers, trusted, active, leaked)
    if signers and not trusted:
        term.say(term.t("   署名者は登録されているが、この PC では信頼の起点がない(別の PC で登録した場合など)。",
                        "   Signers exist but this computer has no trust copy (registered on another computer?)."))
        if term.key(term.t("  ./rk trust と同じ照合をここで行う? [y]/[n] > ", "  verify the fingerprints now (same as ./rk trust)? [y]/[n] > "), "yn") == "y":
            ok = {}
            for k, s in signers.items():
                term.say("  %s  %s(%s、登録 %s)" % (sign.fingerprint(k), s.get("name"), s.get("role"), (s.get("added") or "")[:10]))
                if sign.self_sig_ok(s) and term.key(term.t("  控えた指紋と同じ? [y]/[n] > ", "  same as the one you noted? [y]/[n] > "), "yn") == "y":
                    ok[k] = s
            if ok:
                trust.write_trust_copy(proj, ok, roots=list(ok))
                return ok
        term.say(term.t("  新しい合言葉を登録することもできる(古い署名は、古い鍵が信頼されている PC でだけ有効)。",
                        "  You can also register a new passphrase."))
    term.say(term.t(
        "合言葉(署名の合言葉)を登録する。\n"
        "   合言葉の署名が要るのは二つだけ: VERIFIED(原典を読んで確かめたという宣言)と、提出前の最終確認(内容と AI 利用の開示が正しいという宣言)。\n"
        "   ほかの判断(主張カードの確認、提案の採否、コメントの解決など)は、画面のボタンか端末のキー一つで記録される。\n"
        "   合言葉そのものも秘密鍵も、どこにも保存しない(毎回、合言葉から作って、使い終わったら捨てる)。\n"
        "   ・%d 文字以上。チャット・AI・メールには決して書かない。入力欄は、この端末と、ローカルの証拠ノートの画面だけ。\n"
        "   ・忘れたら新しく登録し直す(古い署名は有効のまま)。" % sign.MIN_PASSPHRASE,
        "Register your signing passphrase.\n"
        "   Only two declarations need it: VERIFIED (you read the original) and the final pre-submission confirmation (the content\n"
        "   and the AI-use disclosure are correct). Other decisions (claim cards, proposals, comments, ...) are a button or a key.\n"
        "   Neither the passphrase nor a private key is stored anywhere.\n"
        "   - At least %d characters. Never type it into the chat, to the AI or into e-mail; only into this terminal and\n"
        "     the local evidence-notebook page.\n"
        "   - If you forget it, register a new one (old signatures stay valid)." % sign.MIN_PASSPHRASE))
    name = load_config(proj).get("student_name") or term.ask(term.t("   記録に残す呼び名(実名でなくてよい。空なら student): ", "   name to record (need not be your real name; empty = student): ")).strip() or "student"
    # a new passphrase next to a trusted one: endorse it with the current one, so the chain from the first signer
    # stays unbroken (CI trusts only signers endorsed through the first one)
    endorser = endorser_secret = None
    active_trusted = {k: s for k, s in trusted.items() if s.get("status", "active") == "active"}
    if active_trusted:
        term.say(term.t("   新しい合言葉を、今の合言葉で承認する(承認がないと、GitHub の CI は新しい鍵を信頼しない)。",
                        "   Endorse the new passphrase with the current one (without it, GitHub CI does not trust the new key)."))
        for _ in range(3):
            cur = sign.read_passphrase(term.t("   今の合言葉(忘れたときは空のまま Enter): ", "   current passphrase (empty if forgotten): "))
            if not cur:
                term.say(term.t("   承認なしで登録する。この PC では信頼の起点になるが、GitHub の CI は最初の署名者からつながらない鍵を信頼しない。"
                                "指導教員と相談する(README「合言葉を忘れたら」)。",
                                "   Registering without endorsement: trusted on this computer, but GitHub CI does not trust a key that is not "
                                "endorsed through the first signer. Talk to your advisor (README).") )
                break
            try:
                endorser, endorser_secret = sign.unlock(active_trusted, cur)
                break
            except sign.SignError:
                term.say(term.t("   一致しない。", "   Does not match."))
            finally:
                cur = None
    for _ in range(3):
        p1 = sign.read_passphrase(term.t("   新しい合言葉: ", "   new passphrase: "))
        p2 = sign.read_passphrase(term.t("   もう一度: ", "   again: "))
        if p1 != p2:
            term.say(term.t("   一致しなかった。", "   They did not match."))
            continue
        weak = sign.weak_reason(p1)
        if weak:
            term.say(term.t("   この合言葉は推測されやすい: %s。公開鍵はプロジェクトにあるので、短い合言葉は PC の上で総当たりできる。" % weak,
                            "   This passphrase is easy to guess: %s. The public key is in the project, so a short one can be "
                            "brute-forced offline." % weak))
            continue
        s, secret = sign.register(proj, name, "student", p1, project_id=load_config(proj).get("project_id", ""),
                                  endorser=endorser, endorser_secret=endorser_secret)
        p1 = p2 = secret = endorser_secret = None
        allowed = dict(trusted)
        allowed[s["key"]] = s
        roots = [k for k in (trust.read_trust_copy(proj) or {}) if (trust.read_trust_copy(proj) or {})[k].get("root")]
        if not trusted or endorser is None:
            roots.append(s["key"])  # the first signer, or a new start after a forgotten passphrase (this computer)
        trust.write_trust_copy(proj, allowed, roots=roots or list(allowed))
        term.say(term.t("   登録した。鍵の指紋: %s\n   この指紋を手帳などに控え、初回の面談で指導教員にも見せる(フォルダで渡すときの照合に使う)。"
                        % sign.fingerprint(s["key"]),
                        "   Registered. Key fingerprint: %s\n   Note it down and show it to your advisor at the first meeting." % sign.fingerprint(s["key"])))
        return allowed
    raise RkError(term.t("合言葉を登録できなかった。", "Could not register a passphrase."))


def rotate(proj, term, signers, trusted, active, leaked):
    """A new passphrase next to a registered one.
    Remembered (leaked or not): the new key is endorsed with the current passphrase; when leaked, the old key is then
    revoked and its revocation, signed with the old key, names the new key as its successor - the only endorsement
    a revoked key keeps, so CI keeps trusting the student's new key. Forgotten: there is nothing to endorse with;
    the new key becomes a new trust root on this computer and a root change is recorded in
    .ryukoku/root-changes.jsonl (signed by the new key) for CI, which prints it prominently for the advisor."""
    pid = load_config(proj).get("project_id", "")
    name = term.ask(term.t("   記録に残す呼び名(実名でなくてよい。空なら student): ", "   name to record (empty = student): ")).strip() or "student"
    endorser = endorser_secret = None
    for _ in range(3):
        cur = sign.read_passphrase(term.t("   今の合言葉(忘れたときは空のまま Enter): ", "   current passphrase (empty if forgotten): "))
        if not cur:
            break
        try:
            endorser, endorser_secret = sign.unlock(active, cur)
            break
        except sign.SignError:
            term.say(term.t("   一致しない。", "   Does not match."))
        finally:
            cur = None
    p1 = _new_passphrase(term)
    s, secret = sign.register(proj, name, "student", p1, project_id=pid, endorser=endorser, endorser_secret=endorser_secret)
    p1 = secret = None
    signers = sign.load_signers(proj)
    allowed = dict(trusted)
    allowed[s["key"]] = s
    tc = trust.read_trust_copy(proj) or {}
    roots = [k for k, v in tc.items() if v.get("root")] or list(trusted)
    if endorser is not None:
        if leaked:
            sign.revoke(signers, endorser["key"], endorser_secret, s["key"])
            sign.save_signers(proj, signers, pid)
            term.say(term.t("   新しい鍵に引き継ぎ、今までの鍵(%s)を失効させた。失効より前の署名は有効のまま。" % sign.fingerprint(endorser["key"]),
                            "   Handed over to the new key and revoked the old key (%s); earlier signatures stay valid." % sign.fingerprint(endorser["key"])))
        endorser_secret = None
        trust.write_trust_copy(proj, allowed, roots=roots)
    else:
        if leaked:
            for k in active:
                sign.revoke(signers, k, None, "")
            sign.save_signers(proj, signers, pid)
        _record_root_change(proj, s, "forgotten" if not leaked else "leaked-and-forgotten")
        trust.write_trust_copy(proj, allowed, roots=roots + [s["key"]])
        term.say(term.t(
            "   今の合言葉で承認できないので、新しい鍵を信頼の起点にした(この PC)。GitHub の CI のために、起点の変更を\n"
            "   .ryukoku/root-changes.jsonl に記録した。main で commit して、自分の端末から push する(pre-push が yes を求める)。\n"
            "   CI は起点が変わったことと新しい指紋を最初に出す。**指導教員に新しい指紋 %s を見せ、照らしてもらう**。" % sign.fingerprint(s["key"]),
            "   Without the current passphrase the new key becomes a new trust root (this computer). For GitHub CI the root change is\n"
            "   recorded in .ryukoku/root-changes.jsonl: commit it on main and push from your terminal (pre-push asks for yes).\n"
            "   CI prints the change and the new fingerprint first. **Show the new fingerprint %s to your advisor.**" % sign.fingerprint(s["key"])))
    term.say(term.t("   登録した。新しい鍵の指紋: %s。GitHub を使うなら .ryukoku/signers.json を main に commit する。" % sign.fingerprint(s["key"]),
                    "   Registered. New key fingerprint: %s. With GitHub, commit .ryukoku/signers.json on main." % sign.fingerprint(s["key"])))
    return allowed


def _new_passphrase(term):
    for _ in range(3):
        p1 = sign.read_passphrase(term.t("   新しい合言葉: ", "   new passphrase: "))
        p2 = sign.read_passphrase(term.t("   もう一度: ", "   again: "))
        if p1 != p2:
            term.say(term.t("   一致しなかった。", "   They did not match."))
            continue
        weak = sign.weak_reason(p1)
        if weak:
            term.say(term.t("   この合言葉は推測されやすい: %s。" % weak, "   This passphrase is easy to guess: %s." % weak))
            continue
        return p1
    raise RkError(term.t("合言葉を登録できなかった。", "Could not register a passphrase."))


def _record_root_change(proj, s, reason):
    """Append a root change signed by the new key itself (it proves the key holder made it; whether that holder is
    the student is what the advisor checks with the fingerprint)."""
    import json
    from .common import append_jsonl, canonical, now_iso
    rec = {"at": now_iso(), "new_key": s["key"], "pub": s["pub"], "reason": reason}
    rec["note"] = "the advisor compares this fingerprint with the student: %s" % sign.fingerprint(s["key"])
    append_jsonl(os.path.join(proj, ".ryukoku", "root-changes.jsonl"), dict(rec, self_sig=s.get("self_sig"), signer=json.loads(canonical(
        {k: s.get(k) for k in ("key", "name", "role", "pub", "kdf", "added")}))))
    return rec


def step_course(proj, term):
    cfg = load_config(proj)
    term.say("")
    term.say(term.t("1. 科目の AI 利用条件(ガイドラインⅢ-3: 担当教員がシラバスや授業で指示する。迷ったら教員に相談)。現在: %s\n"
                    "   許可: AI が原稿を書き・直してよい(段落ごとの由来が自動で記録され、開示の事実になる)\n"
                    "   限定: AI が原稿に書く前に毎回確認が出る。ほかの道具は、選んだ用途の外で確認が出る\n"
                    "   禁止: AI は原稿を書かない・主張カードを作らない。調査・検証・形式の確認はできる\n"
                    "   分からない: 原稿に書く前に毎回確認が出る(シラバスを確かめたら、もう一度 ./rk setup)"
                    % (cfg.get("ai_policy") or "unknown"),
                    "1. Course AI policy (guideline III-3: follow the syllabus / instructor; ask when unsure). Now: %s\n"
                    "   allowed: the AI may write and revise the manuscript (each paragraph's provenance is recorded for the disclosure)\n"
                    "   limited: the AI asks before every manuscript write; other tools ask outside the uses you choose\n"
                    "   prohibited: the AI does not write the manuscript or claim cards; research, verification and format checks remain\n"
                    "   unknown: the AI asks before every manuscript write (run ./rk setup again after checking the syllabus)"
                    % (cfg.get("ai_policy") or "unknown")))
    if cfg.get("ai_policy") and cfg.get("ai_policy") != "unknown":
        if term.key(term.t("   この記録のままでよい? [y]そのまま [e]書き直す > ", "   keep it? [y]es [e]dit > "), "ye") == "y":
            return
    course = term.ask(term.t("   科目名(空なら現在のまま): ", "   course name (empty = keep): ")).strip()
    if course:
        set_config_value(proj, "course_name", '"%s"' % course.replace('"', "'"))
    k = term.key(term.t("   シラバス・教員の指示は? [a]許可 [l]限定(用途を選ぶ) [p]禁止 [u]分からない > ",
                        "   syllabus / instructor says: [a]llowed [l]imited [p]rohibited [u]nknown > "), "alpu")
    set_config_value(proj, "ai_policy", POLICIES[k])
    if k == "l":
        term.say(term.t(
            "   用途の意味(範囲の外の操作には確認が出る):\n"
            "     research  資料の検索と調査の計画(rk.py search、WebSearch・WebFetch、調査のサブエージェント)\n"
            "     verify    文献と主張の機械の確認(rk.py refcheck・ledger、source-verifier)\n"
            "     format    表記・書式の提案と書き出し(rk.py propose・lint・export、pandoc)\n"
            "     review    論証の検証・レビュー・論証図・重なりの点検(rk.py annot・argmap・overlap・verification、claim-verifier ほか)\n"
            "     language  英語の用法の説明(道具の操作には結びつかない。記録の分類と応答の範囲だけ)\n"
            "     ideas     考えの聞き取りと主張カードの整理(claims/)\n"
            "     draft     原稿の執筆・修正の材料の指定(原稿への書き込みそのものは、限定の科目では毎回確認が出る)",
            "   What each use covers (tools outside the allowed uses ask first):\n"
            "     research  searching and research plans (rk.py search, WebSearch/WebFetch, research subagents)\n"
            "     verify    machine checks of sources and claims (rk.py refcheck/ledger, source-verifier)\n"
            "     format    notation/format proposals and export (rk.py propose/lint/export, pandoc)\n"
            "     review    verification, review, argument maps, overlap checks (rk.py annot/argmap/overlap/verification, reviewers)\n"
            "     language  explaining English usage (not tied to a tool; only the log category and the answers)\n"
            "     ideas     interviewing your ideas into claim cards (claims/)\n"
            "     draft     declaring the materials for drafting (each manuscript write still asks in a limited course)"))
        term.say(term.t("   使ってよい用途を、カンマ区切りで(%s)" % ",".join(USES), "   allowed uses, comma separated (%s)" % ",".join(USES)))
        uses = [u.strip() for u in term.ask("   > ").split(",") if u.strip() in USES]
        set_config_value(proj, "ai_allowed_uses", '"%s"' % ",".join(uses))
    else:
        set_config_value(proj, "ai_allowed_uses", '""')
    if k == "u":
        term.say(term.t("   分からないまま進める。シラバスを確かめるか、担当教員に相談したら ./rk setup をもう一度。",
                        "   Continuing as unknown. Check the syllabus or ask the instructor, then run ./rk setup again."))
    src = term.ask(term.t("   根拠を一行で(シラバスの該当箇所・教員の指示の日付など。空でもよい): ", "   source in one line (syllabus section, date of the instruction; may be empty): ")).strip()
    set_config_value(proj, "ai_policy_source", '"%s"' % src.replace('"', "'"))
    disc = term.ask(term.t("   AI 利用の開示の形式・置き場所の指示(空でもよい): ", "   required disclosure format/placement (may be empty): ")).strip()
    set_config_value(proj, "disclosure_format", '"%s"' % disc.replace('"', "'"))
    term.say(term.t("   注意: どの設定でも、問い(RQ)と主張の中身は AI が新しく作ってあなたのものとして置かない。AI が書いた段落は隠さず記録され、"
                    "開示の事実になる(ガイドラインⅢ-4。開示の方法は担当教員に確かめる)。",
                    "   Note: under every setting the AI does not invent your research question or claims and present them as yours. "
                    "What the AI writes is recorded and becomes facts for the disclosure (guideline III-4; ask your instructor how to disclose)."))


def step_git(proj, term):
    term.say("")
    has_git = os.path.isdir(os.path.join(proj, ".git"))
    term.say(term.t("4. Git の使い方を選ぶ。Git なしでも、署名・記録・検査はすべて動く。",
                    "4. Choose how to use Git. Without Git, signatures, records and checks all still work."))
    no_signer = not sign.load_signers(proj)
    k = term.key(term.t("   [n]使わない [g]この PC の Git [h]GitHub も使う%s > " % ("(Git は初期化済み)" if has_git else ""),
                        "   [n]o Git [g] local Git [h] GitHub too%s > " % (" (already a Git repository)" if has_git else "")), "ngh")
    if k == "n":
        set_config_value(proj, "git_mode", "nogit")
        term.say(term.t("   Git なしで進める。指導教員に渡すときは python3 tools/rk/rk.py bundle で HANDOFF.md を作り、指紋を照らしてもらう。",
                        "   No Git. To hand over to your advisor, run python3 tools/rk/rk.py bundle and let them compare the fingerprints."))
        return
    set_config_value(proj, "git_mode", "git")
    if not has_git:
        rc, out = _git(proj, "init")
        if rc:
            term.say("   git init: " + out)
            return
        _git(proj, "symbolic-ref", "HEAD", "refs/heads/main")
    # Git needs a name and an e-mail for a commit; a new PC often has neither
    for key, ja, en in (("user.name", "Git に記録する名前(実名でなくてよい。例: student-2026): ", "name Git records (need not be your real name): "),
                        ("user.email", "Git に記録するメール(公開されうる。GitHub の noreply アドレスでもよい): ",
                         "e-mail Git records (may become public; a GitHub noreply address is fine): ")):
        rc, val = _git(proj, "config", "--get", key)
        envk = "GIT_AUTHOR_NAME" if key == "user.name" else "GIT_AUTHOR_EMAIL"
        if (rc != 0 or not val.strip()) and not os.environ.get(envk):
            v = ""
            while not v:
                v = term.ask("   " + term.t(ja, en)).strip()
            _git(proj, "config", key, v)
    rc, _o = _git(proj, "rev-parse", "--verify", "HEAD")
    if rc != 0:
        _git(proj, "add", "-A")
        rc, out = _git(proj, "commit", "-q", "-m", "rk setup: initial project (signers.json is the trust root)")
        if rc != 0:
            term.say(term.t("   最初の commit ができなかった(信頼の起点ができていないので、ここで Git の段を止める):\n   %s\n"
                            "   直したら、もう一度 ./rk setup(続きから再開する)。" % out[:400],
                            "   The first commit failed (no trust root yet, so the Git step stops here):\n   %s\n"
                            "   Fix it and run ./rk setup again (it resumes)." % out[:400]))
            return
        term.say(term.t("   main に最初の commit を作った(署名者の公開鍵を含む。CI はこれを信頼の起点にする)。" if not no_signer else
                        "   main に最初の commit を作った。合言葉はまだ登録していないので、登録した後に .ryukoku/signers.json を main で commit し、"
                        "自分の端末から push する(CI はその最初の signers.json の署名者を信頼の起点にする)。",
                        "   Made the first commit on main (with the signers' public keys: the trust root for CI)." if not no_signer else
                        "   Made the first commit on main. No passphrase yet: after registering it, commit .ryukoku/signers.json on main and push "
                        "from your terminal (CI takes the signer of that first signers.json as its trust root)."))
    else:
        rc, out = _git(proj, "ls-files", "--error-unmatch", ".ryukoku/signers.json")
        if rc != 0 and not no_signer:
            term.say(term.t("   .ryukoku/signers.json がまだ commit されていない。main で commit してから PR を作る(初回の PR でも作業ツリーは信頼しない)。",
                            "   .ryukoku/signers.json is not committed yet. Commit it on main before opening a PR."))
    _git(proj, "config", "core.hooksPath", ".githooks")
    term.say(term.t("   Git のフック(.githooks: commit と push の前に ./rk check、main への直接 push を止める)を有効にした。",
                    "   Enabled the Git hooks in .githooks (./rk check before commit and push; no direct push to main)."))
    if k == "h":
        from . import sign as _s
        fps = ", ".join(_s.fingerprint(x) for x in trust.local_trusted(proj)[0])
        term.say(term.t("   CI の信頼の起点はこの最初の commit の署名者(指紋 %s)。初回の面談で指導教員にこの指紋を見せる。" % fps,
                        "   CI's trust root is the signer in this first commit (fingerprint %s). Show it to your advisor at the first meeting." % fps))
        term.say(term.t(
            "   GitHub: ブラウザで非公開(private)のリポジトリを作り、表示される URL で\n"
            "     git remote add origin <URL>\n     git push -u origin main\n"
            "   その後は節ごとにブランチ → PR → CI → 本人(と指導教員)のレビュー → マージ。\n"
            "   注意: 非公開リポジトリのブランチ保護は GitHub Pro 以上(GitHub Docs「About protected branches」、"
            "https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-protected-branches/about-protected-branches)。保護がなくても CI と PR のチェックリストは動く。",
            "   GitHub: create a private repository in the browser, then\n     git remote add origin <URL>\n     git push -u origin main\n"
            "   Then: a branch per section -> PR -> CI -> your (and your advisor's) review -> merge.\n"
            "   Branch protection on private repositories needs GitHub Pro or above (GitHub Docs, About protected branches, "
            "https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-protected-branches/about-protected-branches)."))


def step_passphrase_optional(proj, term):
    trusted, _p, _n = trust.local_trusted(proj)
    term.say("")
    if trusted or sign.load_signers(proj):
        term.say(term.t("3. 合言葉", "3. Passphrase"))
        return step_passphrase(proj, term)
    term.say(term.t("3. 合言葉。要るのは VERIFIED と提出前の最終確認のときだけ。今登録しなくても、最初にそのどちらかをするときに登録できる。\n"
                    "   GitHub を使うなら、今登録すると最初の commit に署名者が入り、CI の信頼の起点になる。",
                    "3. Passphrase. It is needed only for VERIFIED and the final pre-submission confirmation; you can register it the first\n"
                    "   time you do one of them. With GitHub, registering now puts the signer into the first commit (CI's trust root)."))
    if term.key(term.t("   [y]今登録する [n]後で > ", "   [y] register now [n] later > "), "yn") == "y":
        return step_passphrase(proj, term)
    term.say(term.t("   後で登録する(./rk verify か ./rk signoff の最初に案内が出る)。", "   Later (./rk verify or ./rk signoff will offer it first)."))
    return {}


def run(proj):
    term = human.start(proj, "最初の設定(この端末で一度だけ)", "First-time setup (once, in this terminal)")
    term.say(term.t(
        "この Plugin は龍谷大学の公式の道具ではない。ガイドラインの解釈は作成者のもので、大学・学部・担当教員の指示が常に優先する。\n"
        "ここで決めること: 1 科目の AI 利用条件 2 オプトアウトの確認 3 合言葉(今でも後でもよい) 4 Git。途中でやめても、もう一度 ./rk setup で続きから。",
        "This plugin is not an official Ryukoku University tool; its reading of the guideline is the author's, and the university's,\n"
        "faculty's and instructor's instructions always take precedence. Steps: 1 course AI policy 2 opt-out 3 passphrase (now or later) 4 Git.\n"
        "You can stop at any point and run ./rk setup again to continue."))
    if not load_config(proj).get("student_name"):
        name = term.ask(term.t("記録に残す呼び名(実名でなくてよい。空なら student): ", "name to record (need not be your real name; empty = student): ")).strip() or "student"
        set_config_value(proj, "student_name", '"%s"' % name.replace('"', "'")[:60])
    step_course(proj, term)
    term.say("")
    items = []
    cfg = subjects.config_subject(proj)
    trusted, _p, _n = trust.local_trusted(proj)
    idx, _b = sign.valid_index(proj, trusted)
    if not sign.current(idx, "config", cfg.sid, cfg.digest):
        items.append({"kind": "config", "id": "course-policy", "decision": "confirmed", "digest": cfg.digest})
    if not sign.latest(idx, "optout", "optout"):
        term.say(term.t("2. 使っている AI サービスで、入力を学習に使わせない設定(オプトアウト)を確認したか(ガイドラインⅡ-2(1): 可能な限りオプトアウト)。\n"
                        "   設定の場所はサービスの公式の案内で確かめる。",
                        "2. Have you checked your AI service's setting that keeps your input out of training (guideline II-2(1))?\n"
                        "   Check the service's official help for where it is."))
        if term.key("   [y]/[n] > ", "yn") == "y":
            items.append({"kind": "optout", "id": "optout", "decision": "checked"})
        else:
            term.say(term.t("   未確認のまま進める。確かめたら ./rk optout。", "   Continuing unchecked; run ./rk optout later."))
    else:
        term.say(term.t("2. オプトアウトの確認: 記録済み。", "2. Opt-out check: recorded."))
    if items:
        human.finish(proj, term, items)
    step_passphrase_optional(proj, term)
    step_git(proj, term)
    term.say("")
    term.say(term.c(term.t("最後に: Claude Code を、このフォルダで開き直す。", "Finally: reopen Claude Code in this folder."), "1;33"))
    term.say(term.t("  端末なら  cd \"%s\"  のあと  claude 。デスクトップのアプリなら、このフォルダを開く。\n"
                    "  (別のフォルダで開いたままだと、記録と検知が働かない場面がある。)\n"
                    "  考え・直感・ニッチな着眼を AI に話すと、主張カード(claims/)に整理される。自分の主張だと確かめたら、画面のボタンで確認する。\n"
                    "  AI は確かめた主張カードと台帳の文献・保存したデータだけを材料に執筆を手伝い(科目が許すとき)、書いた段落の由来を記録し、\n"
                    "  主張とのすり替えや根拠の不足を検証する。判断は AI に『証拠ノートを開いて』と頼み、画面で一件ずつ確かめる。" % proj,
                    "  In a terminal:  cd \"%s\"  then  claude . In the desktop app, open this folder.\n"
                    "  (If Claude Code stays open in another folder, some recording and detection does not apply.)\n"
                    "  Tell the AI your ideas and hunches; it organises them into claim cards (claims/) that you confirm on the screen.\n"
                    "  From confirmed cards, ledger sources and saved data only, the AI helps you draft (if the course allows), records\n"
                    "  what it wrote, and checks it against your claims. Ask it to open the evidence notebook to decide item by item." % proj))
    return 0
