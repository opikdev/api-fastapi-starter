#!/usr/bin/env bash
# Fails when a committed migration was changed, deleted, or renamed, because migrations are
# append-only. Compares the working tree with the merge base of origin/main, or main.
set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")/.."

versions=src/app/migrations/versions

# Edits a reviewer approved, pinned to the file's Git blob hash. 0001 reads procrastinate's schema
# from a frozen copy instead of the installed package, and runs the same SQL as before.
approved=(
  "$versions/0001_init.py ccf9b759bdc939ab1cd0965c1d16b84ee056bf33"
)

base_ref=
for ref in origin/main main; do
  if git rev-parse --verify --quiet "$ref^{commit}" >/dev/null; then
    base_ref=$ref
    break
  fi
done
if [[ -z $base_ref ]]; then
  echo 'Migration check skipped: there is no origin/main or main to compare with'
  exit 0
fi

base=$(git merge-base "$base_ref" HEAD)
errors=0
while IFS=$'\t' read -r status path renamed_to; do
  case $status in
    A*) continue ;;
    M*)
      if printf '%s\n' "${approved[@]}" | grep -qxF "$path $(git hash-object "$path")"; then
        continue
      fi
      echo "Migration check: $path was changed" >&2
      ;;
    D*) echo "Migration check: $path was deleted" >&2 ;;
    R*) echo "Migration check: $path was renamed to $renamed_to" >&2 ;;
    *) echo "Migration check: $path has status $status" >&2 ;;
  esac
  errors=$((errors + 1))
done < <(git diff --name-status --find-renames "$base" -- "$versions")

if ((errors > 0)); then
  echo "Migrations are append-only. Restore them, and add a new revision for the change." >&2
  exit 1
fi
echo "Migration check passed against $base_ref"
