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
