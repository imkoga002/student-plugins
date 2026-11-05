#!/usr/bin/env bash
# UserPromptSubmit of ryukoku-writing. Active only for a project with .ryukoku/config.yml (the session folder, an
# ancestor, or a project one or two levels below it).
#  1. Personal/confidential data -> stop the prompt, name the kind and the line, mask the value, say how to resend
#     (NFKC first so full-width digits are caught). A bare 8-digit "ID: 12345678" only adds a caution.
#  2. Record a prompt *category* in the chained AI-use log (never the prompt text).
#  3. Ghostwriting / question-delegation / translation / "what do you think" requests -> do not stop; inject the
#     reason and the alternatives, and for judgement requests ask for the student's own view first. The final
#     safeguard is structural: the AI cannot write manuscript/ or research/questions.md at all.
#  4. Course AI policy reminder.
set -u; set -f
HERE="$(cd "$(dirname "$0")" && pwd)"; . "$HERE/lib.sh"
INPUT="$(cat 2>/dev/null || true)"
[ -n "$INPUT" ] || exit 0
CWD="$(printf '%s' "$INPUT" | json_string_field cwd)"
PROJ="$(find_session_project "$CWD" 2>/dev/null || true)"
is_active "$PROJ" || exit 0
P="$(printf '%s' "$INPUT" | json_string_field prompt)"
[ -n "$P" ] || exit 0
PLUGIN_ROOT="${CLAUDE_PLUGIN_ROOT:-$(cd "$HERE/../.." && pwd)}"
RK_HOOKCORE="$PLUGIN_ROOT/scripts/rk/hookcore.py"; export RK_HOOKCORE
FB_LANG="$(cfg_get feedback_lang)"; [ -n "$FB_LANG" ] || FB_LANG="$(cfg_get manuscript_lang)"
POLICY="$(cfg_get ai_policy)"; [ -n "$POLICY" ] || POLICY=unknown
TAG="[ryukoku-writing]"

# 1. personal data
HITS="$(printf '%s' "$P" | pii_scan)"
if [ -n "$HITS" ]; then
  if [ "${FB_LANG:-ja}" = en ]; then
    LIST="$(printf '%s\n' "$HITS" | LC_ALL=C awk -F '\t' 'BEGIN { m["メールアドレス"] = "e-mail address"; m["電話番号"] = "phone number"; m["学籍番号"] = "student ID"; m["マイナンバーらしき12桁"] = "12 digits like a My Number"; m["住所の手がかり"] = "address"; m["郵便番号"] = "postal code"; m["カード番号"] = "card number"; m["秘密鍵・トークン"] = "secret key or token" } { k = ($1 in m) ? m[$1] : $1; printf "- %s (line %s): %s\n", k, $2, $3 }' | head -n 12)"
  else
    LIST="$(printf '%s\n' "$HITS" | awk -F '\t' '{printf "- %s(%s 行目): %s\n", $1, $2, $3}' | head -n 12)"
  fi
  R="$(t "個人情報・機密情報らしきものが入力に含まれていたため、送信を止めた(龍谷大学ガイドラインⅡ-2(1): 個人情報・機密情報・公開されると困る情報は生成AIに入力しない)。検知した種類と場所(値は伏せて表示):
$LIST
送り直し方: 該当部分を [電話番号] [メール] [学籍番号] [住所] のような伏せ字に置き換えてから、もう一度送る。論文に関係のない個人の情報は、そもそも入力しない。
誤検知のとき(例: 統計表の 12 桁の番号): 数字の区切り方を変える、または『番号1』のように言い換えて送る。" \
"Your message was not sent because it seems to contain personal or confidential data (Ryukoku guideline II-2(1): do not enter such data into generative AI). Detected kinds and lines (values masked):
$LIST
To resend: replace those parts with placeholders such as [phone] [email] [student-id] [address]. Do not enter personal data unrelated to the paper.
If this is a false positive (e.g. a 12-digit table number), change the digit grouping or call it 'number 1'.")"
  printf '{"decision":"block","reason":"%s"}\n' "$(printf '%s' "$R" | json_escape)"
  exit 0
fi

ci() { printf '%s' "$P" | LC_ALL=C grep -Eiq -e "$1"; }

# 1b. the signing passphrase typed into the chat (it must go only to the terminal or the local notebook page):
#     a "passphrase is ..." form, or a short message that reproduces a registered signer's key
PWHIT=""
if have_python; then PWHIT="$(printf '%s' "$P" | pyrun -I -B "$RK_HOOKCORE" pwcheck "$PROJ" 2>/dev/null || true)"; fi
if [ "$PWHIT" = match ] || ci '(合言葉|あいことば|パスフレーズ|pass ?phrase)[^[:cntrl:]]{0,12}(は|:|：|=|[[:space:]]is[[:space:]])[[:space:]]*["'"'"'「『]?[!-~ ]{10,}'; then
  R="$(t "署名の合言葉らしきものが入力に含まれていたため、送信を止めた。合言葉はチャットに入れない(AI に知られると、あなたの確認を装えてしまう)。入れる場所は、自分の端末とローカルの証拠ノートの画面だけ。もし別の場所で送ってしまったなら、自分の端末で ./rk setup を実行し、新しい合言葉を登録して今までの鍵を失効させる。" \
"Your message was not sent because it seems to contain your signing passphrase. Never type it into the chat (whoever knows it can pose as your confirmation); it goes only into your terminal or the local evidence-notebook page. If you already sent it somewhere, run ./rk setup in your terminal to register a new one and revoke the old key.")"
  printf '{"decision":"block","reason":"%s"}\n' "$(printf '%s' "$R" | json_escape)"
  exit 0
fi

# 2. category gist (no prompt text is stored)
CATS=""
addc() { case ",$CATS," in *",$1,"*) ;; *) CATS="${CATS:+$CATS,}$1" ;; esac; }
ci '調べ|探し|検索|文献|先行研究|資料|search|find|literature|sources?' && addc research
ci '確認|検証|実在|doi|isbn|ncid|verify|check|retract' && addc verify
ci '(^|[^a-z])rq|問い|仮説|論証|主張|根拠|論拠|argument|research question|claim|toulmin|thesis' && addc question
ci '書式|形式|体裁|句読点|表記|docx|pdf|word|latex|format|citation style|mermaid|図|表|数式' && addc format
ci 'コメント|指摘|レビュー|講評|添削|review|comment|feedback' && addc review
ci 'データ|統計|csv|data|e-stat' && addc data
ci '英語|英文|語法|grammar|usage' && addc language
ci '開示|ai利用|disclos' && addc disclosure
ci '締切|進捗|予定|deadline|schedule' && addc schedule
[ -n "$CATS" ] || CATS=other

JA_OBJ='(本文|文章|段落|節|章|序論|序章|はじめに|まえがき|本論|考察|結論|おわりに|結び|要旨|抄録|レポート|論文|卒論|原稿|下書き|草稿|アブストラクト|続き|この文|この部分|ここ|箇条書き|メモ)'
JA_VERB='(書いて|書け|書きなおして|書き直して|かいて|作って|作成して|つくって|生成して|仕上げて|まとめて|直して|なおして|リライト|書き換えて|書きかえて|言い換えて|いいかえて|パラフレーズ|清書|代筆|肉付け|膨らませて|ふくらませて|埋めて|足して|続けて|完成させて|整えて|文章にして|文にして|起こして)'
EN_VERB='(write|draft|rewrite|re-write|paraphrase|rephrase|reword|polish|compose|generate|redo|finish|complete|continue|expand|flesh out|improve|fix|turn)'
EN_OBJ='(essay|paper|report|thesis|dissertation|introduction|conclusion|abstract|paragraph|section|chapter|sentences?|text|draft|discussion|literature review|summary|argument|reasoning|points|ideas|bullet points|notes|outline)'
FLAG=""
if ci "$JA_OBJ.{0,48}$JA_VERB|(代わりに|かわりに|代行して|代行で).{0,40}(書|考|決|作|まとめ)|続きを(書|お願い)|書いて(ください|ほしい|もらえ|くれ)|全部やって|丸投げ|任せたい|(論拠|根拠|理由|反論|説明|具体例|例|裏づけ|裏付け).{0,4}(を|も)?(補って|補足して|加えて|足して|考えて|作って|書いて|出して|用意して|埋めて)|(例文|文例|見本の文|書き出しの例|例を).{0,10}(見せて|ください|出して|書いて|作って|教えて)|序論.{0,12}例を|$EN_VERB[^.?!]{0,40}$EN_OBJ|(make|get)[^.?!]{0,40}(sound|read|look)[^.?!]{0,24}(more|better|academic|formal|natural|fluent|professional)|sound (more )?(academic|formal|scholarly)|write (it|this|that|one) for me|do (it|this) for me|do my (homework|assignment)|ghost ?writ|(example|sample) (sentence|paragraph|opening)|(もっと|より|もう少し)?(学術的|論文らしく|論文っぽく|アカデミック|硬い文体|格調高く)(に|な文に)?(して|しても|書いて|書き|直し|整え|変え)|文案|書き方の(案|候補)を|better version|(rewrite|reword|rephrase|redo|rework)[^.?!]{0,30}(this|it|that)|fill in the (gaps|blanks|holes)|expand (this|it|that|my)[^.?!]{0,30}(into|to) [0-9]+|make (it|this) flow|(so|that) it flows"; then FLAG=ghostwrite; fi
if ci '(rq|ｒｑ|リサーチ・?クエスチョン|研究課題|仮説|結論|主張|問い|論点).{0,40}(決めて|考えて|提案して|立てて|作って|出して|選んで|ちょうだい)|テーマ.{0,30}(決めて|考えて|選んで|提案して|いい|良い|よい|おすすめ|オススメ)|(何|なに)を(研究|書け|書こう|テーマに)|(decide|choose|pick|come up with|suggest|propose|generate|give me|formulate|think of|make up)[^.?!]{0,40}(research question|(^|[^a-z])rq([^a-z]|$)|hypothes|thesis statement|conclusion|topic|argument|claim)|what should (my|the|i|this) [^?]{0,40}(argue|claim|conclude|research|write about|be about|focus on|say)|what (topic|thesis|research question) should|(結論|主張|考察|まとめ)(は|を)(どう|どのように)(すれば|したら|書けば|まとめれば)|(何|なに)について書(けば|いたら|こう)|テーマ.{0,6}(アイデア|アイディア|案|候補)|(言える|いえる)ことを(教えて|挙げて|出して)|この結果から.{0,12}(言える|分かる|わかる)こと'; then FLAG="${FLAG:+$FLAG,}delegate_question"; fi
if ci '(英訳|和訳|翻訳)(して|する|を|お願い)|英語に(して|直して|訳して)|日本語に(して|直して|訳して)|translate[^.?!]{0,40}(into|to) (english|japanese)'; then FLAG="${FLAG:+$FLAG,}translation"; fi
if ci 'どう思う|どう考える|どちらがいい|どっちがいい|どれがいい|べきか|すべき\?|いいと思|正しいか|what do you think|which (one )?is better|should i |is it better|your opinion'; then FLAG="${FLAG:+$FLAG,}judgement"; fi

SID="$(printf '%s' "$INPUT" | json_string_field session_id | LC_ALL=C tr -cd 'A-Za-z0-9_-' | head -c 64)"
NCH="$(printf '%s' "$P" | wc -m | tr -d ' ')"
if have_python; then
  printf '{"type":"prompt","session":"%s","categories":"%s","chars":%s,"flags":"%s"}' "$SID" "$CATS" "${NCH:-0}" "$FLAG" \
    | pyrun -I -B "$RK_HOOKCORE" log "$PROJ" "$(printf '%s' "$INPUT" | json_string_field transcript_path)" >/dev/null 2>&1
fi

MSG=""
case ",$FLAG," in *",ghostwrite,"*)
  MSG="$(t "$TAG この依頼は本文の代筆・書き直し・文例の作成に当たる可能性がある。本文の文章は、一部でも、例文の形でも生成しない(龍谷大学ガイドラインⅢ-4: 生成AIで作ったものを一部でも自分の成果物にすることを強く戒めている。Ⅲ-1: 学びの中心は自分で考えて書くこと。科目の設定でも外せない)。断る理由を一文で示し、説教しない。代わりにできること: (a) 問いかけで考えを言葉にする手伝い(rq-dialogue・argument-map)、(b) その箇所の論証の穴を、基準を名指しした問いで示す(review-comments。修正例は出さない)、(c) 資料探しと実在確認(research-plan・verify-sources)、(d) 表記・書式の統一だけを提案ファイルにする(format-proposals。学生が画面で採否を決める)。表記の見本が要るときは、学生の内容を含まない記号の見本(「X は Y である。」など)だけにする。" \
"$TAG This request may be ghostwriting, rewriting or asking for sample prose. Do not produce manuscript prose, not even part of it or as an example (Ryukoku guideline III-4 strongly warns against presenting AI-made work, even in part, as one's own; III-1: thinking and writing are the core of learning; no course setting lifts this). Give the reason in one sentence, without lecturing. Offer instead: (a) questions that help the student put their idea into words (rq-dialogue, argument-map); (b) criteria-named questions about gaps in that passage (review-comments; no rewritten text); (c) finding and verifying sources (research-plan, verify-sources); (d) notation/format-only proposals the student accepts or rejects on the screen (format-proposals). If a notation example is needed, use a content-free placeholder ('X is Y.').")" ;;
esac
case ",$FLAG," in *",delegate_question,"*)
  MSG="$MSG
$(t "$TAG テーマ・RQ・仮説・主張・結論を AI が決めたり提案したりしない(ガイドラインⅢ-1)。『〜は〜か、という問いはどうか』の形の提案もしない。まず学生の今の考えを聞き、学生の言葉を引用して問いを 1〜2 個だけ返し(番号つきで 3 個以上並べない。学生の言葉がまだ無ければ、今の関心を尋ねる一問だけでよい)、学生が research/questions.md に自分で書くのを待つ(rq-dialogue)。資料が要るなら、学生の問いに由来する調査計画を立てる(research-plan)。" \
"$TAG Do not decide or propose the topic, research question, hypothesis, claim or conclusion (guideline III-1), not even as 'how about the question ...?'. First ask for the student's current view, quote their words, ask one or two questions only (never a numbered list of three or more; with nothing from the student yet, one question about their interest is enough) and let them write it in research/questions.md (rq-dialogue). If sources are needed, plan research that derives from the student's question (research-plan).")" ;;
esac
case ",$FLAG," in *",judgement,"*)
  MSG="$MSG
$(t "$TAG 判断を求める依頼。答える前に、学生自身の考えと、その理由を一言で聞く。答えるときは観点(基準)を並べ、どれを重く見るかは学生に委ねる。論文の内容(主張・結論)については判断を代わりに出さない。" \
"$TAG A request for a judgement. Before answering, ask for the student's own view and reason. When you answer, lay out criteria and leave the weighting to the student. Do not hand down judgements on the paper's content (claims, conclusions).")" ;;
esac
case ",$FLAG," in *",translation,"*)
  MSG="$MSG
$(t "$TAG 学生の和文を提出用の英文に(またはその逆に)翻訳することは、科目が許可し開示する場合を除いて行わない(ガイドラインⅢ-3・Ⅲ-4、作業憲法 第2条)。語や表現の用法の説明、学生が書いた英文の文法上の問題の指摘(箇所と理由)はできる。科目の条件は .ryukoku/config.yml の ai_policy・ai_allowed_uses。" \
"$TAG Do not translate the student's text into submission text unless the course allows it and it is disclosed (guideline III-3, III-4; CONSTITUTION.md article 2). You may explain usage and point out grammar problems in English the student wrote (location and reason). See ai_policy / ai_allowed_uses in .ryukoku/config.yml.")" ;;
esac
if printf '%s' "$P" | LC_ALL=C grep -Eiq '(^|[^a-z0-9])id[[:space:]]*[:：][[:space:]]*[a-z]{0,2}[0-9]{6,10}([^0-9]|$)'; then
  MSG="$MSG
$(t "$TAG 注意: 入力に番号らしきもの(ID: 数字)がある。学籍番号などの個人の番号なら、この先は伏せ字にするよう学生に一言伝える(ガイドラインⅡ-2(1))。" "$TAG Note: the message contains an ID-like number. If it is a personal number such as a student ID, tell the student briefly to mask it next time (guideline II-2(1)).")"
fi
case "$POLICY" in
  prohibited) MSG="$MSG
$(t "$TAG この科目は AI 利用禁止と記録されている(ai_policy: prohibited)。原稿・調査・検証の作業はしない。教員の指示の確認を促す(ガイドラインⅢ-3)。" "$TAG This course is recorded as AI-prohibited (ai_policy: prohibited). Do not work on the manuscript, research or verification; suggest confirming with the instructor (guideline III-3).")" ;;
  limited) MSG="$MSG
$(t "$TAG この科目の AI 利用は限定(ai_allowed_uses: $(cfg_get ai_allowed_uses))。範囲外の用途はフックが確認を求める。" "$TAG AI use in this course is limited (ai_allowed_uses: $(cfg_get ai_allowed_uses)). The hooks ask before other uses.")" ;;
esac
MSG="$(printf '%s' "$MSG" | sed '/^$/d')"
[ -n "$MSG" ] && context_out UserPromptSubmit "$MSG"
exit 0
