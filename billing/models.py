import uuid
from decimal import Decimal

from django.db import models
from django.conf import settings


# ============================================================================
# INSURANCE & PAYER MANAGEMENT
# ============================================================================

class InsurancePayer(models.Model):
    """Insurance company/payer master data - Core entity for Payer Management"""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant = models.ForeignKey("tenants.Tenant", on_delete=models.CASCADE)
    
    # Payer Identification
    payer_id = models.CharField(max_length=50, unique=True, db_index=True, help_text="EDI payer ID (e.g., BCBS, 99999)")
    name = models.CharField(max_length=150)
    short_name = models.CharField(max_length=50, blank=True)
    code = models.CharField(max_length=20, unique=True, help_text="Internal short code")
    
    # Payer Type
    payer_type = models.CharField(
        max_length=20,
        choices=[
            ('COMMERCIAL', 'Commercial'),
            ('MEDICARE', 'Medicare'),
            ('MEDICAID', 'Medicaid'),
            ('SELF_PAY', 'Self Pay'),
            ('WORKERS_COMP', "Workers' Compensation"),
            ('TRICARE', 'Tricare'),
            ('CHAMPVA', 'CHAMPVA'),
            ('AUTO_INSURANCE', 'Auto Insurance'),
            ('OTHER', 'Other'),
        ],
        default='COMMERCIAL',
        db_index=True
    )
    
    # Contact Information
    address_line1 = models.CharField(max_length=150, blank=True)
    address_line2 = models.CharField(max_length=150, blank=True)
    city = models.CharField(max_length=100, blank=True)
    state_province = models.CharField(max_length=50, blank=True)
    postal_code = models.CharField(max_length=20, blank=True)
    country = models.CharField(max_length=3, blank=True)  # ISO 3166-1 alpha-3
    phone = models.CharField(max_length=30, blank=True)
    fax = models.CharField(max_length=30, blank=True)
    email = models.EmailField(blank=True)
    website = models.URLField(blank=True)
    
    # EDI Configuration
    edi_enabled = models.BooleanField(default=False, db_index=True)
    edi_qualifier = models.CharField(max_length=2, blank=True, help_text="e.g., 'PI', 'XV'")
    edi_receiver_id = models.CharField(max_length=50, blank=True, help_text="ISA06/GS02 Receiver ID")
    clearinghouse = models.ForeignKey('Clearinghouse', on_delete=models.SET_NULL, null=True, blank=True, related_name='payers')
    
    # EDI Transaction Specifics
    transmitter_name = models.CharField(max_length=100, blank=True, help_text="Transmitter Name (Loop 1000A)")
    billing_provider_npi = models.CharField(max_length=10, blank=True, help_text="Billing Provider NPI if specific to payer")
    billing_provider_tin = models.CharField(max_length=9, blank=True, help_text="Billing Provider TIN/EIN")
    isa_receiver_id = models.CharField(max_length=15, blank=True, help_text="ISA06 Receiver ID override")
    gs_receiver_id = models.CharField(max_length=15, blank=True, help_text="GS02 Receiver ID override")
    
    # Claim Format Preferences
    claim_format = models.CharField(
        max_length=10, 
        choices=[
            ('837P', 'CMS-1500 / 837P (Professional)'),
            ('837I', 'UB-04 / 837I (Institutional)'),
            ('PAPER', 'Paper Only'),
        ], 
        default='837P'
    )
    
    # Contract & Billing Rules
    fee_schedule = models.ForeignKey('FeeSchedule', on_delete=models.SET_NULL, null=True, blank=True, related_name='payers')
    default_copay = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('0.00'))
    require_auth = models.BooleanField(default=False, help_text="Always require pre-authorization")
    auth_required_for_cpt = models.TextField(blank=True, help_text="Comma-separated CPT codes requiring auth")
    place_of_service_restrictions = models.TextField(blank=True, help_text="Allowed POS codes (comma-separated)")
    
    # ERA/Remittance Rules
    era_enabled = models.BooleanField(default=False)
    era_trace_number_qualifier = models.CharField(max_length=2, default='CI', help_text="Trace Number Qualifier")
    
    # Status
    is_active = models.BooleanField(default=True, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['name']
        indexes = [
            models.Index(fields=['tenant', 'payer_type']),
            models.Index(fields=['tenant', 'is_active']),
            models.Index(fields=['code']),
            models.Index(fields=['edi_enabled']),
        ]

    def __str__(self):
        return f"{self.name} ({self.payer_id})"


class Clearinghouse(models.Model):
    """EDI Clearinghouse configuration for electronic claim submission"""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant = models.ForeignKey("tenants.Tenant", on_delete=models.CASCADE)
    name = models.CharField(max_length=150)
    code = models.CharField(max_length=20, unique=True, help_text="Internal short code")
    
    # Vendor Information
    vendor_name = models.CharField(max_length=150, blank=True)
    support_phone = models.CharField(max_length=30, blank=True)
    support_email = models.EmailField(blank=True)
    website = models.URLField(blank=True)
    
    # Connection Details
    api_endpoint = models.URLField(blank=True, help_text="Base API URL")
    api_username = models.CharField(max_length=100, blank=True)
    api_password = models.CharField(max_length=255, blank=True)  # Encrypted in production
    api_key = models.CharField(max_length=255, blank=True)
    
    # EDI Settings
    sender_id = models.CharField(max_length=50, blank=True, help_text="ISA08 Interchange Sender ID")
    receiver_id = models.CharField(max_length=50, blank=True, help_text="ISA06 Interchange Receiver ID")
    interchange_control_version = models.CharField(max_length=5, default='00501', help_text="EDI version (e.g., 00501)")
    
    # Trading Partner IDs
    trading_partner_id = models.CharField(max_length=50, blank=True, help_text="Clearinghouse-assigned ID")
    
    # Supported Transactions
    supports_837p = models.BooleanField(default=True, help_text="Professional Claims")
    supports_837i = models.BooleanField(default=False, help_text="Institutional Claims")
    supports_835 = models.BooleanField(default=True, help_text="ERA/Remittance Advice")
    supports_270_271 = models.BooleanField(default=True, help_text="Eligibility Inquiry/Response")
    supports_278 = models.BooleanField(default=False, help_text="Authorization Request/Response")
    
    # Transmission Settings
    transmission_protocol = models.CharField(
        max_length=20,
        choices=[
            ('SFTP', 'SFTP'),
            ('HTTPS', 'HTTPS/REST API'),
            ('AS2', 'AS2'),
            ('DIRECT', 'Direct Connect'),
        ],
        default='HTTPS'
    )
    sftp_host = models.CharField(max_length=150, blank=True)
    sftp_port = models.IntegerField(default=22)
    sftp_username = models.CharField(max_length=100, blank=True)
    
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['name']
        indexes = [
            models.Index(fields=['tenant', 'is_active']),
            models.Index(fields=['code']),
        ]

    def __str__(self):
        return f"{self.name} ({self.code})"


class PatientInsurance(models.Model):
    """Patient's insurance coverage information"""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant = models.ForeignKey("tenants.Tenant", on_delete=models.CASCADE)
    patient = models.ForeignKey("patients.Patient", on_delete=models.CASCADE, related_name='insurances')
    payer = models.ForeignKey(InsurancePayer, on_delete=models.PROTECT)
    
    # Coverage Details
    policy_number = models.CharField(max_length=100, db_index=True)
    group_number = models.CharField(max_length=50, blank=True)
    plan_type = models.CharField(max_length=50, blank=True)
    
    # Priority (primary, secondary, tertiary)
    priority = models.IntegerField(default=1)  # 1=primary, 2=secondary, etc.
    
    # Coverage Period
    effective_date = models.DateField()
    termination_date = models.DateField(null=True, blank=True)
    
    # Subscriber Information (may differ from patient)
    subscriber_first_name = models.CharField(max_length=100)
    subscriber_last_name = models.CharField(max_length=100)
    subscriber_middle_name = models.CharField(max_length=100, blank=True)
    subscriber_dob = models.DateField(null=True, blank=True)
    subscriber_gender = models.CharField(
        max_length=1,
        choices=[('M', 'Male'), ('F', 'Female'), ('O', 'Other')],
        blank=True
    )
    relationship_to_patient = models.CharField(
        max_length=10,
        choices=[
            ('SELF', 'Self'),
            ('SPOUSE', 'Spouse'),
            ('CHILD', 'Child'),
            ('PARENT', 'Parent'),
            ('SIBLING', 'Sibling'),
            ('OTHER', 'Other'),
        ],
        default='SELF'
    )
    
    # Additional Coverage Info
    copay_amount = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    deductible_remaining = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    coinsurance_percentage = models.IntegerField(null=True, blank=True, help_text="Percentage (e.g., 80 for 80%)")
    
    # Verification Status
    verified = models.BooleanField(default=False)
    verified_date = models.DateTimeField(null=True, blank=True)
    verification_notes = models.TextField(blank=True)
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['priority']
        indexes = [
            models.Index(fields=['tenant', 'patient', 'priority']),
            models.Index(fields=['tenant', 'policy_number']),
        ]

    def __str__(self):
        return f"{self.patient.mrn} - {self.payer.name} (Priority {self.priority})"


class Authorization(models.Model):
    """Pre-authorization/certification tracking"""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant = models.ForeignKey("tenants.Tenant", on_delete=models.CASCADE)
    exam_order = models.OneToOneField("orders.ExamOrder", on_delete=models.CASCADE, related_name='authorization')
    
    auth_number = models.CharField(max_length=50, db_index=True)
    auth_type = models.CharField(
        max_length=20,
        choices=[
            ('PRE_AUTH', 'Pre-Authorization'),
            ('PRE_CERT', 'Pre-Certification'),
            ('REFERRAL', 'Referral'),
        ]
    )
    status = models.CharField(
        max_length=20,
        choices=[
            ('PENDING', 'Pending'),
            ('APPROVED', 'Approved'),
            ('DENIED', 'Denied'),
            ('EXPIRED', 'Expired'),
            ('CANCELLED', 'Cancelled'),
        ],
        default='PENDING'
    )
    
    # Approval Details
    approved_by = models.CharField(max_length=150, blank=True)  # Insurance reviewer
    approved_date = models.DateTimeField(null=True, blank=True)
    valid_from = models.DateField()
    valid_until = models.DateField()
    
    # Approved Services
    approved_procedures = models.JSONField(default=list, help_text="List of approved CPT codes")
    approved_visits = models.IntegerField(null=True, blank=True, help_text="Number of approved visits")
    authorized_amount = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    
    # Denial Information
    denial_reason = models.TextField(blank=True)
    denial_code = models.CharField(max_length=10, blank=True)  # Standard denial codes
    
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['tenant', 'status']),
            models.Index(fields=['auth_number']),
        ]

    def __str__(self):
        return f"{self.auth_number} - {self.status}"


# ============================================================================
# FEE SCHEDULE & PRICING
# ============================================================================

class FeeSchedule(models.Model):
    """Master fee schedule for procedures"""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant = models.ForeignKey("tenants.Tenant", on_delete=models.CASCADE)
    name = models.CharField(max_length=150)
    description = models.TextField(blank=True)
    
    # Schedule Type
    schedule_type = models.CharField(
        max_length=20,
        choices=[
            ('CHARGEMASTER', 'Chargemaster/List Price'),
            ('MEDICARE', 'Medicare Fee Schedule'),
            ('CONTRACT', 'Contractual Rate'),
            ('SELF_PAY', 'Self-Pay Discounted Rate'),
            ('CASH', 'Cash Price'),
        ],
        default='CHARGEMASTER'
    )
    
    # Applicability
    payer = models.ForeignKey(InsurancePayer, on_delete=models.CASCADE, null=True, blank=True, related_name='fee_schedules')
    modality = models.ForeignKey("tenants.Modality", on_delete=models.CASCADE, null=True, blank=True)
    
    effective_date = models.DateField()
    expiration_date = models.DateField(null=True, blank=True)
    is_default = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['name']
        indexes = [
            models.Index(fields=['tenant', 'schedule_type']),
            models.Index(fields=['tenant', 'is_active']),
        ]

    def __str__(self):
        return f"{self.name} ({self.schedule_type})"


class FeeScheduleItem(models.Model):
    """Individual procedure rates within a fee schedule"""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    fee_schedule = models.ForeignKey(FeeSchedule, on_delete=models.CASCADE, related_name='items')
    
    # Procedure Identification
    procedure_code = models.CharField(max_length=20, db_index=True)  # CPT/HCPCS code
    procedure_description = models.CharField(max_length=250)
    modality = models.ForeignKey("tenants.Modality", on_delete=models.SET_NULL, null=True, blank=True)
    
    # Pricing Components
    professional_component = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('0.00'))
    technical_component = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('0.00'))
    global_fee = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('0.00'))
    
    # Additional Charges
    contrast_charge = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('0.00'))
    sedation_charge = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('0.00'))
    
    # Revenue Code (for UB-04 claims)
    revenue_code = models.CharField(max_length=4, blank=True)
    
    # Units
    default_units = models.DecimalField(max_digits=5, decimal_places=2, default=Decimal('1.00'))
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ['fee_schedule', 'procedure_code']
        ordering = ['procedure_code']

    def __str__(self):
        return f"{self.procedure_code} - {self.procedure_description}"


# ============================================================================
# PATIENT ACCOUNT
# ============================================================================

class PatientAccount(models.Model):
    """Patient's financial account"""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant = models.ForeignKey("tenants.Tenant", on_delete=models.CASCADE)
    patient = models.OneToOneField("patients.Patient", on_delete=models.CASCADE, related_name='financial_account')
    
    # Account Number
    account_number = models.CharField(max_length=50, unique=True, db_index=True)
    
    # Account Status
    account_status = models.CharField(
        max_length=20,
        choices=[
            ('ACTIVE', 'Active'),
            ('CLOSED', 'Closed'),
            ('COLLECTION', 'In Collection'),
            ('BAD_DEBT', 'Bad Debt'),
            ('DECEASED', 'Deceased'),
        ],
        default='ACTIVE'
    )
    
    # Balance Tracking
    current_balance = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('0.00'))
    total_charges = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('0.00'))
    total_payments = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('0.00'))
    total_adjustments = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('0.00'))
    
    # Credit & Limits
    credit_limit = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    
    # Payment Plan
    has_payment_plan = models.BooleanField(default=False)
    payment_plan_balance = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    monthly_payment = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    
    # Financial Assistance
    financial_assistance = models.BooleanField(default=False)
    charity_care = models.BooleanField(default=False)
    
    # Guarantor Information
    guarantor = models.ForeignKey("patients.Patient", on_delete=models.SET_NULL, null=True, blank=True, related_name='guaranteed_accounts')
    
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['tenant', 'account_status']),
            models.Index(fields=['current_balance']),
        ]

    def __str__(self):
        return f"{self.account_number} - {self.patient.mrn}"


# ============================================================================
# CHARGE CAPTURE & BILLING
# ============================================================================

class ServiceLine(models.Model):
    """Individual billable service line item"""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant = models.ForeignKey("tenants.Tenant", on_delete=models.CASCADE)
    exam_order = models.ForeignKey("orders.ExamOrder", on_delete=models.PROTECT, related_name='service_lines')
    patient_account = models.ForeignKey(PatientAccount, on_delete=models.PROTECT, related_name='service_lines')
    
    # Service Details
    service_date = models.DateField(db_index=True)
    procedure_code = models.CharField(max_length=20, db_index=True)  # CPT code
    procedure_name = models.CharField(max_length=250)
    
    # Diagnosis Codes (ICD-10)
    diagnosis_codes = models.JSONField(default=list, help_text="[{'code': 'Z12.31', 'primary': True}, ...]")
    
    # Modifiers
    modifiers = models.JSONField(default=list, help_text="['26', 'TC', '59', etc.]")
    
    # Quantity & Units
    quantity = models.IntegerField(default=1)
    units_of_service = models.CharField(max_length=10, blank=True, help_text="e.g., 'UN', 'MIN'")
    
    # Pricing
    unit_price = models.DecimalField(max_digits=10, decimal_places=2)
    total_charge = models.DecimalField(max_digits=10, decimal_places=2)
    
    # Rendering Provider
    rendering_provider = models.ForeignKey("users.User", on_delete=models.SET_NULL, null=True, related_name='rendered_services')
    supervising_provider = models.ForeignKey("users.User", on_delete=models.SET_NULL, null=True, blank=True)
    
    # Location
    place_of_service = models.CharField(max_length=2, blank=True, help_text="POS code (e.g., '22'=Hospital Outpatient)")
    facility = models.ForeignKey("tenants.Facility", on_delete=models.SET_NULL, null=True, blank=True)
    
    # Billing Status
    billing_status = models.CharField(
        max_length=20,
        choices=[
            ('PENDING', 'Pending Review'),
            ('READY', 'Ready to Bill'),
            ('BILLED', 'Billed'),
            ('PAID', 'Paid'),
            ('DENIED', 'Denied'),
            ('ADJUSTED', 'Adjusted'),
            ('WRITTEN_OFF', 'Written Off'),
        ],
        default='PENDING',
        db_index=True
    )
    
    # Claim Reference
    claim = models.ForeignKey('Claim', on_delete=models.SET_NULL, null=True, blank=True, related_name='service_lines')
    
    audit_notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    billed_at = models.DateTimeField(null=True, blank=True)
    paid_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-service_date']
        indexes = [
            models.Index(fields=['tenant', 'billing_status']),
            models.Index(fields=['tenant', 'service_date']),
            models.Index(fields=['procedure_code']),
        ]

    def __str__(self):
        return f"{self.procedure_code} - {self.service_date} - {self.total_charge}"


class Claim(models.Model):
    """Insurance claim header"""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant = models.ForeignKey("tenants.Tenant", on_delete=models.CASCADE)
    patient_account = models.ForeignKey(PatientAccount, on_delete=models.PROTECT, related_name='claims')
    payer = models.ForeignKey(InsurancePayer, on_delete=models.PROTECT)
    
    # Claim Identification
    claim_number = models.CharField(max_length=50, unique=True, db_index=True)
    internal_claim_id = models.CharField(max_length=50, db_index=True)
    
    # Claim Type
    claim_type = models.CharField(
        max_length=20,
        choices=[
            ('PROFESSIONAL', 'CMS-1500 / 837P'),
            ('INSTITUTIONAL', 'UB-04 / 837I'),
            ('SECONDARY', 'Secondary Claim'),
        ]
    )
    
    # Dates
    date_of_service_from = models.DateField()
    date_of_service_to = models.DateField()
    submission_date = models.DateField(null=True, blank=True)
    
    # Status Tracking
    status = models.CharField(
        max_length=20,
        choices=[
            ('DRAFT', 'Draft'),
            ('SUBMITTED', 'Submitted'),
            ('ACCEPTED', 'Accepted by Payer'),
            ('REJECTED', 'Rejected (Technical)'),
            ('DENIED', 'Denied (Adjudicated)'),
            ('PARTIAL', 'Partially Paid'),
            ('PAID', 'Paid in Full'),
            ('APPEALED', 'Under Appeal'),
        ],
        default='DRAFT',
        db_index=True
    )
    
    # Financial Totals
    total_charges = models.DecimalField(max_digits=12, decimal_places=2)
    expected_insurance = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    expected_patient = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    paid_amount = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('0.00'))
    adjustment_amount = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('0.00'))
    patient_responsibility = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('0.00'))
    
    # EDI Information
    edi_transmission_id = models.CharField(max_length=100, blank=True)
    interchange_control_number = models.CharField(max_length=50, blank=True)
    
    # Clearinghouse Status
    clearinghouse_status = models.CharField(max_length=50, blank=True)
    rejection_reason = models.TextField(blank=True)
    
    # Secondary Claim Reference
    primary_claim = models.ForeignKey('self', on_delete=models.SET_NULL, null=True, blank=True, related_name='secondary_claims')
    
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-date_of_service_from']
        indexes = [
            models.Index(fields=['tenant', 'status']),
            models.Index(fields=['tenant', 'submission_date']),
            models.Index(fields=['claim_number']),
        ]

    def __str__(self):
        return f"{self.claim_number} - {self.status}"


class ClaimLine(models.Model):
    """Individual line items within a claim"""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    claim = models.ForeignKey(Claim, on_delete=models.CASCADE, related_name='lines')
    service_line = models.ForeignKey(ServiceLine, on_delete=models.PROTECT, related_name='claim_lines')
    
    # Line Number
    line_number = models.IntegerField()
    
    # Service Details
    cpt_code = models.CharField(max_length=20)
    modifiers = models.JSONField(default=list)
    diagnosis_pointers = models.JSONField(default=list, help_text="[1, 2, 3] - pointers to diagnosis codes")
    
    # Charges
    charge_amount = models.DecimalField(max_digits=10, decimal_places=2)
    allowed_amount = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    paid_amount = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('0.00'))
    adjustment_amount = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('0.00'))
    
    # Status
    status = models.CharField(
        max_length=20,
        choices=[
            ('PENDING', 'Pending'),
            ('PAID', 'Paid'),
            ('DENIED', 'Denied'),
            ('ADJUSTED', 'Adjusted'),
        ],
        default='PENDING'
    )
    
    # Denial Information
    denial_code = models.CharField(max_length=10, blank=True, help_text="CARC code")
    denial_reason = models.TextField(blank=True)
    remark_codes = models.JSONField(default=list, help_text="RARC codes")
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['line_number']
        unique_together = ['claim', 'line_number']

    def __str__(self):
        return f"Line {self.line_number} - {self.cpt_code}"


# ============================================================================
# PAYMENT POSTING & RECONCILIATION
# ============================================================================

class PaymentPosting(models.Model):
    """Payment and adjustment posting from ERA/EOB"""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant = models.ForeignKey("tenants.Tenant", on_delete=models.CASCADE)
    claim = models.ForeignKey(Claim, on_delete=models.PROTECT, related_name='payment_postings')
    
    # Payment Reference
    posting_date = models.DateField(db_index=True)
    payment_method = models.CharField(
        max_length=20,
        choices=[
            ('ERA', 'Electronic Remittance Advice'),
            ('CHECK', 'Paper Check'),
            ('EFT', 'Electronic Funds Transfer'),
            ('CASH', 'Cash'),
            ('CREDIT_CARD', 'Credit Card'),
        ]
    )
    
    # Payment Details
    check_number = models.CharField(max_length=50, blank=True)
    payment_amount = models.DecimalField(max_digits=10, decimal_places=2)
    
    # ERA Reference
    era_trace_number = models.CharField(max_length=50, blank=True)
    era_file_reference = models.CharField(max_length=100, blank=True)
    
    # Payer Information
    payer = models.ForeignKey(InsurancePayer, on_delete=models.SET_NULL, null=True, blank=True)
    
    # Posting Status
    status = models.CharField(
        max_length=20,
        choices=[
            ('UNPOSTED', 'Received but Not Posted'),
            ('POSTED', 'Posted'),
            ('REVERSED', 'Reversed'),
        ],
        default='UNPOSTED'
    )
    
    posted_by = models.ForeignKey("users.User", on_delete=models.SET_NULL, null=True)
    posted_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-posting_date']
        indexes = [
            models.Index(fields=['tenant', 'status']),
            models.Index(fields=['posting_date']),
        ]

    def __str__(self):
        return f"{self.posting_date} - {self.payment_amount} - {self.status}"


class PaymentDetail(models.Model):
    """Individual payment details per claim line"""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    payment_posting = models.ForeignKey(PaymentPosting, on_delete=models.CASCADE, related_name='details')
    claim_line = models.ForeignKey(ClaimLine, on_delete=models.PROTECT, related_name='payment_details')
    
    # Payment Breakdown
    paid_amount = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('0.00'))
    
    # Adjustments (Contractual, Deductible, Copay, Coinsurance, Denial)
    adjustments = models.JSONField(default=list, help_text="[{'type': 'CO', 'amount': 50.00, 'code': '45', 'reason': 'Fee schedule adjustment'}, ...]")
    # Types: CO (Contractual), PR (Patient Responsibility), FI (Financial Penalty), PI (Payer Initiated)
    
    # Patient Responsibility
    patient_deductible = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('0.00'))
    patient_copay = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('0.00'))
    patient_coinsurance = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('0.00'))
    
    # Denial Information
    is_denied = models.BooleanField(default=False)
    denial_code = models.CharField(max_length=10, blank=True, help_text="CARC")
    denial_reason = models.TextField(blank=True)
    remark_codes = models.JSONField(default=list, help_text="RARC")
    
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Line {self.claim_line.line_number} - Paid: {self.paid_amount}"


# ============================================================================
# PATIENT BILLING
# ============================================================================

class PatientStatement(models.Model):
    """Patient billing statement"""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant = models.ForeignKey("tenants.Tenant", on_delete=models.CASCADE)
    patient_account = models.ForeignKey(PatientAccount, on_delete=models.PROTECT, related_name='statements')
    
    # Statement Details
    statement_number = models.CharField(max_length=50, unique=True, db_index=True)
    statement_date = models.DateField()
    due_date = models.DateField()
    
    # Statement Period
    service_date_from = models.DateField()
    service_date_to = models.DateField()
    
    # Balances
    previous_balance = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('0.00'))
    charges_this_period = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('0.00'))
    payments_this_period = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('0.00'))
    adjustments_this_period = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('0.00'))
    current_balance = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('0.00'))
    
    # Minimum Payment
    minimum_payment_due = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('0.00'))
    
    # Delivery
    delivery_method = models.CharField(
        max_length=10,
        choices=[
            ('MAIL', 'Postal Mail'),
            ('EMAIL', 'Email'),
            ('PORTAL', 'Patient Portal'),
        ],
        default='MAIL'
    )
    sent_date = models.DateField(null=True, blank=True)
    
    # Status
    status = models.CharField(
        max_length=20,
        choices=[
            ('DRAFT', 'Draft'),
            ('SENT', 'Sent'),
            ('PAID', 'Paid in Full'),
            ('PARTIAL', 'Partial Payment'),
            ('OVERDUE', 'Overdue'),
            ('VOID', 'Void'),
        ],
        default='DRAFT'
    )
    
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-statement_date']
        indexes = [
            models.Index(fields=['tenant', 'status']),
            models.Index(fields=['statement_date']),
        ]

    def __str__(self):
        return f"{self.statement_number} - {self.current_balance}"


# ============================================================================
# PAYMENT PROCESSING
# ============================================================================

class Payment(models.Model):
    """Patient payment transaction"""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant = models.ForeignKey("tenants.Tenant", on_delete=models.CASCADE)
    patient_account = models.ForeignKey(PatientAccount, on_delete=models.PROTECT, related_name='payments')
    
    # Payment Details
    payment_date = models.DateTimeField(db_index=True)
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    payment_method = models.CharField(
        max_length=20,
        choices=[
            ('CASH', 'Cash'),
            ('CHECK', 'Check'),
            ('CREDIT_CARD', 'Credit Card'),
            ('DEBIT_CARD', 'Debit Card'),
            ('EFT', 'Electronic Funds Transfer'),
            ('ONLINE', 'Online Payment'),
            ('PAYMENT_PLAN', 'Payment Plan'),
        ]
    )
    
    # Reference Information
    check_number = models.CharField(max_length=50, blank=True)
    card_last_four = models.CharField(max_length=4, blank=True)
    card_type = models.CharField(max_length=20, blank=True)
    transaction_id = models.CharField(max_length=100, blank=True, help_text="Payment gateway reference")
    
    # Allocation
    unapplied_amount = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('0.00'))
    
    # Notes
    notes = models.TextField(blank=True)
    received_by = models.ForeignKey("users.User", on_delete=models.SET_NULL, null=True)
    
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-payment_date']
        indexes = [
            models.Index(fields=['tenant', 'payment_date']),
            models.Index(fields=['payment_method']),
        ]

    def __str__(self):
        return f"{self.payment_date} - {self.amount} - {self.payment_method}"


class PaymentAllocation(models.Model):
    """Allocation of payment to specific service lines"""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    payment = models.ForeignKey(Payment, on_delete=models.CASCADE, related_name='allocations')
    service_line = models.ForeignKey(ServiceLine, on_delete=models.PROTECT)
    
    allocated_amount = models.DecimalField(max_digits=10, decimal_places=2)
    allocation_date = models.DateTimeField(auto_now_add=True)
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ['-allocation_date']

    def __str__(self):
        return f"{self.payment.payment_date} - {self.allocated_amount} -> {self.service_line.procedure_code}"


class PaymentPlan(models.Model):
    """Installment payment plan for patients"""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant = models.ForeignKey("tenants.Tenant", on_delete=models.CASCADE)
    patient_account = models.ForeignKey(PatientAccount, on_delete=models.PROTECT, related_name='payment_plans')
    
    # Plan Terms
    total_amount = models.DecimalField(max_digits=10, decimal_places=2)
    remaining_balance = models.DecimalField(max_digits=10, decimal_places=2)
    monthly_payment = models.DecimalField(max_digits=10, decimal_places=2)
    first_payment_date = models.DateField()
    payment_day = models.IntegerField(help_text="Day of month (1-28)")
    
    # Duration
    number_of_payments = models.IntegerField()
    payments_made = models.IntegerField(default=0)
    
    # Status
    status = models.CharField(
        max_length=20,
        choices=[
            ('ACTIVE', 'Active'),
            ('COMPLETED', 'Completed'),
            ('DEFAULTED', 'Defaulted'),
            ('CANCELLED', 'Cancelled'),
        ],
        default='ACTIVE'
    )
    
    # Terms Agreement
    agreement_signed = models.BooleanField(default=False)
    agreement_date = models.DateField(null=True, blank=True)
    
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['tenant', 'status']),
        ]

    def __str__(self):
        return f"{self.patient_account.account_number} - {self.status} - {self.remaining_balance}"


class PaymentPlanInstallment(models.Model):
    """Individual installment in a payment plan"""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    payment_plan = models.ForeignKey(PaymentPlan, on_delete=models.CASCADE, related_name='installments')
    
    installment_number = models.IntegerField()
    due_date = models.DateField()
    amount_due = models.DecimalField(max_digits=10, decimal_places=2)
    amount_paid = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('0.00'))
    
    status = models.CharField(
        max_length=20,
        choices=[
            ('PENDING', 'Pending'),
            ('PAID', 'Paid'),
            ('LATE', 'Late'),
            ('SKIPPED', 'Skipped'),
        ],
        default='PENDING'
    )
    
    payment = models.ForeignKey(Payment, on_delete=models.SET_NULL, null=True, blank=True)
    paid_date = models.DateField(null=True, blank=True)
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ['installment_number']
        unique_together = ['payment_plan', 'installment_number']

    def __str__(self):
        return f"Installment {self.installment_number} - {self.amount_due} - {self.status}"


# ============================================================================
# DENIAL MANAGEMENT & APPEALS
# ============================================================================

class DenialReason(models.Model):
    """Master table for denial reasons and codes"""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant = models.ForeignKey("tenants.Tenant", on_delete=models.CASCADE)
    
    # Code Systems
    code_system = models.CharField(
        max_length=20,
        choices=[
            ('CARC', 'Claim Adjustment Reason Code'),
            ('RARC', 'Remittance Advice Remark Code'),
            ('OA', 'Other Adjustment'),
            ('INTERNAL', 'Internal Code'),
        ]
    )
    code = models.CharField(max_length=10, db_index=True)
    description = models.TextField()
    category = models.CharField(max_length=50, blank=True, help_text="e.g., 'Eligibility', 'Authorization', 'Coding'")
    
    # Action Required
    requires_appeal = models.BooleanField(default=False)
    appeal_deadline_days = models.IntegerField(default=30)
    common_resolution = models.TextField(blank=True)
    
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ['tenant', 'code_system', 'code']
        ordering = ['code_system', 'code']

    def __str__(self):
        return f"{self.code_system}:{self.code} - {self.description[:50]}"


class ClaimAppeal(models.Model):
    """Track appeals for denied claims"""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant = models.ForeignKey("tenants.Tenant", on_delete=models.CASCADE)
    claim = models.ForeignKey(Claim, on_delete=models.PROTECT, related_name='appeals')
    claim_line = models.ForeignKey(ClaimLine, on_delete=models.PROTECT, null=True, blank=True, related_name='appeals')
    
    # Appeal Details
    appeal_number = models.CharField(max_length=50, unique=True)
    appeal_level = models.CharField(
        max_length=20,
        choices=[
            ('LEVEL1', 'First Level Appeal'),
            ('LEVEL2', 'Second Level Appeal'),
            ('EXTERNAL', 'External Review'),
            ('ADMINISTRATIVE', 'Administrative Appeal'),
        ]
    )
    status = models.CharField(
        max_length=20,
        choices=[
            ('PENDING', 'Pending'),
            ('SUBMITTED', 'Submitted'),
            ('UNDER_REVIEW', 'Under Review'),
            ('APPROVED', 'Approved'),
            ('DENIED', 'Denied'),
            ('WITHDRAWN', 'Withdrawn'),
        ],
        default='PENDING'
    )
    
    # Dates
    filed_date = models.DateField()
    due_date = models.DateField()
    decision_date = models.DateField(null=True, blank=True)
    
    # Documentation
    reason = models.TextField()
    supporting_documents = models.JSONField(default=list, help_text="List of document references")
    submitted_by = models.ForeignKey("users.User", on_delete=models.SET_NULL, null=True)
    
    # Decision
    decision = models.TextField(blank=True)
    reversal_amount = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-filed_date']
        indexes = [
            models.Index(fields=['tenant', 'status']),
            models.Index(fields=['appeal_number']),
        ]

    def __str__(self):
        return f"{self.appeal_number} - {self.status}"
