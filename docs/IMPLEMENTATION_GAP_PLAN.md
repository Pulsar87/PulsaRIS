# RaqeemRIS Implementation and Functional Gap Plan

**Purpose:** Track the code changes, missing safeguards, workflow improvements, and verification needed before RaqeemRIS is considered ready for production use with real clinical data.

**Review basis:** Static repository review of the `main` branch as of 2026-10-12. The findings below are a remediation plan, not a claim that every issue has been reproduced at runtime. Confirm each item with tests and deployment configuration before closing it.

## How to use this plan

- Work in priority order. P0 items block production use with real patient data.
- Open a GitHub issue for each numbered item, assign an owner, and link the pull request and tests.
- Mark an item complete only when its acceptance criteria are met and the relevant automated tests pass.
- Classify discoveries as **Confirmed defect**, **Likely defect—verify**, **Feature gap**, or **Not yet verified**.
- Apply least privilege and tenant/facility isolation consistently across HTML views, APIs, exports, background jobs, and DICOM-facing functionality.
- Do not use production patient data in development or test environments.

## Priority summary

| Priority | Scope | Exit condition |
|---|---|---|
| P0 — Security and clinical safety | Authentication, authorization, facility isolation, report integrity, secrets, production settings | No unauthenticated or cross-facility access; clinical state transitions enforced; secret/configuration review passed |
| P1 — Workflow correctness | Patient/order/report lifecycle, billing, inventory, audit, automated tests | Critical workflows have explicit rules and regression tests |
| P2 — Reliability and operations | DICOM, interoperability, backup/restore, monitoring, deployment hygiene | Failure recovery is demonstrated and operational controls are documented |
| P3 — Product completeness and usability | Workflow gap validation, accessibility, localization, reporting | Requirements matrix reviewed by clinical and operational stakeholders |

---

# P0 — Security and clinical safety

## P0-01 — Add consistent authentication and authorization to patient and report views

**Status:** Likely defect—verify with runtime tests  
**Relevant areas:** `patients/views.py`, `reports/views.py`, `patients/urls.py`, `reports/urls.py`, shared permission helpers.

### Changes
- Audit every view and API endpoint for explicit authentication and permission checks.
- Apply the project's shared authorization helpers or consistent decorators/mixins; do not rely on URL inclusion, license middleware, or template visibility as access control.
- Enforce role-based permissions for patient search, read, create, update, delete, report creation, editing, signing/finalization, verification, export, and deletion.
- Apply object-level authorization on every requested patient, order, report, and related object.
- Protect state-changing requests with Django CSRF protection where session authentication is used; validate API authentication separately.
- Return safe 403/404 responses without leaking whether another facility's records exist.

### Acceptance criteria
- Anonymous requests to protected pages and APIs are rejected or redirected according to the documented authentication policy.
- Users cannot access or mutate records outside their allowed role and facility, including by changing URL IDs.
- Tests cover anonymous, low-privilege, authorized, and cross-facility requests for each sensitive action.
- No permission decision depends solely on a hidden button or frontend state.

## P0-02 — Make facility/tenant scoping fail closed

**Status:** Likely defect—verify policy and runtime behavior  
**Relevant areas:** `orders/views.py` (`_orders_for_user`), `core/views.py` (`facility_search_api`), `license/views.py` (`home`), shared facility/permission helpers, all list/detail/search/export endpoints.

### Changes
- Replace unrestricted fallback behavior when a user has no facility IDs with an explicit deny-by-default policy, unless a documented and tightly permissioned platform-admin role is intended.
- Define one reusable facility-scoping policy for users, orders, patients, reports, schedules, devices, billing, inventory, exports, and APIs.
- Review records with `facility__isnull=True`; handle legacy/unassigned data through an explicit migration or admin-only workflow rather than silently broadening access.
- Scope facility search results to facilities the user is allowed to discover.
- Scope license/dashboard calendar queries and device summaries to the current user's permitted facilities.
- Check facility ownership on create/update operations and on foreign-key IDs supplied by the client.

### Acceptance criteria
- A user with no facility membership sees no facility-owned records by default.
- Cross-facility ID substitution fails for read and write requests.
- Facility scoping applies equally to UI, API, export, background tasks, and dashboard aggregates.
- Tests cover zero facilities, one facility, multiple facilities, unassigned legacy records, and authorized platform administrators.

## P0-03 — Enforce report lifecycle and signing integrity

**Status:** Likely defect—verify current model constraints and business policy  
**Relevant area:** `reports/views.py`, especially `create_report`, plus report models, forms/serializers, order status transitions, verification and edit/delete endpoints.

### Changes
- Never trust a submitted `status` value. Use an allowlisted state machine and server-side permission checks for draft, review, final, amended, and any other supported states.
- Prevent clients from finalizing a report by posting `status=FINAL` directly unless the actor is explicitly authorized and all required conditions are met.
- Validate required findings/impression and any modality-specific report fields before finalization.
- Ensure the order belongs to an authorized facility and is in a state that permits report creation.
- Use a database transaction for report creation and related order-status changes.
- Record finalizing user, timestamps, report version, and amendment reason; preserve an immutable audit trail for signed reports.
- Define whether finalized reports can be edited, corrected, amended, or deleted; prohibit silent overwrites and destructive deletion where retention policy requires preservation.
- Make state transitions idempotent and handle concurrent updates safely.

### Acceptance criteria
- Invalid transitions and unauthorized finalization are rejected server-side.
- Failed report creation cannot leave an order in a misleading state.
- Finalized reports retain signer, timestamp, and version history.
- Tests cover draft save, finalize, duplicate submission, unauthorized signing, amendment, deletion policy, concurrent updates, and cross-facility access.

## P0-04 — Review secrets, environment configuration, and production security settings

**Status:** Confirmed repository hygiene concern; credential validity and exposure history require verification  
**Relevant areas:** tracked `.env`, `.gitignore`, `config/settings/base.py`, deployment documentation, CI configuration, Git history.

### Changes
- Remove tracked environment-specific secrets and local credentials from the repository; replace them with a safe `.env.example` containing placeholders only.
- Inspect Git history and rotate any real or reused secrets, passwords, tokens, and keys. Deleting a secret from the latest commit does not remove it from history.
- Expand `.gitignore` to exclude environment files, local databases, logs, virtual environments, bytecode, generated uploads, test artifacts, and machine-specific settings, while allowing explicitly safe examples.
- Ensure production configuration fails startup when required secrets are absent or insecure defaults are active.
- Disable debug mode in production; configure allowed hosts, secure cookies, HTTPS redirect/HSTS as appropriate to deployment, trusted origins, proxy headers, and appropriate security headers.
- Use least-privilege database credentials and separate development, test, staging, and production configuration.
- Document secret provisioning and rotation without committing secret values.

### Acceptance criteria
- No live secrets or production patient data are present in tracked files or recent history after remediation.
- A production-like configuration test fails safely when required settings are missing.
- Debug mode is off in production and deployment settings are reviewed.
- A clean checkout can be configured using documented environment variables and `.env.example`.

## P0-05 — Establish a reliable audit trail for sensitive access and changes

**Status:** Not yet verified across all modules  
**Relevant areas:** shared audit code, `clinic/views.py`, patient/report/order/billing/inventory views, authentication events.

### Changes
- Define audit events for patient record access where required by policy, create/update/delete, order changes, report draft/finalization/amendment, exports, permission changes, and administrative actions.
- Capture actor, action, timestamp, target identifier, facility, outcome, and a minimal change summary; do not place full clinical content, passwords, tokens, or unnecessary sensitive data in logs.
- Ensure failed authorization attempts and relevant security events are logged.
- Protect audit records from ordinary application-user modification and deletion.
- Add retention, access, export, and monitoring policies appropriate to the deployment's jurisdiction and organizational requirements.

### Acceptance criteria
- Critical actions generate attributable audit events.
- Audit logs cannot be altered through ordinary application endpoints.
- Tests prove sensitive actions are logged and secret/clinical payloads are not unnecessarily copied into logs.

---

# P1 — Clinical and operational workflow correctness

## P1-01 — Define and test the patient registration lifecycle

**Status:** Feature completeness not yet verified  
**Relevant areas:** `patients/`, patient models/forms, clinic patient matching and duplicate-detection code.

### Changes
- Document required demographics, medical record number (MRN) assignment, uniqueness rules, merge/duplicate handling, corrections, inactive/deceased status if in scope, and facility ownership.
- Validate identifiers and normalize matching inputs without treating fuzzy matches as automatic identity proof.
- Add a safe duplicate-review/merge workflow with authorization, audit history, and preservation of linked encounters, orders, reports, and billing records.
- Confirm search and lookup APIs reveal only authorized minimum information.
- Define retention and correction rules with the organization.

### Acceptance criteria
- MRNs follow a documented uniqueness/assignment policy.
- Duplicate candidates can be reviewed without destructive automatic merges.
- Patient edits and merges preserve linked clinical history and are audited.
- Tests cover duplicates, concurrent registration, invalid inputs, and facility access.

## P1-02 — Specify an order and examination state machine

**Status:** Feature completeness not yet verified  
**Relevant areas:** `orders/views.py`, order models/forms, worklist integration, report transitions, devices.

### Changes
- Document valid order/exam states, actors allowed to transition each state, required fields, cancellation rules, and recovery from failed or repeated messages.
- Validate transitions server-side rather than accepting arbitrary status updates.
- Prevent impossible transitions and ensure report finalization and order status stay consistent.
- Define handling for duplicate orders, canceled orders, rescheduling, performed exams, and corrections.
- Add transaction and concurrency protection around state changes.
- Confirm that clinical urgency, priority, ordering clinician, indication, modality, and facility are validated as required by local workflow.

### Acceptance criteria
- Every transition is documented and tested; invalid transitions are rejected.
- Duplicate requests do not create duplicate orders or inconsistent states.
- A report cannot be finalized against an incompatible or unauthorized order.
- Worklist and UI state agree with the persisted order state.

## P1-03 — Validate end-to-end radiology reporting workflow

**Status:** Feature completeness not yet verified  
**Relevant areas:** `reports/`, templates, export/verification endpoints, order integration.

### Changes
- Trace the complete lifecycle from scheduled/ordered exam through worklist, performed exam, draft report, review, finalization, delivery, correction/amendment, and audit.
- Validate report templates, required fields, status display, signer identity, timestamps, and report-to-order/patient linkage.
- Define whether report verification is a separate signature/attestation and who may perform it.
- Verify exports contain only authorized data and do not bypass report access checks.
- Add explicit failure states for incomplete or unavailable downstream delivery.

### Acceptance criteria
- A representative exam can be followed end-to-end with consistent patient, order, report, and status linkage.
- Finalized content and amendments remain traceable.
- Delivery/export failure is visible and retryable without duplicating or silently losing reports.

## P1-04 — Add regression tests for high-risk modules

**Status:** Confirmed test-coverage gap in the reviewed files; broader coverage should be measured  
**Relevant areas:** `patients/tests.py`, `reports/tests.py`, `orders/tests.py`, `users/tests.py`, existing `clinic/tests.py`, CI workflows.

### Changes
- Replace empty test scaffolding with focused model, view, API, permission, and workflow tests.
- Build reusable fixtures for roles, facility membership, patients, orders, reports, and audit events.
- Add negative tests as first-class tests: anonymous access, wrong role, cross-facility ID substitution, invalid transitions, forged status fields, and malformed input.
- Add tests for transactional rollback, duplicate submissions, and concurrent state updates where relevant.
- Run migrations and tests against a clean temporary database in CI.
- Add formatting, linting, dependency/security checks, and test coverage reporting where compatible with the project.

### Acceptance criteria
- CI runs the documented test suite on every pull request.
- All P0 security and lifecycle acceptance tests are automated.
- No critical module is represented only by empty test scaffolding.
- Test failures block merge to the protected production branch.

## P1-05 — Verify billing from clinical activity to reconciliation

**Status:** Feature completeness not yet verified  
**Relevant areas:** billing app, clinic charge creation/signals, orders, patient/facility scoping.

### Changes
- Map the workflow from encounter/exam charge capture to invoice, payment, adjustment/refund, outstanding balance, and reconciliation.
- Define price lists, payer/patient responsibility, discounts, tax rules if applicable, invoice numbering, and permissions.
- Ensure charges are not duplicated by repeated signals, retries, or user submissions; use idempotency keys or stable source references where appropriate.
- Add transaction boundaries and audit events for financial changes.
- If insurance claims are in scope, define claim submission, rejection, remittance, denial, resubmission, and reconciliation workflows instead of assuming invoice generation covers them.
- Confirm reports and financial exports are facility-scoped and role-protected.

### Acceptance criteria
- Each billable clinical event produces the intended charge at most once.
- Payments, refunds, adjustments, and balance calculations reconcile in tested scenarios.
- Unauthorized users cannot view or alter another facility's financial records.
- Any unsupported payer/claims workflow is explicitly documented as out of scope.

## P1-06 — Validate inventory and device/consumable controls

**Status:** Feature completeness not yet verified  
**Relevant areas:** inventory app, exam/device workflows, permissions, audit code.

### Changes
- Verify stock receiving, issue/consumption, adjustment, transfer, returns, and stock counts.
- If the business requires it, track lots/batches, expiry dates, supplier, and recall information.
- Prevent negative stock or require explicit, authorized override with an audit trail.
- Ensure stock movement records are immutable ledger entries rather than only overwriting a current quantity.
- Define reorder thresholds, low-stock alerts, valuation, and reconciliation behavior if needed.
- Check all inventory queries and reports for facility scoping.

### Acceptance criteria
- Stock balances can be reconciled from recorded movements.
- Concurrent issues/receipts do not lose updates or create impossible balances.
- Expired/recall-sensitive stock can be identified where those controls are in scope.
- Stock adjustments are permissioned and audited.

## P1-07 — Review appointment, room, and provider scheduling

**Status:** Existing scheduling logic is present; complete behavior not yet verified  
**Relevant areas:** clinic scheduling, appointments, providers, rooms, encounters.

### Changes
- Verify time zone handling, daylight-saving transitions, working hours, holidays, duration, cancellation, rescheduling, no-show, and waitlist behavior.
- Confirm conflict checks are transaction-safe and cover provider, room, equipment, and facility as applicable.
- Define appointment reminders and delivery failure handling if reminders are in scope.
- Ensure schedules and calendars are facility- and role-scoped.
- Test appointment-to-encounter creation and repeated actions.

### Acceptance criteria
- Conflicting appointments are prevented under concurrent requests.
- Reschedule/cancel operations preserve history and do not orphan encounters.
- Calendar views never disclose appointments outside the user's scope.

## P1-08 — Review medication, allergy, vitals, and clinical-note safety

**Status:** Scope and completeness not yet verified  
**Relevant areas:** clinic encounters, vitals, notes, referrals, patient chart.

### Changes
- Confirm whether medication prescribing/reconciliation and allergy documentation are required for the target clinic workflow.
- If supported, model medication status, dose, route, frequency, duration, prescriber, reconciliation, and discontinuation with validation appropriate to scope.
- Validate vital-sign units/ranges and record the author, time, and correction history.
- Define note status, signing, amendment, and late-entry behavior.
- Make critical alerts visible without allowing alerts alone to substitute for clinical judgment.
- Document features deliberately outside the product's scope.

### Acceptance criteria
- Clinical entries are attributable and time-stamped.
- Corrections do not silently erase signed content.
- Required safety checks and validations are covered by tests.
- Unimplemented clinical capabilities are explicitly identified for product owners.

---

# P2 — Reliability, interoperability, and deployment

## P2-01 — Harden DICOM services and test interoperability

**Status:** DICOM Modality Worklist code/documentation exists; production readiness not yet verified  
**Relevant areas:** `core/management/commands/run_dicom_server.py`, `integrations/dicom/worklist.py`, `DICOM_SERVER.md`, device configuration.

### Changes
- Restrict network exposure to approved modality/network segments; do not expose a DICOM listener broadly without a documented network design.
- Configure explicit AE-title allowlists and permitted calling/called AE titles; document ports, timeouts, and firewall rules.
- Avoid debug-level logs in production and redact patient identifiers where feasible and appropriate.
- Validate query behavior for patient ID, accession number, modality, scheduled station, and date/time according to the supported conformance profile.
- Test malformed requests, timeouts, unavailable modalities, duplicate requests, and recovery after service restart.
- Document supported SOP classes and conformance limits.
- Confirm whether PACS/image archive, image viewer, storage SCP, DICOMweb, MPPS, and image retrieval are external integrations or unsupported features; do not assume a worklist SCP provides those capabilities.
- **Update 2026-10-17 (PACS plan Phase 0):** Confirmed by source inspection — the current `run_dicom_server` SCP registers only Verification, MWL C-FIND, and MPPS contexts; it has no Storage SOP Class context and no C-STORE handler, so RaqeemRIS is **not** an image archive today. The PACS implementation plan (`PACS_plan.md`) has been started: Phase 0 reconnaissance and design freeze are recorded in `docs/PACS_IMPLEMENTATION.md`. Planned capability: dedicated Orthanc archive service (separate AE title/port) with a Django metadata mirror. Until later phases deliver and test it, all PACS/storage/DICOMweb/retrieval items above remain **Feature gap**.
- **Update 2026-10-17 (PACS plan Phase 1, Task 1.1):** A pinned Orthanc archive service (`orthancteam/orthanc:25.9.3`, AE `RAQEEM_PACS`, DICOM port 4242 configurable, REST 8042 internal-only on a private Docker network, persistent `orthanc-db` volume, env-driven config + authenticated health check) is now defined in `docker-compose.yml`; ops runbook added at `docs/PACS_RUNBOOK.md`. Classification: storage SCP is **deployed-by-configuration but not yet runtime-verified** (C-ECHO/C-STORE round-trip, unknown-sender rejection, restart persistence, backup/restore drill pending in a Docker environment). Django-side metadata mirror, reconciliation, study browsing, retrieval, and DICOMweb integration remain **Feature gap** (Phases 2–4). No real modality traffic is enabled until Phase 1 acceptance passes.

### Acceptance criteria
- A test modality can query the worklist using the documented configuration.
- Unauthorized network peers are rejected according to policy.
- Operational errors are logged safely and are diagnosable.
- Supported and unsupported DICOM capabilities are documented accurately.

## P2-02 — Complete HL7/FHIR outbox delivery or document its boundary

**Status:** Integration completeness not yet verified; code comments indicate consumer wiring is deferred  
**Relevant areas:** `clinic/signals.py`, outbox/event models, background jobs, integration configuration.

### Changes
- Trace how outbox records are picked up, transformed, delivered, acknowledged, retried, and marked complete.
- Implement a reliable worker if external delivery is in scope, with bounded retries, exponential backoff, dead-letter/error handling, idempotency, and monitoring.
- Define mappings and validation for the selected HL7 v2 messages and/or FHIR R4 resources; do not claim standards compliance from an outbox table alone.
- Protect credentials and endpoints; log message identifiers and outcomes without exposing unnecessary PHI.
- Document supported message/resource profiles, required fields, transport, acknowledgement behavior, and operational ownership.

### Acceptance criteria
- A failed delivery can be retried without creating duplicate downstream resources.
- Invalid messages are visible and actionable.
- Integration status can be monitored.
- If external interoperability is not in scope, the product documentation states that clearly.

## P2-03 — Implement and rehearse backup, restore, and disaster recovery

**Status:** Not yet verified  
**Relevant areas:** deployment configuration, database and media storage, DICOM/integration data, operations documentation.

### Changes
- Identify every persistent data store, uploaded-file store, configuration item, and integration queue that must be backed up.
- Define backup frequency, encryption, retention, off-site/isolated copies, access controls, and recovery-point/recovery-time objectives with stakeholders.
- Document restoration of the database and media/files in a consistent state.
- Schedule restore drills and verify integrity after restoration.
- Define incident response, ransomware response, and recovery ownership.

### Acceptance criteria
- A clean environment can be restored from documented backups.
- Restore tests validate patient/order/report relationships and uploaded artifacts.
- Recovery objectives and backup retention are approved and documented.

## P2-04 — Remove generated artifacts and improve repository hygiene

**Status:** Confirmed repository hygiene concern  
**Relevant areas:** `.gitignore`, tracked `myenv/`, local databases, logs, bytecode, duplicate/older project copies.

### Changes
- Identify and remove committed virtual environments, bytecode, local databases, logs, generated output, and obsolete copies that are not intentional fixtures or required source.
- Update `.gitignore` and document the supported Python/dependency setup.
- Pin and review dependencies using the project's chosen dependency-management approach.
- Keep reproducible migrations, safe test fixtures, and necessary static assets.
- Check repository history for secrets and sensitive data before/after cleanup.

### Acceptance criteria
- A clean clone can install dependencies and run checks using documented commands.
- Generated/local artifacts are not reintroduced by normal development.
- Required fixtures and assets remain available.

## P2-05 — Add production monitoring and operational runbooks

**Status:** Not yet verified  
**Relevant areas:** application logging, background tasks, DICOM server, outbox/integrations, deployment.

### Changes
- Define health/readiness checks for the web application, database, background workers, DICOM listener, and external integrations.
- Monitor errors, failed jobs, outbox backlog, DICOM connectivity, database/storage capacity, and backup outcomes.
- Configure alerting and escalation without putting sensitive clinical data in alert payloads.
- Document deployment, migrations, rollback, key rotation, incident response, and routine maintenance.

### Acceptance criteria
- Operators can detect a failed worker or integration without manually inspecting database rows.
- Runbooks include safe diagnosis and recovery steps.
- Monitoring is tested in a staging environment.

---

# P3 — Product completeness, standards, and usability

## P3-01 — Build a stakeholder-approved requirements matrix

**Status:** Required before claiming feature parity  
**Areas:** registration, scheduling, encounters, radiology orders, reporting, billing, inventory, administration, integrations.

### Changes
- Interview radiologists, technologists, front-desk staff, clinicians, billing staff, administrators, and IT/security owners.
- For each workflow, record: required behavior, actor/role, data inputs, state transitions, validation, audit requirements, failure handling, report/export needs, and acceptance tests.
- Classify each capability as implemented and verified, partially implemented, missing, intentionally out of scope, or dependent on an external system.
- Compare the resulting requirements against applicable standards and local legal/organizational requirements. Avoid treating any generic checklist as proof of regulatory compliance.

### Acceptance criteria
- Each must-have capability has an owner and testable acceptance criteria.
- Every known gap is linked to an issue and priority.
- Clinical/operational stakeholders sign off on the scope.

## P3-02 — Validate standards and regulatory requirements for the target deployment

**Status:** Not yet verified  
**Reference points:** HL7 FHIR, DICOM, OWASP ASVS, NIST Cybersecurity Framework, applicable privacy/security laws and organizational policy.

### Changes
- Use DICOM specifications and conformance statements for imaging interoperability.
- Use selected FHIR profiles/implementation guides and HL7 v2 specifications where those interfaces are required.
- Use OWASP ASVS as an application security verification checklist and NIST CSF as a risk-management framework.
- Have qualified compliance/security stakeholders determine applicable jurisdiction-specific obligations; do not claim HIPAA or other compliance solely because individual controls exist.
- Maintain a versioned requirements-to-evidence matrix.

### Acceptance criteria
- Each applicable requirement has a control, test/evidence, owner, and status.
- Unsupported interfaces and compliance limitations are documented.

## P3-03 — Test English/Arabic localization, RTL, accessibility, and responsive layouts

**Status:** Localization support exists; completeness not yet verified  
**Areas:** templates, static assets, forms, dashboards, tables, reports, PDF/print output.

### Changes
- Check right-to-left layout, mixed Arabic/Latin identifiers, numbers, dates, punctuation, and form controls.
- Ensure translations cover validation errors, status labels, email/messages, reports, and admin workflows.
- Test keyboard navigation, focus visibility, labels, contrast, error announcements, and responsive layouts.
- Validate PDF/print fonts and layout for Arabic and English.
- Keep internal IDs, accession numbers, and clinically meaningful values unambiguously represented across locales.

### Acceptance criteria
- Core workflows work in both supported languages without layout or data corruption.
- Keyboard-only operation and core accessibility checks pass.
- Printed/exported reports remain readable and correctly linked to the intended patient/order.

## P3-04 — Review reports, exports, dashboards, and search for correctness

**Status:** Not yet verified  
**Areas:** dashboards, worklists, patient/order/report search, CSV/PDF/DICOM exports.

### Changes
- Verify filters, sorting, pagination, date ranges, time zones, totals, and permission-scoped aggregates.
- Prevent spreadsheet formula injection in CSV exports and validate export content/encoding.
- Add audit events for sensitive exports.
- Verify that dashboard counts match the underlying filtered records and do not leak cross-facility totals.
- Add safe empty/error states and bounded query behavior.

### Acceptance criteria
- Search and dashboard results match authorized underlying data.
- Exports contain only the intended records and are safe to open in supported tools.
- Tests cover filters, boundary dates, empty data, and authorization.

---

# Cross-cutting implementation rules

- **Deny by default:** absence of a role/facility assignment must never accidentally grant broader access.
- **Server-side validation:** frontend validation is supplementary, not authoritative.
- **Transactions:** multi-model clinical/financial changes must either complete together or roll back together.
- **Idempotency:** retries must not duplicate orders, charges, reports, integration messages, or stock movements.
- **Auditability:** signed clinical and financial history must not be silently overwritten.
- **Privacy by design:** minimize PHI in logs, errors, exports, test fixtures, and monitoring.
- **Safe migrations:** provide migrations/backfills for existing records and test them on a copy of representative non-production data.
- **No unverified compliance claims:** demonstrate controls and tests, and obtain appropriate professional review where required.

# Suggested execution sequence

1. **Baseline and triage:** record the commit SHA, run the existing tests, inspect deployment settings and routes, and create one issue per item above.
2. **P0 security:** authentication, facility isolation, report lifecycle, secret hygiene, and audit coverage.
3. **P0 verification:** add negative authorization tests and prove cross-facility isolation in a staging environment.
4. **P1 clinical integrity:** patient/order/report lifecycle, then regression tests and end-to-end workflows.
5. **P1 business operations:** billing, inventory, scheduling, and clinical-chart scope agreed with stakeholders.
6. **P2 reliability:** DICOM network/conformance tests, interoperability delivery, restore drills, repository cleanup, and monitoring.
7. **P3 product acceptance:** requirements matrix, standards mapping, localization/accessibility, exports and dashboard review.
8. **Release gate:** do not process real patient data until P0 issues are closed, critical workflows pass, restore capability is demonstrated, and the deployment/security review is approved.

# Definition of done for a remediation item

- [ ] Requirement and risk are understood by the owner.
- [ ] Code and/or configuration change is reviewed.
- [ ] Automated regression test(s) cover the behavior and relevant negative cases.
- [ ] Migration and rollback implications are reviewed where applicable.
- [ ] Logs and audit events are privacy-safe.
- [ ] Documentation and operational guidance are updated.
- [ ] CI passes and the change is verified in staging.
- [ ] Product owner/security/clinical reviewer signs off when the item affects their domain.

## Reference standards and guidance

- HL7 FHIR: https://hl7.org/fhir/
- DICOM Standard: https://www.dicomstandard.org/
- OWASP Application Security Verification Standard: https://owasp.org/www-project-application-security-verification-standard/
- NIST Cybersecurity Framework: https://www.nist.gov/cyberframework
- U.S. HHS HIPAA Security Rule guidance (applicability must be determined for the deployment): https://www.hhs.gov/hipaa/for-professionals/security/index.html

**Important:** This document is a prioritized remediation plan based on static code review. It is not a security certification, clinical safety certification, or regulatory compliance determination.
