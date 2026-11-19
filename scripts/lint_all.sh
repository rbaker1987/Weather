#!/usr/bin/env bash
# Full-repo lint: the same checks CI runs on pushes to master (and now on every PR).
# Run this before opening a PR:   bash scripts/lint_all.sh
#
# It lints the COMMITTED state (HEAD) in a temporary checkout with LF line endings, so results
# match CI even on Windows checkouts where core.autocrlf makes Prettier/ESLint report noise.
# Commit your changes first; uncommitted edits are not checked (the script warns if there are any).
set -u

ROOT=$(git rev-parse --show-toplevel)
cd "$ROOT" || exit 2

if [ -x "$ROOT/.venv/Scripts/python.exe" ]; then
  BIN="$ROOT/.venv/Scripts"
  EXE=".exe"
else
  BIN="$ROOT/.venv/bin"
  EXE=""
fi
export PATH="$BIN:$PATH"

if [ -n "$(git status --porcelain --untracked-files=no)" ]; then
  echo "WARNING: uncommitted changes are NOT linted; this checks HEAD only. Commit first." >&2
fi

TMP=$(mktemp -d)
WT="$TMP/wt"
cleanup() {
  git -C "$ROOT" worktree remove --force "$WT" >/dev/null 2>&1
  rm -rf "$TMP"
}
trap cleanup EXIT

git -c core.autocrlf=false -c core.eol=lf worktree add -q --detach "$WT" HEAD || exit 2

# Reuse the repo's installed node tools inside the temporary checkout.
if [ -d "$ROOT/node_modules" ]; then
  if command -v cygpath >/dev/null 2>&1; then
    cmd //c mklink /J "$(cygpath -w "$WT/node_modules")" "$(cygpath -w "$ROOT/node_modules")" >/dev/null
  else
    ln -s "$ROOT/node_modules" "$WT/node_modules"
  fi
fi

cd "$WT" || exit 2
FAILED=()

step() {
  local name=$1
  shift
  echo
  echo "=== $name"
  if "$@"; then
    echo "--- $name: ok"
  else
    echo "--- $name: FAILED"
    FAILED+=("$name")
  fi
}

step "ruff check" "ruff$EXE" check .
step "ruff format --check" "ruff$EXE" format --check .

if [ -d node_modules ]; then
  step "eslint" node_modules/.bin/eslint "weather_app/static/weather/js/*.js"
  # Same file set as the prettier pre-commit hook (all tracked js/json/css/md, minus lockfile/minified).
  mapfile -t PRETTIER_FILES < <(git ls-files '*.js' '*.json' '*.css' '*.md' | grep -v -E 'package-lock\.json|\.min\.(js|css)$')
  step "prettier --check" node_modules/.bin/prettier --check "${PRETTIER_FILES[@]}"
else
  echo "WARNING: node_modules missing (run 'npm install'); skipping eslint and prettier." >&2
  FAILED+=("eslint/prettier (node_modules missing)")
fi

# All pre-commit hooks (end-of-file, whitespace, yaml/json/toml, detect-secrets, ...) on every file.
# The project-coverage hook runs the whole test suite, so this also covers the 90% coverage gate.
# Auto-fixing hooks exit 1 the first time they change something, so a second run is the real result.
run_precommit() {
  "pre-commit$EXE" run --all-files --show-diff-on-failure >/dev/null 2>&1
  "pre-commit$EXE" run --all-files --show-diff-on-failure
}
git add -A >/dev/null 2>&1
step "pre-commit (all files)" run_precommit

echo
if [ ${#FAILED[@]} -eq 0 ]; then
  echo "ALL LINT CHECKS PASSED"
  exit 0
fi
echo "FAILED: ${FAILED[*]}"
exit 1
