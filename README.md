# student-plugins

学生のレポート・論文執筆を支える Claude Code の Plugin 集です(非公式)。問いと主張は学生のもので、AI はそれを厳密に検証し、科目が許すときは文章化を手伝い、AI が書いた部分を隠さず記録することを前提にしています。

## 導入

```
/plugin marketplace add imkoga002/student-plugins
```

続けて、使う Plugin を入れます。

## Plugin

| Plugin | 内容 | 導入 |
|---|---|---|
| [ryukoku-writing](plugins/ryukoku-writing/README.md) | 龍谷大学の学生向けのレポート・卒論の執筆支援(非公式。大学の公式の道具ではない)。学生の考えを主張カードに整理し、主張と原稿を厳密に検証する(論理・根拠の対応・反証・新規性・主張のすり替え)。科目の AI 利用条件が許すときは、確認済みの材料だけで原稿を書き、書いた段落の由来を自動で記録する。文献は実在を確かめたものだけ。合言葉の署名は VERIFIED と提出前の最終確認だけ。日英対応 | `/plugin install ryukoku-writing@student-plugins` |

## English

Unofficial Claude Code plugins that support students writing reports and theses. They assume that the questions and claims are the students' own; the AI verifies them rigorously, helps with the writing when the course allows it, and records what it wrote.

- [ryukoku-writing](plugins/ryukoku-writing/README.en.md): for Ryukoku University students (not an official university tool). Install with `/plugin marketplace add imkoga002/student-plugins`, then `/plugin install ryukoku-writing@student-plugins`.

## ライセンス / License

MIT([LICENSE](LICENSE))
