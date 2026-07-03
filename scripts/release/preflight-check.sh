#!/usr/bin/env bash
# preflight-check.sh — Run all release gates before publishing.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"
cd "$ROOT_DIR"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

pass() { echo -e "${GREEN}✓${NC} $1"; }
fail() { echo -e "${RED}✗${NC} $1"; exit 1; }
warn() { echo -e "${YELLOW}⚠${NC} $1"; }
info() { echo "  $1"; }
run() {
  local label="$1"
  echo ""
  echo "▶ $label"
  shift
  "$@"
  pass "$label passed"
}

if [ -n "${PYTHON:-}" ]; then
  PYTHON_BIN="$PYTHON"
elif [ -x ".venv/bin/python" ]; then
  PYTHON_BIN=".venv/bin/python"
elif command -v python3.12 >/dev/null 2>&1; then
  PYTHON_BIN="$(command -v python3.12)"
elif command -v python3.11 >/dev/null 2>&1; then
  PYTHON_BIN="$(command -v python3.11)"
elif command -v python3.10 >/dev/null 2>&1; then
  PYTHON_BIN="$(command -v python3.10)"
else
  PYTHON_BIN="${PYTHON:-python3}"
fi

echo "═══════════════════════════════════"
echo "  Release Preflight Checks"
echo "═══════════════════════════════════"

if ! "$PYTHON_BIN" - <<'PY' >/dev/null; then
import sys

raise SystemExit(0 if sys.version_info >= (3, 10) else 1)
PY
  fail "Python 3.10+ is required before releasing. Set PYTHON=/path/to/python3.11 if needed."
fi

echo ""
echo "▶ Checking git status..."
DIRTY=$(git status --porcelain)
if [ -n "$DIRTY" ]; then
  fail "Working directory is not clean. Commit or stash changes first."
fi
pass "Git working directory clean"

BRANCH=$(git branch --show-current)
if [ -z "$BRANCH" ]; then
  fail "Not on a branch (detached HEAD)."
fi
info "Branch: $BRANCH"
git fetch --quiet 2>/dev/null || warn "Could not fetch from remote"
REMOTE=$(git rev-parse "origin/$BRANCH" 2>/dev/null || echo "")
if [ -n "$REMOTE" ] && [ "$(git rev-parse HEAD)" != "$REMOTE" ]; then
  warn "Local branch is not in sync with origin/$BRANCH"
fi

echo ""
echo "▶ Installing release check tools..."
"$PYTHON_BIN" -m pip install --upgrade pip build twine >/dev/null
"$PYTHON_BIN" -m pip install -e ".[dev]" >/dev/null
pass "Release tools installed"

run "Ruff lint" "$PYTHON_BIN" -m ruff check src tests
run "Ruff format" "$PYTHON_BIN" -m ruff format --check src tests
run "Mypy" "$PYTHON_BIN" -m mypy src

if [ -f "package.json" ]; then
  if command -v npm >/dev/null 2>&1; then
    NODE_MAJOR=$(node -e "const major=Number(process.versions.node.split('.')[0]); process.stdout.write(String(major));")
    if [ "$NODE_MAJOR" -lt 18 ]; then
      fail "Node.js 18+ is required before releasing. Current version: $(node --version)"
    fi
    echo ""
    echo "▶ Installing npm dependencies..."
    npm install --omit=dev
    pass "npm dependencies installed"
    run "Node syntax check" npm run check
  else
    fail "npm not found. Install Node.js 18+ before releasing."
  fi
fi

run "Pytest" "$PYTHON_BIN" -m pytest -q

echo ""
echo "▶ Checking version consistency..."
PKG_VERSION=$(node -e "console.log(require('./package.json').version)")
WEB_PKG_VERSION=$(node -e "console.log(require('./src/roundtable/web/package.json').version)")
PYPROJECT_VERSION=$(grep -E '^version = ' pyproject.toml | head -1 | sed -E 's/^version = "(.+)"/\1/')
INIT_VERSION=$("$PYTHON_BIN" -c "import roundtable; print(roundtable.__version__)")
SKILL_VERSION=$(grep -E '^version: ' SKILL.md | head -1 | sed -E 's/^version: //')
SRC_SKILL_VERSION=$(grep -E '^version: ' src/skills/SKILL.md | head -1 | sed -E 's/^version: //')
for item in "$WEB_PKG_VERSION" "$PYPROJECT_VERSION" "$INIT_VERSION" "$SKILL_VERSION" "$SRC_SKILL_VERSION"; do
  if [ "$item" != "$PKG_VERSION" ]; then
    fail "Version mismatch: package.json=$PKG_VERSION web/package.json=$WEB_PKG_VERSION pyproject=$PYPROJECT_VERSION __init__=$INIT_VERSION SKILL=$SKILL_VERSION src/skills=$SRC_SKILL_VERSION"
  fi
done
pass "Version check passed"

echo ""
echo "▶ Building distributions..."
rm -rf dist build
"$PYTHON_BIN" -m build
pass "Build passed"
run "Twine check" "$PYTHON_BIN" -m twine check dist/*

echo ""
echo "▶ Checking distribution hygiene..."
if "$PYTHON_BIN" - <<'PY'
import sys
from pathlib import Path
from zipfile import ZipFile

wheel_paths = list(Path("dist").glob("*.whl"))
if not wheel_paths:
    raise SystemExit("No wheel found in dist/")

bad_entries: list[str] = []
for wheel_path in wheel_paths:
    with ZipFile(wheel_path) as wheel:
        bad_entries.extend(
            name
            for name in wheel.namelist()
            if "/node_modules/" in name or name.endswith("/node_modules")
        )

if bad_entries:
    print("Wheel includes node_modules entries, for example:", file=sys.stderr)
    for name in bad_entries[:10]:
        print(f"  {name}", file=sys.stderr)
    raise SystemExit(1)
PY
then
  pass "Distribution hygiene check passed"
else
  fail "Distribution hygiene check failed"
fi

echo ""
echo "▶ Wheel install smoke test..."
SMOKE_DIR=$(mktemp -d)
"$PYTHON_BIN" -m venv "$SMOKE_DIR/venv"
"$SMOKE_DIR/venv/bin/python" -m pip install --upgrade pip >/dev/null
"$SMOKE_DIR/venv/bin/python" -m pip install dist/*.whl >/dev/null
"$SMOKE_DIR/venv/bin/python" - <<'PY'
from importlib import resources

import roundtable

assert roundtable.__version__ == "2.1.0"
assert (resources.files("roundtable") / "web" / "viewer.js").is_file()
assert (resources.files("roundtable") / "web" / "i18n.js").is_file()
assert (resources.files("roundtable") / "web" / "package.json").is_file()
assert (resources.files("roundtable") / "web" / "package-lock.json").is_file()
assert (resources.files("roundtable") / "templates" / "product-review.json").is_file()
assert (resources.files("roundtable") / "skills" / "mcp-roundtable" / "SKILL.md").is_file()
print("wheel smoke ok")
PY
"$SMOKE_DIR/venv/bin/python" -m roundtable.demo --no-web --rounds 1 >/dev/null
rm -rf "$SMOKE_DIR"
pass "Wheel install smoke test passed"

echo ""
echo "═══════════════════════════════════"
echo -e "  ${GREEN}All preflight checks passed ✓${NC}"
echo "═══════════════════════════════════"
