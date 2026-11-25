#!/usr/bin/env bash
# The Claude Docs guard of ryukoku-writing 3.0 (PreToolUse and PostToolUse; matcher: the Claude Docs tools and the
# browser and screen tools). The rules are in scripts/rk/rklib/docsguard.py. Usage: docs-guard.sh pre|post
# Active only for a project with .ryukoku/config.yml (the session folder, an ancestor, or one or two levels below).
# Without Python the guard cannot read the call: on the registered document it then denies every Docs write.
set -u; set -f
HERE="$(cd "$(dirname "$0")" && pwd)"; . "$HERE/lib.sh"
EVENT="${1:-}"
INPUT="$(cat 2>/dev/null || true)"
[ -n "$INPUT" ] || exit 0
CWD="$(printf '%s' "$INPUT" | json_string_field cwd)"
PROJ="$(find_session_project "$CWD" 2>/dev/null || true)"
is_active "$PROJ" || exit 0
PLUGIN_ROOT="${CLAUDE_PLUGIN_ROOT:-$(cd "$HERE/../.." && pwd)}"
RK_HOOKCORE="$PLUGIN_ROOT/scripts/rk/hookcore.py"
if ! have_python; then
  if [ "$EVENT" = pre ] && [ -f "$PROJ/.ryukoku/docs.json" ]; then
    TOOL="$(printf '%s' "$INPUT" | json_string_field tool_name)"
    case "$TOOL" in
      *Claude_Docs__read|*Claude_Docs__query|*Claude_Docs__export|*Claude_Docs__guide) exit 0 ;;
      *Claude_Docs__*) pre_decide deny "[ryukoku-writing] Python 3 が見つからないので、Docs への書き込みを検査できない。安全のため止めた。Python 3 を入れてから続ける。 / Python 3 is missing, so the Docs guard cannot check this write; denied." ;;
    esac
  fi
  exit 0
fi
printf '%s' "$INPUT" | pyrun -I -B "$RK_HOOKCORE" docs "$PROJ" "$EVENT"
exit 0
