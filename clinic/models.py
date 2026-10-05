"""Clinic Information System models.

Implementation phases (see plan-clinicInformationSystem.prompt.md):
- Phase 0: FacilityAssignment, PatientFacilityIdentifier (foundations)
- Phase 1: ProviderAvailability, RoomBooking, Appointment (operations)
- Phase 2: Encounter, Vitals, Problem, Allergy, Medication, Prescription,
           EncounterNote (clinical records)

Models are added incrementally per phase; this module intentionally starts
empty so migrations stay aligned with the phased rollout.
"""
