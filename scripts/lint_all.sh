#!/usr/bin/env bash
# Pre-PR checks: the whole-repo lint CI runs on every push and pull request, plus the Django
# checks, tests with coverage, and the commit-message rules. Run before opening a PR:
#   bash scripts/lint_all.sh
#
# It checks the COMMITTED state (HEAD) in a temporary checkout with LF line endings, so results
# match CI even on Windows checkouts where core.autocrlf makes Prettier/ESLint report noise.
# Commit your changes first; uncommitted edits are not checked (the script warns if there are any).
#
# Covered: ruff check/format, ESLint, Prettier (same file set as the pre-commit hook), file hygiene
# (final newline, trailing whitespace, stored line endings, JSON/TOML/YAML), commit messages,
# `manage.py check --deploy`, `makemigrations --check`, tests with the 90% coverage gate and
# diff coverage >= 80%.
#
# NOT covered (CI runs them on every PR): detect-secrets and django-upgrade (they hang on the
# maintainer's Windows machine), the check-added-large-files / merge-conflict / case-conflict hooks,
# CodeQL, and the PR description check. If detect-secrets fails in CI, commit the .secrets.baseline
# diff shown in the log.
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
if ! git rev-parse --verify -q "$BASE" >/dev/null; then
  echo "ERROR: neither origin/master nor master exists, so commits and diff coverage cannot be checked." >&2
  exit 2
fi

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

# Conventional Commits as commitlint's config-conventional enforces them, with body lines up to
# 200 characters (commitlint.config.js). Applies to every commit the branch adds on top of BASE.
check_commit_messages() {
  local bad=0 sha subject desc line trailers
  local pattern='^(build|chore|ci|docs|feat|fix|perf|refactor|revert|style|test)(\([^)]+\))?!?: (.+)$'
  for sha in $(git -C "$ROOT" rev-list "$BASE..HEAD"); do
    subject=$(git -C "$ROOT" log -1 --format=%s "$sha")
    if ! [[ $subject =~ $pattern ]]; then
      echo "$sha: subject is not a Conventional Commit: $subject"
      bad=1
      continue
    fi
    desc=${BASH_REMATCH[3]}
    if [[ ${desc:0:1} =~ [A-Z] ]]; then
      echo "$sha: subject should not start with a capital letter (subject-case): $subject"
      bad=1
    fi
    if [[ $desc == *. ]]; then
      echo "$sha: subject should not end with a full stop (subject-full-stop): $subject"
      bad=1
    fi
    if [ ${#subject} -gt 100 ]; then
      echo "$sha: subject is longer than 100 characters"
      bad=1
    fi
    local lines=()
    while IFS= read -r line; do
      lines+=("${line%$'\r'}") # tolerate CRLF inside a message (commitlint does)
    done < <(git -C "$ROOT" log -1 --format=%B "$sha")
    if [ ${#lines[@]} -gt 1 ] && [ -n "${lines[1]}" ]; then
      echo "$sha: the line after the subject must be blank (body-leading-blank)"
      bad=1
    fi
    trailers=$(git -C "$ROOT" log -1 --format='%(trailers:only,unfold)' "$sha")
    for line in "${lines[@]}"; do
      if [ -n "$trailers" ] && [[ $trailers == *"$line"* ]] && [ -n "$line" ]; then
        if [ ${#line} -gt 100 ]; then
          echo "$sha: a footer line is ${#line} characters (max 100): ${line:0:60}..."
          bad=1
        fi
      elif [ ${#line} -gt 200 ]; then
        echo "$sha: a message line is ${#line} characters (max 200): ${line:0:60}..."
        bad=1
      fi
    done
  done
  return $bad
}

# Same settings the CI "Django system checks" and "missing migrations" steps use.
django_checks() {
  (
    cd weather_app || exit 1
    export DJANGO_ALLOWED_HOSTS=testserver
    export DJANGO_SECRET_KEY=ci-check-6Dkq9mR2xV7pL4sN8wH3bF5jT1yC0eG9aK6uQ2zX7vM4rP8
    "$PYTHON" manage.py check --deploy && "$PYTHON" manage.py makemigrations --check --dry-run
  )
}

cd "$WT" || exit 2

step "ruff check" "ruff$EXE" check .
step "ruff format --check" "ruff$EXE" format --check .

if [ -d node_modules ]; then
  step "eslint" node_modules/.bin/eslint "weather_app/static/weather/js/*.js"
  # Same file set as the prettier pre-commit hook (all tracked js/json/css/md, minus lockfile/minified).
  # A read loop instead of mapfile so this also runs on the bash 3.2 that ships with macOS.
  PRETTIER_FILES=()
  while IFS= read -r f; do
    PRETTIER_FILES+=("$f")
  done < <(git ls-files '*.js' '*.json' '*.css' '*.md' | grep -v -E 'package-lock\.json|\.min\.(js|css)$')
  step "prettier --check" node_modules/.bin/prettier --check "${PRETTIER_FILES[@]}"
else
  echo "WARNING: node_modules missing (run 'npm install'); eslint and prettier were NOT run." >&2
  FAILED+=("eslint/prettier (node_modules missing)")
fi

step "file hygiene" "$PYTHON" scripts/check_hygiene.py
step "commit messages ($BASE..HEAD)" check_commit_messages
step "django check --deploy + makemigrations --check" django_checks
step "tests + 90% coverage" env PYTHONPATH="$WT/weather_app" DJANGO_SETTINGS_MODULE=config.settings \
  "$PYTHON" -m pytest tests -q -p no:cacheprovider --cov=weather --cov-fail-under=90 --cov-report=xml:cov.xml
step "diff coverage >= 80% vs $BASE" "diff-cover$EXE" cov.xml --compare-branch="$BASE" --fail-under=80

echo
echo "NOTE: detect-secrets and django-upgrade (and CodeQL) are checked only by CI, on every PR."
if [ ${#FAILED[@]} -eq 0 ]; then
  echo "ALL LOCAL LINT CHECKS PASSED"
  exit 0
fi
echo "FAILED: ${FAILED[*]}"
exit 1
