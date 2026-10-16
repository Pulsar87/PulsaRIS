#!/bin/sh
# ─────────────────────────────────────────────────────────────────────────────
# Orthanc PACS archive — liveness/readiness probe (PACS Phase 1, Task 1.1)
#
# Readiness = the DICOM/REST server is up AND answering authenticated queries.
# Uses only POSIX tools shipped in the orthancteam image (sh + curl), so it
# works without installing anything at runtime. Credentials come from the
# environment; never hardcode them. Exits non-zero (container unhealthy) when:
#   - REST API unreachable / not yet listening (startup), or
#   - authentication rejected (config drift), or
#   - Orthanc reports a database/storage error via /statistics.
# A brief PACS outage must NOT stop Django (web/celery have no depends_on on
# this service); the sync worker retries and surfaces the outage instead.
# ─────────────────────────────────────────────────────────────────────────────
set -eu

ORTHANC_REST_PORT="${ORTHANC_REST_PORT:-8042}"
BASE="http://127.0.0.1:${ORTHANC_REST_PORT}"

# 1) Core readiness: authenticated global statistics query.
stats=$(curl -fsS --max-time 5 \
    -u "${ORTHANC_RIS_USER:?}:${ORTHANC_RIS_PASSWORD:?}" \
    "${BASE}/statistics") || exit 1

# 2) The reply must be a JSON object from a healthy core DB (Orthanc returns
#    e.g. {"DBBackend":"...","DiskUsageBytes":...}; any HTTP error already
#    exited above). Guard against an empty/HTML body.
case "${stats}" in
    *"{"*"}"*) : ;;
    *) exit 1 ;;
esac

exit 0
