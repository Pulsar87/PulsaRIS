from django.test import TestCase  # noqa: F401

# Test coverage targets (plan Verification items 1-5):
# 1. Facility-scoped clinic records with shared patient identity.
# 2. Scheduling conflicts, provider/room availability, check-in,
#    cancellation, no-show transitions.
# 3. Encounter lifecycle, required documentation, signed-note
#    immutability/versioning, audit records.
# 4. Encounter -> ExamOrder and Encounter -> ServiceLine integration
#    without changing existing RIS billing/report workflows.
# 5. Migrations/checks pass; cross-facility manual walk-through.
