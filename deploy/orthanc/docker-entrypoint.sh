#!/bin/sh
# ─────────────────────────────────────────────────────────────────────────────
# Orthanc PACS archive — runtime configuration renderer (PACS Phase 1, Task 1.1)
#
# Generates the effective Orthanc JSON config from ORTHANC_* environment
# variables so that AE titles, ports, credentials and the modality allowlist
# live in .env / secrets — never in Git. See deploy/orthanc/orthanc-sample.json
# for a documented sample of the rendered shape.
#
# Set RUNTIME_CONFIG=0 to skip generation and use a mounted /etc/orthanc config
# (production pattern: permission-restricted mounted file).
# ─────────────────────────────────────────────────────────────────────────────
set -eu

if [ "${RUNTIME_CONFIG:-1}" != "1" ]; then
    echo "RUNTIME_CONFIG=0 — using mounted /etc/orthanc configuration as-is." >&2
    exec "$@"
fi

ORTHANC_NAME="${ORTHANC_NAME:-PulsaRIS-PACS}"
ORTHANC_AE_TITLE="${ORTHANC_AE_TITLE:-PULSAR_PACS}"
ORTHANC_DICOM_PORT="${ORTHANC_DICOM_PORT:-4242}"
ORTHANC_REST_PORT="${ORTHANC_REST_PORT:-8042}"
ORTHANC_DB_DIR="${ORTHANC_DB_DIR:-/var/lib/orthanc/db}"
ORTHANC_CONFIG_DIR="${ORTHANC_CONFIG_DIR:-${ORTHANC_DB_DIR}/ris-config}"
export ORTHANC_NAME ORTHANC_AE_TITLE ORTHANC_DICOM_PORT ORTHANC_REST_PORT ORTHANC_DB_DIR ORTHANC_CONFIG_DIR

# Service-to-service REST credentials (secrets; supplied via env only).
ORTHANC_RIS_USER="${ORTHANC_RIS_USER:?ORTHANC_RIS_USER must be set (no default secret)}"
ORTHANC_RIS_PASSWORD="${ORTHANC_RIS_PASSWORD:?ORTHANC_RIS_PASSWORD must be set (no default secret)}"
ORTHANC_ADMIN_USER="${ORTHANC_ADMIN_USER:-pacs-admin}"
ORTHANC_ADMIN_PASSWORD="${ORTHANC_ADMIN_PASSWORD:?ORTHANC_ADMIN_PASSWORD must be set (no default secret)}"
export ORTHANC_RIS_USER ORTHANC_RIS_PASSWORD ORTHANC_ADMIN_USER ORTHANC_ADMIN_PASSWORD

# Allowlisted senders (Task 1.2): comma-separated list of
#   "<AE Title>:<IPv4 address>"   e.g. "CT_01:10.20.0.11,MR_01:10.20.0.12"
# Empty list => no external sender is allowed to open associations (deny by
# default). Unknown calling AE titles/IPs are rejected at association time —
# the documented quarantine behavior (docs/PACS_IMPLEMENTATION.md §3).
ORTHANC_ALLOWED_SENDERS="${ORTHANC_ALLOWED_SENDERS:-}"

mkdir -p "${ORTHANC_CONFIG_DIR}"

python3 - <<'PYEOF'
import ipaddress
import json
import os
import re
import sys

ae_re = re.compile(r"^[A-Z0-9\-_]{1,16}$")

def build_peers(spec):
    peers = []
    for item in filter(None, (s.strip() for s in spec.split(","))):
        if ":" not in item:
            sys.exit(f"Invalid ORTHANC_ALLOWED_SENDERS entry {item!r}: expected 'AE:IP'")
        ae, _, host = item.rpartition(":")
        ae, host = ae.strip(), host.strip()
        if not ae_re.match(ae):
            sys.exit(f"Invalid AE title {ae!r} in ORTHANC_ALLOWED_SENDERS")
        try:
            ipaddress.IPv4Address(host)
        except ValueError:
            sys.exit(
                f"Invalid host {host!r} for sender {ae!r}: Orthanc peer allowlists "
                "require an IPv4 address (stable source IP per the trust-boundary "
                "review; hostname exceptions require a documented policy change)."
            )
        peers.append({"Name": ae, "IpAddress": host, "Port": 0})
    return peers

config = {
    "Name": os.environ.get("ORTHANC_NAME", "PulsaRIS-PACS"),
    # Dedicated PACS Storage SCP listener (separate AE/port from RIS_SCP MWL).
    "DicomAet": os.environ["ORTHANC_AE_TITLE"],
    "DicomPort": int(os.environ.get("ORTHANC_DICOM_PORT", "4242")),
    "HttpPort": int(os.environ.get("ORTHANC_REST_PORT", "8042")),
    # Reject unknown senders by default; approved modalities come from env.
    "AllowedPeers": build_peers(os.environ.get("ORTHANC_ALLOWED_SENDERS", "")),
    # Integrity: conflicting retransmission of same SOP UID surfaces, never
    # silently overwrites (plan Task 1.2 duplicate policy).
    "CheckIncomingIntegrity": True,
    # REST stays private: RemoteAccessAllowed=true means reachable from other
    # containers on the internal Docker network only (no host port mapping).
    # Auth required; TLS terminates at a reviewed reverse proxy if ever
    # exposed beyond the service network (plan Tasks 1.1/1.3).
    "RemoteAccessAllowed": True,
    "SSLEnabled": False,
    "AuthenticationEnabled": True,
    "RegisteredUsers": {
        os.environ["ORTHANC_RIS_USER"]: os.environ["ORTHANC_RIS_PASSWORD"],
        os.environ.get("ORTHANC_ADMIN_USER", "pacs-admin"): os.environ["ORTHANC_ADMIN_PASSWORD"],
    },
    # No remote script execution as a convenience (plan Task 1.3).
    "LuaScripts": [],
    # Phase 4 (Task 4.3): DICOMweb plugin for the embedded OHIF viewer. The
    # orthancteam/orthanc image ships the plugin pre-installed; enabling it
    # here exposes /dicom-web/ ONLY on the internal REST port, which has no
    # host mapping — the browser reaches it exclusively through the audited
    # Django proxy (pacs/dicomweb_proxy.py), never directly (plan §3).
    "Plugins": [
        "/usr/local/share/orthanc/plugins",
        "/usr/local/lib/orthanc/db"
    ],
    "EnableDICOMweb": True,
    "EnableOnlineDeployment": False,
    # Bounded operations pending representative load tests (Tasks 1.2/1.3).
    "MaxConcurrentConnections": int(os.environ.get("ORTHANC_MAX_CONCURRENT_CONNECTIONS", "16")),
    "LimitQueries": int(os.environ.get("ORTHANC_LIMIT_QUERIES", "512")),
    "LimitMetadata": int(os.environ.get("ORTHANC_LIMIT_METADATA_BYTES", str(16 * 1024 * 1024))),
    # Initial transfer-syntax set; extend ONLY after device conformance testing.
    "AcceptedTransferSyntaxes": [
        "1.2.840.10008.1.2",      # Implicit VR Little Endian
        "1.2.840.10008.1.2.1",    # Explicit VR Little Endian
        "1.2.840.10008.1.2.4.50", # JPEG Baseline
        "1.2.840.10008.1.2.4.51", # JPEG Extended
        "1.2.840.10008.1.2.4.70", # JPEG Lossless SVX1
    ],
    "StorageDirectory": os.environ.get("ORTHANC_DB_DIR", "/var/lib/orthanc/db"),
    "IndexDirectory": os.environ.get("ORTHANC_DB_DIR", "/var/lib/orthanc/db"),
}

out_dir = os.environ.get("ORTHANC_CONFIG_DIR", "/var/lib/orthanc/db/ris-config")
path = os.path.join(out_dir, "orthanc.json")
with open(path, "w") as fh:
    json.dump(config, fh, indent=2)
# Also keep a readable copy of the exact active shape next to the real config.
with open(os.path.join(out_dir, "orthanc-sample-rendered.json"), "w") as fh:
    redacted = json.loads(json.dumps(config))
    redacted["RegisteredUsers"] = {u: "<redacted>" for u in redacted["RegisteredUsers"]}
    json.dump(redacted, fh, indent=2)
print(f"Wrote Orthanc config to {path}", file=sys.stderr)
PYEOF

exec "$@"
