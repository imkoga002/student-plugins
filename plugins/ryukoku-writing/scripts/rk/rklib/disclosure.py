"""AI-use disclosure facts (guideline III-4 lists example items: AI type and version, dates, a summary of the
prompts, where and how it was used). This module lists facts only; the disclosure statement may be drafted by the
AI from these facts (disclosure skill, disclosure/statement.md), and the student checks it in the final
pre-submission confirmation (passphrase signature).

Sources
  .ryukoku/ai-use-log.jsonl   hook-written, hash-chained, committed; no prompt text, only categories
  .ryukoku/signoffs.jsonl     the student's records: `ailog` (a day's prompt summary, in the student's words, with
                              where/how) and `hunk` (format proposals the student accepted)
  .ryukoku/provenance.jsonl   which paragraphs the AI wrote or revised, per file and section, with the purposes and
                              materials (the student's own edits are estimated, and marked as such)
"""
import collections

from . import ailog, provenance, sign, trust

CAT_JA = {"research": "資料の調査", "verify": "文献・事実の検証", "question": "問い・論証についての対話",
          "format": "書式・形式", "review": "レビューコメントへの応答", "data": "データの取得・検証",
          "language": "英語表現の説明", "disclosure": "開示の準備", "schedule": "進捗・締切", "other": "その他"}
CAT_EN = {"research": "finding sources", "verify": "verifying sources and facts", "question": "dialogue on questions and arguments",
          "format": "formatting", "review": "responding to review comments", "data": "data retrieval and checks",
          "language": "explaining English usage", "disclosure": "preparing disclosure", "schedule": "progress and deadlines", "other": "other"}
AREA_JA = {"proposals": "形式の提案ファイルの作成", "research": "調査・検証の記録", "rk:search": "データベース検索",
           "rk:refcheck": "文献の実在確認", "rk:propose": "形式の提案の作成", "rk:annot": "レビューコメントへの問い・返信",
           "rk:export": "提出形式への変換", "rk:lint": "記法の検査", "rk:overlap": "引用の重なりの点検",
           "rk:argmap": "論証構造の図示(学生の文から)", "subagent": "サブエージェントによる調査・検証", "skill": "スキルの使用",
           "web": "Web の検索・取得", "manuscript": "原稿の執筆・修正", "claims": "主張カードの整理(学生の言葉から)",
           "verification": "検証の結果の作成", "rk:verification": "検証の機械の照合", "rk:claims": "主張カードの作成・確認",
           "rk:provenance": "執筆の材料の指定", "statement": "開示文の下書き"}
PURPOSE_JA = {"draft": "下書き", "revise": "修正", "format": "表記・書式", "delete": "削除", "translate": "翻訳"}


def by_day(proj):
    entries, _p = ailog.verify(proj, local=False)
    days = collections.OrderedDict()
    for e in entries:
        d = e.get("date")
        if not d:
            continue
        x = days.setdefault(d, {"models": set(), "cats": collections.Counter(), "areas": collections.Counter(),
                                "flags": collections.Counter(), "prompts": 0, "detections": 0})
        if e.get("model") and e.get("model") not in ("unknown", ""):
            x["models"].add(e["model"])
        t = e.get("type")
        if t == "prompt":
            x["prompts"] += 1
            for c in (e.get("categories") or "other").split(","):
                x["cats"][c] += 1
            for f in (e.get("flags") or "").split(","):
                if f:
                    x["flags"][f] += 1
        elif t == "event":
            a = e.get("area") or e.get("action")
            if a:
                x["areas"][a] += 1
        elif t == "detection":
            x["detections"] += 1
    return days


def suggested_summary(day, lang="ja"):
    names = CAT_EN if lang == "en" else CAT_JA
    cats = [names.get(c, c) for c, _ in day["cats"].most_common(5)]
    s = ("、".join(cats) if lang != "en" else ", ".join(cats)) or ("その他" if lang != "en" else "other")
    if day["flags"].get("ghostwrite"):
        # only what was recorded: the request's category; how the AI answered is not recorded, so nothing
        # here claims that the AI declined
        s += ("(本文の作成・書き直しに当たりうる依頼が %d 回あった。AI の応答の内容は記録していないので、どう扱われたかは自分の記憶で書く)"
              % day["flags"]["ghostwrite"] if lang != "en" else
              " (%d request(s) that may have asked for manuscript text; the AI's answers are not recorded, so describe what "
              "happened from your own memory)" % day["flags"]["ghostwrite"])
    return s


def facts(proj, lang="ja"):
    days = by_day(proj)
    trusted, _pr, _no = trust.local_trusted(proj)
    idx, _bad = sign.valid_index(proj, trusted)
    conf = {}
    hunks = []
    for (kind, sid), recs in idx.items():
        if kind == "ailog":
            conf[sid] = recs[-1]
        elif kind == "hunk":
            hunks += [r for r in recs if r.get("decision") == "accepted"]
    models = set()
    for d in days.values():
        models |= d["models"]
    dates = sorted(set(days) | set(conf))
    L = []
    en = lang == "en"
    if en:
        L.append("# Facts for the AI-use disclosure (the AI may draft the statement from these; you check it in the final confirmation)\n")
        L.append("1. AI tool and version: Claude Code (Anthropic); model(s) recorded: %s" % (", ".join(sorted(models)) or "unknown (fill in)"))
        L.append("2. Dates used: %s" % (", ".join(dates) or "(none recorded)"))
        L.append("3. Prompt summaries (in your words, confirmed by you; unconfirmed days are marked):")
    else:
        L.append("# AI 利用の開示のための事実の一覧(開示文の下書きは AI が作ってよい。提出前の最終確認で自分が確かめる)\n")
        L.append("1. AI の種類・バージョン: Claude Code(Anthropic)、記録されたモデル: %s" % ("、".join(sorted(models)) or "不明(記入する)"))
        L.append("2. 利用年月日: %s" % ("、".join(dates) or "(記録なし)"))
        L.append("3. プロンプトの概要(自分の言葉で書いて確認したもの。未確認の日は印を付ける):")
    unconf = 0
    for d in dates:
        if d in conf:
            L.append("   - %s: %s" % (d, conf[d].get("note", "")))
        elif d in days:
            unconf += 1
            L.append("   - %s: %s %s" % (d, "[unconfirmed; suggestion from categories]" if en else "[未確認。種類からの案]", suggested_summary(days[d], lang)))
    L.append("4. Where and how it was used:" if en else "4. どの部分で、どのように利用したか:")
    areas = collections.Counter()
    for d in days.values():
        areas.update(d["areas"])
    for a, n in areas.most_common():
        L.append("   - %s: %d times" % (a, n) if en else "   - %s: %d 回" % (AREA_JA.get(a, a), n))
    if hunks:
        files = sorted({(r.get("detail") or {}).get("target") for r in hunks if (r.get("detail") or {}).get("target")})
        L.append("   - format-proposal hunks you accepted: %d (files: %s); the tool refuses any proposal that changes a character other than width, the punctuation system, spacing around Japanese, heading numbers or the form of a citation"
                 % (len(hunks), ", ".join(files)) if en else
                 "   - 形式の提案のうち自分が採用した箇所: %d(対象: %s)。全角半角・句読点の組・日本語の周りの空白・見出しの番号・同じ文献の引用の書式以外の文字を変える提案は道具が受け付けない" % (len(hunks), "、".join(files)))
    for d, r in sorted(conf.items()):
        wh = (r.get("detail") or {}).get("where_how")
        if wh:
            L.append("   - %s: %s" % (d, wh))
    s = provenance.summary(proj)
    if s["paragraphs"]:
        bo = s["by_origin"]
        pct = lambda n: (100.0 * n / s["paragraphs"]) if s["paragraphs"] else 0.0  # noqa: E731
        ai_n = bo["ai_wrote"][0] + bo["ai_edited"][0]
        if en:
            L.append("5. Provenance of the manuscript (.ryukoku/provenance.jsonl; the student's own edits are estimated from the differences between AI tool calls):")
            L.append("   - paragraphs: %d; written by the AI %d (%.0f%%, %d chars), revised by the AI %d (%.0f%%), AI paragraphs then revised by the student %d, "
                     "the student's (estimated) %d, unrecorded (before recording started) %d" % (
                         s["paragraphs"], bo["ai_wrote"][0], pct(bo["ai_wrote"][0]), bo["ai_wrote"][1], bo["ai_edited"][0], pct(bo["ai_edited"][0]),
                         bo["student_after_ai"][0], bo["student"][0], bo["unrecorded"][0]))
        else:
            L.append("5. 原稿の由来(.ryukoku/provenance.jsonl。学生の編集は AI のツール実行の間の差分からの推定):")
            L.append("   - 段落 %d のうち、AI が新しく書いた %d(%.0f%%、%d 字)・AI が直した %d(%.0f%%)・AI の段落を学生が直した %d・学生(推定)%d・記録の開始前 %d"
                     % (s["paragraphs"], bo["ai_wrote"][0], pct(bo["ai_wrote"][0]), bo["ai_wrote"][1], bo["ai_edited"][0], pct(bo["ai_edited"][0]),
                        bo["student_after_ai"][0], bo["student"][0], bo["unrecorded"][0]))
        for (f, sec), v in sorted(s["per_section"].items()):
            n = v["ai_wrote"] + v["ai_edited"]
            if n or v["student_after_ai"]:
                L.append(("   - %s / %s: AI-written %d, AI-revised %d, then revised by the student %d, the student's %d" if en else
                          "   - %s / %s: AI が書いた %d・AI が直した %d・その後学生が直した %d・学生 %d")
                         % (f, sec, v["ai_wrote"], v["ai_edited"], v["student_after_ai"], v["student"]))
        if s["purposes"]:
            L.append(("   - purposes of the AI's writing: %s" if en else "   - AI の執筆の用途: %s") % (", " if en else "、").join(
                "%s %d" % (k if en else PURPOSE_JA.get(k, k), v) for k, v in sorted(s["purposes"].items())))
        if s["claims"] or s["sources"]:
            L.append(("   - materials: claim cards %s; sources %s" if en else "   - 材料: 主張カード %s / 文献 %s")
                     % (", ".join(s["claims"]) or "-", ", ".join(s["sources"]) or "-"))
        if not ai_n:
            L.append("   - no paragraph currently in the manuscript was written or revised by the AI (as recorded)" if en else
                     "   - 今の原稿に、AI が書いた・直した段落は(記録の上では)ない")
    L.append("")
    if unconf:
        L.append("%d day(s) unconfirmed: write each day's summary in your own words in the evidence notebook (提出前 tab) or with ./rk disclose." % unconf
                 if en else "未確認の日が %d 日ある。証拠ノートの「提出前」か ./rk disclose で、その日の概要を自分の言葉で書いて確認すると 3 が埋まる。" % unconf)
    L.append("Follow the course's format and placement (disclosure_format in .ryukoku/config.yml). The items follow the examples in guideline III-4."
             if en else "開示の形式と置き場所は科目の指示(.ryukoku/config.yml の disclosure_format)に従う。項目はガイドラインⅢ-4 の記載項目の例に対応。")
    return "\n".join(L) + "\n", unconf
