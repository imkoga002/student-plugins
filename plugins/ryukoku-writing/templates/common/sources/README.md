# sources/(文献と主張の台帳)

- `register.csv`: 文献ごとの行。識別子(DOI・ISBN・NCID・CRID・NDL ID・URL)と、書誌(自分が控えたもの)。
  - 機械の列(machine_*): `python3 tools/rk/rk.py refcheck check` が書く。IDENTITY_CONFIRMED / NOT_FOUND /
    METADATA_MISMATCH / RETRACTED / CANDIDATE。
  - 人間の列(human_*): 自分が記録したときだけ書かれる(証拠ノートの「文献と主張」か `./rk verify`)。VERIFIED は合言葉の署名つき。VERIFIED は、自分が現物か公式の画面で書誌を確かめたもの。
- `claims.csv`: 主張ごとの行。主張 / 出典 / 該当箇所(頁・節)/ 状態。
  人間の状態は VERIFIED(原典がその主張を支えると自分で読んで確かめた)/ CONTRADICTED / NOT_FOUND / CANDIDATE。
  原典と主張が矛盾したら、主張を原典に合わせて直す(逆は禁止)。
- `references.json`: CSL-JSON(Zotero + Better BibTeX などから書き出した控え)。書き出しには使わない。書き出しの文献一覧は台帳(`register.csv`)と、機械の照合が記録した `identity.json` から作る。台帳との違いは `./rk check` が知らせる。
- `identity.json`: `rk.py refcheck check` が、識別子で確かめた文献について登録機関の書誌を記録する(AI も学生も手で書かない)。
- 原稿に引用する文献は、ここで IDENTITY_CONFIRMED 以上であること(台帳にない・それ未満の文献を引くと、提出の段階の検査が通らない)。
- 手で(またはスクリプトで)書いた VERIFIED は、署名と結びつかないので `./rk check` と CI でエラーになる。AI はこの二つの台帳を直接書けない(行の追加は `rk.py ledger`、機械の列は `rk.py refcheck`)。
