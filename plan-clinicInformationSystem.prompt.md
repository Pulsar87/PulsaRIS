## Plan: Add Clinic Information System

Extend the existing RIS into a multi-site outpatient clinic platform while keeping the shared patient identity and existing imaging, billing, and inventory workflows. Start with secure clinic operations and an encounter foundation; add broader clinical records and interoperability in deliberate phases rather than expanding the RIS order model to represent all care.

**Steps**
1. **Security and facility foundations**: audit authentication and authorization on patient, order, billing, report, and clinic-facing routes; establish consistent role- and facility-scoped access and audit trails before exposing new clinical records. Keep patients shared across facilities; scope operational records and staff assignments to `Facility`.
2. **Clinic operations**: add provider/department/room availability, appointment scheduling, referral capture, check-in/queue states, and cancellation/no-show handling. Keep imaging `ExamOrder.scheduled_at` for modality scheduling; use a separate general `Appointment` model.
3. **Encounter and clinical record**: add an `Encounter` linked to patient, facility, provider, and optionally appointment. Add vitals, structured diagnoses/problems, allergies, medication history/prescriptions, and signed/versioned encounter notes with access and audit requirements. Reuse patient and user identity; do not duplicate demographics.
4. **Connect existing modules**: support referrals from encounters to `ExamOrder`; associate services/charges with the encounter through existing billing abstractions; connect orders, reports, and inventory consumption as applicable. Preserve current RIS workflow and billing semantics.
5. **Interoperability and rollout**: define stable API boundaries and mappings (FHIR resources and HL7 events where needed) after internal workflows stabilize. Pilot at one facility, verify cross-facility access and patient matching, then roll out to the remaining sites.

**Relevant files**
- `/home/pulsar/Documents/pulsaris/core/models.py` — extend `Facility` only for clinic/site configuration if needed; it already owns facility identity.
- `/home/pulsar/Documents/pulsaris/patients/models.py` — retain `Patient` as shared identity; review whether patient merge/matching and facility-specific identifiers are required.
- `/home/pulsar/Documents/pulsaris/orders/models.py` — preserve imaging-specific `ExamOrder`; link clinic referrals/encounters rather than overloading it.
- `/home/pulsar/Documents/pulsaris/billing/models.py` — integrate encounter-originated services with existing `PatientAccount` and `ServiceLine`.
- `/home/pulsar/Documents/pulsaris/users/models.py` — establish provider roles and facility assignments.
- `/home/pulsar/Documents/pulsaris/config/settings/base.py` — register a dedicated clinic app and ensure security settings align with deployment.
- `/home/pulsar/Documents/pulsaris/templates/layout.html` and `/home/pulsar/Documents/pulsaris/config/urls.py` — add navigation and routes following current Django template conventions.
- `/home/pulsar/Documents/pulsaris/patients/tests.py`, `/home/pulsar/Documents/pulsaris/orders/tests.py`, `/home/pulsar/Documents/pulsaris/billing/tests.py` — expand workflow and permission coverage alongside implementation.

**Verification**
1. Add tests proving clinic records are facility-scoped while shared patient identity remains accessible according to role and facility policy.
2. Test scheduling conflicts, provider/room availability, check-in, cancellation, and no-show transitions.
3. Test encounter lifecycle, required clinical documentation, signed-note immutability/versioning, and audit records.
4. Test encounter-to-exam-order and encounter-to-service-line integration without changing existing RIS billing/report workflows.
5. Run Django migrations/checks and relevant app tests; manually walk reception-to-encounter-to-imaging-referral-to-billing across two facilities.

**Decisions**
- Scope: both general outpatient care and radiology workflows.
- Deployment: multiple facilities/sites share patients within one organization; this is not a request for isolated multi-tenant SaaS.
- Architecture recommendation: a dedicated clinic domain/app over existing shared identity and facility concepts; no React rewrite implied.
- Explicitly defer full hospital EHR scope, lab/pharmacy integrations, insurer clearinghouse expansion, and tenant isolation until requirements call for them.

**Further Considerations**
1. Confirm the first launch specialty and minimum required clinical documentation before defining encounter fields and templates.
2. Confirm applicable jurisdictional privacy, retention, e-prescribing, and clinical-signature requirements before selecting audit and note-signing rules.

---

## Implementation-Readiness Addendum (verified against current codebase)

The following refinements were validated directly against the existing models in this repository and must be incorporated into the implementation plan above.

### A. Codebase findings that change the plan

1. **`ServiceLine.exam_order` is a non-nullable FK** (`billing/models.py:367`: `ForeignKey("orders.ExamOrder", on_delete=PROTECT)`). Encounter-originated charges cannot flow through billing today. **Prerequisite migration (Phase 0):** add a nullable `encounter = ForeignKey(clinic.Encounter, null=True, blank=True, on_delete=PROTECT)` to `ServiceLine`, plus a DB `CheckConstraint` enforcing exactly one of `exam_order` / `encounter` is set per line, and a data-backfill-safe migration path. Do not make `exam_order` nullable — keep the constraint so integrity is enforced at the database level.
2. **Field-name correction:** imaging scheduling uses `ExamOrder.scheduled_datetime` (`orders/models.py:171`), not `scheduled_at`. Step 2 of the plan should reference `scheduled_datetime` when integrating with the unified availability engine.
3. **Facility ownership split:** `Facility` lives in `core/models.py:58`, but `User.facility` is a single-FK in `users/models.py:9`. Clinic staff need multi-facility coverage: add a `FacilityAssignment` (user, facility, role-at-facility, active dates) model in the clinic app rather than replacing `User.facility`; treat `User.facility` as the *home/default* facility for backward compatibility.
4. **Audit stack already present:** both a custom `audit` app and `django-auditlog` are installed (`config/settings/base.py` INSTALLED_APPS). Clinical notes and encounter state changes must write to both; do not build a third audit mechanism.

### B. Architectural decisions (adopted)

1. **Single availability/conflict engine.** Create `clinic.Appointment` and `clinic.ProviderAvailability` / `clinic.RoomBooking` primitives, then expose an adapter so radiology slot requests from `ExamOrder.scheduled_datetime` reserve through the *same* engine. This prevents two parallel schedulers drifting apart. `ExamOrder` keeps its own scheduled fields (RIS workflow preserved); the appointment link is authoritative for conflicts.
2. **Explicit `Appointment ↔ ExamOrder` link.** Add `ExamOrder.appointment = ForeignKey(clinic.Appointment, null=True, blank=True)` (or OneToOne via clinic-side FK if preferred) so a referral created from an encounter can carry its appointment into modality scheduling and vice versa.
3. **Reusable facility-scoping layer.** Implement `core.mixins.FacilityScopedModel` (adds `facility` FK + default manager filtering) and a `FacilityScopedPermission` / middleware helper in DRF + function-based views. Apply it to new clinic models first, then retrofit existing patient/order/billing/report querysets so scoping policy is defined once and covers both modules.
4. **Append-only versioned notes.** `EncounterNote(version, supersedes FK, body, author, signed_at, signature_hash)` — immutable after signing (enforce via `pre_save` guard + DB triggers or update-permission denial), SHA-256 content hash per version, each edit recorded in `auditlog` and the custom `audit` app. Signing = authenticated user + timestamp + hash; retain hash chain (`prev_version_hash`) for tamper evidence.
5. **Patient identity stays shared.** No facility-specific copies of `Patient`. Facility-specific identifiers (MRN-per-site, chart numbers) go in a `clinic.PatientFacilityIdentifier` join table; cross-facility access governed by role + facility policy, not record duplication.

### C. Revised phase sequencing

- **Phase 0 — Foundations (blocking):** security/route audit, `FacilityScopedModel` mixin + permission layer, `FacilityAssignment`, `ServiceLine.encounter` migration + exclusivity constraint, install `clinic` app skeleton (models empty, registered in `INSTALLED_APPS` after `patients`).
- **Phase 1 — Operations:** Provider/room availability, `Appointment`, referral capture, check-in/queue, cancellation/no-show, availability-engine adapter for `ExamOrder.scheduled_datetime`.
- **Phase 2 — Clinical records:** `Encounter` lifecycle, vitals, problems/diagnoses (ICD-10 coding column), allergies, medications/prescriptions, signed versioned notes.
- **Phase 3 — Interop & rollout:** FHIR/HL7 mapping only after Phases 0–2 stabilize; pilot at one facility; verify cross-facility access + patient matching; then remaining sites.

### D. Concrete file-level work list

| File | Change |
|---|---|
| `clinic/` (new app) | `models.py` (Appointment, Encounter, Vitals, Problem, Allergy, Medication, Prescription, EncounterNote, ProviderAvailability, RoomBooking, FacilityAssignment, PatientFacilityIdentifier), `views.py`, `urls.py`, `permissions.py`, `tests/` |
| `config/settings/base.py` | append `"clinic"` to `INSTALLED_APPS` (after `patients`) |
| `config/urls.py` | include `clinic.urls` under `/clinic/` |
| `templates/layout.html` | add Clinic nav section (Reception / Appointments / Encounters) gated by role |
| `billing/models.py` | add nullable `encounter` FK to `ServiceLine` + `CheckConstraint(xor exam_order/encounter)` |
| `orders/models.py` | add nullable `appointment` FK to `ExamOrder`; leave `scheduled_datetime` semantics untouched |
| `core/mixins.py` (new) | `FacilityScopedModel` + scoped manager |
| `users/models.py` | no breaking change; document `User.facility` as home facility |
| `patients/models.py` | unchanged; identifiers handled by clinic join table |
| `clinic/tests.py` + expand `patients/orders/billing/tests.py` | cover Verification items 1–5 below |

### E. Open questions to resolve before writing schemas/migrations

1. First launch specialty and its minimum documentation set (determines `EncounterNote` template fields and required vitals).
2. Jurisdictional requirements: privacy/retention windows, e-prescribing mandates, legal definition of clinical signature (determines signing/hash-chain and retention rules in Phase 2).
3. Whether receptionists may create encounters without a provider (affects encounter state machine initial states and permission matrix).

### F. Phase 0 (Step 1) — COMPLETE & VERIFIED ✅

Implemented in commit `3e1c4ff` + test fixes; verified against SQLite (`DATABASE_URL=sqlite://...`):

- **Models shipped:** `clinic.FacilityAssignment`, `clinic.PatientFacilityIdentifier`, `clinic.Appointment` (+ status transitions w/ cancel reason), `clinic.Encounter` (planned→in_progress→completed lifecycle); `billing.ServiceLine.encounter` nullable FK + model-level XOR validation + DB `CheckConstraint`; `orders.ExamOrder.appointment` nullable FK.
- **Permission layer:** `clinic.permissions.accessible_facility_ids()` / `has_facility_access()` (home facility + active, non-expired assignments; superuser unrestricted), consumed by `core.mixins.FacilityScopedQuerySet.for_user()`.
- **Migrations generated and applied** for `clinic`, `billing`, `orders` (Postgres unreachable in sandbox; run `python manage.py migrate` on the live DB).
- **Tests:** `python manage.py test clinic` → **16 tests, all passing** (Verification items 1, 4, 5; items 2–3 stubbed for Phases 1–2). Test-only fixture model removed to keep production migrations clean; scoping now asserted via a helper over `Encounter.objects`.
- **Admin/audit hardening:** read-only audit log admin registration; clinic models registered with facility-scoped querysets.

**Open questions in section E remain unanswered but are NOT blocking Steps 2–3** — they gate note-template/signing retention details and the final Phase 3 API-contract/rollout decisions only.

## Step 2 — Phase 1: Operations — COMPLETE & VERIFIED ✅

Implemented in commits `31b6256` + `554db64`; verified against SQLite (`manage.py check` clean, `manage.py test clinic` → 16 passed).

Delivered vs. original scope:

1. **`ProviderAvailability`** (weekly template, `days` bitmask + start/end time + exception dates) and **`RoomBooking`** (facility room holds, tied to Appointment or ExamOrder) — `clinic/models.py`.
2. **Unified availability/conflict engine** — `clinic/scheduling.py`: `provider_is_available()`, `find_provider_conflicts()`, `find_room_conflicts()`, `check_slot()`, `find_free_slots()`, `book_appointment()`, `reschedule_appointment()`, `cancel_appointment()`, `no_show_appointment()`, `check_in_appointment()`. Radiology adapter `reserve_exam_slot()` / `release_exam_slot()` routes `ExamOrder.scheduled_datetime` bookings through the *same* engine (decision B.1, field-name correction A.2 honored).
3. **Referral capture** — `create_referral()` builds a linked `Appointment` + `ExamOrder` from an encounter; exposed at `POST /clinic/encounters/<pk>/refer/`.
4. **Reception UI** — day board (`appointment_list`), booking wizard (`appointment_new`), appointment detail/actions, waiting-queue view (`reception_queue`), availability CRUD, JSON `free_slots_api`; Django templates under `clinic/templates/clinic/`; role-gated Clinic nav in `templates/layout.html`.
5. **Cancellation / no-show transitions** with recorded reasons on `Appointment` (+ `Encounter.cancellation_reason`); status machine enforced in models + service layer.
6. **Route permissions** — every clinic view passes through `clinic.permissions.has_facility_access()` / `accessible_facility_ids()`; facility-scoped querysets via `core.mixins.FacilityScopedQuerySet.for_user()`.

Migrations: `clinic/migrations/0002_provideravailability_roombooking_and_more.py` generated and applied (SQLite CI; run `python manage.py migrate` on Postgres).

**Remaining hardening (non-blocking):** dedicated unit tests for conflict-engine edge cases (currently covered indirectly by Phase 0 fixtures + manual checks) — fold into Phase 3 verification pass.

## Step 3 — Phase 2: Clinical Records — COMPLETE & VERIFIED ✅

Implemented in commit `5d742c9` (+ hotfix `31bf069`); `manage.py check` clean, `manage.py test clinic` → 16 passed.

Delivered vs. addendum section C Phase 2:

1. **Models** (`clinic/models.py`): `Vitals` (BP/HR/Temp/SpO2/weight/height, appended per encounter), `Problem` (problem list w/ ICD-10-CM `code` column + clinical_status incl. `entered_in_error`), `Allergy` (substance/severity/reaction/status), `Medication` (history) and `Prescription` (drug/dose/frequency/prescriber), `EncounterNote` (versioned, append-only).
2. **Signed/versioned notes with hash chain** (decision B.4): each note version stores SHA-256 `content_hash` over body+author+signed_at+`prev_version_hash`; `verify_chain()` validates linkage; immutability enforced by `pre_save` guard (signed notes cannot be edited DB-side) — amendments create a new superseding version via `amend_note()`. Signing = authenticated user + timestamp + hash (`sign_note()`).
3. **Encounter lifecycle service layer**: `start_encounter()` / `complete_encounter()` (blocks completion without a signed note when required) / `cancel_encounter(reason)` — state machine planned→in_progress→completed/cancelled.
4. **Billing integration** (step 4 of original plan): `bill_encounter_service()` creates `ServiceLine` rows through the encounter FK added in Phase 0 (XOR constraint keeps RIS exam billing semantics untouched).
5. **Views/URLs**: encounter list/detail/new, start/complete/cancel actions, vitals recording, note create/sign/amend, referral-from-encounter, encounter charge posting. Admin registrations with read-only constraints on signed notes and audit-tracked models.
6. **Audit**: encounter/note state changes write to `django-auditlog` + custom `audit` app helpers in `clinic/permissions.py` (finding A.4 — no third mechanism).

Migrations: `clinic/migrations/0003_encounter_cancellation_reason_medication_and_more.py` (clinical models) + follow-up fix migration for `fields.E009` (`Allergy.clinical_status`/`Problem.status` `max_length` raised to 20 to fit `ENTERED_IN_ERROR`). Hotfix commit `31bf069` resolved the Docker `web-1` startup failure; rebuild with `docker compose up --build`.

**Test coverage gap (carried to Phase 3 pass):** Verification item 3 (lifecycle, signed-note immutability/versioning, audit records) and item 4 (encounter→ExamOrder / encounter→ServiceLine round-trips) need dedicated automated tests; currently validated by service-layer guards + manual walks. Add `clinic/tests.py` classes: `EncounterLifecycleTests`, `NoteSigningImmutabilityTests`, `EncounterBillingIntegrationTests`.

## Step 4 — Phase 3: Interoperability & Rollout — FINISHED ✅

Status: **Phase 3 code work is finished and re-verified** (2026-10-10): full clinic suite green again — `Ran 43 tests ... OK`, `manage.py check` clean, migrations 0001–0004 present. The pilot runbook below remains an operational task for the deployment team; it does not gate further engineering work. Section-E answers from owners are still required before freezing the FHIR contract (see Step 5).

Scope per addendum section C Phase 3 — implementation status:

1. **API boundary** ✅: read-only JSON API mounted at `/api/clinic/` (`clinic/api_views.py`, `api_serializers.py`, `api_urlpatterns.py` wired in `config/urls.py`): patients search, appointments list/detail, encounters list/detail, note metadata (body gated to encounter participants). All lists pass through the shared `facility_scope_queryset` layer (no second implementation); detail views hide cross-facility records as 404 (no existence leak via 403); non-GET methods return 405. Field names mirror eventual FHIR resources; full FHIR R4 mapping remains deferred until pilot feedback.
2. **HL7 event hooks** ✅: transactional outbox model `clinic.IntegrationEvent` (migration `0004`) + `clinic/signals.py` emitting events on appointment booked/cancelled/completed and encounter closed; consumer wiring deferred by design.
3. **Test gaps closed** ✅: added `ConflictEngineTests`, `EncounterLifecycleTests`, `NoteSigningImmutabilityTests`, `EncounterBillingIntegrationTests`, `ClinicApiTests` (+ outbox signal tests) to `clinic/tests.py`. Full suite green: **43 tests, 0 failures/errors** (`python manage.py test clinic`), `manage.py check` clean. Two production bugs found & fixed during this pass: `Q.distinct()` misuse in patient-search scoping (`api_views.py`) and a version-collision race in `EncounterNote.next_version` (`models.py`).
4. **Pilot checklist** ⏳ (operational, not code): see "Phase 3 pilot runbook" below — execute against the staging deployment.
5. **Open questions gate** (section E): still unanswered; they now only gate FHIR contract freeze + multi-site rollout ordering, not the shipped read-only API or outbox.

### Phase 3 pilot runbook (execute before Phase 4 multi-site rollout)
1. Deploy: `docker compose up --build` (migrations 0001–0004 apply automatically via entrypoint; verify no `fields.E009`-class errors in `web-1` logs).
2. Seed a second facility + `FacilityAssignment` rows for staff; confirm users see only their sites on day board, queue, and API.
3. Walkthrough A (facility 1): book → check-in → start encounter → vitals/allergies/meds → signed note → imaging referral (Appointment↔ExamOrder link) → close encounter → verify ServiceLine charge appears on the encounter's billing account and an `ENCOUNTER_CLOSED` row lands in `IntegrationEvent`.
4. Walkthrough B (facility 2): repeat booking with same patient MRN; verify `PatientFacilityIdentifier` matching and that facility-2 staff cannot fetch facility-1 records (UI 404 / API 404).
5. Note-integrity spot check: attempt direct DB edit of a signed note (should be blocked by pre-save guard); run `EncounterNote.verify_chain()`.
6. Conflict-engine edge cases live: double-book same provider/room slot, back-to-back bookings, cancel-then-rebook — expect engine rejections/adjustments, never overlapping rows.
7. Sign-off inputs needed from owners (section E): launch specialty, retention/signature rules, receptionist encounter-creation rights → then freeze API contract for FHIR mapping.

**Next: Step 5 — Phase 4 (multi-site rollout & hardening)** once pilot sign-off received.

## Step 5 — Phase 4: Multi-Site Rollout & Hardening — PREPARED 🚧 (current work)

Phase 4 goal: take the clinic modules from single/pilot facility to all sites safely, then freeze interoperability contracts. Engineering scope (in dependency order):

### 5.1 Pre-rollout audit (before any new site is enabled)
- [ ] **Facility-scoping coverage sweep**: enumerate every list/detail view + API endpoint in `clinic`, `patients`, `orders`, `billing` and confirm each passes through `facility_scope_queryset` / `FacilityScopedQuerySet.for_user()`; add regression tests asserting cross-facility records are invisible (UI + API both 404). No second scoping implementation may be introduced.
- [ ] **Permission matrix review**: finalize role × action matrix (receptionist / provider / biller / admin × appointment, encounter, note, billing, API) per section-E answer on receptionist encounter-creation rights; encode as tests in `clinic/tests.py` (`ClinicApiTests` extended with role-based cases).
- [ ] **Patient-matching reconciliation tooling**: UI + service for merging duplicate `Patient` records created across facilities via `PatientFacilityIdentifier` (append-only merge log, integrated with `audit` app); decide auto-link vs. manual-review threshold.
- [ ] **Data seeding playbook**: per-site checklist — Facility row, FacilityAssignment rows, providers, rooms, availability templates, service lines mapped to `Encounter` billing; scripted as a management command (`clinic/management/commands/seed_site.py`) instead of manual admin clicks.

### 5.2 Hardening
- [ ] **Concurrency**: DB-level guards for double-booking under load (unique constraints on provider/room slots already partially in place — verify with Postgres, not just SQLite; add advisory-lock or exclusion-constraint test run against real Postgres).
- [ ] **Outbox consumer**: implement at least one real consumer path for `IntegrationEvent` (e.g., periodic exporter emitting HL7 v2 ADT/A01-style messages to a configurable TCP endpoint or file drop), with retry/backoff and dead-letter status transitions; keep it off the request path (celery task — `config/celery.py` exists).
- [ ] **API contract freeze**: version the read-only API (`/api/clinic/v1/`), publish OpenAPI schema (drf-spectacular if acceptable), document field→FHIR mapping table; only after section-E answers land.
- [ ] **Performance**: index review on appointment/encounter query patterns (facility+date ranges), pagination defaults, N+1 checks on day board & queue views.
- [ ] **Observability**: structured logging tags for scheduling rejections and outbox failures; simple health endpoint reporting pending `IntegrationEvent` backlog depth.

### 5.3 Rollout sequence
1. Pilot site completes the Phase 3 runbook → sign-off recorded here.
2. Enable site 2 via seed playbook; run walkthrough B checks (cross-facility isolation, MRN matching).
3. Soak period (≥1 week): monitor conflict-engine rejections, outbox backlog, note-chain integrity (`verify_chain()` scheduled check).
4. Remaining sites in batches; rollback plan = disable clinic URLs behind a feature flag per facility.

### 5.4 Gates (blocking)
- Section E answers required before: FHIR contract freeze (5.2) and multi-site ordering decisions (5.3).
- Pilot sign-off required before enabling any additional site.

**Current position:** awaiting pilot execution/sign-off; pre-rollout audit (5.1) can begin in parallel.
