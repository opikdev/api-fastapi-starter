#!/usr/bin/env bash
# Fails when `make client` changed openapi.json or clients/python, because they must be committed
# with the route change that changed them. `make check-generated` regenerates them, then runs this.
set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")/.."

paths=(openapi.json clients/python)
changed=$(git diff --name-only -- "${paths[@]}")
# Once the generated files are tracked, a new untracked file means a commit would miss it.
if git ls-files --error-unmatch openapi.json >/dev/null 2>&1; then
  changed+=$'\n'$(git ls-files --others --exclude-standard -- "${paths[@]}")
fi
changed=$(sed '/^$/d' <<<"$changed")

if [[ -n $changed ]]; then
  echo "make client changed these files, so they were out of date or aren't staged:" >&2
  echo "$changed" >&2
  echo "Review the changes, then stage them with: git add openapi.json clients/python" >&2
  exit 1
fi
echo "openapi.json and clients/python are up to date"
