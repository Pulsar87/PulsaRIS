# PACS Operations Runbook — Orthanc Archive (PACS Phase 1)

Scope: the `orthanc` Docker Compose service added in Phase 1 (Task 1.1) and its
planned follow-ups (Tasks 1.2–1.4). Architecture/trust-boundary rationale lives
in `docs/PACS_IMPLEMENTATION.md`; this file is the operational counterpart.
**Status: deployment configuration delivered; live acceptance (C-ECHO/C-STORE
against a running container, restart persistence, unauthorized-sender tests)
must be executed in the target environment before any real modality sends data.**

---

## 1. Services, volumes, ports, credentials

| Item | Value | Source of truth |
|---|---|---|
| Archive image (pinned) | `orthancteam/orthanc:25.9.3` | `docker-compose.yml` (`orthanc` service). Production must additionally pin the immutable digest `@sha256:...`. Record active plugin versions at deploy time (`GET /` and `/plugins` on the REST API). |
| PACS AE Title | `PULSAR_PACS` (env `ORTHANC_AE_TITLE`) | DICOM Storage SCP for modalities |
| DICOM storage port | `4242` (env `ORTHANC_DICOM_PORT`) | Published host interface via `ORTHANC_DICOM_BIND_IP` — **default `127.0.0.1`**; bind to the medical LAN/VPN interface only after the firewall review |
| MWL SCP (unchanged) | AE `RIS_SCP`, port `11112` | `dicom-server` service — do not conflate with PACS |
| REST/DICOMweb | `8042` inside the private `pacs` network only | **No host port mapping by design.** Never expose publicly (plan §1.7). |
| Object storage + index | named volume `orthanc-db` → `/var/lib/orthanc/db` | persistent; transient layers are never acceptable |
| Runtime config | rendered at start into `${ORTHANC_DB_DIR}/ris-config/orthanc.json` from env | entrypoint `deploy/orthanc/docker-entrypoint.sh`; sample shape: `deploy/orthanc/orthanc-sample.json`; redacted copy kept as `orthanc-sample-rendered.json` |
| Credentials | `ORTHANC_RIS_USER/PASSWORD` (service-to-service), `ORTHANC_ADMIN_USER/PASSWORD` | `.env` / secrets manager only — no real values in Git, compose, docs, or commands |
| Approved senders | `ORTHANC_ALLOWED_SENDERS="AE:IPv4,AE:IPv4"` | built from `core.Device` rows (`dicom_ae_title` + `dicom_host`). **Empty = deny all** (documented default policy) |

Django reads the same identifiers via settings `PACS_ORTHANC_*`
(`config/settings/base.py`); `ORTHANC_API_URL=http://orthanc:8042` works only
for containers attached to the `pacs` network (`web`, `celery`).

## 2. Start / stop / status

```bash
docker compose up -d orthanc          # archive only (starts independently)
docker compose ps                     # orthanc should reach "healthy"
docker compose logs --since 10m orthanc
```

- Health check (`deploy/orthanc/healthcheck.sh`): authenticated `GET /statistics`
  over localhost inside the container; unhealthy if REST is down, auth fails,
  or the reply isn't JSON. Interval 15s, start_period 30s.
- **Django does not depend on Orthanc**: `web`/`celery` start normally when the
  archive is down (outage surfaced by the sync worker's retries/errors once
  Phase 2 lands; nothing is marked successful during an outage).

## 3. Onboarding a modality (procedure)

1. Register the device in RIS (`core.Device`): `dicom_ae_title`, stable
   `dicom_host` (IPv4), facility, `is_active=True`. Devices without a stable IP
   need a documented exception review (trust boundary §3 of the architecture note).
2. Add `"AE:IP"` to `ORTHANC_ALLOWED_SENDERS` in `.env`/secrets and
   `docker compose up -d orthanc` (config re-renders at start). Unknown AE/IP →
   association rejected (deny-by-default; tested behavior, see §7).
3. Configure the device: worklist → `RIS_SCP@<ris-host>:11112`; images →
   `PULSAR_PACS@<pacs-host>:4242`.
4. Interoperability test (synthetic/de-identified data only):
   ```bash
   echoscu  <pacs-host> 4242 -aet <DEVICE_AE> -aec PULSAR_PACS     # expect acceptance
   storescu <pacs-host> 4242 -aet <DEVICE_AE> -aec PULSAR_PACS test.dcm
   ```
   Verify against the device's conformance statement; extend
   `AcceptedTransferSyntaxes` in the entrypoint **only** for syntaxes validated
   end-to-end (do not claim untested support).
5. Record the result (SOP classes, transfer syntaxes, instance counts) in the
   pilot log before production routing.

## 4. Backup (pair — object store AND index)

Development/staging layout (filesystem store + local index, both under
`orthanc-db`) is backed up as one unit; consistent snapshot procedure:

```bash
docker compose stop orthanc
docker run --rm -v <project>_orthanc-db:/db -v $(pwd)/backups:/out alpine \
  tar czf /out/orthanc-db-$(date +%Y%m%dT%H%M%SZ).tar.gz -C /db .
docker compose start orthanc
```

- Backing up only Django/PostgreSQL, or only half of the Orthanc volume, is
  insufficient (plan Task 1.4). Include `.env`/secrets recovery process.
- When the production PostgreSQL-index arrangement is adopted (dedicated DB +
  credentials, separate from `ris_db`), back up the index DB and the object
  volume **as a timed pair** and re-test this section.
- Retention/legal hold/purge require clinical+legal sign-off; no automatic purge.

## 5. Restore drill (execute in non-production first)

1. Stop `orthanc`; restore the tarball into a fresh `orthanc-db` volume.
2. Start; wait for `healthy`.
3. Verify: study/series/instance counts (`GET /studies`, `/statistics`),
   retrieve sample original objects (`GET /instances/<id>/file`), compare
   checksums/UIDs against the pre-backup inventory, confirm the DICOM mirror
   can be rebuilt/reconciled (Phase 2 replay command once available).
4. Log date, operator, results. Re-run after every storage/index change.

## 6. Disk capacity & alerting

- Monitor free space on the `orthanc-db` volume host path; Orthanc reports
  `DiskUsageBytes` via `GET /statistics`. Define site thresholds from
  representative volume measurements (not invented numbers) — e.g. warn before
  ingest failures occur; Orthanc refuses new stores when the disk is full,
  which must page, not pass silently.
- Capacity planning per facility before widening `ORTHANC_ALLOWED_SENDERS`.

## 7. Failure modes & expected behavior

| Scenario | Expected behavior |
|---|---|
| Unknown calling AE / non-allowlisted IP | Association rejected by Orthanc peer allowlist (deny-by-default). Documented + must be tested (§Phase-1 acceptance). |
| Empty `ORTHANC_ALLOWED_SENDERS` | Nobody may send; RIS features still function. |
| Same SOP Instance UID retransmitted, identical content | Idempotent; no duplicate objects (`CheckIncomingIntegrity` on). |
| Same SOP Instance UID, different content | Rejected/surfaced by integrity checks — never silent overwrite. |
| Orthanc down | Health check goes unhealthy; Django/Celery unaffected; sync jobs retry (Phase 2); operators alerted via container health. |
| OHIF shows “Sorry, this page does not exist” | Use the OHIF route `/pacs/viewer/<StudyInstanceUID>`; do not nest the RIS study UUID in the OHIF path. `/pacs/viewer?studyInstanceUIDs=<StudyInstanceUID>` is accepted and redirects to the native route. Both resolve only studies visible to the signed-in user's facility. |
| OHIF DICOMweb request returns Orthanc `404 Unknown resource` | Confirm `GET /plugins` lists DICOMweb and authenticated `GET /dicom-web/studies` works from the private network. The runtime config must define `DicomWeb: { "Enable": true, "Root": "/dicom-web/" }`; restart Orthanc after changing the entrypoint/config. |
| Container recreation | Data persists on `orthanc-db`; verify counts after recreate. |
| Missing secret env vars | Compose/entrypoint fail fast with a clear message (no default credentials anywhere). |

## 8. Credential rotation

1. Generate new value in the secrets manager.
2. Update `.env` (`ORTHANC_RIS_PASSWORD` / `ORTHANC_ADMIN_PASSWORD`).
3. `docker compose up -d orthanc` (config re-rendered) and update the Django
   side settings source; verify `healthcheck` returns healthy (auth failure ⇒
   unhealthy ⇒ caught immediately).

## 9. Outage troubleshooting quick list

`docker compose ps` (health?) → `docker compose logs orthanc` → exec probe
manually: `docker compose exec orthanc sh /opt/ris-orthanc/healthcheck.sh` →
check volume mount/disk space → restart `orthanc` alone (safe: stateless
process over persistent volume). For OHIF `404 Unknown resource` responses,
verify the DICOMweb plugin is listed by `GET /plugins` and that
`/dicom-web/studies` responds from within the private network; then restart
Orthanc so its runtime config is regenerated. Escalate with restore drill §5
if the archive is corrupted.

## 10. Pending before production (honest status)

- Tasks 1.2–1.4 hardening items that require a live environment: sender
  rejection tests, transfer-syntax conformance per device, load-tested limits,
  executed backup/restore drill, disk encryption/permissions review, TLS/reverse
  proxy decision if REST is ever exposed beyond the service network.
- Phase 2 sync worker will consume `PACS_ORTHANC_*` settings; until then the
  archive receives but Django does not yet mirror studies (feature gap tracked
  in `docs/IMPLEMENTATION_GAP_PLAN.md`).
