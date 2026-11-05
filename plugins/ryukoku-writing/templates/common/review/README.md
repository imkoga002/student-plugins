# review/(レビューのコメントと論証図)

- `annotations.json`: レビューのコメント(W3C Web Annotation の TextQuoteSelector と TextPositionSelector で位置を持つ。原稿が変わっても引用文で位置を探し直す)。
  自分や指導教員のコメントは証拠ノートの画面で書く。AI は `python3 tools/rk/rk.py annot reply|flag` で、基準と問いだけを置く(書き換えの文は書けない)。
- 解決は人間だけ: 証拠ノートの「レビュー」でコメントを表示して「解決」を選び、合言葉で署名する(端末なら `./rk resolve`)。
- `argument-*.json` / `argument-*.md`: 自分の文から取り出した論証の構造と図(argument-map スキル)。欠けている要素は問いだけが付く。
