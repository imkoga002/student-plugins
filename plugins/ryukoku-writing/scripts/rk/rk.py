#!/usr/bin/env python3
"""rk - the project tool of ryukoku-writing (Python 3 standard library only).

The student runs ./rk <command> (Windows: rk.cmd / rk.ps1). The launcher runs the installed plugin's copy of this
file; the AI runs the machine commands as `python3 tools/rk/rk.py <command>`. Human-only commands refuse to run
from the project copy and without a terminal (rklib/human.py). `./rk help` explains everything.
"""
import argparse
import json
import os
import shutil
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from rklib import (argmap, check, criticmarkup, datacheck, disclosure, docx_comments, export, ledger,  # noqa: E402
                   overlap, proposals, refcheck, search, searchlog, sign, style, subjects, trust)
from rklib.common import (RkError, append_jsonl, feedback_lang, find_project, is_inside, load_config,  # noqa: E402
                          manuscript_files, now_iso, read_text, safe_rel, sha256_bytes, tr)

HUMAN = ("setup", "apply", "verify", "style", "resolve", "signoff", "disclose", "changes", "optout", "import-docx",
         "sign", "trust", "update-tools")
VERSION = "1.0.0"


def out(*a):
    print(*a, flush=True)


def L(proj, ja, en):
    """The project's feedback language (machine commands follow it too)."""
    return tr(feedback_lang(proj), ja, en)


def model_name(proj):
    from rklib import ailog
    for e in reversed(ailog.verify(proj, local=False)[0]):
        if e.get("model") and e.get("model") != "unknown":
            return e["model"]
    return "unknown"


HELP_JA = """rk - ryukoku-writing の道具(非公式。大学・教員の指示が優先する)

最初に一度だけ(自分の端末で):
  ./rk setup            合言葉の登録、科目の AI 利用条件、オプトアウトの確認、Git の選択

判断はまとめて画面で(おすすめ): Claude に「証拠ノートを開いて」と頼むか、./rk notebook
  画面で項目を一つずつ表示して確かめ、選んだものを合言葉一回で署名する。
端末で一件ずつ決めることもできる(どれも最後に合言葉を一回入れる):
  ./rk apply            AI の提案(表記・書式の統一)を一か所ずつ見て、採用 y / 不採用 n
  ./rk verify           原典を読んで、文献・主張に VERIFIED などを付ける
  ./rk style            抽出された記法規則を一件ずつ承認する(承認したものだけ使う)
  ./rk resolve          レビューコメントの解決
  ./rk changes          AI のツール実行中に検知した変更を、残す・自分の編集だった・戻すで決める
  ./rk disclose         AI 利用の概要を日ごとに自分の言葉で書く(開示の材料)
  ./rk signoff          提出前: 節ごとに前回の署名からの差分を読んで署名し、チェックリストを確かめる
  ./rk optout           学習へのオプトアウトの確認を記録する
  ./rk import-docx F --doc manuscript/X.md   指導教員が Word に入れたコメントを取り込む
  ./rk trust            別の PC で、署名者の指紋を照らして信頼する
誰が使ってもよい: ./rk check(検査。CI と同じ)、./rk status、./rk facts(開示の事実の一覧)
合言葉は端末と、ローカルの画面にだけ入れる。チャットや AI には決して入れない。"""
HELP_EN = """rk - ryukoku-writing tool (unofficial; your university and instructor take precedence)

Once, in your own terminal:
  ./rk setup            passphrase, course AI policy, opt-out check, Git

Decide in one go on the screen (recommended): ask Claude to "open the evidence notebook", or ./rk notebook.
  Open each item, check it, choose, and sign the chosen items with one passphrase entry.
Or decide item by item in the terminal (each ends with one passphrase entry):
  ./rk apply / verify / style / resolve / changes / disclose / signoff / optout / import-docx / trust
Anyone: ./rk check (same as CI), ./rk status, ./rk facts (facts for the AI-use disclosure)
Type the passphrase only into your terminal or the local page. Never into the chat or to the AI."""


def cmd_help(proj, a):
    out(HELP_EN if feedback_lang(proj) == "en" else HELP_JA)
    return 0


# ===================================================================== check / status / facts
def cmd_check(proj, a):
    stage = "submit" if a.submit else a.stage
    rep = check.run(proj, stage=stage, ci=a.ci, base_ref=a.base_ref)
    en = rep.lang == "en"
    for h in rep.head:
        out(h)
    for e in rep.errors:
        out("NG   " + e)
    for w in rep.warns:
        out(("WARN " if en else "注意 ") + w)
    for n in rep.notes:
        out(("-    " if en else "・   ") + n)
    out(("check(%s%s): %d error(s) / %d warning(s)" if en else "check(%s%s): エラー %d 件 / 注意 %d 件")
        % (stage, ", CI" if a.ci else "", len(rep.errors), len(rep.warns)))
    return 1 if rep.errors else 0


def cmd_status(proj, a):
    trusted, _p, _n = trust.local_trusted(proj)
    idx, _b = sign.valid_index(proj, trusted)
    from rklib import msguard
    cl = subjects.claims(proj)
    out(L(proj, "提案の未判断: %d か所  主張: %d 件(VERIFIED %d)  未解決コメント: %d  検知した変更(未判断): %d  署名者: %d",
          "undecided proposal hunks: %d  claims: %d (VERIFIED %d)  open comments: %d  undecided detections: %d  signers: %d")
        % (len(subjects.hunks(proj)), len(cl), sum(1 for c in cl if c.claimed == "VERIFIED"),
           len([c for c in subjects.comments(proj) if not c.claimed]), len(msguard.pending(proj, idx)), len(trusted)))
    return 0


def cmd_facts(proj, a):
    txt, _ = disclosure.facts(proj, feedback_lang(proj))
    out(txt)
    return 0


# ===================================================================== propose (AI)
def cmd_propose(proj, a):
    if a.sub == "list":
        for m in proposals.pending(proj):
            n = len([h for h in m["hunks"] if h["n"] not in proposals.decided(m)])
            out(L(proj, "%s %-8s %-40s %d か所  %s", "%s %-8s %-40s %d hunk(s)  %s") % (m["id"], m.get("kind"), m.get("target"), n, m.get("why", "")))
            for h in m["hunks"]:
                if h["n"] in proposals.decided(m):
                    continue
                try:
                    lines = read_text(os.path.join(proj, m["target"])).split("\n")
                except OSError:
                    lines = []
                if proposals.locate(lines, h, False) is None:
                    out(L(proj, "    #%d: 位置を特定できない(原稿が変わった)。作り直しが要る(採用できない)",
                          "    #%d: cannot be located (the manuscript changed); needs to be regenerated (cannot be accepted)") % h["n"])
        return 0
    if a.sub == "start":
        full, r = safe_rel(proj, a.file, "manuscript/")
        tok = "W" + sha256_bytes((r + now_iso()).encode())[:8]
        wd = os.path.join(proj, "proposals", ".work", tok)
        os.makedirs(wd, exist_ok=True)
        dst = os.path.join(wd, os.path.basename(r))
        shutil.copy2(full, dst)
        with open(os.path.join(wd, "target.txt"), "w", encoding="utf-8") as f:
            f.write(r + "\n" + sha256_bytes(read_text(full).encode("utf-8")) + "\n")
        out(os.path.relpath(dst, proj))
        out(L(proj, "この写しを編集し(表記・書式だけ)、'python3 tools/rk/rk.py propose finish %s --kind format --why \"...\"' で提案にする。",
              "Edit this copy (notation/format only), then make it a proposal with 'python3 tools/rk/rk.py propose finish %s --kind format --why \"...\"'.") % tok)
        return 0
    if a.sub == "finish":
        wd = os.path.join(proj, "proposals", ".work", a.token)
        try:
            target, base = read_text(os.path.join(wd, "target.txt")).split("\n")[:2]
        except (OSError, ValueError):
            raise RkError(L(proj, "作業用の写し %s がない", "working copy %s not found") % a.token)
        old = read_text(os.path.join(proj, target))
        if sha256_bytes(old.encode("utf-8")) != base:
            raise RkError(L(proj, "写しを作った後に原稿が変わった(学生が書き進めた)。学生の変更を消さないよう、propose start からやり直す",
                            "The manuscript changed after the copy was made (the student kept writing). Start again with propose start so their changes are kept"))
        new = read_text(os.path.join(wd, os.path.basename(target)))
        path, meta, n = proposals.create(proj, target, old, new, a.kind, a.why, a.rule or "", "ai", model_name(proj))
        shutil.rmtree(wd, ignore_errors=True)
        out(L(proj, "提案 %s を作った(%d か所): %s", "made proposal %s (%d hunk(s)): %s") % (meta["id"], n, os.path.relpath(path, proj)))
        out(L(proj, "学生に: 証拠ノート(画面)の「提案」で一か所ずつ見て決めるか、自分の端末で ./rk apply。",
              "Tell the student: decide each hunk under 'Proposals' in the evidence notebook, or with ./rk apply in their terminal."))
        return 0
    if a.sub == "from-cm":
        full, r = safe_rel(proj, a.target, "manuscript/")
        old, new = criticmarkup.old_new(read_text(a.cmfile))
        cur = read_text(full)
        if old != cur:
            raise RkError(L(proj, "CriticMarkup の『元の文』が現在の原稿と一致しない。現在の原稿の写しに記号を付けること",
                            "The CriticMarkup 'old' text does not match the current manuscript; mark up a copy of the current file"))
        path, meta, n = proposals.create(proj, r, cur, new, a.kind, a.why, a.rule or "", "ai", model_name(proj))
        out(L(proj, "提案 %s を作った(%d か所): %s", "made proposal %s (%d hunk(s)): %s") % (meta["id"], n, os.path.relpath(path, proj)))
        return 0
    if a.sub in ("style", "mermaid"):
        trusted, _p, _n = trust.local_trusted(proj)
        idx, _b = sign.valid_index(proj, trusted)
        lang = "en" if load_config(proj).get("manuscript_lang", "ja").startswith("en") else "ja"
        rules, _probs = style.approved_rules(proj, idx, lang)
        made = 0
        for f in a.files:
            full, r = safe_rel(proj, f, "manuscript/")
            old = read_text(full)
            if a.sub == "style":
                new, used = style.fix_text(old, rules)
                kind, why, rule = "format", "承認済みの記法規則(%s)に合わせる機械的な置換。語は変えない" % ",".join(used), ",".join(used)
            else:
                new, _cnt = style.pin_mermaid(old)
                kind, why, rule = "diagram", "Mermaid 12 で既定の見た目が変わったため、front matter で theme・look・layout を固定する(Mermaid の Flowchart syntax の「Default theme, look and layout (v12.0.0+)」、https://mermaid.js.org/syntax/flowchart.html)", ""
            if new == old:
                out(L(proj, "%s: 直す箇所はない", "%s: nothing to fix") % r)
                continue
            path, meta, n = proposals.create(proj, r, old, new, kind, why, rule, "tool", model_name(proj))
            made += 1
            out(L(proj, "提案 %s を作った(%d か所): %s", "made proposal %s (%d hunk(s)): %s") % (meta["id"], n, os.path.relpath(path, proj)))
        if not made and a.sub == "style" and not rules:
            out(L(proj, "承認済みの記法規則がない(学生が署名して承認するまで、規則は適用しない)。",
                  "No approved style rules (rules apply only after the student signs their approval)."))
        return 0
    return 2


def cmd_lint(proj, a):
    trusted, _p, _n = trust.local_trusted(proj)
    idx, _b = sign.valid_index(proj, trusted)
    lang = "en" if load_config(proj).get("manuscript_lang", "ja").startswith("en") else "ja"
    rules, probs = style.approved_rules(proj, idx, lang)
    for p in probs:
        out("注意 " + p)
    files = a.files or manuscript_files(proj)
    n = 0
    texts = []
    for f in files:
        t = read_text(f)
        texts.append(t)
        for path, line, rid, why in style.lint(t, rules, os.path.relpath(f, proj)):
            out("%s:%d [%s] %s" % (path, line, rid, why))
            n += 1
    total, lens = style.length_report(texts, rules)
    out(L(proj, "本文の字数(空白・見出し・表・コードを除く概算): %d", "text length (approx., without spaces, headings, tables, code): %d") % total)
    for rid, kind, lim, _tot, bad in lens:
        out("[%s] %s %d: %s" % (rid, "上限" if kind == "max_chars" else "下限", lim, "超えている" if bad and kind == "max_chars" else ("足りない" if bad else "満たす")))
    _t, prop = style.load(style.proposed_path(proj))
    if prop:
        out("未承認のため適用していない規則: %s(学生が画面か ./rk style で承認)" % ", ".join(r.get("id", "?") for r in prop))
    out(L(proj, "lint: 指摘 %d 件。直すのは本人(機械的な置換は 'rk.py propose style' で提案にできる)",
          "lint: %d findings. The student fixes them (mechanical replacements can be proposed with 'rk.py propose style')") % n)
    return 1 if n else 0


def cmd_rules(proj, a):
    _t, prop = style.load(style.proposed_path(proj))
    probs = style.validate_proposed(prop)
    for p in probs:
        out("NG " + p)
    out("規則の提案: %d 件、問題 %d 件" % (len(prop), len(probs)))
    return 1 if probs else 0


# ===================================================================== refcheck / search / searchlog / ledger
def _mailto(proj):
    return os.environ.get("CLAUDE_PLUGIN_OPTION_CROSSREF_MAILTO") or load_config(proj).get("crossref_mailto") or None


def _appid():
    return os.environ.get("CLAUDE_PLUGIN_OPTION_CINII_APPID") or os.environ.get("CINII_APPID") or None


def cmd_refcheck(proj, a):
    reg = ledger.paths(proj)[0]
    if a.sub == "offline":
        if a.doi:
            d = refcheck.normalize_doi(a.doi)
            out(json.dumps({"doi": d, "syntax_ok": refcheck.valid_doi_syntax(d)}))
        if a.isbn:
            out(json.dumps({"isbn": refcheck.clean_isbn(a.isbn), "isbn13_valid": refcheck.isbn13_valid(a.isbn)}))
        return 0
    rows = ledger.read(reg, ledger.REGISTER)
    net = refcheck.Net(mailto=_mailto(proj), cache_dir=os.path.join(proj, ".ryukoku", "cache"))
    results = []
    for r in rows:
        if a.id and r["id"] not in a.id:
            continue
        ref = {"id": r["id"], "doi": r.get("doi"), "isbn": r.get("isbn"), "ncid": r.get("ncid"), "crid": r.get("crid"),
               "ndl_id": r.get("ndl_id"), "title": r.get("title"), "authors": r.get("authors"),
               "year": int(r["year"]) if (r.get("year") or "").strip().isdigit() else None}
        res = refcheck.check_ref(ref, net, _appid())
        results.append(res)
        out("%-6s %-18s %s" % (r["id"], res.get("status") or L(proj, "(未判定)", "(undecided)"), res.get("reason", "")))
    if a.dry_run:
        return 0
    rows = refcheck.apply_results(rows, results)
    ledger.write(reg, rows, ledger.REGISTER)
    for res in results:
        append_jsonl(os.path.join(proj, "sources", "verification-log.jsonl"), refcheck.log_entry(res))
    out(L(proj, "機械の列を更新した。VERIFIED は学生が原典を読んで付ける(証拠ノートか ./rk verify)。",
          "Updated the machine columns. VERIFIED is set by the student after reading the source (evidence notebook or ./rk verify)."))
    return 0


def cmd_search(proj, a):
    try:
        rec, items, extra = search.run(proj, a.db, a.query, a.question_ref, a.rows, a.type, a.cql, _mailto(proj), _appid(),
                                       a.by, a.purpose)
    except search.UnknownQuestion as e:
        sys.stderr.write(str(e) + "\n")
        return 2
    out(L(proj, "検索記録 %s: %s 「%s」 件数=%s 問い=%s 目的=%s", "search record %s: %s \"%s\" hits=%s question=%s purpose=%s")
        % (rec["id"], rec["db"], rec["query"], L(proj, "不明", "unknown") if rec["hits"] is None else rec["hits"],
           rec["question_ref"], rec.get("purpose")))
    for i, it in enumerate(items, 1):
        out("  %2d. %s | %s | %s | %s" % (i, it.get("title", "")[:90], it.get("year") or "", it.get("authors", "")[:40], it.get("id", "")))
    if extra:
        out(extra)
    out(L(proj, "候補は自動で選ばない(実在確認の前)。読む候補を選んだら: rk.py searchlog annotate %s --selected <id,...> --reason \"...\"",
          "Nothing is selected automatically (existence is not checked yet). After choosing what to read: rk.py searchlog annotate %s --selected <id,...> --reason \"...\"") % rec["id"])
    return 0


def cmd_searchlog(proj, a):
    if a.sub == "validate":
        errs, warns = searchlog.validate(searchlog.load(proj))
        for e in errs:
            out("NG " + e)
        for w in warns:
            out("注意 " + w)
        out(L(proj, "検索記録: エラー %d / 注意 %d", "search log: %d errors / %d notes") % (len(errs), len(warns)))
        return 1 if errs else 0
    if a.sub == "export":
        sys.stdout.write(searchlog.to_markdown(searchlog.load(proj)))
        return 0
    if a.sub == "annotate":
        if a.question_ref and a.question_ref not in search.question_ids(proj):
            raise RkError("問い %s が research/questions.md にない" % a.question_ref)
        r = searchlog.annotate(proj, a.id, a.question_ref, a.selected, a.reason, a.hits)
        out(json.dumps(r, ensure_ascii=False))
        return 0
    if a.question_ref not in search.question_ids(proj):
        raise RkError("問い %s が research/questions.md にない(学生が書いた問いの id を使う)" % a.question_ref)
    r = searchlog.add(proj, a.db, a.query, a.question_ref, a.hits, a.filters,
                      [s for s in (a.selected or "").split(",") if s], a.reason or "", a.by, purpose=a.purpose, auto=False)
    out(r["id"])
    return 0


def cmd_ledger(proj, a):
    if a.sub == "add-source":
        r = ledger.add_source(proj, id=a.id or "", citekey=a.citekey or "", doi=a.doi or "", isbn=a.isbn or "",
                              ncid=a.ncid or "", crid=a.crid or "", ndl_id=a.ndl_id or "", url=a.url or "",
                              title=a.title or "", authors=a.authors or "", year=a.year or "", container=a.container or "",
                              language=a.language or "", medium=a.medium or "")
        out(L(proj, "source %s を追加した(機械の状態 CANDIDATE)。次: rk.py refcheck check --id %s",
              "added source %s (machine status CANDIDATE). Next: rk.py refcheck check --id %s") % (r["id"], r["id"]))
        return 0
    if a.sub == "add-claim":
        r = ledger.add_claim(proj, a.claim, a.source_id or "", a.locator or "", a.used_in or "")
        out(L(proj, "claim %s を追加した(CANDIDATE)。頁などの位置(locator)と VERIFIED は、学生が原典を読んで画面か ./rk verify で付ける",
              "added claim %s (CANDIDATE). The student reads the source and sets the locator (pages) and VERIFIED on the screen or with ./rk verify") % r["claim_id"])
        return 0
    reg, cl = ledger.paths(proj)
    for r in ledger.read(reg, ledger.REGISTER):
        out("%s  machine=%s human=%s  %s" % (r["id"], r["machine_status"], r["human_status"] or "-", r["title"][:60]))
    for c in ledger.read(cl, ledger.CLAIMS):
        out("%s  %s  src=%s loc=%s  human=%s" % (c["claim_id"], c["claim"][:50], c["source_id"], c["locator"], c["human_status"] or "CANDIDATE"))
    return 0


def cmd_data(proj, a):
    root = os.path.join(proj, "data")
    if a.sub == "add":
        out(json.dumps(datacheck.add(root, a.file, a.url, a.provider, a.license, a.method, a.note or ""), ensure_ascii=False))
        return 0
    if a.sub == "package":
        datacheck.package(root)
        out("datapackage.json を作り直した")
        return 0
    probs = datacheck.verify(root) if a.sub == "verify" else datacheck.check_numbers(root, a.manuscript)
    for x in probs:
        out("NG " + x)
    out("%s: 問題 %d 件" % (a.sub, len(probs)))
    return 1 if probs else 0


def cmd_overlap(proj, a):
    rows = overlap.report(proj, a.files or manuscript_files(proj), a.n)
    md = overlap.to_markdown(rows)
    if a.out:
        _f, r = safe_rel(proj, a.out, "review/")
        with open(os.path.join(proj, r), "w", encoding="utf-8") as f:
            f.write(md)
        out("書いた: " + r)
    else:
        sys.stdout.write(md)
    return 0


def cmd_argmap(proj, a):
    argv = [a.input] + (["--manuscript", a.manuscript] if a.manuscript else []) + (["--out", a.out] if a.out else []) + (["--json"] if a.json else [])
    if a.out:
        safe_rel(proj, a.out, "review/")
    return argmap.main(argv)


def list_docs(proj):
    return [os.path.relpath(p, proj).replace(os.sep, "/") for p in manuscript_files(proj)]


def read_doc(proj, relp):
    try:
        full, _r = safe_rel(proj, relp, "manuscript/")
    except RkError:
        return None
    return read_text(full) if os.path.isfile(full) else None


def cmd_annot(proj, a):
    from review.store import Store, StoreError
    st = Store(proj)
    try:
        if a.sub == "list":
            for d in ([a.doc] if a.doc else list_docs(proj)):
                t = read_doc(proj, d)
                if t is not None:
                    st.reanchor(d, t)
            items = [x for x in st.load()["items"] if (not a.doc or x["target"]["source"] == a.doc)
                     and (not a.open or x["review"]["status"] == "open")]
            for x in items:
                rv = x["review"]
                qx = x["target"]["selector"][0]["exact"].replace("\n", " ")
                cm = next((b["value"] for b in x["body"] if b["purpose"] == "commenting"), "")
                ch = rv.get("channel") or ""
                who = {"notebook": "(画面から・本人確認なし / typed on the screen, identity not verified)",
                       "tty": "(端末の取り込み・署名あり / imported in the terminal, signed)",
                       "agent-cli": "(AI)"}.get(ch, "(経路の記録なし / channel not recorded)")
                out("%s\n  [%s] %s %s/%s by %s %s @%s 位置:%s\n  引用: 「%s」\n  コメント: %s" % (
                    x["id"], rv["status"], rv["code"], rv["severity"], rv["confidence"], x["creator"]["name"], who,
                    x["target"]["source"], rv.get("anchor", {}).get("state"), qx[:80], cm))
                for rp in rv["replies"]:
                    out("  └ %s(%s): %s" % (rp["author"], rp["kind"], rp["text"]))
            if not items:
                out("(該当するコメントはない)")
        elif a.sub == "reply":
            out(json.dumps(st.add_reply(a.id, "agent", a.text, a.kind), ensure_ascii=False))
        elif a.sub == "flag":
            text = read_doc(proj, a.doc)
            if text is None:
                raise RkError("原稿が見つからない")
            n = text.count(a.quote)
            if n != 1:
                raise RkError("引用が原稿中に %d 箇所ある(1 箇所に絞る)" % n)
            i = text.index(a.quote)
            out(st.create(a.doc, text, i, i + len(a.quote), a.code, a.comment, "agent", a.severity)["id"])
    except (StoreError, KeyError, PermissionError) as e:
        raise RkError(str(e))
    return 0


def cmd_docx_comments(proj, a):
    for it in docx_comments.extract(a.file):
        out("[%s] %s %s: %s\n   対象: 「%s」" % (it["kind"], it.get("author"), it.get("date"), it.get("comment"), (it.get("anchor") or "")[:80]))
    return 0


def cmd_export(proj, a):
    files = None
    if a.file:
        full, _r = safe_rel(proj, a.file)
        files = [full]
    target, warns = export.build(proj, a.format, None, files)
    for w in warns:
        out("注意 " + w)
    out("書き出した: " + os.path.relpath(target, proj))
    return 0


def cmd_guideline(proj, a):
    import hashlib
    import urllib.request
    cfg = load_config(proj)
    url, want = cfg.get("guideline_url"), cfg.get("guideline_sha256")
    req = urllib.request.Request(url, headers={"User-Agent": "ryukoku-writing/%s" % VERSION})
    with urllib.request.urlopen(req, timeout=60) as r:
        body = r.read()
        st = r.status
    got = hashlib.sha256(body).hexdigest()
    out("HTTP %s, %d bytes, sha256 %s" % (st, len(body), got))
    if got == want:
        out("記録と一致(ガイドラインは変わっていない)。")
        return 0
    out("記録と違う。改訂の可能性がある(ガイドラインⅣ)。原文を読み、この Plugin の記述と照らし、必要なら教員に確認する。Plugin の更新も確かめる。")
    return 1


def cmd_bundle(proj, a):
    """HANDOFF.md for handing the folder to an advisor without Git (the signers are listed every time)."""
    trusted, tprobs, _n = trust.local_trusted(proj)
    rep = check.run(proj, stage="draft")
    signers = sign.load_signers(proj)
    lines = ["# HANDOFF(ryukoku-writing・非公式)", "",
             "作成: %s / プロジェクト: %s" % (now_iso(), os.path.basename(proj)), "",
             "## 署名者(指紋を、初回の面談で控えたものと照らす)", ""]
    for k, s in sorted(signers.items(), key=lambda x: x[1].get("added", "")):
        lines.append("- %s %s(%s、登録 %s)%s%s" % (sign.fingerprint(k), s.get("name"), s.get("role"), (s.get("added") or "")[:10],
                     "、承認: " + sign.fingerprint(s["endorsed_by"]) if s.get("endorsed_by") else "",
                     "" if k in trusted else " **この PC では信頼されていない**"))
    lines += ["", "署名者の数: %d(登録の後に足された署名者があれば、上に別の行として出る)" % len(signers)]
    for p in tprobs:
        lines.append("- 問題: " + p)
    lines += ["", "## 検査(rk check)", "", "エラー %d 件 / 注意 %d 件" % (len(rep.errors), len(rep.warns))]
    lines += ["- NG " + e for e in rep.errors] + ["- 注意 " + w for w in rep.warns]
    lines += ["", "## 原稿のハッシュ", ""] + ["- %s %s" % (s.sid, s.content["sha256"]) for s in subjects.sections(proj)]
    with open(os.path.join(proj, "HANDOFF.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    out("HANDOFF.md を書いた")
    return 0


def cmd_notebook(proj, a):
    if is_inside(HERE, proj):
        raise RkError(tr(feedback_lang(proj), "証拠ノートの画面は、インストールされた Plugin から起動する(プロジェクトの中の tools/ からは起動しない)。./rk notebook か、Claude に「証拠ノートを開いて」と頼む。",
                         "Start the notebook from the installed plugin, not from tools/. Use ./rk notebook or ask Claude to open it."))
    from notebook.server import serve
    return serve(proj, a.port, a.open, a.once)


def cmd_update_tools(proj, a):
    from rklib import human
    term = human.start(proj, "プロジェクトの tools/ を、インストールされた Plugin の版に入れ替える", "Replace the project's tools/ with the installed plugin's version")
    if term.key(term.t("  Plugin を更新したときだけ行う。入れ替える? [y]/[n] > ", "  Only after updating the plugin. Replace? [y]/[n] > "), "yn") != "y":
        return 1
    dst = os.path.join(proj, "tools", "rk")
    shutil.rmtree(dst, ignore_errors=True)
    shutil.copytree(HERE, dst, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    for name in ("rk", "rk.cmd", "rk.ps1"):
        shutil.copy2(os.path.join(HERE, "launchers", name), os.path.join(proj, name))
    term.say(term.t("入れ替えた。Git を使うなら main で commit する(PR に混ぜない。CI は基準ブランチの道具で検査する)。",
                    "Replaced. With Git, commit this on main (not inside a section PR)."))
    return 0


# ===================================================================== parser
def build_parser():
    p = argparse.ArgumentParser(prog="rk", description="ryukoku-writing project tool (./rk help)")
    p.add_argument("--project", default=None)
    p.add_argument("--version", action="version", version="ryukoku-writing rk " + VERSION)
    sub = p.add_subparsers(dest="cmd")
    sub.add_parser("help")
    s = sub.add_parser("check"); s.add_argument("--submit", action="store_true"); s.add_argument("--ci", action="store_true")
    s.add_argument("--stage", default="draft", choices=["draft", "pr", "submit"]); s.add_argument("--base-ref")
    sub.add_parser("status"); sub.add_parser("facts"); sub.add_parser("bundle")
    s = sub.add_parser("propose"); ps = s.add_subparsers(dest="sub", required=True)
    x = ps.add_parser("start"); x.add_argument("file")
    x = ps.add_parser("finish"); x.add_argument("token"); x.add_argument("--kind", required=True, choices=proposals.KINDS); x.add_argument("--why", required=True); x.add_argument("--rule")
    x = ps.add_parser("from-cm"); x.add_argument("cmfile"); x.add_argument("--target", required=True); x.add_argument("--kind", default="format", choices=proposals.KINDS); x.add_argument("--why", required=True); x.add_argument("--rule")
    x = ps.add_parser("style"); x.add_argument("files", nargs="+")
    x = ps.add_parser("mermaid"); x.add_argument("files", nargs="+")
    ps.add_parser("list")
    s = sub.add_parser("lint"); s.add_argument("files", nargs="*")
    s = sub.add_parser("rules"); s.add_argument("sub", choices=["validate"])
    s = sub.add_parser("refcheck"); rs = s.add_subparsers(dest="sub", required=True)
    x = rs.add_parser("check"); x.add_argument("--id", action="append"); x.add_argument("--dry-run", action="store_true")
    x = rs.add_parser("offline"); x.add_argument("--doi"); x.add_argument("--isbn")
    s = sub.add_parser("search"); s.add_argument("db", choices=search.DBS); s.add_argument("query"); s.add_argument("--question-ref", required=True)
    s.add_argument("--rows", type=int, default=10); s.add_argument("--type", default="all"); s.add_argument("--cql")
    s.add_argument("--by", default="agent", choices=["agent", "human"]); s.add_argument("--purpose", default="main", choices=list(search.PURPOSES))
    s = sub.add_parser("searchlog"); ss = s.add_subparsers(dest="sub", required=True)
    ss.add_parser("validate"); ss.add_parser("export")
    x = ss.add_parser("annotate"); x.add_argument("id"); x.add_argument("--question-ref"); x.add_argument("--selected"); x.add_argument("--reason"); x.add_argument("--hits", type=int)
    x = ss.add_parser("add"); x.add_argument("--db", required=True); x.add_argument("--query", required=True); x.add_argument("--question-ref", required=True)
    x.add_argument("--hits", type=int); x.add_argument("--filters", default=""); x.add_argument("--selected"); x.add_argument("--reason")
    x.add_argument("--by", default="human", choices=["human", "agent"]); x.add_argument("--purpose", default="main", choices=list(search.PURPOSES))
    s = sub.add_parser("ledger"); ls = s.add_subparsers(dest="sub", required=True)
    x = ls.add_parser("add-source")
    for k in ("id", "citekey", "doi", "isbn", "ncid", "crid", "ndl-id", "url", "title", "authors", "year", "container", "language", "medium"):
        x.add_argument("--" + k)
    x = ls.add_parser("add-claim"); x.add_argument("--claim", required=True); x.add_argument("--source-id"); x.add_argument("--locator"); x.add_argument("--used-in")
    ls.add_parser("list")
    s = sub.add_parser("data"); ds = s.add_subparsers(dest="sub", required=True)
    x = ds.add_parser("add"); x.add_argument("file"); x.add_argument("--url", required=True); x.add_argument("--provider", required=True); x.add_argument("--license", required=True); x.add_argument("--method", required=True); x.add_argument("--note")
    ds.add_parser("verify"); x = ds.add_parser("numbers"); x.add_argument("--manuscript"); ds.add_parser("package")
    s = sub.add_parser("overlap"); s.add_argument("files", nargs="*"); s.add_argument("--n", type=int, default=12); s.add_argument("--out")
    s = sub.add_parser("argmap"); s.add_argument("input"); s.add_argument("--manuscript"); s.add_argument("--out"); s.add_argument("--json", action="store_true")
    s = sub.add_parser("annot"); an = s.add_subparsers(dest="sub", required=True)
    x = an.add_parser("list"); x.add_argument("--open", action="store_true"); x.add_argument("--doc")
    x = an.add_parser("reply"); x.add_argument("id"); x.add_argument("--kind", required=True, choices=["question", "howto", "note"]); x.add_argument("--text", required=True)
    x = an.add_parser("flag"); x.add_argument("--doc", required=True); x.add_argument("--quote", required=True); x.add_argument("--code", required=True); x.add_argument("--comment", required=True); x.add_argument("--severity", default="推奨")
    s = sub.add_parser("docx-comments"); s.add_argument("file")
    s = sub.add_parser("export"); s.add_argument("format", choices=export.FMT); s.add_argument("--file", help="export one file (e.g. examples/format-examples.md)")
    sub.add_parser("guideline-check")
    s = sub.add_parser("notebook"); s.add_argument("--project", default=argparse.SUPPRESS, help=argparse.SUPPRESS)
    s.add_argument("--port", type=int, default=0); s.add_argument("--open", action="store_true"); s.add_argument("--once", action="store_true", help=argparse.SUPPRESS)
    # human-only
    sub.add_parser("setup"); sub.add_parser("trust"); sub.add_parser("update-tools")
    s = sub.add_parser("apply"); s.add_argument("ids", nargs="*")
    s = sub.add_parser("verify"); s.add_argument("ids", nargs="*")
    sub.add_parser("style")
    s = sub.add_parser("resolve"); s.add_argument("ids", nargs="*")
    sub.add_parser("signoff"); sub.add_parser("disclose"); sub.add_parser("changes"); sub.add_parser("optout")
    s = sub.add_parser("import-docx"); s.add_argument("file"); s.add_argument("--doc", required=True)
    s = sub.add_parser("sign"); s.add_argument("kind", choices=sorted(subjects.KIND_DECISIONS)); s.add_argument("id"); s.add_argument("--decision", required=True); s.add_argument("--note")
    return p


DISPATCH = {"help": cmd_help, "check": cmd_check, "status": cmd_status, "facts": cmd_facts, "propose": cmd_propose,
            "lint": cmd_lint, "rules": cmd_rules, "refcheck": cmd_refcheck, "search": cmd_search,
            "searchlog": cmd_searchlog, "ledger": cmd_ledger, "data": cmd_data, "overlap": cmd_overlap,
            "argmap": cmd_argmap, "annot": cmd_annot, "docx-comments": cmd_docx_comments, "export": cmd_export,
            "guideline-check": cmd_guideline, "bundle": cmd_bundle, "notebook": cmd_notebook, "update-tools": cmd_update_tools}


def main(argv=None):
    p = build_parser()
    a = p.parse_args(argv)
    try:
        proj = find_project(a.project)
        os.chdir(proj)
        if not a.cmd:
            a.cmd = "help"
        if a.cmd == "ledger" and a.sub == "add-source":
            a.ndl_id = getattr(a, "ndl_id", None)
        if a.cmd == "setup":
            from rklib import setup
            return setup.run(proj)
        if a.cmd in HUMAN and a.cmd != "update-tools":
            from rklib import human
            return human.run_human(a.cmd, proj, a)
        return DISPATCH[a.cmd](proj, a)
    except RkError as e:
        sys.stderr.write(str(e) + "\n")
        return 2
    except KeyboardInterrupt:
        sys.stderr.write("\n中断した / interrupted\n")
        return 130


if __name__ == "__main__":
    sys.exit(main())
