#!/usr/bin/env python3
"""CriticMarkup の受理・却下・除去フィルタ(標準ライブラリのみ)。

  {++追加++} {--削除--} {~~旧~>新~~} {==強調==} {>>コメント<<}
モード:
  accept : 提案をすべて受理(追加を採用、削除を適用、置換は新を採用)。コメントと強調は除去。
  reject : 提案をすべて却下(元の文)。コメントと強調は除去。
  strip  : コメントと強調の記号だけ除去(強調の対象文字は残す)。提案はそのまま残す。
  check  : 記法が残っていれば終了コード 1(提出前・エクスポート前の確認用)。
Pandoc も Quarto も CriticMarkup に対応していない(pandoc の MANUAL https://pandoc.org/MANUAL.html と 3.13 までの
リリースノート https://pandoc.org/releases.html に "critic" の語が無く、Quarto の文書にも見当たらない。2026-11-04 確認)
ため、同梱の小さなフィルタで処理する。提案(proposals)のために old_new() も持つ。
"""
import re
import sys

PATTERNS = {
    "add": re.compile(r"\{\+\+(.*?)\+\+\}", re.S),
    "del": re.compile(r"\{--(.*?)--\}", re.S),
    "sub": re.compile(r"\{~~(.*?)~>(.*?)~~\}", re.S),
    "hl": re.compile(r"\{==(.*?)==\}", re.S),
    "com": re.compile(r"\{>>(.*?)<<\}", re.S),
}
ANY = re.compile(r"\{(\+\+|--|~~|==|>>)")


def convert(text, mode):
    if mode not in ("accept", "reject", "strip"):
        raise ValueError(mode)
    t = PATTERNS["com"].sub("", text)
    t = PATTERNS["hl"].sub(lambda m: m.group(1), t)
    if mode == "strip":
        return t
    if mode == "accept":
        t = PATTERNS["add"].sub(lambda m: m.group(1), t)
        t = PATTERNS["del"].sub("", t)
        t = PATTERNS["sub"].sub(lambda m: m.group(2), t)
    else:
        t = PATTERNS["add"].sub("", t)
        t = PATTERNS["del"].sub(lambda m: m.group(1), t)
        t = PATTERNS["sub"].sub(lambda m: m.group(1), t)
    return t


def old_new(text):
    """(original, proposed) text from a CriticMarkup-marked copy."""
    return convert(text, "reject"), convert(text, "accept")


def has_markup(text):
    return bool(ANY.search(text))


def main(argv):
    if len(argv) < 2 or argv[0] not in ("accept", "reject", "strip", "check"):
        sys.stderr.write("usage: criticmarkup.py accept|reject|strip|check FILE [-o OUT]\n")
        return 2
    mode, path = argv[0], argv[1]
    with open(path, encoding="utf-8") as f:
        text = f.read()
    if mode == "check":
        if has_markup(text):
            sys.stderr.write("CriticMarkup が残っています: " + path + "\n")
            return 1
        return 0
    out = convert(text, mode)
    if "-o" in argv:
        with open(argv[argv.index("-o") + 1], "w", encoding="utf-8") as f:
            f.write(out)
    else:
        sys.stdout.write(out)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
