import json

from django.contrib import messages
from django.db.models import Q
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.translation import gettext as _

from patients.models import Patient


def add_patient(request):
    """Handle patient creation page and form submission."""
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


def patient_list(request):
    """Display list of patients with search functionality."""
    query = request.GET.get("q", "")

    patients = Patient.objects.filter(is_deleted=False)

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


def patient_detail(request, pk):
    """Display patient details."""
    patient = get_object_or_404(Patient, pk=pk)
    context = {
        "patient": patient,
    }
    return render(request, "patients/patient_detail.html", context)


def edit_patient(request, pk):
    """Edit an existing patient."""
    patient = get_object_or_404(Patient, pk=pk)

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


def delete_patient(request, pk):
    """Delete a patient (soft delete with audit logging)."""
    from audit.models import AuditLog

    patient = get_object_or_404(Patient, pk=pk)

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


def search_patient(request):
    """HTMX endpoint for searching patients by MRN or name."""
    query = request.GET.get("q", "")

    patients = []
    if query:
        patients = Patient.objects.filter(
            Q(mrn__icontains=query)
            | Q(first_name_en__icontains=query)
            | Q(last_name_en__icontains=query)
            | Q(first_name_ar__icontains=query)
            | Q(last_name_ar__icontains=query)
            | Q(national_id__icontains=query),
        )[:10]  # Limit to 10 results

    context = {
        "patients": patients,
    }
    return render(request, "patients/partials/search_results.html", context)


def patient_lookup(request):
    """API endpoint for patient lookup supporting multiple search fields.

    Returns JSON response with matching patients.
    Search supports: MRN, name (English/Arabic), national ID, phone.
    """
    query = request.GET.get("q", "").strip()

    if not query:
        return JsonResponse({"patients": [], "error": "No search query provided"}, status=400)

    patients = Patient.objects.filter(
        Q(mrn__icontains=query)
        | Q(first_name_en__icontains=query)
        | Q(last_name_en__icontains=query)
        | Q(first_name_ar__icontains=query)
        | Q(last_name_ar__icontains=query)
        | Q(national_id__icontains=query)
        | Q(phone__icontains=query),
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



def patient_search_api(request):
    """Select2-compatible API endpoint for patient search.

    Returns JSON response in Select2 format with pagination support.
    Search supports: MRN, name (English/Arabic), national ID, phone.
    Excludes deleted patients.
    """
    query = request.GET.get("q", "").strip()
    page = int(request.GET.get("page", 1))
    page_size = 20

    if not query:
        return JsonResponse({
            "results": [],
            "pagination": {"more": False}
        })

    patients_qs = Patient.objects.filter(
        is_deleted=False
    ).filter(
        Q(mrn__icontains=query)
        | Q(first_name_en__icontains=query)
        | Q(last_name_en__icontains=query)
        | Q(first_name_ar__icontains=query)
        | Q(last_name_ar__icontains=query)
        | Q(national_id__icontains=query)
        | Q(phone__icontains=query),
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
            'dob': dob_str,
            'gender': p.gender,
        })

    return JsonResponse({
        "results": results,
        "pagination": {"more": has_more}
    })
