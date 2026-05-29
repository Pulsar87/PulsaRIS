# Financial System Implementation Plan for Radiology Information System (RIS)

## Executive Summary

This document outlines a comprehensive plan to implement a financial/billing module for the existing RIS platform. The design follows international standards including HL7 FHIR, DICOM Modality Performed Procedure Step (MPPS), and best practices from leading commercial RIS systems (GE Centricity, Siemens Syngo, Philips iSite, Merge RIS).

---

## 1. Financial Requirements Analysis

### 1.1 Core Financial Workflows in RIS

#### A. Pre-Service Financial Activities
1. **Insurance Verification & Eligibility**
   - Real-time insurance eligibility checking
   - Coverage verification (in-network/out-of-network)
   - Pre-authorization/pre-certification tracking
   - Copay/deductible estimation

2. **Price Estimation & Quotation**
   - Procedure-based pricing (CPT/HCPCS codes)
   - Insurance contract rate application
   - Self-pay rate calculation
   - Patient responsibility estimation

#### B. Point-of-Service Financial Activities
3. **Patient Registration & Financial Clearance**
   - Demographic and insurance data capture
   - Consent forms (financial responsibility)
   - Copay collection at time of service
   - Payment plan setup

4. **Order Financial Validation**
   - Authorization number validation
   - Medical necessity checks (ICD-10 to CPT linkage)
   - Referral management

#### C. Post-Service Financial Activities
5. **Charge Capture & Coding**
   - Automatic charge generation from completed procedures
   - CPT/HCPCS code assignment
   - ICD-10 diagnosis code linkage
   - Modifier application (professional/technical components)

6. **Claim Generation & Submission**
   - CMS-1500/UB-04 claim form generation
   - Electronic claim submission (EDI 837P/837I)
   - Claim scrubbing (error detection)
   - Secondary/tertiary claim coordination

7. **Payment Posting & Reconciliation**
   - ERA (Electronic Remittance Advice) processing (EDI 835)
   - EOB (Explanation of Benefits) posting
   - Payment reconciliation
   - Denial management and appeals

8. **Accounts Receivable Management**
   - Aging reports
   - Follow-up workflows
   - Write-off management
   - Collection agency integration

9. **Patient Billing**
   - Statement generation
   - Online payment portal
   - Payment plan management
   - Financial assistance/charity care

---

## 2. Data Model Design

### 2.1 Core Financial Entities

```
┌─────────────────────────────────────────────────────────────────┐
│                    FINANCIAL DOMAIN MODEL                        │
└─────────────────────────────────────────────────────────────────┘

┌──────────────────┐       ┌──────────────────┐
│   InsurancePlan  │◄──────│  PatientGuarantor │
├──────────────────┤       ├──────────────────┤
│ • plan_id        │       │ • guarantor_id   │
│ • payer_name     │       │ • relationship   │
│ • plan_type      │       │ • responsibility │
│ • contract_rates │       └──────────────────┘
│ • copay_rules    │              ▲
│ • deductible_info│              │
└──────────────────┘              │
        ▲                         │
        │                         │
        ▼                         │
┌──────────────────┐       ┌──────────────────┐
│  Authorization   │       │    PatientAccount │
├──────────────────┤       ├──────────────────┤
│ • auth_number    │       │ • account_id     │
│ • status         │       │ • balance        │
│ • valid_from/to  │       │ • credit_limit   │
│ • approved_procs │       └──────────────────┘
│ • referring_md   │              ▲
└──────────────────┘              │
        ▲                         │
        │                         │
        ▼                         ▼
┌──────────────────┐       ┌──────────────────┐       ┌──────────────────┐
│   ExamOrder      │──────►│    ServiceLine   │◄──────│   ChargeItem    │
├──────────────────┤       ├──────────────────┤       ├──────────────────┤
│ • accession_num  │       │ • line_id        │       │ • cpt_code       │
│ • patient_id     │       │ • procedure_code │       │ • description    │
│ • modality       │       │ • cpt_code       │       │ • unit_price     │
│ • status         │       │ • icd10_codes    │       │ • modifier       │
└──────────────────┘       │ • quantity       │       │ • revenue_code   │
                           │ • unit_price     │       └──────────────────┘
                           │ • total_amount   │              ▲
                           │ • billing_status │              │
                           └──────────────────┘              │
                                   ▲                         │
                                   │                         │
                                   ▼                         │
                           ┌──────────────────┐              │
                           │     Claim        │──────────────┘
                           ├──────────────────┤
                           │ • claim_id       │
                           │ • claim_number   │
                           │ • claim_type     │
                           │ • submission_date│
                           │ • status         │
                           │ • total_charges  │
                           │ • insurance_amt  │
                           │ • patient_amt    │
                           └──────────────────┘
                                   ▲
                                   │
                           ┌──────────────────┐
                           │   PaymentPosting │
                           ├──────────────────┤
                           │ • posting_id     │
                           │ • era_reference  │
                           │ • payment_date   │
                           │ • payment_amount │
                           │ • adjustment_amt │
                           │ • denial_reason  │
                           └──────────────────┘
```

### 2.2 Django Models Specification

#### A. Insurance & Payer Management

```python
class InsurancePayer(models.Model):
    """Insurance company/payer master data"""
    id = UUIDField(primary_key=True)
    tenant = ForeignKey(Tenant)
    payer_id = CharField(max_length=50, unique=True)  # EDI payer ID
    name = CharField(max_length=150)
    type = ChoiceField(choices=['COMMERCIAL', 'MEDICARE', 'MEDICAID', 'SELF_PAY', 'WORKERS_COMP'])
    address = TextField()
    phone = CharField(max_length=30)
    email = EmailField()
    website = URLField()
    
    # EDI Configuration
    edi_qualifier = CharField(max_length=2)  # e.g., 'PI', 'XV'
    edi_receiver_id = CharField(max_length=50)
    clearinghouse = ForeignKey('Clearinghouse', null=True)
    
    # Contract Settings
    fee_schedule = ForeignKey('FeeSchedule', null=True)
    default_copay = DecimalField(max_digits=10, decimal_places=2)
    is_active = BooleanField(default=True)


class PatientInsurance(models.Model):
    """Patient's insurance coverage information"""
    id = UUIDField(primary_key=True)
    tenant = ForeignKey(Tenant)
    patient = ForeignKey(Patient)
    payer = ForeignKey(InsurancePayer)
    
    # Coverage Details
    policy_number = CharField(max_length=100)
    group_number = CharField(max_length=50, blank=True)
    plan_type = CharField(max_length=50, blank=True)
    
    # Priority (primary, secondary, tertiary)
    priority = IntegerField()  # 1=primary, 2=secondary, etc.
    
    # Coverage Period
    effective_date = DateField()
    termination_date = DateField(null=True, blank=True)
    
    # Subscriber Information (may differ from patient)
    subscriber_first_name = CharField(max_length=100)
    subscriber_last_name = CharField(max_length=100)
    subscriber_dob = DateField()
    subscriber_gender = ChoiceField(choices=[('M', 'Male'), ('F', 'Female')])
    relationship_to_patient = ChoiceField(choices=['SELF', 'SPOUSE', 'CHILD', 'PARENT', 'OTHER'])
    
    # Additional Coverage Info
    is_primary = BooleanField(default=False)
    copay_amount = DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    deductible_remaining = DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    
    class Meta:
        ordering = ['priority']


class Authorization(models.Model):
    """Pre-authorization/certification tracking"""
    id = UUIDField(primary_key=True)
    tenant = ForeignKey(Tenant)
    exam_order = OneToOneField(ExamOrder, on_delete=models.CASCADE)
    
    auth_number = CharField(max_length=50)
    auth_type = ChoiceField(choices=['PRE_AUTH', 'PRE_CERT', 'REFERRAL'])
    status = ChoiceField(choices=['PENDING', 'APPROVED', 'DENIED', 'EXPIRED'])
    
    # Approval Details
    approved_by = CharField(max_length=150)  # Insurance reviewer
    approved_date = DateTimeField()
    valid_from = DateField()
    valid_until = DateField()
    
    # Approved Services
    approved_procedures = JSONField()  # List of approved CPT codes
    approved_visits = IntegerField(null=True, blank=True)  # Number of approved visits
    authorized_amount = DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    
    # Denial Information
    denial_reason = TextField(blank=True)
    denial_code = CharField(max_length=10, blank=True)  # Standard denial codes
    
    created_at = DateTimeField(auto_now_add=True)
    updated_at = DateTimeField(auto_now=True)
```

#### B. Fee Schedule & Pricing

```python
class FeeSchedule(models.Model):
    """Master fee schedule for procedures"""
    id = UUIDField(primary_key=True)
    tenant = ForeignKey(Tenant)
    name = CharField(max_length=150)
    description = TextField(blank=True)
    
    # Schedule Type
    schedule_type = ChoiceField(choices=[
        ('CHARGEMASTER', 'Chargemaster/List Price'),
        ('MEDICARE', 'Medicare Fee Schedule'),
        ('CONTRACT', 'Contractual Rate'),
        ('SELF_PAY', 'Self-Pay Discounted Rate'),
    ])
    
    # Applicability
    payer = ForeignKey(InsurancePayer, null=True, blank=True)
    modality = ForeignKey(Modality, null=True, blank=True)
    
    effective_date = DateField()
    expiration_date = DateField(null=True, blank=True)
    is_default = BooleanField(default=False)
    is_active = BooleanField(default=True)
    
    created_at = DateTimeField(auto_now_add=True)
    updated_at = DateTimeField(auto_now=True)


class FeeScheduleItem(models.Model):
    """Individual procedure rates within a fee schedule"""
    id = UUIDField(primary_key=True)
    fee_schedule = ForeignKey(FeeSchedule, on_delete=models.CASCADE)
    
    # Procedure Identification
    procedure_code = CharField(max_length=20)  # CPT/HCPCS code
    procedure_description = CharField(max_length=250)
    modality = ForeignKey(Modality, null=True)
    
    # Pricing Components
    professional_component = DecimalField(max_digits=10, decimal_places=2)  # Physician fee
    technical_component = DecimalField(max_digits=10, decimal_places=2)  # Facility fee
    global_fee = DecimalField(max_digits=10, decimal_places=2)  # Combined fee
    
    # Additional Charges
    contrast_charge = DecimalField(max_digits=10, decimal_places=2, default=0)
    sedation_charge = DecimalField(max_digits=10, decimal_places=2, default=0)
    
    # Revenue Code (for UB-04 claims)
    revenue_code = CharField(max_length=4, blank=True)
    
    class Meta:
        unique_together = ['fee_schedule', 'procedure_code']


class PatientAccount(models.Model):
    """Patient's financial account"""
    id = UUIDField(primary_key=True)
    tenant = ForeignKey(Tenant)
    patient = ForeignKey(Patient)
    
    # Account Status
    account_status = ChoiceField(choices=[
        ('ACTIVE', 'Active'),
        ('CLOSED', 'Closed'),
        ('COLLECTION', 'In Collection'),
        ('BAD_DEBT', 'Bad Debt'),
    ])
    
    # Balance Tracking
    current_balance = DecimalField(max_digits=12, decimal_places=2, default=0)
    total_charges = DecimalField(max_digits=12, decimal_places=2, default=0)
    total_payments = DecimalField(max_digits=12, decimal_places=2, default=0)
    total_adjustments = DecimalField(max_digits=12, decimal_places=2, default=0)
    
    # Credit & Limits
    credit_limit = DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    
    # Payment Plan
    has_payment_plan = BooleanField(default=False)
    payment_plan_balance = DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    monthly_payment = DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    
    # Financial Assistance
    financial_assistance = BooleanField(default=False)
    charity_care = BooleanField(default=False)
    
    created_at = DateTimeField(auto_now_add=True)
    updated_at = DateTimeField(auto_now=True)
```

#### C. Charge Capture & Billing

```python
class ServiceLine(models.Model):
    """Individual billable service line item"""
    id = UUIDField(primary_key=True)
    tenant = ForeignKey(Tenant)
    exam_order = ForeignKey(ExamOrder, on_delete=models.PROTECT)
    patient_account = ForeignKey(PatientAccount, on_delete=models.PROTECT)
    
    # Service Details
    service_date = DateField()
    procedure_code = CharField(max_length=20)  # CPT code
    procedure_name = CharField(max_length=250)
    
    # Diagnosis Codes (ICD-10)
    diagnosis_codes = JSONField()  # [{'code': 'Z12.31', 'primary': True}, ...]
    
    # Modifiers
    modifiers = JSONField(default=list)  # ['26', 'TC', '59', etc.]
    
    # Quantity & Units
    quantity = IntegerField(default=1)
    units_of_service = CharField(max_length=10, blank=True)  # e.g., 'UN', 'MIN'
    
    # Pricing
    unit_price = DecimalField(max_digits=10, decimal_places=2)
    total_charge = DecimalField(max_digits=10, decimal_places=2)
    
    # Rendering Provider
    rendering_provider = ForeignKey('users.User', null=True)  # Radiologist
    supervising_provider = ForeignKey('users.User', null=True, blank=True)
    
    # Location
    place_of_service = CharField(max_length=2)  # POS code (e.g., '22'=Hospital Outpatient)
    facility = ForeignKey(Facility, null=True)
    
    # Billing Status
    billing_status = ChoiceField(choices=[
        ('PENDING', 'Pending Review'),
        ('READY', 'Ready to Bill'),
        ('BILLED', 'Billed'),
        ('PAID', 'Paid'),
        ('DENIED', 'Denied'),
        ('ADJUSTED', 'Adjusted'),
        ('WRITTEN_OFF', 'Written Off'),
    ], default='PENDING')
    
    # Audit
    created_at = DateTimeField(auto_now_add=True)
    updated_at = DateTimeField(auto_now=True)
    billed_at = DateTimeField(null=True, blank=True)
    paid_at = DateTimeField(null=True, blank=True)


class Claim(models.Model):
    """Insurance claim header"""
    id = UUIDField(primary_key=True)
    tenant = ForeignKey(Tenant)
    patient_account = ForeignKey(PatientAccount, on_delete=models.PROTECT)
    payer = ForeignKey(InsurancePayer)
    
    # Claim Identification
    claim_number = CharField(max_length=50, unique=True)
    internal_claim_id = CharField(max_length=50, db_index=True)
    
    # Claim Type
    claim_type = ChoiceField(choices=[
        ('PROFESSIONAL', 'CMS-1500 / 837P'),
        ('INSTITUTIONAL', 'UB-04 / 837I'),
        ('SECONDARY', 'Secondary Claim'),
    ])
    
    # Dates
    date_of_service_from = DateField()
    date_of_service_to = DateField()
    submission_date = DateField(null=True, blank=True)
    
    # Status Tracking
    status = ChoiceField(choices=[
        ('DRAFT', 'Draft'),
        ('SUBMITTED', 'Submitted'),
        ('ACCEPTED', 'Accepted by Payer'),
        ('REJECTED', 'Rejected (Technical)'),
        ('DENIED', 'Denied (Adjudicated)'),
        ('PARTIAL', 'Partially Paid'),
        ('PAID', 'Paid in Full'),
        ('APPEALED', 'Under Appeal'),
    ], default='DRAFT')
    
    # Financial Totals
    total_charges = DecimalField(max_digits=12, decimal_places=2)
    expected_insurance = DecimalField(max_digits=12, decimal_places=2, null=True)
    expected_patient = DecimalField(max_digits=12, decimal_places=2, null=True)
    paid_amount = DecimalField(max_digits=12, decimal_places=2, default=0)
    adjustment_amount = DecimalField(max_digits=12, decimal_places=2, default=0)
    patient_responsibility = DecimalField(max_digits=12, decimal_places=2, default=0)
    
    # EDI Information
    edi_transmission_id = CharField(max_length=100, blank=True)
    interchange_control_number = CharField(max_length=50, blank=True)
    
    # Clearinghouse Status
    clearinghouse_status = CharField(max_length=50, blank=True)
    rejection_reason = TextField(blank=True)
    
    created_at = DateTimeField(auto_now_add=True)
    updated_at = DateTimeField(auto_now=True)


class ClaimLine(models.Model):
    """Individual line items within a claim"""
    id = UUIDField(primary_key=True)
    claim = ForeignKey(Claim, on_delete=models.CASCADE, related_name='lines')
    service_line = ForeignKey(ServiceLine, on_delete=models.PROTECT)
    
    # Line Number
    line_number = IntegerField()
    
    # Service Details
    cpt_code = CharField(max_length=20)
    modifiers = JSONField(default=list)
    diagnosis_pointers = JSONField()  # [1, 2, 3] - pointers to diagnosis codes
    
    # Charges
    charge_amount = DecimalField(max_digits=10, decimal_places=2)
    allowed_amount = DecimalField(max_digits=10, decimal_places=2, null=True)
    paid_amount = DecimalField(max_digits=10, decimal_places=2, default=0)
    adjustment_amount = DecimalField(max_digits=10, decimal_places=2, default=0)
    
    # Status
    status = ChoiceField(choices=[
        ('PENDING', 'Pending'),
        ('PAID', 'Paid'),
        ('DENIED', 'Denied'),
        ('ADJUSTED', 'Adjusted'),
    ], default='PENDING')
    
    # Denial Information
    denial_code = CharField(max_length=10, blank=True)  # CARC code
    denial_reason = TextField(blank=True)
    remark_codes = JSONField(default=list)  # RARC codes


class PaymentPosting(models.Model):
    """Payment and adjustment posting from ERA/EOB"""
    id = UUIDField(primary_key=True)
    tenant = ForeignKey(Tenant)
    claim = ForeignKey(Claim, on_delete=models.PROTECT)
    
    # Payment Reference
    posting_date = DateField()
    payment_method = ChoiceField(choices=[
        ('ERA', 'Electronic Remittance Advice'),
        ('CHECK', 'Paper Check'),
        ('EFT', 'Electronic Funds Transfer'),
        ('CASH', 'Cash'),
        ('CREDIT_CARD', 'Credit Card'),
    ])
    
    # Payment Details
    check_number = CharField(max_length=50, blank=True)
    payment_amount = DecimalField(max_digits=10, decimal_places=2)
    
    # ERA Reference
    era_trace_number = CharField(max_length=50, blank=True)
    era_file_reference = CharField(max_length=100, blank=True)
    
    # Payer Information
    payer = ForeignKey(InsurancePayer, null=True)
    
    # Posting Status
    status = ChoiceField(choices=[
        ('UNPOSTED', 'Received but Not Posted'),
        ('POSTED', 'Posted'),
        ('REVERSED', 'Reversed'),
    ], default='UNPOSTED')
    
    posted_by = ForeignKey('users.User', null=True)
    posted_at = DateTimeField(null=True, blank=True)
    created_at = DateTimeField(auto_now_add=True)


class PaymentDetail(models.Model):
    """Individual payment details per claim line"""
    id = UUIDField(primary_key=True)
    payment_posting = ForeignKey(PaymentPosting, on_delete=models.CASCADE, related_name='details')
    claim_line = ForeignKey(ClaimLine, on_delete=models.PROTECT)
    
    # Payment Breakdown
    paid_amount = DecimalField(max_digits=10, decimal_places=2, default=0)
    
    # Adjustments (Contractual, Deductible, Copay, Coinsurance, Denial)
    adjustments = JSONField(default=list)
    # Format: [{'type': 'CO', 'amount': 50.00, 'code': '45', 'reason': 'Fee schedule adjustment'}, ...]
    # Types: CO (Contractual), PR (Patient Responsibility), FI (Financial Penalty), PI (Payer Initiated)
    
    # Patient Responsibility
    patient_deductible = DecimalField(max_digits=10, decimal_places=2, default=0)
    patient_copay = DecimalField(max_digits=10, decimal_places=2, default=0)
    patient_coinsurance = DecimalField(max_digits=10, decimal_places=2, default=0)
    
    # Denial Information
    is_denied = BooleanField(default=False)
    denial_code = CharField(max_length=10, blank=True)  # CARC
    denial_reason = TextField(blank=True)
    remark_codes = JSONField(default=list)  # RARC


class PatientStatement(models.Model):
    """Patient billing statement"""
    id = UUIDField(primary_key=True)
    tenant = ForeignKey(Tenant)
    patient_account = ForeignKey(PatientAccount, on_delete=models.PROTECT)
    
    # Statement Details
    statement_number = CharField(max_length=50, unique=True)
    statement_date = DateField()
    due_date = DateField()
    
    # Statement Period
    service_date_from = DateField()
    service_date_to = DateField()
    
    # Balances
    previous_balance = DecimalField(max_digits=10, decimal_places=2)
    charges_this_period = DecimalField(max_digits=10, decimal_places=2)
    payments_this_period = DecimalField(max_digits=10, decimal_places=2)
    adjustments_this_period = DecimalField(max_digits=10, decimal_places=2)
    current_balance = DecimalField(max_digits=10, decimal_places=2)
    
    # Minimum Payment
    minimum_payment_due = DecimalField(max_digits=10, decimal_places=2)
    
    # Delivery
    delivery_method = ChoiceField(choices=[
        ('MAIL', 'Postal Mail'),
        ('EMAIL', 'Email'),
        ('PORTAL', 'Patient Portal'),
    ])
    sent_date = DateField(null=True, blank=True)
    
    # Status
    status = ChoiceField(choices=[
        ('DRAFT', 'Draft'),
        ('SENT', 'Sent'),
        ('PAID', 'Paid in Full'),
        ('PARTIAL', 'Partial Payment'),
        ('OVERDUE', 'Overdue'),
    ], default='DRAFT')
    
    created_at = DateTimeField(auto_now_add=True)
```

#### D. Payment Processing

```python
class Payment(models.Model):
    """Patient payment transaction"""
    id = UUIDField(primary_key=True)
    tenant = ForeignKey(Tenant)
    patient_account = ForeignKey(PatientAccount, on_delete=models.PROTECT)
    
    # Payment Details
    payment_date = DateTimeField()
    amount = DecimalField(max_digits=10, decimal_places=2)
    payment_method = ChoiceField(choices=[
        ('CASH', 'Cash'),
        ('CHECK', 'Check'),
        ('CREDIT_CARD', 'Credit Card'),
        ('DEBIT_CARD', 'Debit Card'),
        ('EFT', 'Electronic Funds Transfer'),
        ('ONLINE', 'Online Payment'),
        ('PAYMENT_PLAN', 'Payment Plan'),
    ])
    
    # Reference Information
    check_number = CharField(max_length=50, blank=True)
    card_last_four = CharField(max_length=4, blank=True)
    card_type = CharField(max_length=20, blank=True)
    transaction_id = CharField(max_length=100, blank=True)  # Payment gateway reference
    
    # Allocation
    unapplied_amount = DecimalField(max_digits=10, decimal_places=2, default=0)
    
    # Notes
    notes = TextField(blank=True)
    received_by = ForeignKey('users.User', null=True)
    
    created_at = DateTimeField(auto_now_add=True)


class PaymentAllocation(models.Model):
    """Allocation of payment to specific service lines"""
    id = UUIDField(primary_key=True)
    payment = ForeignKey(Payment, on_delete=models.CASCADE)
    service_line = ForeignKey(ServiceLine, on_delete=models.PROTECT)
    
    allocated_amount = DecimalField(max_digits=10, decimal_places=2)
    allocation_date = DateTimeField(auto_now_add=True)


class PaymentPlan(models.Model):
    """Installment payment plan for patients"""
    id = UUIDField(primary_key=True)
    tenant = ForeignKey(Tenant)
    patient_account = ForeignKey(PatientAccount, on_delete=models.PROTECT)
    
    # Plan Terms
    total_amount = DecimalField(max_digits=10, decimal_places=2)
    remaining_balance = DecimalField(max_digits=10, decimal_places=2)
    monthly_payment = DecimalField(max_digits=10, decimal_places=2)
    first_payment_date = DateField()
    payment_day = IntegerField()  # Day of month (1-28)
    
    # Duration
    number_of_payments = IntegerField()
    payments_made = IntegerField(default=0)
    
    # Status
    status = ChoiceField(choices=[
        ('ACTIVE', 'Active'),
        ('COMPLETED', 'Completed'),
        ('DEFAULTED', 'Defaulted'),
        ('CANCELLED', 'Cancelled'),
    ], default='ACTIVE')
    
    # Terms Agreement
    agreement_signed = BooleanField(default=False)
    agreement_date = DateField(null=True, blank=True)
    
    created_at = DateTimeField(auto_now_add=True)
    updated_at = DateTimeField(auto_now=True)


class PaymentPlanInstallment(models.Model):
    """Individual installment in a payment plan"""
    id = UUIDField(primary_key=True)
    payment_plan = ForeignKey(PaymentPlan, on_delete=models.CASCADE, related_name='installments')
    
    installment_number = IntegerField()
    due_date = DateField()
    amount_due = DecimalField(max_digits=10, decimal_places=2)
    amount_paid = DecimalField(max_digits=10, decimal_places=2, default=0)
    
    status = ChoiceField(choices=[
        ('PENDING', 'Pending'),
        ('PAID', 'Paid'),
        ('LATE', 'Late'),
        ('SKIPPED', 'Skipped'),
    ], default='PENDING')
    
    payment = ForeignKey(Payment, null=True, blank=True)
    paid_date = DateField(null=True, blank=True)
```

---

## 3. Process Flow Models

### 3.1 Order-to-Cash Workflow

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                         ORDER-TO-CASH PROCESS FLOW                          │
└─────────────────────────────────────────────────────────────────────────────┘

┌─────────────┐    ┌─────────────┐    ┌─────────────┐    ┌─────────────┐
│   ORDER     │───►│  SCHEDULE   │───►│   CHECK-IN  │───►│  PERFORM    │
│  CREATION   │    │   EXAM      │    │   PATIENT   │    │   EXAM      │
└─────────────┘    └─────────────┘    └─────────────┘    └─────────────┘
       │                  │                  │                  │
       ▼                  ▼                  ▼                  ▼
  • Verify          • Confirm          • Collect           • Complete
    insurance         insurance          copay               procedure
  • Check             eligibility      • Verify            • Document
    authorization   • Estimate          demographics        all services
  • Price             patient            & insurance       • Capture
    estimate          responsibility   • Obtain              charges
                                       signatures
                                           │
                                           ▼
                                    ┌─────────────┐
                                    │   REPORT    │
                                    │   EXAM      │
                                    └─────────────┘
                                           │
                                           ▼
                                    ┌─────────────┐
                                    │  GENERATE   │
                                    │   CLAIM     │
                                    └─────────────┘
                                           │
                              ┌────────────┴────────────┐
                              ▼                         ▼
                       ┌─────────────┐          ┌─────────────┐
                       │  SUBMIT TO  │          │  PATIENT    │
                       │  PAYER/EDI  │          │  STATEMENT  │
                       └─────────────┘          └─────────────┘
                              │                         │
                              ▼                         ▼
                       ┌─────────────┐          ┌─────────────┐
                       │   RECEIVE   │          │   COLLECT   │
                       │   ERA/EOB   │          │   PAYMENT   │
                       └─────────────┘          └─────────────┘
                              │                         │
                              ▼                         ▼
                       ┌─────────────┐          ┌─────────────┐
                       │   POST      │          │   APPLY     │
                       │  PAYMENTS   │          │  PAYMENT    │
                       └─────────────┘          └─────────────┘
                              │                         │
                              └────────────┬────────────┘
                                           ▼
                                    ┌─────────────┐
                                    │ RECONCILE & │
                                    │    CLOSE    │
                                    └─────────────┘
```

### 3.2 Claim Lifecycle State Machine

```
┌──────────────────────────────────────────────────────────────────┐
│                    CLAIM LIFECYCLE STATES                        │
└──────────────────────────────────────────────────────────────────┘

    ┌─────────┐
    │  DRAFT  │ ◄──── Create claim from service lines
    └────┬────┘
         │
         ▼
    ┌─────────┐
    │SUBMITTED│ ◄──── Transmit via EDI/Clearinghouse
    └────┬────┘
         │
    ┌────┴────┐
    │         │
    ▼         ▼
┌─────────┐ ┌─────────┐
│ ACCEPTED│ │ REJECTED│ ◄──── Technical rejection (fix & resubmit)
└────┬────┘ └────┬────┘
     │           │
     │           └──────────────────────┐
     ▼                                  │
┌─────────┐                             │
│ PENDING │ ◄──── Awaiting adjudication │
│ADJUDICATION                        │
└────┬────┘                             │
     │                                  │
     ├──────────────┬──────────────┬────┘
     ▼              ▼              ▼
┌─────────┐  ┌─────────┐   ┌──────────┐
│  PAID   │  │ DENIED  │   │ PARTIAL  │
└────┬────┘  └────┬────┘   └────┬─────┘
     │           │              │
     │     ┌─────┴─────┐        │
     │     │           │        │
     │     ▼           ▼        │
     │ ┌──────┐  ┌────────┐     │
     │ │APPEAL│  │WRITE-OFF│     │
     │ └──┬───┘  └────────┘     │
     │    │                     │
     │    └──────────┬──────────┘
     │               │
     ▼               ▼
┌─────────────────────────┐
│      CLOSED/RESOLVED    │
└─────────────────────────┘
```

### 3.3 Payment Posting Workflow

```
┌─────────────────────────────────────────────────────────────────┐
│                   PAYMENT POSTING WORKFLOW                      │
└─────────────────────────────────────────────────────────────────┘

         ┌──────────────┐
         │ RECEIVE ERA  │ (EDI 835) or Paper EOB
         │    FILE      │
         └──────┬───────┘
                │
                ▼
         ┌──────────────┐
         │ PARSE &      │
         │ VALIDATE     │
         └──────┬───────┘
                │
                ▼
         ┌──────────────┐
         │ AUTO-MATCH   │ Match to claims by claim number
         │   CLAIMS     │
         └──────┬───────┘
                │
         ┌──────┴──────┐
         │             │
         ▼             ▼
    ┌─────────┐   ┌──────────┐
    │ MATCHED │   │ UNMATCHED│
    └────┬────┘   └────┬─────┘
         │             │
         │             ▼
         │      ┌──────────────┐
         │      │ MANUAL       │
         │      │ RECONCILIATION│
         │      └──────┬───────┘
         │             │
         ▼             │
    ┌──────────────────┘
    │
    ▼
┌──────────────┐
│ POST         │ For each claim line:
│ DETAILS      │ • Record payment
└──────┬───────┘ • Record adjustments
       │        • Update balances
       │
       ▼
┌──────────────┐
│ UPDATE       │ • Service line status
│ STATUSES     │ • Claim status
└──────┬───────┘ • Patient account balance
       │
       ▼
┌──────────────┐
│ GENERATE     │ If balance remains:
│ PATIENT      │ • Create statement
│ STATEMENTS   │ • Send to patient
└──────┬───────┘
       │
       ▼
┌──────────────┐
│ RECONCILE    │ Match to bank deposit
│ WITH BANK    │
└──────────────┘
```

---

## 4. Integration Points

### 4.1 External System Integrations

```
┌─────────────────────────────────────────────────────────────────┐
│                    RIS FINANCIAL INTEGRATIONS                   │
└─────────────────────────────────────────────────────────────────┘

┌─────────────────┐         ┌─────────────────┐
│  ELIGIBILITY    │◄─HL7/V2─┤   CLEARINGHOUSE │
│  VERIFICATION   │         │  (Change Healthcare)│
│  SYSTEM         │         │  • Claims (837)  │
└─────────────────┘         │  • ERA (835)     │
                            │  • Eligibility   │
┌─────────────────┐         └─────────────────┘
│  EHR/EMR        │◄─HL7/FHIR
│  (Epic, Cerner) │
└─────────────────┘
                            ┌─────────────────┐
┌─────────────────┐         │  PAYMENT        │
│  PACS/DICOM     │◄─MPPS───┤  GATEWAY        │
│  MPPS Messages  │         │  (Stripe, PayPal)│
└─────────────────┘         └─────────────────┘

┌─────────────────┐         ┌─────────────────┐
│  CODING         │◄─API────┤  ANALYTICS &    │
│  DATABASE       │         │  REPORTING      │
│  (CPT, ICD-10)  │         │  (Power BI)     │
└─────────────────┘         └─────────────────┘
```

### 4.2 HL7 Message Types

| Message Type | Direction | Purpose |
|-------------|-----------|---------|
| DFT^P03 | Inbound | Patient registration with financial class |
| BAR^P01 | Inbound | Add patient account information |
| QEL^E22 | Outbound | Eligibility inquiry |
| ELS^E23 | Inbound | Eligibility response |
| REF^I12 | Outbound | Authorization request |
| RQA^I13 | Inbound | Authorization response |
| HCQ^Q22 | Outbound | Health care services invoice query |

### 4.3 EDI Transaction Sets

| Transaction | ASC X12 Code | Purpose |
|------------|--------------|---------|
| Professional Claim | 837P | Submit CMS-1500 claims electronically |
| Institutional Claim | 837I | Submit UB-04 claims electronically |
| Remittance Advice | 835 | Receive payment & adjustment details |
| Eligibility Inquiry | 270 | Check patient insurance eligibility |
| Eligibility Response | 271 | Receive eligibility determination |
| Claim Status Inquiry | 276 | Check claim processing status |
| Claim Status Response | 277 | Receive claim status update |

---

## 5. Implementation Phases

### Phase 1: Foundation (Weeks 1-6)
**Goal:** Core data model and basic charge capture

- [ ] Create all database models
- [ ] Implement fee schedule management
- [ ] Build insurance/payer master data management
- [ ] Integrate with existing ExamOrder model
- [ ] Basic charge capture from completed exams
- [ ] Simple patient account creation

### Phase 2: Claims Management (Weeks 7-12)
**Goal:** Claim generation and submission

- [ ] Claim generation engine
- [ ] CMS-1500 form generation (PDF)
- [ ] EDI 837P file generation
- [ ] Clearinghouse integration (test environment)
- [ ] Claim status tracking
- [ ] Basic reporting dashboard

### Phase 3: Payment Processing (Weeks 13-18)
**Goal:** Payment posting and reconciliation

- [ ] ERA (835) parsing and auto-posting
- [ ] Manual payment posting interface
- [ ] Payment allocation logic
- [ ] Patient statement generation
- [ ] Basic accounts receivable aging
- [ ] Bank reconciliation tools

### Phase 4: Advanced Features (Weeks 19-24)
**Goal:** Full revenue cycle management

- [ ] Eligibility verification integration
- [ ] Pre-authorization workflow
- [ ] Denial management and appeals tracking
- [ ] Payment plan management
- [ ] Online payment portal integration
- [ ] Advanced analytics and KPI dashboards
- [ ] Automated follow-up workflows

### Phase 5: Optimization & Compliance (Weeks 25-30)
**Goal:** Production readiness and compliance

- [ ] HIPAA security audit
- [ ] PCI-DSS compliance for payment processing
- [ ] Performance optimization
- [ ] User acceptance testing
- [ ] Staff training materials
- [ ] Go-live preparation

---

## 6. Key Reports & Analytics

### 6.1 Operational Reports

1. **Daily Charge Capture Report**
   - Procedures performed but not yet billed
   - Missing documentation alerts

2. **Claim Submission Report**
   - Claims submitted today
   - Rejection rate analysis
   - First-pass acceptance rate

3. **Payment Posting Report**
   - Payments received by payer
   - Unapplied cash report
   - Deposit reconciliation

### 6.2 Financial Reports

4. **Accounts Receivable Aging**
   - 0-30 days
   - 31-60 days
   - 61-90 days
   - 90+ days

5. **Denial Management Report**
   - Top denial reasons
   - Denial rate by payer
   - Appeal success rate

6. **Revenue Analysis**
   - Revenue by modality
   - Revenue by procedure code
   - Revenue by referring physician
   - Revenue by payer mix

7. **Collection Metrics**
   - Days in A/R
   - Net collection rate
   - Gross collection rate
   - Cost to collect

### 6.3 Compliance Reports

8. **Audit Trail Report**
   - All financial transactions
   - User activity logs
   - Changes to claims/payments

9. **HIPAA Privacy Report**
   - Access to PHI
   - Disclosure logs

---

## 7. Security & Compliance Considerations

### 7.1 HIPAA Compliance
- All PHI encrypted at rest and in transit
- Role-based access control (RBAC)
- Comprehensive audit logging
- Business Associate Agreements (BAA) with vendors
- Regular security risk assessments

### 7.2 PCI-DSS Compliance
- Never store full credit card numbers
- Use tokenization for recurring payments
- Secure payment gateway integration
- Regular PCI compliance scans

### 7.3 SOX Compliance (if applicable)
- Segregation of duties
- Financial controls
- Change management procedures
- Documentation requirements

---

## 8. Technology Stack Recommendations

### Backend
- **Framework:** Django (existing) + Django REST Framework
- **Database:** PostgreSQL (existing) with django-tenants
- **Task Queue:** Celery (existing) for async tasks
- **EDI Processing:** Custom parser or library like `python-edi`

### Frontend
- **Templates:** Django Templates + HTMX (existing)
- **JavaScript:** Alpine.js or Vue.js for dynamic components
- **Charts:** Chart.js or Apache ECharts for dashboards

### Integrations
- **Clearinghouse:** Change Healthcare, Availity, or Waystar APIs
- **Eligibility:** real-time eligibility APIs (Teladoc Health, Experian)
- **Payment Gateway:** Stripe, Square, or PayPal Braintree
- **Document Generation:** WeasyPrint or ReportLab for PDFs

---

## 9. Database Schema Migration Strategy

Given the existing multi-tenant architecture with `django-tenants`:

1. **Create migration files** in new `billing` app
2. **Add to TENANT_APPS** in settings
3. **Migrate shared tables** (payers, fee schedules) to public schema if global
4. **Migrate tenant-specific tables** to each tenant schema
5. **Data seeding** for standard code sets (CPT, ICD-10, revenue codes)

---

## 10. Success Metrics

| Metric | Target | Measurement Frequency |
|--------|--------|----------------------|
| First-pass claim acceptance rate | >95% | Weekly |
| Days in Accounts Receivable | <40 days | Monthly |
| Net collection rate | >96% | Monthly |
| Claim denial rate | <5% | Weekly |
| Average payment posting time | <48 hours | Daily |
| Patient satisfaction (billing) | >4.5/5 | Quarterly |
| Bad debt percentage | <3% | Monthly |

---

## Conclusion

This financial system implementation plan provides a comprehensive roadmap for adding enterprise-grade billing and revenue cycle management to your RIS. The modular design allows for phased implementation while maintaining compatibility with your existing multi-tenant Django architecture.

Key success factors:
1. **Start with accurate charge capture** - garbage in, garbage out
2. **Automate where possible** - ERA auto-posting, claim scrubbing
3. **Monitor KPIs continuously** - early detection of issues
4. **Train staff thoroughly** - proper coding and documentation
5. **Maintain compliance** - HIPAA, PCI-DSS, and payer-specific rules

The proposed system aligns with industry standards and will scale with your organization's growth.
