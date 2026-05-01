#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
TEMPLATE_PATH="${ROOT_DIR}/START-PROMPT.md"

usage() {
  cat <<'EOF'
Usage:
  scripts/run_phase.sh --phase <P1|P2|P3|P4|P5> --go <yes|no> [--scope "<text>"] [--deliverables "<text>"]
EOF
}

escape_sed_replacement() {
  printf '%s' "$1" | sed -e 's/[&|\\]/\\&/g'
}

PHASE=""
GO_VALUE=""
SCOPE="current requested scope only"
DELIVERABLES="only artifacts allowed in approved phase"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --phase) PHASE="${2:-}"; shift 2 ;;
    --go) GO_VALUE="${2:-}"; shift 2 ;;
    --scope) SCOPE="${2:-}"; shift 2 ;;
    --deliverables) DELIVERABLES="${2:-}"; shift 2 ;;
    -h|--help) usage; exit 0 ;;
    *) echo "ERR_CONFIG: unknown argument: $1" >&2; usage >&2; exit 2 ;;
  esac
done

if [[ -z "${PHASE}" || -z "${GO_VALUE}" ]]; then
  echo "ERR_CONFIG: --phase and --go are required" >&2
  usage >&2
  exit 2
fi

case "${PHASE}" in
  P1|P2|P3|P4|P5) ;;
  *) echo "ERR_CONFIG: --phase must be P1, P2, P3, P4, or P5" >&2; exit 2 ;;
esac

case "${GO_VALUE}" in
  yes|no) ;;
  *) echo "ERR_CONFIG: --go must be yes or no" >&2; exit 2 ;;
esac

if [[ ! -f "${TEMPLATE_PATH}" ]]; then
  echo "ERR_INDEX_MISSING: template not found at ${TEMPLATE_PATH}" >&2
  exit 3
fi

ESC_PHASE="$(escape_sed_replacement "${PHASE}")"
ESC_GO_VALUE="$(escape_sed_replacement "${GO_VALUE}")"
ESC_SCOPE="$(escape_sed_replacement "${SCOPE}")"
ESC_DELIVERABLES="$(escape_sed_replacement "${DELIVERABLES}")"

sed \
  -e "s|{{PHASE}}|${ESC_PHASE}|g" \
  -e "s|{{GO}}|${ESC_GO_VALUE}|g" \
  -e "s|{{SCOPE}}|${ESC_SCOPE}|g" \
  -e "s|{{DELIVERABLES}}|${ESC_DELIVERABLES}|g" \
  "${TEMPLATE_PATH}"
