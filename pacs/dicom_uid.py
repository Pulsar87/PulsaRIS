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

_MAX_UID_LENGTH = 64
_UID_RE = re.compile(r"^[0-9]+(\.[0-9]+)*$")
_NO_LEADING_ZERO_RE = re.compile(r"^(0|[1-9][0-9]*)$")


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
