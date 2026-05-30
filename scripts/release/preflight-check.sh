#!/usr/bin/env bash
# preflight-check.sh — Run all checks before release.
# Exits non-zero if any check fails.

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
info() { echo -e "  $1"; }

echo "═══════════════════════════════════"
echo "  Release Preflight Checks"
echo "═══════════════════════════════════"
echo ""

# 1. Git clean
echo "▶ Checking git status..."
DIRTY=$(git status --porcelain)
if [ -n "$DIRTY" ]; then
  fail "Working directory is not clean. Commit or stash changes first."
fi
pass "Git working directory clean"

# 2. On a valid branch
BRANCH=$(git branch --show-current)
if [ -z "$BRANCH" ]; then
  fail "Not on a branch (detached HEAD)."
fi
info "Branch: $BRANCH"

# 3. Up to date with remote
git fetch --quiet 2>/dev/null || warn "Could not fetch from remote (offline?)"
LOCAL=$(git rev-parse HEAD)
REMOTE=$(git rev-parse "origin/$BRANCH" 2>/dev/null || echo "")
if [ -n "$REMOTE" ] && [ "$LOCAL" != "$REMOTE" ]; then
  warn "Local branch is not in sync with origin/$BRANCH"
fi
pass "Branch check passed"

# 4. Python tests (this is a Python package — pytest is authoritative)
echo ""
echo "▶ Running Python tests..."
# Prefer `python -m pytest` so we never depend on a console-script shebang
# that may be stale (e.g. when the venv was moved or the repo renamed).
if [ -x ".venv/bin/python" ]; then
  PYTEST_BIN=".venv/bin/python -m pytest"
elif command -v python3 >/dev/null 2>&1 && python3 -c "import pytest" 2>/dev/null; then
  PYTEST_BIN="python3 -m pytest"
elif command -v pytest >/dev/null 2>&1; then
  PYTEST_BIN=pytest
else
  fail "pytest not found. Install with: pip install -e '.[dev]'"
fi

if $PYTEST_BIN tests/ --ignore=tests/test_web_viewer.py -q; then
  pass "Python tests passed"
else
  fail "Python tests failed"
fi

# 5. npm tests (if present)
echo ""
echo "▶ Running npm tests..."
if [ -f "package.json" ]; then
  SCRIPTS=$(node -e "const p=require('./package.json'); console.log(Object.keys(p.scripts||{}).join(','))")
  if echo "$SCRIPTS" | grep -q "test"; then
    npm test 2>&1 && pass "npm tests passed" || fail "npm tests failed"
  else
    warn "No npm test script found — skipping"
  fi
else
  warn "No package.json found — skipping npm tests"
fi

# 6. Lint
echo ""
echo "▶ Running lint..."
if [ -f "package.json" ]; then
  if echo "${SCRIPTS:-}" | grep -q "lint"; then
    npm run lint 2>&1 && pass "Lint passed" || fail "Lint failed"
  else
    warn "No lint script found — skipping"
  fi
fi

# 7. Build
echo ""
echo "▶ Running build..."
if [ -f "package.json" ]; then
  if echo "${SCRIPTS:-}" | grep -q "build"; then
    npm run build 2>&1 && pass "Build passed" || fail "Build failed"
  else
    warn "No build script found — skipping"
  fi
fi

# 8. Version consistency across package.json, pyproject.toml, SKILL.md, src/skills/SKILL.md
echo ""
echo "▶ Checking version consistency..."

PKG_VERSION=$(node -e "console.log(require('./package.json').version)")
info "package.json version:        $PKG_VERSION"

PYPROJECT_VERSION=""
if [ -f "pyproject.toml" ]; then
  PYPROJECT_VERSION=$(grep -E '^version = ' pyproject.toml | head -1 | sed -E 's/^version = "(.+)"/\1/')
  info "pyproject.toml version:      $PYPROJECT_VERSION"
fi

SKILL_VERSION=""
if [ -f "SKILL.md" ]; then
  SKILL_VERSION=$(grep -E '^version: ' SKILL.md | head -1 | sed -E 's/^version: //')
  info "SKILL.md version:            $SKILL_VERSION"
fi

SRC_SKILL_VERSION=""
if [ -f "src/skills/SKILL.md" ]; then
  SRC_SKILL_VERSION=$(grep -E '^version: ' src/skills/SKILL.md | head -1 | sed -E 's/^version: //')
  info "src/skills/SKILL.md version: $SRC_SKILL_VERSION"
fi

# All non-empty versions must match package.json
MISMATCH=0
for v in "$PYPROJECT_VERSION" "$SKILL_VERSION" "$SRC_SKILL_VERSION"; do
  if [ -n "$v" ] && [ "$v" != "$PKG_VERSION" ]; then
    MISMATCH=1
  fi
done
if [ $MISMATCH -eq 1 ]; then
  fail "Version mismatch — all of package.json, pyproject.toml, SKILL.md, src/skills/SKILL.md must agree."
fi
pass "Version check passed"

echo ""
echo "═══════════════════════════════════"
echo -e "  ${GREEN}All preflight checks passed ✓${NC}"
echo "═══════════════════════════════════"
