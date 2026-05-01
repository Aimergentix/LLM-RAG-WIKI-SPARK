#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PROJECT_FILE="${ROOT_DIR}/project.toml"

usage() {
  cat <<'EOF'
Usage:
  scripts/bump_version.sh [patch|minor|major]

Default:
  patch
EOF
}

if [[ ! -f "${PROJECT_FILE}" ]]; then
  echo "ERR_CONFIG: missing ${PROJECT_FILE}" >&2
  exit 2
fi

BUMP_TYPE="${1:-patch}"
case "${BUMP_TYPE}" in
  patch|minor|major) ;;
  -h|--help)
    usage
    exit 0
    ;;
  *)
    echo "ERR_CONFIG: bump type must be patch, minor, or major" >&2
    usage >&2
    exit 2
    ;;
esac

CURRENT_VERSION="$(
  sed -n 's/^version = "\([0-9]\+\.[0-9]\+\.[0-9]\+\)"$/\1/p' "${PROJECT_FILE}" | sed -n '1p'
)"

if [[ -z "${CURRENT_VERSION}" ]]; then
  echo "ERR_SCHEMA: could not read semantic version from [project].version" >&2
  exit 2
fi

IFS='.' read -r MAJOR MINOR PATCH <<< "${CURRENT_VERSION}"

case "${BUMP_TYPE}" in
  patch)
    PATCH=$((PATCH + 1))
    ;;
  minor)
    MINOR=$((MINOR + 1))
    PATCH=0
    ;;
  major)
    MAJOR=$((MAJOR + 1))
    MINOR=0
    PATCH=0
    ;;
esac

NEW_VERSION="${MAJOR}.${MINOR}.${PATCH}"
TODAY="$(date +%F)"
TMP_FILE="$(mktemp "${PROJECT_FILE}.tmp.XXXXXX")"
trap 'rm -f "${TMP_FILE}"' EXIT

set +e
awk \
  -v current_version="${CURRENT_VERSION}" \
  -v new_version="${NEW_VERSION}" \
  -v today="${TODAY}" '
BEGIN {
  updated_version = 0
  updated_date = 0
}
{
  if (!updated_version && $0 == "version = \"" current_version "\"") {
    print "version = \"" new_version "\""
    updated_version = 1
    next
  }
  if (!updated_date && $0 ~ /^date = "[0-9]{4}-[0-9]{2}-[0-9]{2}"$/) {
    print "date = \"" today "\""
    updated_date = 1
    next
  }
  print
}
END {
  if (!updated_version) {
    exit 10
  }
  if (!updated_date) {
    exit 11
  }
}
' "${PROJECT_FILE}" > "${TMP_FILE}"
AWK_STATUS=$?
set -e

case "${AWK_STATUS}" in
  0) ;;
  10)
    echo "ERR_SCHEMA: could not update semantic version in [project].version" >&2
    exit 2
    ;;
  11)
    echo "ERR_SCHEMA: could not update [release].date in ISO-8601 format" >&2
    exit 2
    ;;
  *)
    echo "ERR_RUNTIME: failed to rewrite ${PROJECT_FILE}" >&2
    exit 5
    ;;
esac

mv "${TMP_FILE}" "${PROJECT_FILE}"
trap - EXIT

echo "Version bumped: ${CURRENT_VERSION} -> ${NEW_VERSION}"
echo "Release date set: ${TODAY}"
