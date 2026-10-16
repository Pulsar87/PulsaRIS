# PulsaRIS PACS Implementation — Architecture Note (Phase 0)

**Prepared:** 2026-10-17
**Plan reference:** `PACS_plan.md` (PulsaRIS PACS Implementation Plan, 2026-10-16)
**Status:** Phase 0 — Repository reconnaissance and design freeze. No PACS code deployed yet.
**Review basis:** Static inspection of branch `qwen-code-4f8d27e0-fd75-4dde-b94b-a21226e8db9a` (identical tree to `main` at this point; no unmerged PACS/Orthanc code was found in the working tree or branches). Findings below are source observations, not runtime verification.

---

## 1. Current RIS workflows (Task 0.1 findings)

### 1.1 ExamOrder lifecycle and identifiers
- Model: `orders/models.py::ExamOrder`.
  - `accession_number`: `CharField(max_length=50)`, globally unique via constraint `unique_accession_number`. **It is supplied by the user in the order create/edit forms** (`orders/views.py`, ~lines 105–197 create, ~257–331 edit). There is **no server-side accession generator** today. Uniqueness is enforced only at the DB level (duplicate check + constraint).
  - `dicom_study_instance_uid`: `CharField(max_length=64, blank=True, db_index=True)`. **Nothing currently populates it** except manual/admin input; there is no generation code anywhere in the repository (verified by search). It is consumed read-only by `integrations/dicom/worklist.py` (`ds.StudyInstanceUID = order.dicom_study_instance_uid or ""`). Consequence: MWL items typically carry an empty Study Instance UID, so modalities generate their own UIDs and UID-based order matching will initially fail for most studies (see §5 matching policy and Task 3.2 gap).
  - Status flow enum: `REGISTERED → SCHEDULED → IN_PROGRESS → COMPLETED → REPORTED → FINALIZED / CANCELLED`. Soft delete via `is_deleted`/`deleted_at`.
  - Relations reused for PACS: `patient`, `facility` (FK to `core.Facility`, nullable), `modality`, `room_station` (FK to `core.Device`), `scheduled_datetime`. **No second order model will be created.**

### 1.2 Tenant/facility scoping
- The deployment is **single Postgres database, standard Django models — no schema routing** (`config/settings/base.py` line ~87 comment "no tenant routing"). Multi-site isolation is implemented as **row-level facility scoping**.
- Helpers: `clinic/permissions.py`
  - `accessible_facility_ids(user)` → set of Facility PKs (home `User.facility` + active non-expired `FacilityAssignment`; superuser → `None` = unrestricted).
  - `has_facility_access`, `facility_scope_queryset`, `role_required`, `facility_scoped_view`, `record_audit` / `record_audit_service` (writes to the `audit` app), and a DRF `FacilityScopedPermission`.
- All PACS views, reconciliation actions, background tasks, and retrieval endpoints **must** use these helpers (plan Global Instructions).

### 1.3 MWL attributes currently sent to modalities
Two implementations exist:
1. **Active SCP** — `core/management/commands/run_dicom_server.py` (pynetdicom; docker service `dicom-server`, port 11112, AE title `RIS_SCP`, configurable via CLI flags). Declares Verification, MWL C-FIND, and MPPS (N-CREATE/N-SET) contexts. Its worklist builder emits per item:
   - `PatientName`, `PatientID` (= `patient.mrn`), `PatientBirthDate`, `PatientSex`
   - Scheduled step: `Modality`, `ScheduledStationAETitle` (= `room_station.dicom_ae_title`), start date/time, `ScheduledProcedureStepDescription`, `ScheduledPerformingPhysicianName`
   - `ScheduledProcedureStepID` = accession (truncated 16), `AccessionNumber` = accession (truncated 16), `RequestedProcedureID` = procedure_code (truncated 16)
   - **It does NOT emit `StudyInstanceUID`** and **does NOT register a Storage SOP Class context or C-STORE handler** — this service is *not* an image archive and must not be described as one.
2. **Library helper** — `integrations/dicom/worklist.py` (push-style MWL; includes `StudyInstanceUID` from the order field when set). Not the docker-served path.

### 1.4 Report creation/finalization and DICOM SR export
- `reports/views.py::export_report_dicom()` (line ~420): exports FINAL/AMENDED reports as Basic Text SR (`1.2.840.10008.5.1.4.1.1.88.11`).
- **Confirmed defect (per plan §2):** it calls `generate_uid()` for `ds.StudyInstanceUID`, producing a brand-new study that is unrelated to the imaging study even when `order.dicom_study_instance_uid` exists. Fix is scheduled in Phase 5 (Task 5.1); no clinical report content changes.
- Minor observation to verify in Phase 5: the SR reads `report.order.tenant` which does not exist on `ExamOrder` (the FK is `facility`) — InstitutionName is therefore always empty.

### 1.5 Deployment, CI, migration, and test conventions
- `docker-compose.yml`: services `postgres:16-alpine`, `redis:7`, `web` (Django, `.env` file), `celery` (`celery -A config worker`), `dicom-server` (built from `Dockerfile.dicom`, python:3.11-slim, runs `run_dicom_server --host 0.0.0.0 --port 11112`). Named volumes `pgdata`, `redisdata`, `static_volume`. Health checks on postgres/web. Settings modules: `config/settings/{base,dev}.py`, env-driven via `django-environ` reading `.env`.
- Celery is configured (`CELERY_BROKER_URL=redis://redis:6379/1`) — the existing task convention for long-running work.
- Tests: per-app `tests.py` files (Django test runner pattern). Dependencies already include `pydicom==3.0.2`, `pynetdicom==3.0.4`. **`requests` is not currently in `requirements.txt`** (will be added in Phase 2 for the Orthanc adapter, or stdlib `urllib` used).
- `docs/IMPLEMENTATION_GAP_PLAN.md` (line ~292) already warns that worklist support ≠ PACS/archive/DICOMweb/retrieval. This note and future phase summaries will keep that inventory updated as features land.
- No existing PACS/Orthanc integration code was found on any branch in this repository snapshot (searched for `orthanc|pacs` across Python sources).

---

## 2. Selected architecture (design freeze)

Per plan §1 decisions 1–7:

- Django/RIS keeps clinical workflow ownership (patients, facilities, orders, reports, users, permissions, audit).
- **Orthanc** is the dedicated DICOM archive (Storage SCP, original objects, hierarchy, low-level retrieval). No image bytes in Django models/FileFields; Django stores only a metadata mirror with stable Orthanc resource IDs + DICOM UIDs.
- Existing MWL SCP (`run_dicom_server`, AE `RIS_SCP`, port 11112) is **preserved unchanged**; PACS gets its own AE title and port.
- C-STORE receipt ≠ clinical completion; states tracked separately (Phase 2 Task 2.3). No auto-link on PatientName/DOB alone. Storage Commitment deferred (not claimed).

### 2.1 Orthanc version/image and plugins
- **Pinned image (initial proposal, to be re-validated before production):** `orthancteam/orthanc:25.9.3` (tracks Orthanc server ≥ 1.12.7 with maintained plugins). Production deployments must pin an immutable digest, never `latest`.
- **Plugins expected in that image (record exact versions at deployment time):**
  - `DICOMweb` plugin (QIDO-RS/WADO-RS/STOW-RS) — enabled but **private to the internal network**; optional per plan (Phase 4 Task 4.3).
  - PostgreSQL plugin — **optional for production index** (see storage strategy below); not required for MVP staging.
  - Index-size monitoring available via built-in `/statistics`.
- Explicitly **not** enabled initially: Stone web viewer default, AWS, Lua scripting endpoints, plugin auto-load of anything else. Remote script execution stays disabled (plan Task 1.3).

### 2.2 AE Titles and ports
| Service | AE Title | Port | Exposure |
|---|---|---|---|
| PulsaRIS MWL SCP (existing) | `RIS_SCP` (unchanged, configurable via `--ae-title`) | 11112 (unchanged) | medical LAN/VPN only |
| Orthanc PACS archive (new) | `PULSAR_PACS` (example default; configurable via `ORTHANC_AE_TITLE`) | 4242 (configurable via `ORTHANC_DICOM_PORT`) | private Docker network; published only to LAN/VPN interface |
| Orthanc REST/DICOMweb | n/a | 8042 inside the `pacs` network; **not mapped to a host port by default** | internal Docker network only |
| PulsaRIS → Orthanc API calls | service user via HTTP basic auth | internal network | credentials from env/secrets only |

All values are environment-configurable (`ORTHANC_*` variables); the compose defaults above are development/staging values and must be finalized against the real deployment and device conformance statements before production.

### 2.3 Storage root, index strategy, volumes
- DICOM objects: named volume `orthanc-db` mounted at `/var/lib/orthanc/db` (persistent; a transient container layer is never acceptable). Development uses Orthanc's default filesystem store + local index.
- Production target pattern (plan Task 1.4): PostgreSQL-backed index in a **dedicated database and credentials** (separate from `ris_db`) plus the same persistent object volume; backup pair = object volume + index DB. To be load-tested before go-live; decision recorded here as *planned*, current compose implements the development arrangement.
- Original DICOM files are stored unmodified; no de-identification or transformation happens silently at ingestion.

### 2.4 Database strategy for the Django mirror
- New isolated app `pacs` (added to `INSTALLED_APPS`) with tables `PACSStudy` (+ series/instance mirrors evaluated in Phase 2 Task 2.1 — initial release may keep study-level rows only), a durable event/checkpoint table, and a reconciliation status field. Unique constraints on UIDs; validated UID syntax/length. Orthanc remains authoritative for objects; Django never reads Orthanc's private tables.

### 2.5 Rollout plan (summary of plan Task 6.5)
1. Develop against synthetic/de-identified studies + test archive volume (this repo, staging compose).
2. Staging deploy, full automated + manual DICOM interop tests (echoscu/storescu).
3. Pilot: one approved modality, one facility, documented cutover/rollback.
4. Validate capacity, retrieval, links, permissions, backup/restore, runbook.
5. Facility-by-facility rollout; daily review of ingest errors and reconciliation queue.
6. No real clinical traffic until security/clinical/privacy/backup sign-offs complete.

---

## 3. Facility/AE trust boundary (Task 0.2 design decision)

- **One shared archive instance serving multiple facilities is accepted**, with study ownership determined **exclusively by the trusted sender mapping**, never by arbitrary DICOM tags.
- Trust chain for an incoming association:
  1. Network layer: only allowlisted modality hosts on the private medical LAN/VPN can reach port 4242 (firewall + Docker network isolation). AE Title alone is *not* a cryptographic identity (plan decision).
  2. Application layer: calling AE Title must match an enabled `core.Device.dicom_ae_title`. **Proposed extension (Phase 1/2 implementation task):** enforce that the association's remote address matches that device's `dicom_host` (source-IP pinning); devices without a stable IP require a documented exception and review before being allowed to send.
  3. Ownership: `Device.facility` determines the facility/tenant attributed to every received study. Unknown calling AE titles, inactive devices, or IP mismatches → association rejected at the Orthanc peer allowlist level (unknown senders cannot even open C-STORE associations) and, if they somehow arrive, quarantined with `RECONCILIATION_REQUIRED` + audit event — never auto-assigned to a facility.
- Rejection behavior is documented and tested in Phase 1 acceptance ("Unauthorized/unknown sender tests fail in the documented way").
- Orthanc REST credentials are service-to-service secrets supplied via environment; never embedded in browser JavaScript or generated URLs (plan Task 1.3).

---

## 4. Known gaps carried into later phases (from reconnaissance)

| Finding | Classification | Phase |
|---|---|---|
| `run_dicom_server` has no Storage context/C-STORE handler (not an archive) | Confirmed by inspection (feature gap vs. PACS) | 1 |
| MWL responses omit StudyInstanceUID; order field never populated | Feature gap | 3 (Task 3.2) |
| Accession numbers are operator-supplied, uniqueness global | Verified behavior; matching rule 2 relies on it | 3 |
| `export_report_dicom()` invents a new StudyInstanceUID | Confirmed defect | 5 (Task 5.1) |
| SR export references `order.tenant` (nonexistent attribute) | Likely defect—verify | 5 |
| `requests` missing from requirements for REST adapter | Dependency note | 2 |

## 5. Next steps
Phase 0 acceptance gate: this note reviewed (security boundary + study ownership rules) **before any real modality is allowed to send data**. Then Phase 1 (deploy/harden Orthanc service, Storage SCP configuration, REST lockdown, storage/backup strategy) begins with concrete compose/config changes.
