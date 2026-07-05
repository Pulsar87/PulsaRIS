"""
EDI Services for HIPAA X12 Transactions
Supports: 837P (Professional Claims), 837I (Institutional Claims), 835 (ERA)
"""
import json
from datetime import datetime
from decimal import Decimal
from typing import List, Dict, Optional, Any
from dataclasses import dataclass, asdict
import uuid

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from .models import (
    Claim, ClaimLine, ServiceLine, PaymentPosting, PaymentDetail,
    InsurancePayer, Clearinghouse, PatientAccount, DenialReason
)


# ============================================================================
# DATA CLASSES FOR EDI SEGMENTS
# ============================================================================

@dataclass
class ISA_Segment:
    """Interchange Control Header"""
    sender_id_qualifier: str = "ZZ"
    sender_id: str = ""
    receiver_id_qualifier: str = "ZZ"
    receiver_id: str = ""
    interchange_date: str = ""
    interchange_time: str = ""
    repetition_separator: str = "^"
    interchange_control_version: str = "00501"
    interchange_control_number: str = ""
    acknowledgment_requested: str = "1"
    usage_indicator: str = "P"  # P=Production, T=Test
    component_element_separator: str = ">"


@dataclass
class GS_Segment:
    """Functional Group Header"""
    functional_identifier: str = "HC"  # HC=Healthcare Claim
    application_sender_code: str = ""
    application_receiver_code: str = ""
    date: str = ""
    time: str = ""
    group_control_number: str = ""
    responsible_agency: str = "X"
    version: str = "005010X222A1"


@dataclass
class ST_Segment:
    """Transaction Set Header"""
    transaction_set_identifier: str = "837"
    transaction_set_control_number: str = ""


@dataclass
class BHT_Segment:
    """Beginning of Hierarchical Transaction"""
    hierarchical_structure_code: str = "0011"
    transaction_set_purpose: str = "00"  # 00=Original
    reference_identification: str = ""
    date: str = ""
    time: str = ""


@dataclass
class NM1_Billing_Provider:
    """Billing Provider Name"""
    entity_identifier: str = "2"  # 2=Provider
    entity_type: str = "2"  # 1=Person, 2=Non-Person
    name_last: str = ""
    name_first: str = ""
    npi: str = ""
    tax_id: str = ""


@dataclass
class NM1_Subscriber:
    """Subscriber Name"""
    entity_identifier: str = "0"
    entity_type: str = "1"  # 1=Person
    name_last: str = ""
    name_first: str = ""
    member_id: str = ""


@dataclass
class DMG_Subscriber:
    """Subscriber Demographics"""
    date_of_birth: str = ""
    gender: str = ""  # M=Male, F=Female


@dataclass
class REF_Claim:
    """Claim Reference"""
    reference_id_qualifier: str = "D9"  # D9=Claim Number
    reference_id: str = ""


@dataclass
class CLM_Claim:
    """Claim Information"""
    claim_id: str = ""
    total_charge: Decimal = Decimal('0.00')
    facility_code: str = ""
    claim_frequency: str = "1"  # 1=Original
    signature_indicator: str = "Y"
    assignment_benefits: str = "Y"
    release_info: str = "N"
    provider_accept_assignment: str = "Y"
    epsdt_flag: str = ""
    special_program_indicator: str = ""


@dataclass
class SVC_Service_Line:
    """Service Line Information"""
    composite_rate_code: Dict = None  # {'id': 'CPT', 'code': '99213'}
    charge_amount: Decimal = Decimal('0.00')
    unit_rate: Decimal = Decimal('0.00')
    service_unit_count: int = 1
    diagnosis_pointer: str = ""
    service_modifiers: List[str] = None
    place_of_service: str = ""


@dataclass
class DTP_Service_Date:
    """Date/Time - Service Date"""
    date_time_qualifier: str = "472"  # 472=Service
    date_format_qualifier: str = "D8"  # D8=YYYYMMDD
    date: str = ""


@dataclass
class HI_Diagnosis:
    """Health Care Code Information - Diagnosis"""
    code_list_qualifier: str = "ABK"  # ABK=ICD-10-CM
    diagnosis_code: str = ""


# ============================================================================
# EDI 837 GENERATOR (PROFESSIONAL CLAIMS)
# ============================================================================

class EDI837Generator:
    """Generate HIPAA X12 837P Professional Claim files"""
    
    def __init__(self, claim: Claim):
        self.claim = claim
        self.segments = []
        self.control_number = str(uuid.uuid4())[:9]
        
    def generate(self) -> str:
        """Generate complete 837P file content"""
        self.segments = []
        
        # Interchange Control Header
        self._add_isa()
        
        # Functional Group Header
        self._add_gs()
        
        # Transaction Set
        self._add_transaction_set()
        
        # Functional Group Trailer
        self._add_ge()
        
        # Interchange Control Trailer
        self._add_iea()
        
        return self._join_segments()
    
    def _add_isa(self):
        """Add ISA segment"""
        now = timezone.now()
        isa = ISA_Segment(
            sender_id=settings.EDI_SENDER_ID if hasattr(settings, 'EDI_SENDER_ID') else "",
            receiver_id=self.claim.payer.edi_receiver_id if self.claim.payer else "",
            interchange_date=now.strftime("%y%m%d"),
            interchange_time=now.strftime("%H%M"),
            interchange_control_number=self.control_number.zfill(9),
        )
        # Format: ISA*00*          *00*          *ZZ*SENDER_ID      *ZZ*RECEIVER_ID    *230101*1200*^*00501*000000001*1*P*>
        segment = f"ISA*{isa.sender_id_qualifier}*{isa.sender_id.ljust(10)}*{isa.receiver_id_qualifier}*{isa.receiver_id.ljust(10)}*{isa.interchange_date}*{isa.interchange_time}*{isa.repetition_separator}*{isa.interchange_control_version}*{isa.interchange_control_number}*{isa.acknowledgment_requested}*{isa.usage_indicator}*{isa.component_element_separator}"
        self.segments.append(segment)
    
    def _add_gs(self):
        """Add GS segment"""
        now = timezone.now()
        gs = GS_Segment(
            application_sender_code=settings.EDI_SENDER_ID if hasattr(settings, 'EDI_SENDER_ID') else "",
            application_receiver_code=self.claim.payer.payer_id if self.claim.payer else "",
            date=now.strftime("%Y%m%d"),
            time=now.strftime("%H%M%S"),
            group_control_number=self.control_number,
        )
        segment = f"GS*{gs.functional_identifier}*{gs.application_sender_code}*{gs.application_receiver_code}*{gs.date}*{gs.time}*{gs.group_control_number}*{gs.responsible_agency}*{gs.version}"
        self.segments.append(segment)
    
    def _add_transaction_set(self):
        """Add ST, BHT, and claim details"""
        # ST Segment
        st = ST_Segment(transaction_set_control_number=self.control_number)
        self.segments.append(f"ST*{st.transaction_set_identifier}*{st.transaction_set_control_number}")
        
        # BHT Segment
        now = timezone.now()
        bht = BHT_Segment(
            reference_identification=self.claim.claim_number,
            date=now.strftime("%Y%m%d"),
            time=now.strftime("%H%M"),
        )
        self.segments.append(f"BHT*{bht.hierarchical_structure_code}*{bht.transaction_set_purpose}*{bht.reference_identification}*{bht.date}*{bht.time}")
        
        # Billing Provider
        self._add_billing_provider()
        
        # Subscriber/Patient
        self._add_subscriber()
        
        # Claim Level
        self._add_claim_level()
        
        # Service Lines
        self._add_service_lines()
        
        # SE Segment (Transaction Set Trailer)
        segment_count = len([s for s in self.segments if s.startswith(('NM1', 'REF', 'DMG', 'CLM', 'SVC', 'DTP', 'HI'))]) + 4  # ST, BHT, SE + segments
        self.segments.append(f"SE*{segment_count}*{st.transaction_set_control_number}")
    
    def _add_billing_provider(self):
        """Add billing provider information"""
        # Placeholder - would need to integrate with providers app
        # NM1*Billing Provider*2*LastName*FirstName***XX*NPI~
        self.segments.append("NM1*85*2*BILLING*PROVIDER***XX*0000000000")
        self.segments.append("N3*123 MAIN STREET")
        self.segments.append("N4*CITY*STATE*ZIPCODE")
    
    def _add_subscriber(self):
        """Add subscriber/patient information"""
        patient = self.claim.patient_account.patient if hasattr(self.claim.patient_account, 'patient') else None
        if patient:
            nm1 = NM1_Subscriber(
                name_last=getattr(patient, 'last_name', ''),
                name_first=getattr(patient, 'first_name', ''),
                member_id=getattr(patient, 'mrn', ''),
            )
            self.segments.append(f"NM1*IL*1*{nm1.name_last}*{nm1.name_first}**MB*{nm1.member_id}")
            
            if hasattr(patient, 'date_of_birth'):
                dob = getattr(patient, 'date_of_birth', None)
                if dob:
                    self.segments.append(f"DMG*D8*{dob.strftime('%Y%m%d')}*{getattr(patient, 'gender', 'U')}")
    
    def _add_claim_level(self):
        """Add claim level information"""
        # REF segment for claim number
        ref = REF_Claim(reference_id=self.claim.claim_number)
        self.segments.append(f"REF*{ref.reference_id_qualifier}*{ref.reference_id}")
        
        # CLM segment
        clm = CLM_Claim(
            claim_id=self.claim.claim_number,
            total_charge=self.claim.total_charges,
            facility_code="22" if self.claim.claim_type == "PROFESSIONAL" else "",
        )
        self.segments.append(f"CLM*{clm.claim_id}*{clm.total_charge}***{clm.facility_code}:{clm.claim_frequency}*{clm.signature_indicator}*{clm.assignment_benefits}*{clm.release_info}*{clm.provider_accept_assignment}")
        
        # DTP for service dates
        self.segments.append(f"DTP*472*D8*{self.claim.date_of_service_from.strftime('%Y%m%d')}-{self.claim.date_of_service_to.strftime('%Y%m%d')}")
        
        # Diagnosis codes from service lines
        diagnosis_codes = []
        for line in self.claim.lines.all():
            if line.service_line and line.service_line.diagnosis_codes:
                for dx in line.service_line.diagnosis_codes:
                    if isinstance(dx, dict) and dx.get('code') not in diagnosis_codes:
                        diagnosis_codes.append(dx['code'])
        
        for i, dx_code in enumerate(diagnosis_codes[:12], 1):  # Max 12 diagnosis codes
            self.segments.append(f"HI*ABK:{dx_code}")
    
    def _add_service_lines(self):
        """Add service line items"""
        for line in self.claim.lines.all():
            svc = SVC_Service_Line(
                composite_rate_code={'id': 'CPT', 'code': line.cpt_code},
                charge_amount=line.charge_amount,
                unit_rate=line.charge_amount / line.service_line.quantity if line.service_line and line.service_line.quantity > 0 else line.charge_amount,
                service_unit_count=line.service_line.quantity if line.service_line else 1,
                place_of_service=line.service_line.place_of_service if line.service_line else "",
            )
            
            modifiers_str = ":".join(line.modifiers) if line.modifiers else ""
            diag_ptr = ":".join(str(p) for p in line.diagnosis_pointers) if line.diagnosis_pointers else "1"
            
            line_str = f"SVC*{svc.composite_rate_code['id']}:{svc.composite_rate_code['code']}"
            if modifiers_str:
                line_str += f":{modifiers_str}"
            line_str += f"*{svc.charge_amount}*{svc.unit_rate}*{svc.service_unit_count}*{diag_ptr}"
            
            if svc.place_of_service:
                line_str += f"*{svc.place_of_service}"
                
            self.segments.append(line_str)
            
            # DTP for service line date
            if line.service_line:
                self.segments.append(f"DTP*472*D8*{line.service_line.service_date.strftime('%Y%m%d')}")
    
    def _add_ge(self):
        """Add GE segment (Functional Group Trailer)"""
        self.segments.append(f"GE*1*{self.control_number}")
    
    def _add_iea(self):
        """Add IEA segment (Interchange Control Trailer)"""
        self.segments.append(f"IEA*1*{self.control_number.zfill(9)}")
    
    def _join_segments(self) -> str:
        """Join all segments with tilde delimiter"""
        return "~\n".join(self.segments) + "~\n"


# ============================================================================
# EDI 835 PARSER (ELECTRONIC REMITTANCE ADVICE)
# ============================================================================

class EDI835Parser:
    """Parse HIPAA X12 835 ERA files and create payment postings"""
    
    def __init__(self, file_content: str, tenant):
        self.content = file_content
        self.tenant = tenant
        self.segments = self._parse_segments()
        self.payment_postings = []
        
    def _parse_segments(self) -> List[str]:
        """Split content into segments"""
        return self.content.replace('\n', '').split('~')
    
    def parse(self) -> List[PaymentPosting]:
        """Parse ERA and create payment posting records"""
        current_claim = None
        current_clp_segment = None
        current_cas_segments = []
        current_lx_segments = []
        
        for segment in self.segments:
            parts = segment.split('*')
            if not parts:
                continue
                
            segment_id = parts[0]
            
            if segment_id == 'CLP':
                # Claim Payment Information
                current_claim = self._process_clp(parts)
                current_cas_segments = []
                current_lx_segments = []
                
            elif segment_id == 'CAS' and current_claim:
                # Claim Adjustment Segment
                current_cas_segments.append(parts)
                
            elif segment_id == 'LX' and current_claim:
                # Service Line Identification
                current_lx_segments.append(parts)
                
            elif segment_id == 'PLB' and current_claim:
                # Provider Level Adjustment - finalize claim
                if current_claim:
                    posting = self._create_payment_posting(current_claim, current_cas_segments, current_lx_segments)
                    if posting:
                        self.payment_postings.append(posting)
        
        return self.payment_postings
    
    def _process_clp(self, parts: List[str]) -> Dict:
        """Process CLP segment - Claim Payment Information"""
        # CLP*CLAIM_NUM*STATUS*PAID*CHARGED*ALLOWED*DEDUCTIBLE*COINSURANCE*COPAY
        return {
            'claim_number': parts[1] if len(parts) > 1 else '',
            'status': parts[2] if len(parts) > 2 else '',
            'paid_amount': Decimal(parts[3]) if len(parts) > 3 and parts[3] else Decimal('0.00'),
            'charged_amount': Decimal(parts[4]) if len(parts) > 4 and parts[4] else Decimal('0.00'),
            'allowed_amount': Decimal(parts[5]) if len(parts) > 5 and parts[5] else Decimal('0.00'),
            'deductible': Decimal(parts[6]) if len(parts) > 6 and parts[6] else Decimal('0.00'),
            'coinsurance': Decimal(parts[7]) if len(parts) > 7 and parts[7] else Decimal('0.00'),
            'copay': Decimal(parts[8]) if len(parts) > 8 and parts[8] else Decimal('0.00'),
        }
    
    def _create_payment_posting(self, claim_data: Dict, cas_segments: List, lx_segments: List) -> Optional[PaymentPosting]:
        """Create PaymentPosting record from parsed data"""
        try:
            # Find the claim
            claim = Claim.objects.filter(
                tenant=self.tenant,
                claim_number=claim_data['claim_number']
            ).first()
            
            if not claim:
                return None
            
            # Create payment posting
            posting = PaymentPosting.objects.create(
                tenant=self.tenant,
                claim=claim,
                posting_date=timezone.now().date(),
                payment_method='ERA',
                payment_amount=claim_data['paid_amount'],
                era_trace_number=claim_data['claim_number'],
                payer=claim.payer,
                status='UNPOSTED',
            )
            
            # Process adjustments from CAS segments
            for cas in cas_segments:
                if len(cas) >= 4:
                    adjustment_code = cas[2] if len(cas) > 2 else ''
                    adjustment_amount = Decimal(cas[3]) if len(cas) > 3 and cas[3] else Decimal('0.00')
                    
                    # Create denial reason if it's a denial
                    if adjustment_amount < 0:
                        DenialReason.objects.get_or_create(
                            tenant=self.tenant,
                            code=adjustment_code,
                            defaults={
                                'description': f"Adjustment code {adjustment_code}",
                                'category': 'UNKNOWN',
                            }
                        )
            
            # Process service lines from LX segments
            for lx in lx_segments:
                if len(lx) >= 2:
                    line_number = int(lx[1]) if len(lx) > 1 and lx[1].isdigit() else 0
                    # Additional processing for service line payments
                    
            return posting
            
        except Exception as e:
            # Log error but don't fail entire batch
            print(f"Error creating payment posting: {e}")
            return None


# ============================================================================
# CLEARINGHOUSE INTEGRATION
# ============================================================================

class ClearinghouseClient:
    """Generic clearinghouse API client"""
    
    def __init__(self, clearinghouse: Clearinghouse):
        self.clearinghouse = clearinghouse
        self.base_url = clearinghouse.api_endpoint
        
    def submit_claim(self, edi_content: str) -> Dict:
        """Submit 837 claim to clearinghouse"""
        import requests
        
        headers = {
            'Content-Type': 'application/x12',
            'Authorization': f"Bearer {self.clearinghouse.api_key}",
        }
        
        try:
            response = requests.post(
                f"{self.base_url}/claims/submit",
                data=edi_content,
                headers=headers,
                timeout=30
            )
            
            if response.status_code == 200:
                result = response.json()
                return {
                    'success': True,
                    'transmission_id': result.get('transmission_id'),
                    'control_number': result.get('control_number'),
                    'message': 'Claim submitted successfully',
                }
            else:
                return {
                    'success': False,
                    'error': response.text,
                    'status_code': response.status_code,
                }
                
        except requests.RequestException as e:
            return {
                'success': False,
                'error': str(e),
            }
    
    def check_claim_status(self, claim_number: str) -> Dict:
        """Check claim status via 276/271 transaction"""
        import requests
        
        headers = {
            'Authorization': f"Bearer {self.clearinghouse.api_key}",
        }
        
        try:
            response = requests.get(
                f"{self.base_url}/claims/{claim_number}/status",
                headers=headers,
                timeout=30
            )
            
            if response.status_code == 200:
                return response.json()
            else:
                return {'error': response.text}
                
        except requests.RequestException as e:
            return {'error': str(e)}
    
    def fetch_era(self, start_date: datetime = None, end_date: datetime = None) -> List[str]:
        """Fetch ERA files from clearinghouse"""
        import requests
        
        headers = {
            'Authorization': f"Bearer {self.clearinghouse.api_key}",
        }
        
        params = {}
        if start_date:
            params['start_date'] = start_date.strftime('%Y-%m-%d')
        if end_date:
            params['end_date'] = end_date.strftime('%Y-%m-%d')
        
        try:
            response = requests.get(
                f"{self.base_url}/era/files",
                headers=headers,
                params=params,
                timeout=60
            )
            
            if response.status_code == 200:
                files = response.json().get('files', [])
                return [f['content'] for f in files]
            else:
                return []
                
        except requests.RequestException as e:
            print(f"Error fetching ERA: {e}")
            return []


# ============================================================================
# UTILITY FUNCTIONS
# ============================================================================

def generate_claim_837(claim_id: str) -> Optional[str]:
    """Generate 837 file for a claim"""
    try:
        claim = Claim.objects.select_related('payer', 'patient_account').prefetch_related('lines__service_line').get(id=claim_id)
        generator = EDI837Generator(claim)
        return generator.generate()
    except Claim.DoesNotExist:
        return None


def process_era_file(file_content: str, tenant) -> List[PaymentPosting]:
    """Process ERA file and create payment postings"""
    parser = EDI835Parser(file_content, tenant)
    return parser.parse()


def submit_claim_to_clearinghouse(claim_id: str) -> Dict:
    """Submit claim to configured clearinghouse"""
    try:
        claim = Claim.objects.select_related('payer__clearinghouse').get(id=claim_id)
        
        if not claim.payer or not claim.payer.clearinghouse:
            return {'success': False, 'error': 'No clearinghouse configured for payer'}
        
        # Generate 837
        edi_content = generate_claim_837(claim_id)
        if not edi_content:
            return {'success': False, 'error': 'Failed to generate 837'}
        
        # Submit to clearinghouse
        client = ClearinghouseClient(claim.payer.clearinghouse)
        result = client.submit_claim(edi_content)
        
        if result.get('success'):
            # Update claim with transmission info
            claim.edi_transmission_id = result.get('transmission_id')
            claim.interchange_control_number = result.get('control_number')
            claim.status = 'SUBMITTED'
            claim.submission_date = timezone.now().date()
            claim.save(update_fields=['edi_transmission_id', 'interchange_control_number', 'status', 'submission_date'])
        
        return result
        
    except Claim.DoesNotExist:
        return {'success': False, 'error': 'Claim not found'}
    except Exception as e:
        return {'success': False, 'error': str(e)}
