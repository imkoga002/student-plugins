#!/usr/bin/env bash
# Scaffold: shared project with placeholder content, plus one concrete, neutral question of the student's own
# (argumentation theory, unrelated to any thesis topic) so that a real search makes sense.
set -eu
bash "$(cd "$(dirname "$0")/.." && pwd)/_shared/scaffold.sh" ja
printf '| Q2 | トゥールミンの論証モデルは、いつ、どの本で示されたか | 初出の書誌 | 着手 |\n' >> research/questions.md
