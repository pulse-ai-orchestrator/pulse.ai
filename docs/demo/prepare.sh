#!/usr/bin/env bash
set -euo pipefail

demo_dir="$(cd "$(dirname "$0")" && pwd)"
repo_dir="$(cd "$demo_dir/../.." && pwd)"
root="${PULSE_DEMO_ROOT:-/tmp/pulse-demo}"
project="$root/calculadora"

if [ -f "$root/home/.pulse/daemon.json" ]; then
    HOME="$root/home" "$repo_dir/.venv/bin/pulse" daemon stop >/dev/null
fi
if nc -z 127.0.0.1 8787 2>/dev/null; then
    echo "prepare.sh: port 8787 is taken; run \`pulse daemon stop\` first" >&2
    exit 1
fi

rm -rf "$root"
mkdir -p "$root/home" "$root/bin" "$project"
{
    echo "#!$repo_dir/.venv/bin/python"
    tail -n +2 "$demo_dir/fake_agent.py"
} >"$root/bin/agent"
chmod 0755 "$root/bin/agent"
ln -s "$repo_dir/.venv/bin/pulse" "$root/bin/pulse"

cat >"$project/calc.py" <<'PY'
def media(valores: list[float]) -> float:
    return sum(valores) / len(valores)
PY

cat >"$project/test_calc.py" <<'PY'
from calc import media


def test_media_de_valores():
    assert media([2, 4, 6]) == 4
PY

git -C "$project" init -q -b main
git -C "$project" add .
GIT_AUTHOR_NAME=demo GIT_AUTHOR_EMAIL=demo@example.com \
GIT_COMMITTER_NAME=demo GIT_COMMITTER_EMAIL=demo@example.com \
    git -C "$project" commit -q -m "feat: media"

HOME="$root/home" PATH="$root/bin:$PATH" "$repo_dir/.venv/bin/python" - "$project" <<'PY'
import sys
from pathlib import Path

from pulse.config.onboarding import complete_onboarding

complete_onboarding(
    runtime_id="cursor",
    workspace=Path(sys.argv[1]),
    model="Auto",
    permission_policy="ask",
    auth_method="cursor_login",
    acp_test_passed=True,
)
PY
