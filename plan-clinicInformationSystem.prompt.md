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

### F. Phase 0 scaffolding — completed in the working repo

The following groundwork is now in place and verified (`manage.py check`: no issues; `makemigrations --check`: no pending changes):

- **`clinic/` app created** with `apps.py`, phase-documented `models.py` (documents which models land in which phase), placeholder `urls.py` (`app_name="clinic"`), `permissions.py` stub (documents the Phase 0 permission API), `admin.py`, `tests.py` (encodes Verification items 1–5 as test targets), and `migrations/__init__.py`.
- **Registered** in `config/settings/base.py` `INSTALLED_APPS` immediately after `patients`.
- **Wired** into `config/urls.py` as `path("clinic/", include("clinic.urls"))`.
- **`core/mixins.py` added**: `FacilityScopedModel` abstract base + `FacilityScopedQuerySet` with `.for_facility()` / `.for_user()` — the reusable scoping layer from decision B.3.
- **`templates/layout.html`**: marked the insertion point for the role-gated Clinic nav (Phase 1), following the existing inventory-dropdown pattern.

**Next actionable step (first real migration):** add `FacilityAssignment` and `PatientFacilityIdentifier` to `clinic/models.py`, then the `ServiceLine.encounter` FK + exclusivity `CheckConstraint` in `billing/models.py` and `ExamOrder.appointment` FK in `orders/models.py` — these three migrations unblock Phases 1–2. Run `python manage.py makemigrations clinic billing orders && python manage.py migrate` against a live DB.