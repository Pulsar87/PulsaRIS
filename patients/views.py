import json

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db.models import Avg, Count, Q
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.translation import gettext as _

from clinic.permissions import accessible_facility_ids, patient_scope_queryset
from patients.models import Patient

# Numeric vital columns displayed on the HL7 vitals page (model column ->
# display label). Mirrors integrations.hl7.parsing.NUMERIC_DB_FIELDS order;
# units live in the sibling "<column>_unit" text columns.
HL7_VITAL_LABELS = {
    "spo2": _("SpO2"),
    "pulse_rate": _("Pulse rate"),
    "heart_rate": _("Heart rate"),
    "respiratory_rate": _("Resp. rate"),
    "systolic_bp": _("Systolic BP"),
    "diastolic_bp": _("Diastolic BP"),
    "mean_bp": _("Mean BP"),
    "nibp_pulse_rate": _("NIBP pulse"),
    "body_temperature": _("Temperature"),
    "etco2": _("EtCO2"),
    "fio2": _("FiO2"),
    "weight": _("Weight"),
    "height": _("Height"),
}


def _fmt_number(value):
    """Format a measurement to at most 2 decimals without trailing zeros."""
    if value is None:
        return ""
    return f"{round(float(value), 2):g}"


def _vitals_table_data(qs):
    """Return (rows, columns) for the readings table.

    ``columns`` lists only vitals that actually have readings —
    ``{"key", "label", "unit"}`` — and each row contains ``message`` plus a
    pre-formatted ``values`` list aligned with ``columns`` (empty string when
    the reading lacks that vital). The averages summary row is computed over
    *all* messages in ``qs`` (not just the displayed page).
    """
    aggregate_kwargs = {}
    for column in HL7_VITAL_LABELS:
        aggregate_kwargs[f"avg_{column}"] = Avg(column)
        aggregate_kwargs[f"cnt_{column}"] = Count(column)
    totals = qs.aggregate(**aggregate_kwargs)

    columns = []
    for column, label in HL7_VITAL_LABELS.items():
        count = totals[f"cnt_{column}"]
        if not count:
            continue
        unit_values = (
            qs.exclude(**{f"{column}_unit": ""})
            .exclude(**{f"{column}_unit": None})
            .values(f"{column}_unit")
            .annotate(n=Count("id"))
            .order_by("-n")
        )
        unit = unit_values[0][f"{column}_unit"] if unit_values else ""
        columns.append(
            {
                "key": column,
                "label": label,
                "unit": unit or "",
                "count": count,
                "average": _fmt_number(totals[f"avg_{column}"]),
            }
        )

    rows = []
    for msg in qs.order_by("-received_at")[:500]:
        values = []
        for column in columns:
            value = getattr(msg, column["key"])
            values.append(_fmt_number(value) if value is not None else "")
        rows.append({"message": msg, "values": values})

    return rows, columns


def _hl7_vitals_context(request):
    """Build the readings table + per-vital averages for accepted HL7 messages.

    Non-superusers only see messages whose parsed patient identifier matches a
    patient they are allowed to access (facility scoping, same rule as the rest
    of the patients module).
    """
    from integrations.hl7.models import HL7VitalMessage, MessageStatus

    qs = HL7VitalMessage.objects.filter(status=MessageStatus.ACCEPTED)
    ids = accessible_facility_ids(request.user)
    if ids is not None:
        visible_mrns = list(
            patient_scope_queryset(
                request.user, Patient.objects.filter(is_deleted=False)
            ).values_list("mrn", flat=True)
        )
        # Match on raw and normalized MRN forms (leading-zero variants).
        mrn_candidates = set(visible_mrns)
        for mrn in visible_mrns:
            stripped = mrn.lstrip("0")
            if stripped:
                mrn_candidates.add(stripped)
        qs = qs.filter(parsed_json__patient__patient_id__in=list(mrn_candidates))

    rows, columns = _vitals_table_data(qs)
    total_messages = qs.count()

    return {
        "rows": rows,
        "columns": columns,
        "reading_count": total_messages,
        "truncated": total_messages > len(rows),
    }


@login_required
def hl7_vitals(request):
    """Page listing all HL7 vitals readings with an averages summary row."""
    _require_access(request)
    context = _hl7_vitals_context(request)
    return render(request, "patients/hl7_vitals.html", context)


def _require_access(request):
    if not request.user.is_authenticated:
        raise PermissionDenied("Authentication required.")
    ids = accessible_facility_ids(request.user)
    if ids is not None and not ids:
        raise PermissionDenied("No facility access.")


@login_required
def add_patient(request):
    """Handle patient creation page and form submission."""
    _require_access(request)
    if request.method == "POST":
        # Get form data
        mrn = request.POST.get("mrn", "").strip()
        first_name_en = request.POST.get("first_name_en", "").strip()
        last_name_en = request.POST.get("last_name_en", "").strip()
        first_name_ar = request.POST.get("first_name_ar", "").strip()
        last_name_ar = request.POST.get("last_name_ar", "").strip()
        dob = request.POST.get("dob", "")
        gender = request.POST.get("gender", "")
        nationality = request.POST.get("nationality", "").strip()
        national_id = request.POST.get("national_id", "").strip()
        phone = request.POST.get("phone", "").strip()
        email = request.POST.get("email", "").strip()
        address = request.POST.get("address", "").strip()
        emergency_contact_name = request.POST.get("emergency_contact_name", "").strip()
        emergency_contact_phone = request.POST.get(
            "emergency_contact_phone", ""
        ).strip()
        insurance_provider = request.POST.get("insurance_provider", "").strip()
        insurance_policy_number = request.POST.get(
            "insurance_policy_number", ""
        ).strip()
        consent_data_sharing = request.POST.get("consent_data_sharing") == "on"
        data_retention_until = request.POST.get("data_retention_until", "") or None

        # Basic validation
        if not mrn:
            messages.error(request, _("MRN is required"))
            return redirect("patients:add_patient")

        if not first_name_en or not last_name_en:
            messages.error(request, _("English first name and last name are required"))
            return redirect("patients:add_patient")

        if not dob:
            messages.error(request, _("Date of birth is required"))
            return redirect("patients:add_patient")

        if not gender:
            messages.error(request, _("Gender is required"))
            return redirect("patients:add_patient")

        # Check for duplicate MRN
        if Patient.objects.filter(mrn=mrn).exists():
            messages.error(
                request, _("A patient with this MRN already exists in your system")
            )
            return redirect("patients:add_patient")

        # Create patient
        try:
            patient = Patient.objects.create(
                mrn=mrn,
                first_name_en=first_name_en,
                last_name_en=last_name_en,
                first_name_ar=first_name_ar,
                last_name_ar=last_name_ar,
                dob=dob,
                gender=gender,
                nationality=nationality,
                national_id=national_id,
                phone=phone,
                email=email,
                address=address,
                emergency_contact_name=emergency_contact_name,
                emergency_contact_phone=emergency_contact_phone,
                insurance_provider=insurance_provider,
                insurance_policy_number=insurance_policy_number,
                consent_data_sharing=consent_data_sharing,
                data_retention_until=data_retention_until
                if data_retention_until
                else None,
            )
            messages.success(
                request, _("Patient added successfully! MRN: %(mrn)s") % {"mrn": mrn}
            )
            return redirect("patients:patient_detail", pk=patient.pk)
        except Exception as e:
            messages.error(
                request, _("Error creating patient: %(error)s") % {"error": str(e)}
            )
            return redirect("patients:add_patient")

    return render(request, "patients/add_patient.html")


@login_required
def patient_list(request):
    """Display list of patients with search functionality."""
    _require_access(request)
    query = request.GET.get("q", "")

    patients = patient_scope_queryset(
        request.user, Patient.objects.filter(is_deleted=False)
    )

    if query:
        patients = patients.filter(
            Q(mrn__icontains=query)
            | Q(first_name_en__icontains=query)
            | Q(last_name_en__icontains=query)
            | Q(national_id__icontains=query)
            | Q(phone__icontains=query)
        )

    context = {
        "patients": patients,
        "query": query,
    }
    return render(request, "patients/patient_list.html", context)


@login_required
def patient_detail(request, pk):
    """Display patient details."""
    _require_access(request)
    patient = get_object_or_404(
        patient_scope_queryset(request.user, Patient.objects.filter(is_deleted=False)),
        pk=pk,
    )
    context = {
        "patient": patient,
    }
    return render(request, "patients/patient_detail.html", context)


@login_required
def edit_patient(request, pk):
    """Edit an existing patient."""
    _require_access(request)
    patient = get_object_or_404(
        patient_scope_queryset(request.user, Patient.objects.filter(is_deleted=False)),
        pk=pk,
    )

    if request.method == "POST":
        # Get form data
        mrn = request.POST.get("mrn", "").strip()
        first_name_en = request.POST.get("first_name_en", "").strip()
        last_name_en = request.POST.get("last_name_en", "").strip()
        first_name_ar = request.POST.get("first_name_ar", "").strip()
        last_name_ar = request.POST.get("last_name_ar", "").strip()
        dob = request.POST.get("dob", "")
        gender = request.POST.get("gender", "")
        nationality = request.POST.get("nationality", "").strip()
        national_id = request.POST.get("national_id", "").strip()
        phone = request.POST.get("phone", "").strip()
        email = request.POST.get("email", "").strip()
        address = request.POST.get("address", "").strip()
        emergency_contact_name = request.POST.get("emergency_contact_name", "").strip()
        emergency_contact_phone = request.POST.get(
            "emergency_contact_phone", ""
        ).strip()
        insurance_provider = request.POST.get("insurance_provider", "").strip()
        insurance_policy_number = request.POST.get(
            "insurance_policy_number", ""
        ).strip()
        consent_data_sharing = request.POST.get("consent_data_sharing") == "on"
        data_retention_until = request.POST.get("data_retention_until", "") or None
        is_deceased = request.POST.get("is_deceased") == "on"

        # Basic validation
        if not mrn:
            messages.error(request, _("MRN is required"))
            return redirect("patients:edit_patient", pk=pk)

        if not first_name_en or not last_name_en:
            messages.error(request, _("English first name and last name are required"))
            return redirect("patients:edit_patient", pk=pk)

        if not dob:
            messages.error(request, _("Date of birth is required"))
            return redirect("patients:edit_patient", pk=pk)

        if not gender:
            messages.error(request, _("Gender is required"))
            return redirect("patients:edit_patient", pk=pk)

        # Check for duplicate MRN (excluding current patient)
        if Patient.objects.filter(mrn=mrn).exclude(pk=pk).exists():
            messages.error(
                request, _("A patient with this MRN already exists in your system")
            )
            return redirect("patients:edit_patient", pk=pk)

        # Update patient
        try:
            patient.mrn = mrn
            patient.first_name_en = first_name_en
            patient.last_name_en = last_name_en
            patient.first_name_ar = first_name_ar
            patient.last_name_ar = last_name_ar
            patient.dob = dob
            patient.gender = gender
            patient.nationality = nationality
            patient.national_id = national_id
            patient.phone = phone
            patient.email = email
            patient.address = address
            patient.emergency_contact_name = emergency_contact_name
            patient.emergency_contact_phone = emergency_contact_phone
            patient.insurance_provider = insurance_provider
            patient.insurance_policy_number = insurance_policy_number
            patient.consent_data_sharing = consent_data_sharing
            patient.data_retention_until = data_retention_until if data_retention_until else None
            patient.is_deceased = is_deceased
            patient.save()

            messages.success(request, _("Patient updated successfully!"))
            return redirect("patients:patient_detail", pk=patient.pk)
        except Exception as e:
            messages.error(
                request, _("Error updating patient: %(error)s") % {"error": str(e)}
            )
            return redirect("patients:edit_patient", pk=pk)

    context = {
        "patient": patient,
    }
    return render(request, "patients/edit_patient.html", context)


@login_required
def delete_patient(request, pk):
    """Delete a patient (soft delete with audit logging)."""
    _require_access(request)
    from audit.models import AuditLog

    patient = get_object_or_404(
        patient_scope_queryset(request.user, Patient.objects.filter(is_deleted=False)),
        pk=pk,
    )

    if request.method == "POST":
        try:
            # Store old values for audit
            old_values = {
                'mrn': patient.mrn,
                'first_name_en': patient.first_name_en,
                'last_name_en': patient.last_name_en,
                'first_name_ar': patient.first_name_ar,
                'last_name_ar': patient.last_name_ar,
                'dob': str(patient.dob),
                'gender': patient.gender,
            }

            # Soft delete instead of hard delete
            patient.soft_delete()

            # Create audit log entry
            AuditLog.objects.create(
                user=request.user if request.user.is_authenticated else None,
                action='DELETE',
                entity_type='Patient',
                entity_id=patient.id,
                old_values=old_values,
                new_values={'is_deleted': True, 'deleted_at': str(patient.deleted_at)},
                ip_address=request.META.get('REMOTE_ADDR'),
                user_agent=request.META.get('HTTP_USER_AGENT', '')[:500],
            )

            messages.success(request, _("Patient deleted successfully!"))
            return redirect("patients:patient_list")
        except Exception as e:
            messages.error(
                request, _("Error deleting patient: %(error)s") % {"error": str(e)}
            )
            return redirect("patients:patient_detail", pk=pk)

    context = {
        "patient": patient,
    }
    return render(request, "patients/delete_patient.html", context)


@login_required
def search_patient(request):
    """HTMX endpoint for searching patients by MRN or name."""
    _require_access(request)
    query = request.GET.get("q", "")

    patients = []
    if query:
        patients = patient_scope_queryset(
            request.user,
            Patient.objects.filter(is_deleted=False).filter(
                Q(mrn__icontains=query)
                | Q(first_name_en__icontains=query)
                | Q(last_name_en__icontains=query)
                | Q(first_name_ar__icontains=query)
                | Q(last_name_ar__icontains=query)
                | Q(national_id__icontains=query),
            ),
        )[:10]  # Limit to 10 results

    context = {
        "patients": patients,
    }
    return render(request, "patients/partials/search_results.html", context)


@login_required
def patient_lookup(request):
    """API endpoint for patient lookup supporting multiple search fields.

    Returns JSON response with matching patients.
    Search supports: MRN, name (English/Arabic), national ID, phone.
    """
    _require_access(request)
    query = request.GET.get("q", "").strip()

    if not query:
        return JsonResponse({"patients": [], "error": "No search query provided"}, status=400)

    patients = patient_scope_queryset(
        request.user,
        Patient.objects.filter(is_deleted=False).filter(
            Q(mrn__icontains=query)
            | Q(first_name_en__icontains=query)
            | Q(last_name_en__icontains=query)
            | Q(first_name_ar__icontains=query)
            | Q(last_name_ar__icontains=query)
            | Q(national_id__icontains=query)
            | Q(phone__icontains=query),
        ),
    ).values(
        'id', 'mrn', 'first_name_en', 'last_name_en',
        'first_name_ar', 'last_name_ar', 'dob', 'gender', 'phone'
    )[:20]  # Limit to 20 results

    # Convert to list of dicts with formatted data
    patient_list = []
    for p in patients:
        patient_list.append({
            'id': str(p['id']),
            'mrn': p['mrn'],
            'name_en': f"{p['first_name_en']} {p['last_name_en']}",
            'name_ar': f"{p['first_name_ar']} {p['last_name_ar']}".strip(),
            'dob': p['dob'].isoformat() if p['dob'] else '',
            'gender': p['gender'],
            'phone': p['phone'],
            'display': f"{p['mrn']} - {p['first_name_en']} {p['last_name_en']}"
        })

    return JsonResponse({"patients": patient_list})



@login_required
def patient_search_api(request):
    """Select2-compatible API endpoint for patient search.

    Returns JSON response in Select2 format with pagination support.
    Search supports: MRN, name (English/Arabic), national ID, phone.
    Excludes deleted patients.
    """
    _require_access(request)
    query = request.GET.get("q", "").strip()
    page = int(request.GET.get("page", 1))
    page_size = 20

    if not query:
        return JsonResponse({
            "results": [],
            "pagination": {"more": False}
        })

    patients_qs = patient_scope_queryset(
        request.user,
        Patient.objects.filter(is_deleted=False).filter(
            Q(mrn__icontains=query)
            | Q(first_name_en__icontains=query)
            | Q(last_name_en__icontains=query)
            | Q(first_name_ar__icontains=query)
            | Q(last_name_ar__icontains=query)
            | Q(national_id__icontains=query)
            | Q(phone__icontains=query),
        ),
    ).order_by('last_name_en', 'first_name_en')

    # Check if there are more results
    total_count = patients_qs.count()
    has_more = total_count > page * page_size

    # Get paginated results
    patients_qs = patients_qs[(page-1)*page_size : page*page_size]

    results = []
    for p in patients_qs:
        dob_str = p.dob.strftime('%Y-%m-%d') if p.dob else ''
        gender_display = dict(Patient.GENDER_CHOICES).get(p.gender, '')
        display_text = f"{p.first_name_en} {p.last_name_en} ({p.mrn})"
        if dob_str:
            display_text += f" - {dob_str}"
        if gender_display:
            display_text += f" - {gender_display}"

        results.append({
            'id': str(p.id),
            'text': display_text,
            'mrn': p.mrn,
            'first_name_en': p.first_name_en or '',
            'last_name_en': p.last_name_en or '',
            'first_name_ar': p.first_name_ar or '',
            'last_name_ar': p.last_name_ar or '',
            'dob': dob_str,
            'gender': p.gender,
            'phone': p.phone or '',
        })

    return JsonResponse({
        "results": results,
        "pagination": {"more": has_more}
    })
