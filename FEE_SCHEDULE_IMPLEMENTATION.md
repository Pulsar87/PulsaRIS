# Fee Schedule Management - Implementation Summary

## Overview
This implementation provides comprehensive fee schedule management for the RIS financial system, following universal standards from GE Centricity, Siemens Syngo, and Philips iSite.

## Components Created

### 1. Django Models (Already in models.py)
- **FeeSchedule**: Master fee schedule container with:
  - Schedule types: CHARGEMASTER, MEDICARE, MEDICAID, COMMERCIAL, CONTRACT, SELF_PAY
  - Effective/expiration date tracking
  - Payer linkage
  - Multi-tenant support
  
- **FeeScheduleItem**: Individual procedure pricing with:
  - CPT/HCPCS procedure codes
  - Modifier support (26, TC, etc.)
  - Three-component fee structure:
    - Professional Fee (PC) - physician interpretation
    - Technical Fee (TC) - equipment/facility
    - Global Fee - combined when applicable
  - Unit of service tracking

### 2. Forms (billing/forms.py)
- `FeeScheduleForm`: ModelForm for schedule header information
- `FeeScheduleItemForm`: ModelForm for procedure items
- `FeeScheduleItemFormSet`: Inline formset for bulk item management

### 3. Views (billing/views.py)
#### Class-Based Views:
- `FeeScheduleListView`: List/filter/search schedules with statistics
- `FeeScheduleDetailView`: Detailed view with items and analytics
- `FeeScheduleCreateView`: Create new schedules
- `FeeScheduleUpdateView`: Edit schedule information
- `FeeScheduleDeleteView`: Soft delete (deactivate) schedules
- `FeeScheduleItemCreateView`: Add items to schedules
- `FeeScheduleItemUpdateView`: Edit procedure items
- `FeeScheduleItemDeleteView`: Remove items

#### API Endpoints:
- `fee_lookup_api`: GET endpoint to lookup fees by procedure code
  - Parameters: procedure_code, modifier, schedule_type, payer_id
  - Returns: All matching fees with component breakdown
  
- `fee_calculate_api`: POST endpoint to calculate total charges
  - Input: JSON array of procedures with codes, modifiers, units
  - Output: Line-item breakdown with total charges

### 4. URL Configuration (billing/urls.py)
```python
/billing/fee-schedules/                    # List
/billing/fee-schedules/create/             # Create
/billing/fee-schedules/<uuid:pk>/          # Detail
/billing/fee-schedules/<uuid:pk>/update/   # Update
/billing/fee-schedules/<uuid:pk>/delete/   # Delete
/billing/fee-schedules/<uuid:pk>/items/add/ # Add item
/billing/fee-schedule-items/<uuid:pk>/update/ # Update item
/billing/fee-schedule-items/<uuid:pk>/delete/ # Delete item
/billing/api/fee-lookup/                   # API lookup
/billing/api/fee-calculate/                # API calculation
```

### 5. Templates
- `fee_schedule_list.html`: Dashboard with filters, search, pagination
- `fee_schedule_detail.html`: Schedule details with statistics and item table
- `fee_schedule_form.html`: Create/edit schedule form with help panel
- `fee_schedule_item_form.html`: Add/edit item form with fee calculator

## Key Features

### 1. Multi-Component Pricing
Supports radiology-specific billing:
- **Professional Component (Modifier 26)**: Radiologist interpretation
- **Technical Component (Modifier TC)**: Equipment, facility, staff
- **Global Fee**: When both components provided by same entity

### 2. Schedule Type Hierarchy
Priority-based fee lookup:
1. CONTRACT (highest priority - negotiated rates)
2. MEDICARE (federal rates)
3. MEDICAID (state rates)
4. COMMERCIAL (private insurance)
5. SELF_PAY (cash patients)
6. CHARGEMASTER (default list prices)

### 3. Date-Effective Pricing
- Effective date enforcement
- Expiration date tracking
- Automatic status calculation (Active/Expired/Inactive)
- Historical rate tracking

### 4. Advanced Filtering & Search
- Filter by status (Active/Expired/Inactive)
- Filter by schedule type
- Search by name, code, or description
- Pagination for large datasets

### 5. Analytics & Reporting
- Item count per schedule
- Average professional/technical/global fees
- Status dashboard with color-coded badges

### 6. API Integration Ready
- RESTful JSON APIs for external integration
- Real-time fee calculation
- Compatible with order entry systems
- Support for batch processing

## Usage Examples

### API: Fee Lookup
```bash
GET /billing/api/fee-lookup/?procedure_code=71045&modifier=26&schedule_type=MEDICARE

Response:
{
  "results": [
    {
      "id": "uuid",
      "procedure_code": "71045",
      "procedure_name": "Chest X-ray, 2 views",
      "modifier": "",
      "fee_schedule_name": "Medicare 2024 National",
      "fee_schedule_type": "MEDICARE",
      "professional_fee": "15.50",
      "technical_fee": "45.00",
      "global_fee": "60.50",
      "calculated_fee": "15.50",  # Based on modifier 26
      "unit_of_service": "EACH"
    }
  ],
  "count": 1
}
```

### API: Fee Calculation
```bash
POST /billing/api/fee-calculate/
Content-Type: application/json

{
  "items": [
    {"procedure_code": "71045", "modifier": "26", "units": 1},
    {"procedure_code": "71046", "modifier": "", "units": 2}
  ],
  "schedule_type": "MEDICARE"
}

Response:
{
  "line_items": [
    {
      "procedure_code": "71045",
      "modifier": "26",
      "units": "1",
      "unit_fee": "15.50",
      "line_total": "15.50",
      "fee_schedule": "Medicare 2024 National"
    },
    {
      "procedure_code": "71046",
      "modifier": "",
      "units": "2",
      "unit_fee": "68.00",
      "line_total": "136.00",
      "fee_schedule": "Medicare 2024 National"
    }
  ],
  "total_charges": "151.50",
  "currency": "USD",
  "calculated_at": "2024-01-15T10:30:00Z"
}
```

## Integration Points

### 1. Charge Capture
When a radiology exam is completed:
```python
from billing.models import FeeScheduleItem

def calculate_exam_charges(exam_order):
    procedure_code = exam_order.procedure.code
    modifier = exam_order.modifier
    
    # Get appropriate fee based on patient insurance
    fee_item = FeeScheduleItem.objects.filter(
        procedure_code=procedure_code,
        fee_schedule__schedule_type=get_schedule_for_patient(exam_order.patient),
        fee_schedule__is_active=True,
    ).first()
    
    if modifier == '26':
        return fee_item.professional_fee
    elif modifier == 'TC':
        return fee_item.technical_fee
    else:
        return fee_item.global_fee or (fee_item.professional_fee + fee_item.technical_fee)
```

### 2. Claim Generation
Service lines use fee schedule items as the basis for claim amounts.

### 3. Contract Management
Contract fee schedules link to specific payers for automated rate application.

## Database Schema

### FeeSchedule
- id (UUID, PK)
- tenant (FK)
- name (VARCHAR)
- code (VARCHAR, unique per tenant)
- description (TEXT)
- schedule_type (CHOICES)
- payer (FK, nullable)
- effective_date (DATE)
- expiration_date (DATE, nullable)
- is_active (BOOLEAN)
- currency (CHAR(3))
- created_by, modified_by (FK User)
- created_at, modified_at (TIMESTAMP)

### FeeScheduleItem
- id (UUID, PK)
- tenant (FK)
- fee_schedule (FK)
- procedure_code (VARCHAR)
- procedure_name (VARCHAR)
- modifier (VARCHAR, nullable)
- professional_fee (DECIMAL)
- technical_fee (DECIMAL)
- global_fee (DECIMAL, nullable)
- unit_of_service (CHOICES)
- description (TEXT)
- created_by, modified_by (FK User)
- created_at, modified_at (TIMESTAMP)

## Best Practices

1. **One Active Schedule Per Type**: Maintain only one active schedule per type/payer combination
2. **Annual Review**: Review and update Medicare/Medicaid rates annually
3. **Effective Dating**: Set future effective dates for upcoming rate changes
4. **Code Validation**: Validate CPT/HCPCS codes against current year code sets
5. **Audit Trail**: All changes tracked with user/timestamp
6. **Soft Deletes**: Deactivate rather than delete to preserve history

## Next Steps

1. **Data Import**: Create management command to import CMS Medicare fee schedules
2. **Code Set Integration**: Integrate with CPT/HCPCS code database
3. **Bulk Upload**: Add CSV import functionality for mass item creation
4. **Version Control**: Implement schedule versioning for audit/compliance
5. **Reporting**: Add fee schedule comparison and variance reports
6. **Approval Workflow**: Add multi-level approval for schedule changes

## Compliance Notes

- HIPAA compliant (no PHI in fee schedules)
- Supports Medicare fee schedule transparency requirements
- Audit trail for all pricing changes
- Multi-tenant data isolation
