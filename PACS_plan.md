RaqeemRIS PACS Implementation Plan
Goal: Add reliable DICOM reception, durable study storage, indexing, RIS-order reconciliation, and a safe path to study retrieval in the existing Django RIS.
Target repository: Raqeem87/RaqeemRIS
Prepared: 2026-10-16
Plan type: Step-by-step instructions for an AI coding agent
Review status: Static repository inspection only. Confirm implementation details with tests and deployment configuration; do not assume that existing features are production-ready.
1. Non-negotiable architecture decisions
1. Keep Django/RIS responsible for clinical workflow. Patients, facilities/tenants, exam orders, reporting, users, permissions, and audit history remain in RaqeemRIS.
2. Use a dedicated DICOM archive service, preferably Orthanc, for PACS storage and DICOM networking. It should accept incoming DICOM C-STORE associations and own the original DICOM objects, storage lifecycle, DICOM resource hierarchy, and low-level DICOM retrieval. Do not implement a full PACS archive from scratch inside Django or store image bytes in ordinary Django model/FileField rows.
3. Keep the current Modality Worklist (MWL) service. It serves a different purpose from image reception. Do not remove or silently replace core/management/commands/run_dicom_server.py or its existing MWL behavior. Keep the current MWL endpoint/port configurable and introduce a separate, documented PACS AE Title and storage port for Orthanc.
4. Treat the archive as the source of truth for DICOM objects. Django may keep a small metadata/index mirror for work queues, search, and order linking, but it must store stable archive IDs and DICOM UIDs—not duplicate the binary objects or directly query Orthanc's private database tables.
5. A successful C-STORE is not the same as the study being clinically complete or formally storage-committed. Track instance receipt, reconciliation, and workflow completion as distinct states. Implement DICOM Storage Commitment only if a device/vendor workflow requires it; document the actual supported behavior.
6. Do not auto-link a study to a patient/order based only on patient name or date of birth. Prefer an exact Study Instance UID or a carefully validated combination of facility context, accession number, and Patient ID/MRN. Ambiguous data must go to a reconciliation queue.
7. Do not expose the Orthanc administrative REST API to the public Internet. DICOM and REST network access, authentication, permissions, encryption, backup, and retention must be handled explicitly before production use with real PHI.
Recommended service layout
CT / MR / DX / US / Other DICOM Modality
       | C-ECHO / C-STORE (restricted medical LAN or VPN)
       v
Orthanc PACS Archive (dedicated AE + storage port; persistent DICOM volume)
       | internal REST API / changes feed; DICOMweb optional
       v
RaqeemRIS PACS integration worker (idempotent metadata synchronization)
       |
       +--> PACS study/series/instance metadata mirror in Django/PostgreSQL
       +--> Match Study UID / accession / Patient ID to ExamOrder
       +--> Unmatched/ambiguous study reconciliation work queue
       +--> Study list and archive status in RIS UI

Existing modality MWL queries continue to go to the existing RaqeemRIS MWL SCP.
Suggested initial network configuration: Keep the existing RaqeemRIS MWL server on its configured port (currently documented as 11112) and configure a separate Orthanc PACS AE Title and storage port (commonly 4242, but make it configurable). Do not publish Orthanc HTTP/REST (commonly 8042) on a public host port. Use a private Docker network and explicit firewall rules. Production ports must be finalized against the actual deployment and device configuration.
2. Existing repository findings to account for
These are observations from source inspection, not runtime verification.
- core/management/commands/run_dicom_server.py is a pynetdicom server that declares Verification, Modality Worklist C-FIND, and MPPS contexts/handlers. The inspected code does not register a Storage SOP Class context or a C-STORE handler. Do not call this an image archive today.
- DICOM_SERVER.md documents the current MWL server and currently discusses it as a worklist service. Update the document so readers can distinguish MWL from PACS storage.
- Dockerfile.dicom and the dicom-server service in docker-compose.yml already exist. Extend deployment without breaking the current service or conflating the MWL and PACS AE Titles.
- orders/models.py includes ExamOrder.dicom_study_instance_uid, and ExamOrder already has accession number, patient, modality, facility, status, and station relationships. Reuse these fields after verifying their lifecycle and uniqueness requirements; do not make a second independent order model.
- reports/views.py contains export_report_dicom(). The current implementation generates a new StudyInstanceUID for the exported SR. Review and correct this as part of DICOM/report interoperability so a report is linked to the actual imaging study when one exists. Do not change a finalized report's clinical content as a side effect of PACS integration.
- docs/IMPLEMENTATION_GAP_PLAN.md already warns that worklist support does not imply PACS/image archive, storage SCP, DICOMweb, or image retrieval. Keep the new plan consistent with that inventory and update it when features are delivered.
- requirements.txt already includes pydicom and pynetdicom. Their presence alone does not mean C-STORE reception, durable archive behavior, transfer-syntax interoperability, or retrieval have been implemented.
Before coding, inspect the current default branch, settings modules, tenant/schema behavior, permission helpers, audit models, Docker conventions, migrations, existing PACS-related changes, and exact report export code. If the repository has changed since this plan was prepared, adapt the plan and report each changed assumption.
3. Scope and staged delivery
MVP included in this plan
- A dedicated, persistent DICOM archive endpoint receives studies from configured modalities via C-STORE.
- A trusted background integration syncs received resources into Django metadata tables.
- A study is matched to an existing RIS order when matching is unambiguous; unmatched/ambiguous studies are visible to authorized staff for manual reconciliation.
- RIS users can view the received study list, study details, series/instance counts, ingest status, and linkage to the RIS order.
- The archive and metadata synchronization survive restarts, duplicate sends, temporary outages, and worker retries.
- Tests, monitoring, backup/restore procedures, and deployment/security documentation are provided.
Explicitly defer unless separately approved
- A full in-browser diagnostic viewer and advanced viewing tools.
- Advanced hanging protocols, measurements, annotations, and diagnostic display qualification.
- Cross-facility federation and cloud/off-site routing.
- Automated image processing or AI inference.
- Vendor-specific routing and workflow logic not required for initial reception.
- DICOM Storage Commitment, MPPS completion integration, and HL7/FHIR reconciliation beyond the existing project behavior, unless a target modality or clinical workflow requires them.
Use DICOMweb (QIDO-RS for query, WADO-RS for retrieval, STOW-RS for web storage) as an optional standards-based path for a later web viewer or web integrations. C-STORE remains the initial modality-to-archive storage path.
Phase 0 — Repository reconnaissance and design freeze
Task 0.1 — Map the current RIS workflows
- Trace ExamOrder creation/editing and the code that generates accession_number and dicom_study_instance_uid.
- Trace tenant/facility scoping in the database and clinic.permissions helpers. Determine how an incoming calling AE/IP maps to exactly one facility/tenant.
- Trace DICOM MWL attributes currently sent to modalities, especially Patient ID, Accession Number, Requested Procedure ID, Study Instance UID, Scheduled Station AE Title, modality, and procedure description.
- Trace report creation/finalization and export_report_dicom().
- Inspect current Docker Compose, environment variable conventions, health checks, logging, CI, migration, and test patterns.
- Search for existing unmerged/branch code for PACS/Orthanc before implementing duplicate functionality.
Deliverable: Add a short architecture note to docs/PACS_IMPLEMENTATION.md describing current behavior, assumptions, selected Orthanc version/image and required plugins, AE Titles, ports, storage root, database strategy, tenant/facility mapping, and rollout plan.
Task 0.2 — Decide the facility/AE trust boundary
- Create or extend a configuration model/setting mapping each approved modality's calling AE Title and network identity to an authorized facility and allowed operations.
- AE Title alone is not a cryptographic identity; enforce network allowlisting as well. Document whether modalities have stable source IPs and whether the network is private/VPN.
- Decide whether one archive serves one tenant or multiple facilities. For multi-facility use, never trust arbitrary DICOM tags to choose the tenant.
- Define how unknown calling AE Titles, unknown facilities, inactive devices, and source-IP mismatches are rejected or quarantined.
Acceptance: The security boundary and study ownership rules are reviewed before any real modality is allowed to send data.
Phase 1 — Deploy and harden the DICOM archive
Task 1.1 — Add Orthanc as a separate service
- Pin an approved Orthanc container/image version; do not use an unpinned latest tag in production.
- Prefer an image containing the required maintained plugins, but record exactly which plugins and versions are active.
- Add an orthanc/pacs service to docker-compose.yml or the production deployment manifests. Keep it separate from Django/Gunicorn/Celery and from the existing MWL server process.
- Configure dedicated values via environment/secrets or a mounted, permission-restricted config file: archive name, AE Title, DICOM port, storage directory, index strategy, REST settings, accepted modalities, limits, and logging.
- Add a persistent volume for original DICOM storage and a persistent/managed index database. A transient container layer is never acceptable for clinical images.
- Add a health check that verifies the PACS service is ready; ensure Django can start even if PACS is briefly unavailable, while clearly surfacing the outage and queuing/retrying sync jobs.
- Keep the Orthanc REST API accessible only on the internal Docker network or localhost unless a reviewed reverse-proxy/authentication design requires otherwise. Do not map port 8042 publicly by default.
- Do not reuse the Django database schema as an undocumented dependency. If using PostgreSQL for Orthanc's index, use a dedicated database and credentials. A common production pattern is a PostgreSQL-backed index plus filesystem/NAS storage for DICOM objects; test the chosen storage/index backup strategy as a pair.
Task 1.2 — Configure Storage SCP / modality access
- Configure the archive's DICOM listener with a unique PACS AE Title (example only: RAQEEM_PACS) and a configurable private-network port (commonly 4242).
- Explicitly configure the known modalities: calling AE Title, IP/host, called AE Title, and facility/device mapping.
- Enable C-ECHO and C-STORE for approved senders; reject unknown senders according to the selected security policy. Do not leave permissive “unknown modality” behavior without a documented and tested reason.
- Start with the transfer syntaxes required by the connected devices and validate each device's conformance statement. Do not claim support for every DICOM SOP Class/transfer syntax without testing.
- Configure maximum request/resource sizes, network timeouts, concurrent associations, query limits, and storage thresholds based on representative tests.
- Choose the duplicate/overwrite policy deliberately. Never silently overwrite a stored instance solely because the incoming SOP Instance UID matches. Define behavior for same UID/same content and same UID/different content; retain audit evidence for conflicts.
- If approved modalities require encrypted DICOM transport, configure DICOM TLS only where supported and tested by both peers. Otherwise require isolated private networks/VPN and firewall restrictions; never expose an unencrypted DICOM listener directly to the public Internet.
Task 1.3 — Secure Orthanc REST and DICOMweb surfaces
- Keep REST and DICOMweb private to the service network by default.
- If REST access is enabled outside localhost, require authentication, HTTPS at the service/reverse-proxy boundary, strong credentials stored outside source control, restricted host/proxy settings, and least-privilege network access.
- Do not use an administrator account/password in browser JavaScript or embed it in generated viewer URLs.
- Disable unneeded management/script endpoints and features; especially do not enable remote script execution as a convenience.
- Use explicit request timeouts and bounded query results. Never permit arbitrary remote users to perform unrestricted searches, export, or delete operations.
- Treat DICOMweb as a separate optional API surface; configure authentication and HTTPS before exposing it to users or external networks.
Task 1.4 — Storage strategy and recovery
- Development may use Orthanc's default local index and filesystem store on persistent volumes. Production must use a deliberately selected and load-tested index/storage arrangement.
- Store original DICOM files without modifying pixel data or clinical tags. Any de-identification or transformation must be an explicit separate workflow, never a silent ingestion side effect.
- Use disk encryption and appropriate file/system permissions. Define storage capacity and alert thresholds.
- Back up the object storage and index in a consistent, documented way. Backing up only Django/PostgreSQL or only Orthanc's index is insufficient.
- Write and execute a restore drill: restore the archive, confirm study/series/instance counts, retrieve sample original objects, verify checksums, and confirm Django's mirror can be rebuilt/reconciled.
- Define retention, legal hold, archive deletion, and purge authorization with clinical/legal owners. Do not build automatic purge based only on age or database soft-delete flags.
Phase 1 acceptance criteria
- Orthanc starts reliably with persistent storage after container recreation.
- Only the intended private peers can reach the DICOM listener and REST API.
- An approved test sender can C-ECHO and C-STORE a test study; a restarted service can still query and retrieve its objects.
- Unauthorized/unknown sender tests fail in the documented way.
- The operations/backup runbook documents volumes, credentials, ports, storage alerting, and tested restore steps.
Phase 2 — Synchronize archived study metadata into Django
Task 2.1 — Define metadata models and migration strategy
Add a pacs Django app or a similarly isolated integration module. Keep binary DICOM files outside Django. At minimum, decide whether the RIS needs these metadata models:
- PACSStudy: unique StudyInstanceUID; archive resource ID; tenant/facility association; optional matched ExamOrder; Patient ID/MRN as received; Accession Number; Study Date/Time; Study Description; referring physician when present; modality summary; study status; received/last-updated timestamps; counts; and reconciliation status/reason.
- PACSSeries: unique SeriesInstanceUID; foreign key to study; archive series/resource ID; Modality; Series Number/Description; instance count and received timestamps.
- PACSInstance: unique SOPInstanceUID; foreign key to series; archive instance/resource ID; SOP Class UID; transfer syntax if available; byte size/checksum if returned or computed safely; received timestamp and ingest/index status.
Use unique constraints and indexes on UIDs, accession number, matched order, facility/tenant, status, and time fields as justified by search patterns. Enforce the DICOM UID field length correctly and validate UID syntax. A UID is an identifier, not proof that the demographic data are correct.
Important modeling rule: Study/series/instance rows are a lightweight application metadata mirror. Orthanc remains the authoritative archive for actual objects. Do not duplicate all DICOM tags into relational columns without a concrete use case. Do not directly read or mutate Orthanc's private tables.
Review whether series and instance mirrors are essential for the first release. If a single study row plus authoritative Orthanc IDs can meet the immediate scope, keep the initial schema smaller and make expansion explicit. Do not create a redundant schema merely to mirror every archive table.
Task 2.2 — Implement an idempotent synchronization worker
- Use the Orthanc REST API/changes feed or another documented supported event integration to detect new stored instances/resources. Do not scrape logs or depend on the archive's private database schema.
- Add a durable checkpoint/cursor or event table so worker restarts do not lose events. Process events at least once and make every handler idempotent.
- Retrieve trusted metadata from Orthanc by its internal resource ID; validate required UIDs before writing the Django mirror. Do not trust an arbitrary browser/client to post its own claimed archive IDs or metadata.
- Update study/series/instance records with update_or_create/transaction-safe equivalents and database uniqueness constraints. Handle out-of-order arrival and concurrent events.
- Retry transient failures with bounded exponential backoff. Preserve failed jobs and error categories for operational review; do not silently swallow exceptions.
- The worker should tolerate the archive being temporarily down, metadata temporarily unavailable, or a duplicate notification. Reconciliation/replay commands must be available to rebuild the mirror from the archive after a missed event or deployment failure.
- Log event IDs, archive resource IDs, UID references where operationally necessary, duration, and result; avoid logging patient names, birth dates, full DICOM payloads, or more PHI than needed.
Task 2.3 — Define archive and study lifecycle states
Use explicit, documented states, for example:
- RECEIVED / INDEXED: one or more DICOM instances exist in the archive and metadata has synced.
- RECONCILIATION_REQUIRED: study exists, but patient/order/facility cannot be linked safely or conflicting identifiers exist.
- SYNC_ERROR: archived resource exists but application metadata synchronization needs attention.
- AVAILABLE: study is indexed and authorized users can retrieve it.
- Optional ARCHIVE_VERIFIED or STORAGE_COMMITTED: only if the implementation performs the corresponding verification/commitment workflow.
Do not infer ExamOrder.Status.COMPLETED from arrival of the first instance. A CT/MR study usually arrives instance by instance, and the absence of new objects for a short time is not authoritative proof that acquisition is complete. If completion is required, use a separately defined MPPS or modality/workflow signal, or explicitly document a configurable quiet-period heuristic as non-authoritative.
Task 2.4 — Handle duplicate UIDs and inconsistent metadata safely
- Same Study UID / Series UID / SOP Instance UID must be idempotent when a retransmission is equivalent.
- A UID collision with materially different content or incompatible parent UIDs must create a visible integrity conflict; do not update the matched order or overwrite objects automatically.
- Validate the hierarchy: a series belongs to the expected study and an instance to the expected series. Detect a Study UID, Series UID, or SOP Instance UID collision across facilities/tenants.
- Do not rewrite UIDs on incoming objects automatically. If de-identification/migration requires remapping, implement it as a separately audited workflow.
Phase 2 acceptance criteria
- A multi-series test study appears once in Django, with the correct Study UID, series, instance counts, and archive resource IDs.
- Duplicate notifications/retransmissions do not create duplicate mirror records.
- Stopping and restarting the worker does not lose events; a replay/rebuild command can repair the mirror.
- Archive unavailability causes retries and a visible operational error, not missing/false success.
Phase 3 — Link received studies to RIS patients and exam orders
Task 3.1 — Implement deterministic matching rules
Use an ordered, auditable matching policy:
1. Exact StudyInstanceUID: If ExamOrder.dicom_study_instance_uid contains the same UID and the order's patient/facility context is valid, link to that order after validating available identifiers for conflicts.
2. Exact accession + Patient ID/MRN + authorized facility/tenant: Use only if the Study UID is not already linked and local accession/MRN semantics have been verified. Enforce conflict checks and any necessary uniqueness policy.
3. No safe match / conflicting fields: leave the study unlinked and set RECONCILIATION_REQUIRED.
Never auto-match on PatientName, DOB, StudyDescription, or procedure text alone. Never let incoming tags select a tenant/facility without a trusted sender-to-facility mapping. Do not merge Patient records or update demographics automatically because a DICOM object differs from the RIS.
Task 3.2 — Support modality behavior around Study Instance UID
- Check how existing MWL responses populate StudyInstanceUID. Prefer assigning an appropriate study UID when the order is created/scheduled and returning it in MWL when the workflow/device supports it.
- Some devices may omit or not echo the scheduled UID. When the archive receives a new Study UID, only assign it to ExamOrder.dicom_study_instance_uid after the matching policy confirms the order is the correct one and the field is currently empty or consistent.
- If the order already has another Study UID, do not overwrite it automatically. Flag the collision and ask an authorized user to reconcile.
- Normalize and validate DICOM attribute representations carefully (padding, whitespace, character sets, case sensitivity, DA/TM parsing, missing values). Do not normalize UIDs or identifiers in a way that can make two distinct identifiers equal.
Task 3.3 — Create a reconciliation work queue
- Add a facility-scoped UI listing unmatched and conflicting studies with the minimum necessary metadata: Study UID, accession, Patient ID as received, study date, modality, series/instance counts, sender/device, and reason for review.
- Actions should be limited to authorized roles: link to an existing order, mark as incorrectly received, move to the correct authorized facility only under an audited policy, or escalate to a supervisor. Avoid destructive “delete” as the default resolution.
- Before confirming a link, show the differences between DICOM metadata and RIS demographics/order metadata. Require explicit confirmation for mismatches.
- Log who performed each action, when, the before/after order link, the reason, and any conflicting identifiers. Protect all routes with server-side object-level/facility permissions and CSRF protections.
Task 3.4 — Add integration audit and metrics
Record auditable service events without dumping PHI, including:
- instance/study accepted or rejected by the archive when available;
- metadata synchronization started/succeeded/failed;
- order match succeeded, failed, or was manually reconciled;
- UID/data integrity conflict;
- manual relink/unlink action;
- authorized retrieval/export action if provided by the RIS.
Metrics should include queue depth, event lag, failed syncs, unmatched study count/age, disk free space, and archive/worker health. Avoid logging full DICOM datasets or credentials.
Phase 3 acceptance criteria
- A study with exact matching UID links to the correct order.
- A study with no UID but unambiguous matching accession/MRN/facility is handled according to the written policy.
- Conflicting patient, facility, accession, or existing Study UID produces a reconciliation case and does not silently link to the wrong patient.
- A user cannot view/relink studies outside permitted facility/tenant scope, including through URL-ID manipulation.
Phase 4 — RIS study browsing and retrieval integration
Task 4.1 — Add a study list and detail page
- Add a facility-scoped PACS/study list searchable by date range, patient/MRN, accession number, Study UID, modality, order status, and reconciliation status. Validate inputs and paginate results; do not run unbounded queries.
- Show Patient/Order linkage, Study/Series/Instance counts, received timestamps, archive state, and actionable errors.
- Link a study to the correct RIS order and report screens. Make it clear when a study is unlinked, still arriving, or has synchronization problems.
- Follow existing UI localization patterns (English/Arabic if supported), accessibility expectations, and consistent permission helpers.
- Add a staff-facing diagnostics view that shows system state, not full DICOM payloads or secret configuration.
Task 4.2 — Add authorized retrieval, not direct filesystem access
- All DICOM retrieval must be mediated through a trusted backend/viewer integration or a separately authenticated DICOMweb path. Never construct file paths from DICOM tags or allow the browser to access storage volumes directly.
- Authorize each requested study against the current user and facility/tenant before obtaining a short-lived or otherwise controlled retrieval URL/token, or proxy the retrieval through the backend as appropriate.
- Use Orthanc's supported API for archive lookups and retrieval. Do not expose an unrestricted Orthanc admin credential or API to the browser.
- Set appropriate content types, response size/time limits, caching rules for PHI, and access audit behavior.
Task 4.3 — Optional DICOMweb viewer milestone
If a browser viewer is needed, enable Orthanc's DICOMweb plugin and integrate a maintained viewer such as OHIF/Stone in a separate, permission-aware task. DICOMweb commonly provides:
- QIDO-RS — search for DICOM resources;
- WADO-RS — retrieve studies/series/instances/frames/metadata;
- STOW-RS — store DICOM resources over HTTP.
Do not assume plugin support means every DICOMweb feature or every transfer syntax is supported. Verify the chosen Orthanc/plugin/viewer version combination with the target studies and document the supported profile. A diagnostic viewer needs a separate clinical validation/usability/performance process; a basic web viewer is not automatically diagnostic-grade.
Phase 4 acceptance criteria
- An authorized user can find a received study and open its detail page.
- An unauthorized or cross-facility user cannot discover or retrieve it through UI, guessed IDs, API endpoints, or direct archive URLs.
- Study retrieval returns original/expected DICOM data and does not depend on a Django web process reading arbitrary filesystem paths.
Phase 5 — Report and order interoperability corrections
Task 5.1 — Correct DICOM SR study linkage
- Review reports/views.py::export_report_dicom() and all related tests. It currently creates a fresh StudyInstanceUID; this can produce a report that does not belong to the associated imaging study.
- Where a report is exported as a DICOM SR associated with an existing imaging study, use the linked ExamOrder.dicom_study_instance_uid/PACS study UID and create a new, unique SeriesInstanceUID and SOPInstanceUID for the SR as required.
- If there is no linked imaging study, do not silently invent a relationship. Either block the export with a clear message or implement a documented standalone-report export policy with correct identifiers and references.
- Check that the emitted SR meets the chosen DICOM SR IOD requirements; the current code labels a Basic Text SR class and builds content sequences, so validate with an independent DICOM validator and a receiving archive/viewer. Generating a .dcm file is not enough to establish conformance.
- Ensure the SR patient/accession/study metadata match the order/study; do not mutate signed report text as part of export.
Task 5.2 — Keep RIS order/report statuses correct
- Define separately what causes: ExamOrder.IN_PROGRESS, COMPLETED, REPORTED, and FINALIZED (as used by this repository). Map image receipt, MPPS events if implemented, report draft/finalization, and PACS availability to these states only through documented transitions.
- Do not switch orders to COMPLETED after first DICOM file receipt. Do not make archived images inaccessible because a report is amended, and do not delete studies when an order is soft-deleted.
- Use transactions for changes that must stay consistent (e.g. verified order link plus UID assignment plus audit record); handle concurrent arrivals safely.
Phase 5 acceptance criteria
- An exported SR for a linked report identifies the same study as the images and can be stored/retrieved by the test archive.
- Reports without a valid study relationship follow the explicit standalone-export policy.
- Existing report finalization/amendment and order lifecycle regression tests continue to pass.
Phase 6 — Testing, validation, observability, and rollout
Task 6.1 — Unit tests
Add tests for:
- DICOM UID syntax/length validation and required metadata parsing;
- Study → Series → Instance hierarchy integrity;
- timestamp and character-set parsing for relevant tags;
- idempotency on repeated store/change notifications;
- duplicate UID with identical versus conflicting content/metadata;
- reconciliation rules and ambiguous/missing identifiers;
- tenant/facility mapping and object-level access control;
- failure/retry/cursor resume and replay/rebuild behavior;
- no unauthorized state change when study data arrive;
- report SR UID alignment and invalid/missing-study behavior;
- safe logging and secret redaction where testable.
Use synthetic or publicly approved de-identified test datasets only. Do not check PHI datasets into Git or use production patient data in tests.
Task 6.2 — DICOM integration tests
- Add repeatable tests using a DICOM test client such as pynetdicom/storescu and echoscu, with a known test AE Title.
- Test association setup, C-ECHO, successful C-STORE, unsupported SOP class/transfer syntax behavior, malformed input, client disconnects, timeout, disk full, archive restart, worker restart, and retry.
- Test at least one representative multi-series study and several modalities actually used at the site (e.g. CT, MR, DX/CR, US); include compressed transfer syntaxes used by the deployed devices.
- Compare received instance counts, UIDs, content hashes or equivalent integrity checks, study/series hierarchy, and retrieval after archive restart.
- Validate target vendor/device conformance and test with a test device or approved simulator before production connection.
Task 6.3 — Performance and resilience tests
- Simulate a large study and concurrent associations using representative sizes and rates. Do not infer capacity from tiny test files.
- Confirm uploads do not consume unbounded Django worker memory or block the web requests that serve ordinary RIS screens.
- Test the archive's disk-full behavior, low-space alerts, database connection failure, unavailable archive API, paused Celery/worker, and process restart.
- Add monitoring/alerts for disk capacity, store failure rate, event lag, sync retries, unmatched studies, archive health, worker health, and backup age.
- Establish site-specific performance goals after measuring realistic volumes; do not invent throughput guarantees in documentation.
Task 6.4 — Backup/restore and runbooks
- Automate or document consistent backup of Orthanc's object storage and index plus the Django PACS metadata mirror and necessary configuration/secrets recovery process.
- Perform a restore drill in a non-production environment, then verify original object retrieval, UIDs, counts, order links, and audit continuity.
- Document onboarding a modality (AE Titles, host/IP, ports, allowed operations, transfer syntaxes, test procedure), certificate rotation if used, disk expansion, restore, outage troubleshooting, reconciliation, and retention/deletion authorization.
- Ensure all credentials are supplied through environment/secrets; no real credential in Docker Compose, committed config, docs, or example commands.
Task 6.5 — Rollout plan
1. Develop against synthetic/de-identified studies and a test archive volume.
2. Deploy to a staging environment with no production routing; run all automated and manual DICOM interoperability tests.
3. Pilot with one approved modality, one facility, and test/pilot data under a documented cutover and rollback plan.
4. Validate storage capacity, archive retrieval, metadata links, permissions, backup and restore, and support runbook before adding further modalities.
5. Roll out facility by facility; monitor ingest errors and reconciliation cases daily during the initial period.
6. Do not enable real clinical traffic until the clinical, security, privacy, backup/restore, and operational sign-offs required by the organization are complete.
Global AI-coder instructions
- First inspect the current repository and create a branch for this work. Do not commit production secrets or DICOM files.
- Implement in small, reviewable steps matching the phases above. Summarize changed files, migration impact, tests run, test results, open issues, and manual deployment steps at each phase.
- Preserve current worklist behavior and existing report workflows unless a specific change is required and covered by regression tests.
- Use an archive adapter/service module for Orthanc API interactions. Do not spread raw REST URLs, credential handling, or DICOM-specific parsing throughout Django views.
- Keep long-running synchronization out of request/response views. Use the existing task/worker conventions where reliable, plus a durable checkpoint and replay path.
- Make database changes backward-compatible where practical. Include migrations, constraints, indexes, and tests; handle legacy rows with empty Study UIDs explicitly.
- Every endpoint, page, API, background task, and reconciliation action must apply the project's authorization and facility/tenant scope. Treat service-to-service credentials as secrets.
- Do not automatically change patient demographics, destroy archived objects, overwrite conflicting instances, or mark orders complete merely because data arrived.
- Never store DICOM binary data in Django model fields as the main archive. Never derive a storage path from DICOM tags. Never log full DICOM metadata or PHI unnecessarily.
- Do not claim DICOM conformance from passing unit tests alone. Document the tested SOP Classes, transfer syntaxes, C-STORE behavior, known limitations, and device interoperability results.
- Do not mark a checklist item complete until its acceptance criteria and tests pass. Classify findings as Confirmed defect, Likely defect—verify, Feature gap, or Not yet verified where appropriate.
Definition of done
The initial PACS receiver/storage release is done only when all the following are true:
- [ ] Approved modalities can C-ECHO and C-STORE to a configured PACS AE over the restricted network.
- [ ] Stored DICOM objects and the archive index survive container/process restart and a tested backup/restore cycle.
- [ ] The metadata mirror is idempotent, replayable, and consistent with the archive's study/series/instance hierarchy.
- [ ] Study-to-order linking follows documented UID/accession/MRN/facility rules and ambiguity is handled by a reconciliation queue.
- [ ] PACS study list/detail UI and retrieval authorization enforce per-user and per-facility access controls.
- [ ] Report SR export uses correct study linkage or follows an explicit no-study policy.
- [ ] Failure modes, transfer syntax support, sender allowlisting, storage capacity, audit events, retention policy, and runbooks are documented and tested.
- [ ] Security, clinical workflow, interoperability, monitoring, and recovery sign-offs required by the organization are complete before live clinical use.