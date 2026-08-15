from django.http import JsonResponse
from django.db.models import Q
from django.shortcuts import render

from core.models import Facility, Device, Modality


def facility_search_api(request):
    """Select2-compatible API endpoint for facility search.

    Returns JSON response in Select2 format with pagination support.
    Search supports: name, address, contact phone.
    Only returns active facilities.
    """
    query = request.GET.get("q", "").strip()
    page = int(request.GET.get("page", 1))
    page_size = 20

    if not query:
        return JsonResponse({
            "results": [],
            "pagination": {"more": False}
        })

    facilities_qs = Facility.objects.filter(
        is_active=True
    ).filter(
        Q(name__icontains=query)
        | Q(address__icontains=query)
        | Q(contact_phone__icontains=query)
        | Q(dicom_ae_title__icontains=query),
    ).order_by('name')

    # Check if there are more results
    total_count = facilities_qs.count()
    has_more = total_count > page * page_size

    # Get paginated results
    facilities_qs = facilities_qs[(page-1)*page_size : page*page_size]

    results = []
    for f in facilities_qs:
        location_text = ""
        if f.address:
            # Extract city/state from address if available
            address_parts = f.address.split(',')
            if len(address_parts) >= 2:
                location_text = f"{address_parts[-2].strip()}, {address_parts[-1].strip()}"
            else:
                location_text = f.address[:50]

        display_text = f.name
        if location_text:
            display_text += f" - {location_text}"

        results.append({
            'id': str(f.id),
            'text': display_text,
            'name': f.name,
            'address': f.address,
            'dicom_ae_title': f.dicom_ae_title,
        })

    return JsonResponse({
        "results": results,
        "pagination": {"more": has_more}
    })


def device_search_api(request):
    """Select2-compatible API endpoint for device search.

    Returns JSON response in Select2 format with pagination support.
    Search supports: name, room number, DICOM AE title, host, modality.
    Only returns active devices.
    Optionally filters by facility_id if provided.
    """
    query = request.GET.get("q", "").strip()
    page = int(request.GET.get("page", 1))
    page_size = 20
    facility_id = request.GET.get("facility_id", None)

    if not query:
        return JsonResponse({
            "results": [],
            "pagination": {"more": False}
        })

    devices_qs = Device.objects.filter(
        is_active=True
    ).filter(
        Q(name__icontains=query)
        | Q(room_number__icontains=query)
        | Q(dicom_ae_title__icontains=query)
        | Q(dicom_host__icontains=query)
        | Q(modality__code__icontains=query)
        | Q(modality__name__icontains=query),
    )

    # Filter by facility if provided
    if facility_id:
        devices_qs = devices_qs.filter(facility_id=facility_id)

    devices_qs = devices_qs.order_by('modality__code', 'name')

    # Check if there are more results
    total_count = devices_qs.count()
    has_more = total_count > page * page_size

    # Get paginated results
    devices_qs = devices_qs[(page-1)*page_size : page*page_size]

    results = []
    for d in devices_qs:
        facility_text = ""
        if d.facility:
            facility_text = f" @ {d.facility.name}"

        display_text = f"{d.name} - {d.modality.code}{facility_text}"
        if d.room_number:
            display_text += f" (Room {d.room_number})"

        results.append({
            'id': str(d.id),
            'text': display_text,
            'name': d.name,
            'modality_code': d.modality.code,
            'modality_name': d.modality.name,
            'room_number': d.room_number,
            'facility_id': str(d.facility.id) if d.facility else None,
            'facility_name': d.facility.name if d.facility else None,
            'dicom_ae_title': d.dicom_ae_title,
            'dicom_host': d.dicom_host,
            'dicom_port': d.dicom_port,
        })

    return JsonResponse({
        "results": results,
        "pagination": {"more": has_more}
    })
