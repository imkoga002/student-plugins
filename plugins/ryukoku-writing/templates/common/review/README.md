# review/(レビューのコメント、論証図、検証の結果)

- `annotations.json`: レビューのコメント(W3C Web Annotation の TextQuoteSelector と TextPositionSelector で位置を持つ。原稿が変わっても引用文で位置を探し直す)。
  自分や指導教員のコメントは証拠ノートの画面で書く。AI は `python3 tools/rk/rk.py annot reply|flag` で、基準と問いを置く。
- 解決は人間だけ: 証拠ノートの「レビュー」でコメントを表示して「解決」を記録する(合言葉は要らない。端末なら `./rk resolve`)。
- `argument-*.json` / `argument-*.md`: 自分の文から取り出した論証の構造と図(argument-map スキル)。
- `verification/<日付>-<対象>.md`: 主張カードと原稿の段落の厳密な検証(claim-verification スキル)。重大度(致命・重要・軽微)と
  根拠つきの指摘、反証、新規性の位置づけ、AI の文と主張カードの食い違い(すり替え)、修正案。修正案を採るかは自分で決める。
