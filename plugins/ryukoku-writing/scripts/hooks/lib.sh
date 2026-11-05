#!/usr/bin/env bash
# ryukoku-writing: shared helpers for hooks.
# Portable: macOS bash 3.2 (BSD tools), Linux, Git Bash. No jq. Python 3 is optional (fail open).
# The project is found from the TARGET path as well as from the session folder (so a session opened in a parent
# or child folder is still guarded); text is NFKC-normalised before the personal-data scan (full-width digits);
# spaced phone numbers are matched; the per-user state folder is a protected path.

# Byte semantics everywhere: in a UTF-8 locale bash's `read` fails on a line that ends inside a multibyte
# character (seen with bash 5.2 when grep -o cuts a Japanese character), and BSD/GNU tools differ.
export LC_ALL=C

# json_string_field KEY (stdin JSON) -> decoded first string value of KEY
json_string_field() {
  LC_ALL=C awk -v key="$1" '
    BEGIN { RS = "\001"; ORS = "" }
    {
      s = $0
      pat = "\"" key "\"[ \t\r\n]*:[ \t\r\n]*\""
      if (match(s, pat) == 0) exit
      i = RSTART + RLENGTH; n = length(s); out = ""
      while (i <= n) {
        c = substr(s, i, 1)
        if (c == "\\") {
          d = substr(s, i + 1, 1)
          if (d == "n") out = out "\n"
          else if (d == "t") out = out "\t"
          else if (d == "r") out = out "\r"
          else if (d == "\"" || d == "\\" || d == "/") out = out d
          else out = out "\\" d
          i += 2; continue
        }
        if (c == "\"") break
        out = out c; i++
      }
      print out
    }'
}

# json_bool_true KEY (stdin JSON) -> exit 0 when "KEY": true appears
json_bool_true() { LC_ALL=C grep -Eq "\"$1\"[[:space:]]*:[[:space:]]*true"; }

# json_escape: stdin text -> JSON string body (no surrounding quotes)
json_escape() {
  LC_ALL=C tr -d '\000-\010\013\014\016-\037' | LC_ALL=C awk 'BEGIN{RS="\001";ORS=""}{gsub(/\\/,"\\\\");gsub(/"/,"\\\"");gsub(/\t/,"\\t");gsub(/\r/,"");gsub(/\n/,"\\n");print}'
}

# cfg_get KEY -> top-level "key: value" scalar from .ryukoku/config.yml (quotes/comments removed). The FIRST line
# that sets KEY counts (Python's load_config reads it the same way); cfg_count KEY says how many lines set it.
cfg_get() {
  local f="$PROJ/.ryukoku/config.yml"
  [ -f "$f" ] || return 0
  LC_ALL=C sed -n "s/^$1[[:space:]]*:[[:space:]]*//p" "$f" | head -n 1 | sed -e 's/^#.*$//' -e 's/^"\([^"]*\)".*$/\1/' -e "s/^'\([^']*\)'.*\$/\1/" -e 's/[[:space:]]#.*$//' -e 's/[[:space:]]*$//'
}
cfg_count() { LC_ALL=C grep -c "^$1[[:space:]]*:" "$PROJ/.ryukoku/config.yml" 2>/dev/null || echo 0; }

# project_dir CWD_FROM_JSON -> CLAUDE_PROJECT_DIR, else cwd from the hook JSON, else $PWD
project_dir() {
  local d="${CLAUDE_PROJECT_DIR:-}"
  [ -n "$d" ] || d="$1"
  [ -n "$d" ] || d="$PWD"
  printf '%s' "$d"
}

# registered DIR -> 0 when DIR is a project this user has used (state_home()/projects.tsv, written by the hooks).
# A registered folder stays guarded even if its marker is moved away.
RK_REG="${RK_STATE_HOME:-$HOME/.ryukoku-writing}/projects.tsv"
registered() {
  [ -n "$1" ] && [ -f "$RK_REG" ] && [ -d "$1" ] || return 1
  LC_ALL=C awk -F '\t' -v d="$1" '$1 == d { f = 1 } END { exit !f }' "$RK_REG"
}

# is_active PROJ -> 0 only when PROJ carries the project marker (or is registered). Otherwise every hook does
# nothing (no output, no files).
is_active() { [ -n "$1" ] && { [ -f "$1/.ryukoku/config.yml" ] || registered "$1"; }; }

# phys_dir DIR -> physical path of DIR's deepest existing ancestor plus the rest (symlinks resolved, so a link into the project matches the project)
phys_dir() {
  local d="$1" rest="" b
  case "$d" in /*) ;; *) return 1 ;; esac
  while [ -n "$d" ] && [ "$d" != "/" ] && [ ! -d "$d" ]; do
    b="${d##*/}"; rest="/$b$rest"; d="${d%/*}"; [ -n "$d" ] || d="/"
  done
  [ -d "$d" ] || return 1
  printf '%s%s' "$(cd "$d" 2>/dev/null && pwd -P)" "$rest"
}

# marker_up DIR -> nearest ancestor (DIR included, at most 12 levels) that carries .ryukoku/config.yml
marker_up() {
  local d="$1" n=0
  while [ -n "$d" ] && [ $n -lt 12 ]; do
    { [ -f "$d/.ryukoku/config.yml" ] || registered "$d"; } && { printf '%s' "$d"; return 0; }
    [ "$d" = "/" ] && return 1
    d="${d%/*}"; [ -n "$d" ] || d="/"
    n=$((n + 1))
  done
  return 1
}

# phys_file PATH -> PATH with its directory resolved and, when the last component is a symbolic link, the link
# followed (at most 8 times; POSIX readlink without -f, so it works with BSD tools too)
phys_file() {
  local p="$1" n=0 t d
  while [ -L "$p" ] && [ $n -lt 8 ]; do
    t="$(readlink "$p" 2>/dev/null)" || break
    case "$t" in /*) p="$t" ;; *) p="${p%/*}/$t" ;; esac
    n=$((n + 1))
  done
  d="$(phys_dir "${p%/*}" 2>/dev/null)" || { printf '%s' "$p"; return 0; }
  printf '%s/%s' "$d" "${p##*/}"
}

# abs_of PATH BASE -> PATH made absolute against BASE ("\" -> "/"; Windows drive paths returned as they are)
abs_of() {
  local p
  p="$(printf '%s' "$1" | tr '\\' '/')"
  case "$p" in /*|[A-Za-z]:/*) printf '%s' "$p" ;; "~"/*) printf '%s%s' "$HOME" "${p#\~}" ;; *) printf '%s/%s' "${2%/}" "$p" ;; esac
}

# project_for_path PATH BASE -> the project that contains PATH (walking up from it, symlinks resolved)
project_for_path() {
  local a d
  a="$(abs_of "$1" "$2")"
  d="$(phys_dir "${a%/*}" 2>/dev/null)" || d="${a%/*}"
  marker_up "$d" || { [ "${a%/*}" != "$d" ] && marker_up "${a%/*}"; }
}

# child_project DIR -> a project folder one or two levels below DIR (a session opened in a parent folder)
child_project() {
  local c found="" noglob=0
  case "$-" in *f*) noglob=1; set +f ;; esac
  for c in "$1"/*/.ryukoku/config.yml "$1"/*/*/.ryukoku/config.yml; do
    if [ -f "$c" ]; then found="${c%/.ryukoku/config.yml}"; break; fi
  done
  [ "$noglob" = 1 ] && set -f
  [ -n "$found" ] && { printf '%s' "$found"; return 0; }
  return 1
}

# find_session_project CWD -> project of the session folder (walking up), else a child project, else nothing
find_session_project() {
  local base
  base="$(project_dir "$1")"
  marker_up "$base" && return 0
  [ -n "$1" ] && [ "$1" != "$base" ] && marker_up "$1" && return 0
  child_project "$base"
}

# norm_path TEXT -> lower case, "\" -> "/", "C:" drive prefix removed, "//" collapsed (so Windows-style paths match too)
norm_path() {
  printf '%s' "$1" | LC_ALL=C tr 'A-Z\\' 'a-z/' | LC_ALL=C sed -e 's#^[a-z]:/#/#' -e 's#//*#/#g' -e ':a' -e 's#/\./#/#g' -e 'ta' -e 's#^\./##'
}

# rel_norm PROJ FILE -> normalised FILE relative to normalised PROJ (leading ./ removed)
rel_norm() {
  local p f
  p="$(norm_path "$1")"; p="${p%/}"
  f="$(norm_path "$2")"
  case "$f" in "$p"/*) f="${f#"$p"/}" ;; esac
  f="${f#./}"
  printf '%s' "$f"
}

# path_class REL -> one of: manuscript ryukoku tools questions searchlog thinking statement disclosure annotations ledger
#                   bibliography claude runconfig startup raw statehome ci proposals claims verification research other
# (the Python twin is scripts/rk/rklib/paths.py; a test keeps them in agreement)
# REL must already be normalised. A "manuscript" segment anywhere counts (also absolute paths that point at
# another checkout of the same project, and Windows paths passed with a foreign cwd).
path_class() {
  local r="$1"
  case "/$r" in
    */.ryukoku-writing/*|*/.ryukoku-writing) echo statehome; return ;;
    */.claude/*|*/.claude) echo claude; return ;;
    */.git/*|*/.git|*/.gitconfig|*/.gitmodules|*/.config/git/*|*/site-packages/*|*/sitecustomize.py|*/usercustomize.py|*.pth) echo runconfig; return ;;
    */.bashrc|*/.bash_profile|*/.bash_login|*/.bash_logout|*/.profile|*/.zshrc|*/.zprofile|*/.zshenv|*/.zlogin|*/.inputrc|*/.kshrc|*/.cshrc|*/.tcshrc|*/.netrc|*/.envrc|*/config.fish|*/profile.ps1|*/microsoft.powershell_profile.ps1) echo startup; return ;;
    */.local/bin/*|*/bin/*|*/.config/autostart/*|*/.config/systemd/user/*|*/library/launchagents/*|*/.vscode/*|*/.config/fish/*) echo startup; return ;;
    */manuscript/*|*/manuscript) echo manuscript; return ;;
    */.ryukoku/*|*/.ryukoku) echo ryukoku; return ;;
    */tools/rk/*|*/tools/rk|*/tools) echo tools; return ;;
    */rk|*/rk.cmd|*/rk.ps1) echo tools; return ;;
    */research/questions.md) echo questions; return ;;
    */research/search-log.jsonl) echo searchlog; return ;;
    */thinking/*|*/thinking) echo thinking; return ;;
    */disclosure/statement*.md) echo statement; return ;;
    */disclosure/*|*/disclosure) echo disclosure; return ;;
    */review/annotations.json|*/review/annotations-log.jsonl) echo annotations; return ;;
    */sources/register.csv|*/sources/claims.csv) echo ledger; return ;;
    */sources/references.json) echo bibliography; return ;;
    */data/raw/*) echo raw; return ;;
    */.github/*|*/.githooks/*|*/.git/hooks/*) echo ci; return ;;
    */proposals/*) echo proposals; return ;;
    */claims/*) echo claims; return ;;
    */review/verification/*) echo verification; return ;;
    */research/*|*/sources/*|*/review/*|*/excerpts/*) echo research; return ;;
  esac
  echo other
}

# utf8_clean: drop bytes that do not form valid UTF-8 (byte-wise matches in LC_ALL=C can split a character)
utf8_clean() {
  if command -v iconv >/dev/null 2>&1; then iconv -f UTF-8 -t UTF-8 -c 2>/dev/null || cat; else LC_ALL=C tr -d '\200-\377'; fi
}

# tool_input_paths: stdin hook JSON -> one value per line: every string value inside tool_input that looks like a
# path (has a / or \, or names a file with an extension), except fields that carry text rather than a path
tool_input_paths() {
  LC_ALL=C grep -o '"[A-Za-z0-9_]*"[[:space:]]*:[[:space:]]*"[^"]*"' | while IFS= read -r kv; do
    k="${kv#\"}"; k="${k%%\"*}"
    case "$k" in content|text|body|old_string|new_string|new_str|old_str|prompt|description|query|url|pattern|command|new_source|message|comment|title|tool_name|hook_event_name|session_id|tool_use_id|transcript_path|cwd|permission_mode) continue ;; esac
    v="${kv#*:}"; v="${v#"${v%%[![:space:]]*}"}"; v="${v#\"}"; v="${v%\"}"
    case "$v" in *"\\n"*) continue ;; esac
    case "$v" in */*|*\\*|*.md|*.csv|*.json|*.jsonl|*.yml|*.yaml|*.txt|*.py|*.sh) printf '%s\n' "$v" | sed 's#\\\\#\\#g' ;; esac
  done
}

# pii_scan: stdin text -> lines "kind<TAB>line<TAB>masked" (never prints the full value)
# Kinds: メールアドレス, 電話番号, 学籍番号, マイナンバーらしき12桁, 住所の手がかり, 郵便番号, カード番号, 秘密鍵・トークン
pii_scan() {
  local t tmp
  t="$(cat)"
  # NFKC (full-width digits and hyphen-like characters -> ASCII) before matching. Without python3 a sed
  # table covers the full-width digits and the common hyphen variants.
  if [ -n "${RK_HOOKCORE:-}" ] && have_python; then
    t="$(printf '%s' "$t" | pyrun -I -B "$RK_HOOKCORE" nfkc 2>/dev/null || printf '%s' "$t")"
  else
    t="$(printf '%s' "$t" | LC_ALL=C sed -e 's/０/0/g' -e 's/１/1/g' -e 's/２/2/g' -e 's/３/3/g' -e 's/４/4/g' -e 's/５/5/g' -e 's/６/6/g' -e 's/７/7/g' -e 's/８/8/g' -e 's/９/9/g' -e 's/−/-/g' -e 's/－/-/g' -e 's/ー/-/g' -e 's/‐/-/g' -e 's/　/ /g' -e 's/＋/+/g')"
  fi
  tmp="$(printf '%s\n' "$t")"
  _pii() { # kind ERE [extra grep flag]
    printf '%s\n' "$tmp" | LC_ALL=C grep -n -o -E ${3:-} -e "$2" 2>/dev/null | while IFS= read -r m; do
      ln="${m%%:*}"; v="${m#*:}"
      case "$1" in
        メールアドレス) printf '%s' "$v" | LC_ALL=C grep -Eiq '^git@|@example\.(com|org|net|jp)$|noreply' && continue ;;
      esac
      # mask: digits -> *, e-mail local part -> first letter + ***. The full value is never printed.
      mk="$(printf '%s' "$v" | LC_ALL=C sed -e 's/[0-9]/*/g' -e 's/^\([A-Za-z]\)[^@]*@/\1***@/' | utf8_clean)"
      # an address: show only up to the prefecture (the place names are never shown)
      [ "$1" = 住所の手がかり ] && mk="$(printf '%s' "$v" | LC_ALL=C sed -E 's/(都|道|府|県).*/\1***/' | utf8_clean)"
      printf '%s\t%s\t%s\n' "$1" "$ln" "$mk"
    done
  }
  _pii メールアドレス '[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}'
  _pii 電話番号 '(^|[^0-9./-])\(0[0-9]{1,4}\)[ -]?[0-9]{1,4}[- ]?[0-9]{3,4}($|[^0-9])|(^|[^0-9./-])0[0-9]{1,4}\.[0-9]{1,4}\.[0-9]{4}($|[^0-9.])|(^|[^0-9./-])0[0-9]{1,4}[-(][0-9]{1,4}[-)][0-9]{3,4}($|[^0-9])|\+81[- ]?[0-9]{1,4}[- ][0-9]{1,4}[- ][0-9]{4}|(^|[^0-9])0[789]0[0-9]{8}($|[^0-9])|\+81[0-9]{9,10}|(^|[^0-9.,:/-])0[0-9]{1,4} [0-9]{2,4} [0-9]{4}($|[^0-9])'
  _pii 学籍番号 '(学籍番号|学生番号|学生証番号|学籍no|student[ _-]?(id|number|no\.?)|id[ _-]?number|id番号)[^A-Za-z0-9]{0,12}((is|was|=)[^A-Za-z0-9]{0,4})?[A-Za-z]{0,3}[0-9]{4,10}' -i
  _pii マイナンバーらしき12桁 '(マイナンバー|個人番号|my ?number)[^0-9]{0,12}[0-9]{4}[ -]?[0-9]{4}[ -]?[0-9]{4}' -i
  _pii マイナンバーらしき12桁 '(^|[^0-9-])[0-9]{4}[ -][0-9]{4}[ -][0-9]{4}($|[^0-9-])|(^|[^0-9.-])[0-9]{12}($|[^0-9.-])'
  _pii 郵便番号 '(〒|郵便番号)[^0-9]{0,4}[0-9]{3}-?[0-9]{4}'
  _pii 住所の手がかり '(都|道|府|県).{1,36}(市|区|町|村).{0,48}([0-9]|０|１|２|３|４|５|６|７|８|９)+(丁目|番地|号|-[0-9])'
  _pii カード番号 '(^|[^0-9])[0-9]{4}[ -][0-9]{4}[ -][0-9]{4}[ -][0-9]{4}($|[^0-9])'
  _pii 秘密鍵・トークン 'sk-[A-Za-z0-9_-]{20,}|ghp_[A-Za-z0-9]{30,}|AKIA[0-9A-Z]{16}|-----BEGIN [A-Z ]*PRIVATE KEY-----'
}

# pii_kinds: stdin -> space separated unique kinds
pii_kinds() { pii_scan | cut -f1 | LC_ALL=C sort -u | tr '\n' ' ' | sed 's/ $//'; }

# pre_decide deny|ask REASON -> print PreToolUse JSON and exit 0
pre_decide() {
  local r
  r="$(printf '%s' "$2" | json_escape)"
  printf '{"hookSpecificOutput":{"hookEventName":"PreToolUse","permissionDecision":"%s","permissionDecisionReason":"%s"}}\n' "$1" "$r"
  exit 0
}

# context_out EVENT TEXT -> additionalContext JSON
context_out() {
  local c; c="$(printf '%s' "$2" | head -c 9500 | json_escape)"
  printf '{"hookSpecificOutput":{"hookEventName":"%s","additionalContext":"%s"}}\n' "$1" "$c"
}

today() { date +%Y-%m-%d; }
now_iso() { date +%Y-%m-%dT%H:%M:%S%z; }

# days_since YYYY-MM-DD -> integer days (empty when the date cannot be parsed). GNU date or BSD date.
days_since() {
  local then now
  then="$(date -d "$1" +%s 2>/dev/null || date -j -f %Y-%m-%d "$1" +%s 2>/dev/null || true)"
  [ -n "$then" ] || return 0
  now="$(date +%s)"
  echo $(( (now - then) / 86400 ))
}

# have_python -> 0 when a Python 3 that really runs was found; sets RK_PY ("python3", "python" or "py") (on
# Windows "python3" is often the Microsoft Store stub, which exists but does not run). pyrun ARGS runs it.
RK_PY=""
# is_session_tmp NORM_PATH NORM_PROJ -> 0 when NORM_PATH is a session temp dir writable without asking ($TMPDIR,
# /tmp, /var/tmp), AND the project is not itself under that temp root (so a project under /tmp, as in the tests,
# does not make its surroundings free).
is_session_tmp() {
  local n="$1" proj="$2" td
  td="$(norm_path "${TMPDIR:-}")"
  [ -n "$td" ] && case "$n/" in "$td"/*) case "$proj/" in "$td"/*) return 1 ;; *) return 0 ;; esac ;; esac
  case "$n/" in
    /tmp/*|/var/tmp/*|/private/tmp/*|/private/var/tmp/*)
      case "$proj/" in /tmp/*|/var/tmp/*|/private/tmp/*|/private/var/tmp/*) return 1 ;; *) return 0 ;; esac ;;
    /dev/null/|/dev/stdout/|/dev/stderr/) return 0 ;;
  esac
  return 1
}

have_python() {
  [ -n "$RK_PY" ] && return 0
  if command -v python3 >/dev/null 2>&1 && python3 -c 'import sys; sys.exit(sys.version_info[0] != 3)' >/dev/null 2>&1; then RK_PY=python3
  elif command -v python >/dev/null 2>&1 && python -c 'import sys; sys.exit(sys.version_info[0] != 3)' >/dev/null 2>&1; then RK_PY=python
  elif command -v py >/dev/null 2>&1 && py -3 -c 'import sys' >/dev/null 2>&1; then RK_PY=py
  else return 1; fi
  return 0
}
pyrun() { if [ "$RK_PY" = py ]; then py -3 "$@"; else "$RK_PY" "$@"; fi; }

# t JA EN -> message in the feedback language of the project
t() { if [ "${FB_LANG:-ja}" = en ]; then printf '%s' "$2"; else printf '%s' "$1"; fi; }
