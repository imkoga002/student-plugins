#!/usr/bin/env bash
# Run every test of ryukoku-writing: shell syntax, bash-3.2 portability lint of the hooks, JSON files, the
# manifest of the tools, and the Python unit tests (standard library only; the browser test runs when node and
# playwright exist; live API tests only with RK_NET_TESTS=1). Leaves no __pycache__ behind.
set -u
cd "$(dirname "$0")/.."
export PYTHONDONTWRITEBYTECODE=1
rc=0
for f in scripts/hooks/*.sh scripts/init-project.sh templates/github/.githooks/* evals/*/scaffold.sh evals/_shared/*.sh; do
  [ -f "$f" ] || continue
  bash -n "$f" || { echo "syntax error: $f"; rc=1; }
done
sh -n scripts/rk/launchers/rk || { echo "syntax error: launchers/rk"; rc=1; }
# bash 3.2 (macOS) lacks these: associative arrays, case-modifying expansions, mapfile/readarray, |&, ;;&
if grep -nE 'declare -A|\$\{[A-Za-z_]+(,,|\^\^)|mapfile|readarray|\|&[[:space:]]|;;&' scripts/hooks/*.sh scripts/init-project.sh; then
  echo "bash 3.2 incompatible construct found"; rc=1
fi
# GNU-only options in the hooks (BSD userland on macOS)
if grep -nE 'grep -P|sed -i|readlink -f|stat -c|date \+%s%N' scripts/hooks/*.sh; then echo "GNU-only option in a hook"; rc=1; fi
grep -nE '^[^#]*(^|[^a-z])jq([^a-z]|$)' scripts/hooks/*.sh && { echo "hooks must not need jq"; rc=1; }
for f in .claude-plugin/plugin.json hooks/hooks.json scripts/rk/review/taxonomy.json; do
  python3 -m json.tool "$f" >/dev/null || { echo "bad json: $f"; rc=1; }
done
LOG="${TMPDIR:-/tmp}/rkw-tests-$$.log"
# the tests must not leave anything in the real home
HOME_STATE="$HOME/.ryukoku-writing"
BEFORE="$(ls -laR "$HOME_STATE" 2>/dev/null | LC_ALL=C cksum)"
python3 -B -W ignore -m unittest discover -s tests -p 'test_*.py' -v >"$LOG" 2>&1
urc=$?
grep -E '(FAIL|ERROR|skipped)' "$LOG" | grep -vE '^(Ran|OK)' | head -n 60
tail -n 4 "$LOG"
[ $urc -eq 0 ] || { rc=1; echo "full log: $LOG"; }
[ $urc -eq 0 ] && rm -f "$LOG"
find . -name __pycache__ -type d -prune -exec rm -rf {} +
AFTER="$(ls -laR "$HOME_STATE" 2>/dev/null | LC_ALL=C cksum)"
if [ "$BEFORE" != "$AFTER" ]; then echo "the tests changed $HOME_STATE (they must use a temporary HOME)"; rc=1; fi
[ $rc -eq 0 ] && echo "ALL OK" || echo "FAILED"
exit $rc
