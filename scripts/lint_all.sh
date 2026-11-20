#!/usr/bin/env bash
# Pre-PR checks: the whole-repo lint CI runs on every push and pull request, plus tests and the
# commit-message rules. Run before opening a PR:   bash scripts/lint_all.sh
#
# It checks the COMMITTED state (HEAD) in a temporary checkout with LF line endings, so results
# match CI even on Windows checkouts where core.autocrlf makes Prettier/ESLint report noise.
# Commit your changes first; uncommitted edits are not checked (the script warns if there are any).
#
# Not run here, because they cannot run reliably on every machine (detect-secrets and the
# pre-commit hook environments hang on the maintainer's Windows machine): the detect-secrets and
# django-upgrade hooks. CI runs all pre-commit hooks on the whole repo for every PR, so if
# detect-secrets reports a shifted line number, refresh .secrets.baseline as the CI log shows.
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
PYTHON="$BIN/python$EXE"
export PATH="$BIN:$PATH"

if [ -n "$(git status --porcelain --untracked-files=no)" ]; then
  echo "WARNING: uncommitted changes are NOT checked; this checks HEAD only. Commit first." >&2
fi

BASE=master
git rev-parse --verify -q origin/master >/dev/null && BASE=origin/master

TMP=$(mktemp -d)
WT="$TMP/wt"
cleanup() {
  # Remove the node_modules junction itself first so deleting the checkout can never follow it
  # into the real node_modules (rmdir on a junction removes only the link).
  if command -v cygpath >/dev/null 2>&1 && [ -e "$WT/node_modules" ]; then
    cmd.exe //c rmdir "$(cygpath -w "$WT/node_modules")" >/dev/null 2>&1
  fi
  git -C "$ROOT" worktree remove --force "$WT" >/dev/null 2>&1
  rm -rf "$TMP"
}
trap cleanup EXIT

git -c core.autocrlf=false -c core.eol=lf worktree add -q --detach "$WT" HEAD || exit 2

# Reuse the repo's installed node tools inside the temporary checkout.
if [ -d "$ROOT/node_modules" ]; then
  if command -v cygpath >/dev/null 2>&1; then
    # A junction needs no admin rights on Windows (a symlink does).
    powershell.exe -NoProfile -Command \
      "New-Item -ItemType Junction -Path '$(cygpath -w "$WT/node_modules")' -Target '$(cygpath -w "$ROOT/node_modules")' | Out-Null"
  else
    ln -s "$ROOT/node_modules" "$WT/node_modules"
  fi
fi

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

# Conventional Commits (commitlint config-conventional) with body lines <= 200 characters,
# for every commit this branch adds on top of the base branch.
check_commit_messages() {
  local bad=0 sha subject
  local pattern='^(build|chore|ci|docs|feat|fix|perf|refactor|revert|style|test)(\([^)]+\))?!?: .+'
  for sha in $(git -C "$ROOT" rev-list "$BASE..HEAD"); do
    subject=$(git -C "$ROOT" log -1 --format=%s "$sha")
    if ! [[ $subject =~ $pattern ]]; then
      echo "$sha: subject is not a Conventional Commit: $subject"
      bad=1
    fi
    if [ ${#subject} -gt 100 ]; then
      echo "$sha: subject is longer than 100 characters"
      bad=1
    fi
    while IFS= read -r line; do
      if [ ${#line} -gt 200 ]; then
        echo "$sha: a message line is ${#line} characters (max 200): ${line:0:60}..."
        bad=1
      fi
    done < <(git -C "$ROOT" log -1 --format=%B "$sha")
  done
  return $bad
}

cd "$WT" || exit 2

step "ruff check" "ruff$EXE" check .
step "ruff format --check" "ruff$EXE" format --check .

if [ -d node_modules ]; then
  step "eslint" node_modules/.bin/eslint "weather_app/static/weather/js/*.js"
  # Same file set as the prettier pre-commit hook (all tracked js/json/css/md, minus lockfile/minified).
  mapfile -t PRETTIER_FILES < <(git ls-files '*.js' '*.json' '*.css' '*.md' | grep -v -E 'package-lock\.json|\.min\.(js|css)$')
  step "prettier --check" node_modules/.bin/prettier --check "${PRETTIER_FILES[@]}"
else
  echo "WARNING: node_modules missing (run 'npm install'); eslint and prettier were NOT run." >&2
  FAILED+=("eslint/prettier (node_modules missing)")
fi

step "file hygiene" "$PYTHON" scripts/check_hygiene.py
step "commit messages ($BASE..HEAD)" check_commit_messages
step "tests + 90% coverage" env PYTHONPATH="$WT/weather_app" DJANGO_SETTINGS_MODULE=config.settings \
  "$PYTHON" -m pytest tests -q -p no:cacheprovider --cov=weather --cov-fail-under=90

echo
echo "NOTE: detect-secrets and django-upgrade are checked only by CI (run on every PR)."
if [ ${#FAILED[@]} -eq 0 ]; then
  echo "ALL LOCAL LINT CHECKS PASSED"
  exit 0
fi
echo "FAILED: ${FAILED[*]}"
exit 1
