#!/usr/bin/env bash
# init-project.sh --dir DIR [--lang ja|en] [--feedback ja|en]
# Creates a ryukoku-writing project in DIR (an absolute path is safest; a relative one is resolved against the
# caller's working directory, never against the plugin). Refuses, before creating anything: the plugin's own
# folder, the home folder itself, and a folder that is already a project. Never overwrites an existing file. Git, the passphrase and the course policy are set afterwards by the student with ./rk setup.
# Portable: bash 3.2 / BSD tools / Git Bash. pandoc is optional (reference.docx is generated when present).
set -u
PLUGIN="$(cd "$(dirname "$0")/.." && pwd -P)"
DIR=""; LANGC=ja; FB=""
while [ $# -gt 0 ]; do
  case "$1" in
    --dir) DIR="${2:-}"; shift 2 ;;
    --lang) LANGC="${2:-ja}"; shift 2 ;;
    --feedback) FB="${2:-}"; shift 2 ;;
    -h|--help) sed -n '2,6p' "$0"; exit 0 ;;
    *) echo "unknown option: $1" >&2; exit 2 ;;
  esac
done
[ -n "$DIR" ] || { echo "--dir が要る(論文のフォルダ。例: --dir \"\$PWD\")/ --dir is required" >&2; exit 2; }
case "$LANGC" in ja|en) ;; *) echo "--lang は ja か en / --lang must be ja or en" >&2; exit 2 ;; esac
[ -n "$FB" ] || FB="$LANGC"
case "$FB" in ja|en) ;; *) echo "--feedback は ja か en" >&2; exit 2 ;; esac
case "$DIR" in /*|[A-Za-z]:*) ;; *) DIR="$(pwd -P)/$DIR" ;; esac
EX="$DIR"; REST=""
while [ ! -d "$EX" ]; do REST="/$(basename "$EX")$REST"; EX="$(dirname "$EX")"; done
CHECK="$(cd "$EX" && pwd -P)$REST"
case "$CHECK/" in "$PLUGIN"/*) echo "Plugin 自身のフォルダの中には作らない: $CHECK / refusing to initialise inside the plugin" >&2; exit 2 ;; esac
HOMEP="$(cd "$HOME" 2>/dev/null && pwd -P)"
[ -n "$HOMEP" ] && [ "${CHECK%/}" = "$HOMEP" ] && { echo "ホームフォルダそのものには作らない。論文用のフォルダを作って指定する / refusing to initialise the home folder itself" >&2; exit 2; }
[ "${CHECK%/}" = "" ] && { echo "/ には作らない" >&2; exit 2; }
if [ -f "$CHECK/.ryukoku/config.yml" ]; then
  echo "既に初期化されている($CHECK/.ryukoku/config.yml)。続きは自分の端末で ./rk setup / already initialised" >&2; exit 3
fi
[ -f "$PLUGIN/scripts/rk/MANIFEST.sha256" ] || { echo "Plugin の scripts/rk/MANIFEST.sha256 がない(Plugin を入れ直す)" >&2; exit 4; }
mkdir -p "$DIR" || exit 1
DIR="$(cd "$DIR" && pwd -P)"

copy_tree() { # SRC DST: copy files (dotfiles included), never overwrite
  local src="$1" dst="$2" f rel
  [ -d "$src" ] || return 0
  (cd "$src" && find . -type f ! -name '*.pyc' ! -path '*/__pycache__/*') | while IFS= read -r f; do
    rel="${f#./}"
    mkdir -p "$dst/$(dirname "$rel")"
    [ -e "$dst/$rel" ] && continue
    cp -p "$src/$rel" "$dst/$rel"
  done
}
T="$PLUGIN/templates"
copy_tree "$T/common" "$DIR"
copy_tree "$T/github" "$DIR"
copy_tree "$T/$LANGC" "$DIR"
OTHER=en; [ "$LANGC" = en ] && OTHER=ja
copy_tree "$T/$OTHER/pandoc" "$DIR/pandoc"   # both languages' export settings: switching = one config line
mkdir -p "$DIR/.ryukoku" "$DIR/proposals" "$DIR/review" "$DIR/research/reports"
PID="$(od -An -N8 -tx1 /dev/urandom 2>/dev/null | tr -d ' \n')"
[ -n "$PID" ] || PID="$(date +%s)$$"
sed -e "s/__LANG__/$LANGC/" -e "s/__FBLANG__/$FB/" -e "s/__PID__/p$PID/" "$T/common/.ryukoku/config.yml.tmpl" > "$DIR/.ryukoku/config.yml"
rm -f "$DIR/.ryukoku/config.yml.tmpl"
[ -f "$DIR/proposals/style-rules.yml" ] || mv "$DIR/style-rules.yml" "$DIR/proposals/style-rules.yml" 2>/dev/null
rm -f "$DIR/style-rules.yml"
# the project copy of the tools (used by the AI's machine commands and, from the base branch, by CI)
copy_tree "$PLUGIN/scripts/rk" "$DIR/tools/rk"
for L in rk rk.cmd rk.ps1; do
  [ -e "$DIR/$L" ] || cp -p "$PLUGIN/scripts/rk/launchers/$L" "$DIR/$L"
done
chmod +x "$DIR/rk" "$DIR/tools/rk/rk.py" "$DIR/.githooks/pre-push" "$DIR/.githooks/pre-commit" 2>/dev/null
# where the installed plugin is, for ./rk (kept outside the project, so a tool call in the project cannot
# redirect it), with a record of its location and MANIFEST that the human commands compare with before asking
# for the passphrase. On Windows (Git Bash) the path is written in the Windows form, which rk.cmd / rk.ps1 /
# Windows Python read (cygpath or pwd -W of Git Bash; not tried on a Windows machine).
SH="${RK_STATE_HOME:-$HOME/.ryukoku-writing}"
PLUGIN_W="$PLUGIN"
case "$(uname -s 2>/dev/null)" in
  MINGW*|MSYS*|CYGWIN*)
    if command -v cygpath >/dev/null 2>&1; then PLUGIN_W="$(cygpath -w "$PLUGIN")"
    else PLUGIN_W="$(cd "$PLUGIN" && pwd -W 2>/dev/null || printf '%s' "$PLUGIN")"; fi ;;
esac
PYX=""
for c in python3 python; do
  if command -v "$c" >/dev/null 2>&1 && "$c" -c 'import sys; sys.exit(sys.version_info[0] != 3)' >/dev/null 2>&1; then PYX="$c"; break; fi
done
mkdir -p "$SH"
if [ -n "$PYX" ]; then
  "$PYX" -I -B -c 'import sys; sys.path.insert(0, sys.argv[1]); from rklib.common import record_plugin_root, register_project; record_plugin_root(sys.argv[2], "init-project"); register_project(sys.argv[3])' \
    "$PLUGIN/scripts/rk" "$PLUGIN_W" "$DIR" 2>/dev/null || printf '%s\n' "$PLUGIN_W" > "$SH/plugin-root"
elif command -v py >/dev/null 2>&1; then
  py -3 -I -B -c 'import sys; sys.path.insert(0, sys.argv[1]); from rklib.common import record_plugin_root, register_project; record_plugin_root(sys.argv[2], "init-project"); register_project(sys.argv[3])' \
    "$PLUGIN_W/scripts/rk" "$PLUGIN_W" "$DIR" 2>/dev/null || printf '%s\n' "$PLUGIN_W" > "$SH/plugin-root"
else
  printf '%s\n' "$PLUGIN_W" > "$SH/plugin-root"
  echo "python3 が見つからない。./rk には Python 3 が要る(https://www.python.org/)/ Python 3 is required for ./rk" >&2
fi
# reference.docx (pandoc's own default; then edit only its styles in Word: pandoc manual, --reference-doc,
# https://pandoc.org/MANUAL.html#option--reference-doc)
if [ ! -f "$DIR/pandoc/reference.docx" ]; then
  if command -v pandoc >/dev/null 2>&1; then
    pandoc -o "$DIR/pandoc/reference.docx" --print-default-data-file reference.docx && echo "pandoc/reference.docx を作った / created"
  else
    echo "pandoc がないので pandoc/reference.docx は作らなかった。pandoc を入れてから: pandoc -o pandoc/reference.docx --print-default-data-file reference.docx"
  fi
fi
if [ "$FB" = en ]; then
cat <<EOF
Initialised: $DIR (manuscript: $LANGC, feedback: $FB)
Next, in your own terminal (once):
  cd "$DIR"
  ./rk setup        (Windows cmd: rk setup / PowerShell: .\\rk.cmd setup; Windows is not tested yet)
It registers your passphrase, the course AI policy (guideline III-3), the training opt-out check and Git.
Never type the passphrase into the chat. Then reopen Claude Code in this folder.
EOF
else
cat <<EOF
初期化した: $DIR(原稿: $LANGC、講評: $FB)
次に、自分の端末(ターミナル)で一度だけ:
  cd "$DIR"
  ./rk setup        (Windows の cmd は  rk setup、PowerShell は  .\\rk.cmd setup。Windows は未確認)
合言葉の登録、科目の AI 利用条件(ガイドラインⅢ-3)、学習へのオプトアウトの確認、Git の選択を行う。
合言葉はチャットに決して入れない。終わったら、Claude Code をこのフォルダで開き直す。
EOF
fi
