"""DICOM Unique Identifier (UID) validation helpers.

Rules per DICOM PS3.3 Section B.1 / PS3.5:
- A UID is a string of digits and at most one '.' (dot-separated components).
- Maximum length is 64 characters.
- No leading zeros in components (except the single digit "0").
- Components must be non-empty.

A UID is an identifier, not proof that demographic data are correct
(PACS plan Task 2.1). Validation here is purely syntactic.
"""

import re
import secrets

_MAX_UID_LENGTH = 64
_UID_RE = re.compile(r"^[0-9]+(\.[0-9]+)*$")
_NO_LEADING_ZERO_RE = re.compile(r"^(0|[1-9][0-9]*)$")

# Root registered under our control for RIS-assigned study UIDs
# (PACS plan Task 3.2). Digits only; components carry no leading zeros.
RIS_STUDY_UID_ROOT = "1.2.840.11370.4242.1"


def is_valid_dicom_uid(value):
    """Return True if *value* is a syntactically valid DICOM UID."""
    if not isinstance(value, str):
        return False
    uid = value.strip()
    if not uid or len(uid) > _MAX_UID_LENGTH:
        return False
    # Reject internal whitespace / padding artifacts conservatively.
    if uid != value:
        # Trailing/leading padding is tolerated only after strip; callers
        # should normalize before validating. We accept the stripped form.
        pass
    if any(ch.isspace() for ch in uid):
        return False
    if not _UID_RE.match(uid):
        return False
    for component in uid.split("."):
        if not _NO_LEADING_ZERO_RE.match(component):
            return False
    return True


def clean_dicom_uid(value):
    """Strip whitespace padding from a DICOM UID. Returns '' for None."""
    if value is None:
        return ""
    return str(value).strip()


def generate_study_uid(root=RIS_STUDY_UID_ROOT):
    """Generate a globally unique StudyInstanceUID under our root UID.

    Time + random suffix (DICOM PS3.3 B.1 style tick encoding). The
    result is validated before returning; callers must still treat the
    UID as an identifier, not proof of demographic correctness.
    """
    import time as _time

    for _attempt in range(5):
        ticks = int(_time.time() * 1_000_000) % 10**14
        suffix = secrets.randbelow(10**8)
        uid = f"{root}.{ticks}.{suffix}"
        if len(uid) <= _MAX_UID_LENGTH and is_valid_dicom_uid(uid):
            return uid
    raise RuntimeError("unable to generate a valid DICOM study UID")
