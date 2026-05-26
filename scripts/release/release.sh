#!/usr/bin/env bash
# release.sh — Main release entry point.
#
# Usage:
#   ./scripts/release/release.sh [--dry-run] [--type=patch|minor|major]
#
# Steps:
#   1. Preflight checks (git clean, tests, lint, build)
#   2. Calculate version bump (conventional commits)
#   3. Generate changelog
#   4. Commit version bump + changelog
#   5. Create git tag
#   6. (If not dry-run) npm publish, Docker build, GitHub Release, git push

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
  node "$SCRIPT_DIR/bump-version.js" --dry-run $BUMP_ARGS
  NEW_VERSION=$(node "$SCRIPT_DIR/bump-version.js" $BUMP_ARGS 2>/dev/null | tail -1)
else
  NEW_VERSION=$(node "$SCRIPT_DIR/bump-version.js" $BUMP_ARGS)
  ok "Version bumped to v$NEW_VERSION (package.json updated)"
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
  echo "  Would commit: package.json, CHANGELOG.md"
  echo "  Would create tag: v$NEW_VERSION"
else
  git add package.json CHANGELOG.md
  git -c user.name="agent-mafei" -c user.email="mafei@izmw.me" \
    commit -m "chore(release): v$NEW_VERSION"
  git tag -a "v$NEW_VERSION" -m "Release v$NEW_VERSION"
  ok "Committed and tagged v$NEW_VERSION"
fi

# ---------------------------------------------------------------------------
# Step 5: Publish
# ---------------------------------------------------------------------------

step 5 "Publishing..."
if $DRY_RUN; then
  echo "  Would publish to npm"
  echo "  Would build & push Docker image"
  echo "  Would create GitHub Release"
  echo "  Would push to origin"
  echo ""
  echo -e "${GREEN}═══════════════════════════════════════════${NC}"
  echo -e "${GREEN}  Dry run complete. No changes published.${NC}"
  echo -e "${GREEN}═══════════════════════════════════════════${NC}"
  exit 0
fi

# npm publish
if [ -f "package.json" ]; then
  IS_PRIVATE=$(node -e "console.log(require('./package.json').private || false)")
  if [ "$IS_PRIVATE" != "true" ]; then
    echo "  Publishing to npm..."
    npm publish 2>&1 && ok "Published to npm" || warn "npm publish failed (check auth)"
  else
    warn "Package is private — skipping npm publish"
  fi
fi

# Docker build & push
if [ -f "Dockerfile" ]; then
  echo "  Building Docker image..."
  IMAGE_NAME=$(node -e "console.log(require('./package.json').name || 'roundtable')")
  docker build -t "$IMAGE_NAME:v$NEW_VERSION" -t "$IMAGE_NAME:latest" . 2>&1 \
    && ok "Docker image built" \
    || warn "Docker build failed"

  if command -v docker &>/dev/null; then
    docker push "$IMAGE_NAME:v$NEW_VERSION" 2>&1 && ok "Pushed $IMAGE_NAME:v$NEW_VERSION" || warn "Docker push failed"
    docker push "$IMAGE_NAME:latest" 2>&1 && ok "Pushed $IMAGE_NAME:latest" || warn "Docker push failed"
  fi
else
  warn "No Dockerfile found — skipping Docker build"
fi

# GitHub Release
if command -v gh &>/dev/null; then
  echo "  Creating GitHub Release..."
  # Extract latest changelog section
  CHANGELOG_LATEST=$(awk "/^## \\[$NEW_VERSION/{found=1; next} /^## \\[/{if(found) exit} found{print}" CHANGELOG.md)
  if [ -n "$CHANGELOG_LATEST" ]; then
    echo "$CHANGELOG_LATEST" > /tmp/release-notes-$NEW_VERSION.md
    gh release create "v$NEW_VERSION" \
      --title "v$NEW_VERSION" \
      --notes-file "/tmp/release-notes-$NEW_VERSION.md" \
      2>&1 && ok "GitHub Release created" || warn "GitHub Release failed"
    rm -f "/tmp/release-notes-$NEW_VERSION.md"
  else
    gh release create "v$NEW_VERSION" \
      --title "v$NEW_VERSION" \
      --generate-notes \
      2>&1 && ok "GitHub Release created" || warn "GitHub Release failed"
  fi
else
  warn "gh CLI not found — skipping GitHub Release"
fi

# Git push
echo "  Pushing to origin..."
BRANCH=$(git branch --show-current)
git push origin "$BRANCH" 2>&1 && ok "Pushed branch" || warn "Branch push failed"
git push origin --tags 2>&1 && ok "Pushed tags" || warn "Tag push failed"

echo ""
echo -e "${GREEN}═══════════════════════════════════════════${NC}"
echo -e "${GREEN}  ✅ Release v$NEW_VERSION complete!${NC}"
echo -e "${GREEN}═══════════════════════════════════════════${NC}"
