#!/usr/bin/env bash
# Deletes untagged GHCR package versions that have 0 downloads
# or whose last download was more than DAYS_OLD days ago.
#
# Usage:
#   ./scripts/cleanup-ghcr.sh [--dry-run] [--days 90]
#
# Requirements: gh CLI (authenticated)

set -euo pipefail

OWNER="actuarysailor"
PACKAGE="gha-repo-manager"
PACKAGE_TYPE="container"
DRY_RUN=false
DAYS_OLD=90

# Parse args
while [[ $# -gt 0 ]]; do
  case $1 in
    --dry-run) DRY_RUN=true; shift ;;
    --days) DAYS_OLD="$2"; shift 2 ;;
    *) echo "Unknown arg: $1"; exit 1 ;;
  esac
done

CUTOFF_EPOCH=$(date -d "-${DAYS_OLD} days" +%s 2>/dev/null || date -v-"${DAYS_OLD}"d +%s)

echo "Fetching untagged versions for ghcr.io/${OWNER}/${PACKAGE} ..."
echo "Will delete: 0 downloads OR last download > ${DAYS_OLD} days ago"
[[ "$DRY_RUN" == "true" ]] && echo "(DRY RUN — nothing will be deleted)"
echo ""

API_PATH="/users/${OWNER}/packages/${PACKAGE_TYPE}/${PACKAGE}/versions"

DELETED=0
SKIPPED=0

# Collect ALL versions first (all pages), then delete.
# Deleting while paginating shifts offsets and causes items to be skipped.
ALL_VERSIONS=""
PAGE=1
echo "Collecting all versions (paginating)..."
while true; do
  PAGE_JSON=$(gh api \
    --method GET \
    -H "Accept: application/vnd.github+json" \
    "${API_PATH}?per_page=100&page=${PAGE}" \
    2>/dev/null || true)

  PAGE_COUNT=$(printf '%s' "$PAGE_JSON" | python3 -c "
import sys, json
try:
    data = json.load(sys.stdin)
    print(len(data) if isinstance(data, list) else 0)
except Exception:
    print(0)
" 2>/dev/null || echo "0")

  [[ "$PAGE_COUNT" -eq 0 ]] && break

  # Append untagged entries as TSV lines
  PAGE_ROWS=$(printf '%s' "$PAGE_JSON" | python3 -c "
import sys, json
try:
    data = json.load(sys.stdin)
except Exception:
    sys.exit(0)
if not isinstance(data, list):
    sys.exit(0)
for v in data:
    tags = v.get('metadata', {}).get('container', {}).get('tags', [])
    if tags:
        continue
    print('\t'.join([
        str(v['id']),
        v.get('name', ''),
        str(v.get('download_count', 0)),
        v.get('updated_at', ''),
    ]))
" 2>/dev/null || true)

  if [[ -n "$PAGE_ROWS" ]]; then
    ALL_VERSIONS="${ALL_VERSIONS}"$'\n'"${PAGE_ROWS}"
  fi

  PAGE=$((PAGE + 1))
done
echo "Done collecting. Processing untagged versions..."
echo ""

# Now process all collected untagged versions
while IFS=$'\t' read -r ID NAME DOWNLOADS UPDATED_AT; do
  [[ -z "$ID" ]] && continue

  UPDATED_EPOCH=$(date -d "$UPDATED_AT" +%s 2>/dev/null || echo "0")
  IS_OLD=false
  [[ "$UPDATED_EPOCH" -lt "$CUTOFF_EPOCH" ]] && IS_OLD=true

  REASON="downloads=${DOWNLOADS}, updated=${UPDATED_AT}"

  if [[ "$DOWNLOADS" -eq 0 ]] || [[ "$IS_OLD" == "true" ]]; then
    if [[ "$DRY_RUN" == "true" ]]; then
      echo "  [DRY RUN] Would delete id=${ID} name=${NAME} (${REASON})"
      DELETED=$((DELETED + 1))
    else
      echo "  Deleting id=${ID} name=${NAME} (${REASON})"
      if gh api \
        --method DELETE \
        -H "Accept: application/vnd.github+json" \
        "${API_PATH}/${ID}" 2>/dev/null; then
        DELETED=$((DELETED + 1))
      else
        echo "  WARNING: Failed to delete id=${ID}"
      fi
    fi
  else
    echo "  Keeping id=${ID} name=${NAME} (${REASON})"
    SKIPPED=$((SKIPPED + 1))
  fi
done <<< "$ALL_VERSIONS"

echo ""
if [[ "$DRY_RUN" == "true" ]]; then
  echo "Dry run complete. Would delete ${DELETED} versions, keep ${SKIPPED}."
else
  echo "Done. Deleted ${DELETED} versions, kept ${SKIPPED}."
fi
