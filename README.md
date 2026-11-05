# student-plugins

学生のレポート・論文執筆を支える Claude Code の Plugin 集です(非公式)。問いを立て、主張を組み、本文を書くのは学生自身であることを前提にしています。

## 導入

```
/plugin marketplace add imkoga002/student-plugins
```

続けて、使う Plugin を入れます。

## Plugin

| Plugin | 内容 | 導入 |
|---|---|---|
| [ryukoku-writing](plugins/ryukoku-writing/README.md) | 龍谷大学の学生向けのレポート・卒論の執筆支援(非公式。大学の公式の道具ではない)。AI は問いかけ・資料の調査と実在確認・表記の統一の提案・レビューの問いを担い、原稿には書けない。人間の判断は学生の合言葉による署名でだけ記録される。日英対応 | `/plugin install ryukoku-writing@student-plugins` |

## English

Unofficial Claude Code plugins that support students writing reports and theses. They assume that students ask the questions, build the arguments and write the text themselves.

- [ryukoku-writing](plugins/ryukoku-writing/README.en.md): for Ryukoku University students (not an official university tool). Install with `/plugin marketplace add imkoga002/student-plugins`, then `/plugin install ryukoku-writing@student-plugins`.

## ライセンス / License

MIT([LICENSE](LICENSE))
