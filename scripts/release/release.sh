#!/usr/bin/env bash
# release.sh — Pre-release: bump version, changelog, commit, tag, push.
#
# Usage:
#   ./scripts/release/release.sh [--dry-run] [--type=patch|minor|major]
#
# After pushing the tag, GitHub Actions (release.yml) will automatically:
#   - Build sdist + wheel
#   - Publish to PyPI
#   - Publish to ClawHub
#   - Create GitHub Release

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"

cd "$ROOT_DIR"

# ---------------------------------------------------------------------------
# Args
# ---------------------------------------------------------------------------

DRY_RUN=false
BUMP_TYPE=""

for arg in "$@"; do
  case "$arg" in
    --dry-run) DRY_RUN=true ;;
    --type=*) BUMP_TYPE="${arg#--type=}" ;;
  esac
done

RED='\033[0;31m'
GREEN='\033[0;32m'
CYAN='\033[0;36m'
YELLOW='\033[1;33m'
BOLD='\033[1m'
NC='\033[0m'

step() { echo -e "\n${CYAN}[$1/5]${NC} ${BOLD}$2${NC}"; }
ok() { echo -e "  ${GREEN}✓${NC} $1"; }
warn() { echo -e "  ${YELLOW}⚠${NC} $1"; }
die() { echo -e "  ${RED}✗${NC} $1"; exit 1; }

echo "═══════════════════════════════════════════"
echo "  🚀 Roundtable Release"
if $DRY_RUN; then
  echo -e "  ${YELLOW}DRY RUN — no changes will be published${NC}"
fi
echo "═══════════════════════════════════════════"

# ---------------------------------------------------------------------------
# Step 1: Preflight
# ---------------------------------------------------------------------------

step 1 "Running preflight checks..."
bash "$SCRIPT_DIR/preflight-check.sh" || die "Preflight checks failed"

# ---------------------------------------------------------------------------
# Step 2: Calculate version
# ---------------------------------------------------------------------------

step 2 "Calculating version bump..."
BUMP_ARGS=""
if [ -n "$BUMP_TYPE" ]; then
  BUMP_ARGS="--type=$BUMP_TYPE"
fi

if $DRY_RUN; then
  # Dry-run path: only show preview, never mutate files
  node "$SCRIPT_DIR/bump-version.js" --dry-run $BUMP_ARGS
  NEW_VERSION=$(node "$SCRIPT_DIR/bump-version.js" --dry-run $BUMP_ARGS | grep "New version:" | sed 's/.*v//')
else
  NEW_VERSION=$(node "$SCRIPT_DIR/bump-version.js" $BUMP_ARGS)
  ok "Version bumped to v$NEW_VERSION across packages, locks and skills"
fi

# ---------------------------------------------------------------------------
# Step 3: Generate changelog
# ---------------------------------------------------------------------------

step 3 "Generating changelog..."
if $DRY_RUN; then
  node "$SCRIPT_DIR/changelog.js" --dry-run --version="$NEW_VERSION"
else
  node "$SCRIPT_DIR/changelog.js" --version="$NEW_VERSION"
  ok "CHANGELOG.md updated"
fi

# ---------------------------------------------------------------------------
# Step 4: Commit & tag
# ---------------------------------------------------------------------------

step 4 "Committing and tagging..."
if $DRY_RUN; then
  echo "  Would commit version declarations, locks, skills and CHANGELOG.md"
  echo "  Would create tag: v$NEW_VERSION"
else
  git add package.json package-lock.json pyproject.toml uv.lock \
    src/roundtable/__init__.py src/roundtable/web/package.json \
    src/roundtable/web/package-lock.json SKILL.md src/skills/SKILL.md CHANGELOG.md
  git commit -m "chore(release): v$NEW_VERSION"
  git tag -a "v$NEW_VERSION" -m "Release v$NEW_VERSION"
  ok "Committed and tagged v$NEW_VERSION"
fi

# ---------------------------------------------------------------------------
# Step 5: Git push & tag (triggers CI release)
# ---------------------------------------------------------------------------

step 5 "Pushing to origin..."
if $DRY_RUN; then
  echo "  Would push branch to origin"
  echo "  Would push tags → triggers GitHub Actions release"
  echo ""
  echo -e "${GREEN}═══════════════════════════════════════════${NC}"
  echo -e "${GREEN}  Dry run complete. No changes published.${NC}"
  echo -e "${GREEN}═══════════════════════════════════════════${NC}"
  exit 0
fi

BRANCH=$(git branch --show-current)
git push origin "$BRANCH" 2>&1 && ok "Pushed branch" || die "Branch push failed"
git push origin "v$NEW_VERSION" 2>&1 && ok "Pushed release tag" || die "Tag push failed"

echo ""
echo -e "${GREEN}═══════════════════════════════════════════${NC}"
echo -e "${GREEN}  ✅ Release v$NEW_VERSION — tag pushed!${NC}"
echo -e "${GREEN}═══════════════════════════════════════════${NC}"
echo ""
echo -e "  GitHub Actions will now automatically:"
echo -e "    • Build & publish to ${CYAN}PyPI${NC}"
echo -e "    • Publish to ${CYAN}ClawHub${NC}"
echo -e "    • Create ${CYAN}GitHub Release${NC}"
echo ""
echo -e "  Track progress: ${CYAN}gh run list --workflow=release.yml${NC}"
