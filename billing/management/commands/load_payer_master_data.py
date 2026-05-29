"""
Django management command to load initial Insurance/Payer master data
Usage: python manage.py load_payer_master_data
"""
from django.core.management.base import BaseCommand
from django.db import transaction
from billing.models import InsurancePayer, Clearinghouse


class Command(BaseCommand):
    help = 'Load initial insurance payer and clearinghouse master data'

    @transaction.atomic
    def handle(self, *args, **options):
        self.stdout.write('Loading Insurance/Payer master data...')
        
        # Get or create default tenant (adjust based on your setup)
        from tenants.models import Tenant
        tenant, _ = Tenant.objects.get_or_create(
            name='Default',
            slug='default',
            defaults={'is_active': True}
        )
        
        # Create Clearinghouses
        clearinghouses_data = [
            {
                'code': 'CHANGE',
                'name': 'Change Healthcare',
                'vendor_name': 'Change Healthcare Inc.',
                'transmission_protocol': 'HTTPS',
                'supports_837p': True,
                'supports_837i': True,
                'supports_835': True,
                'supports_270_271': True,
                'interchange_control_version': '00501',
            },
            {
                'code': 'AVIATRA',
                'name': 'Aviatra Health',
                'vendor_name': 'Aviatra Health LLC',
                'transmission_protocol': 'SFTP',
                'supports_837p': True,
                'supports_837i': False,
                'supports_835': True,
                'supports_270_271': True,
                'interchange_control_version': '00501',
            },
            {
                'code': 'TRIZETTO',
                'name': 'TriZetto',
                'vendor_name': 'TriZetto Corporation (Cognizant)',
                'transmission_protocol': 'HTTPS',
                'supports_837p': True,
                'supports_837i': True,
                'supports_835': True,
                'supports_270_271': True,
                'interchange_control_version': '00501',
            },
            {
                'code': 'OFFICEALLY',
                'name': 'OfficeAlly',
                'vendor_name': 'OfficeAlly Inc.',
                'transmission_protocol': 'HTTPS',
                'supports_837p': True,
                'supports_837i': False,
                'supports_835': True,
                'supports_270_271': True,
                'interchange_control_version': '00501',
            },
        ]
        
        created_ch = 0
        for ch_data in clearinghouses_data:
            code = ch_data.pop('code')
            ch, created = Clearinghouse.objects.get_or_create(
                code=code,
                tenant=tenant,
                defaults=ch_data
            )
            if created:
                created_ch += 1
                self.stdout.write(self.style.SUCCESS(f'Created clearinghouse: {ch.name}'))
            else:
                self.stdout.write(f'Clearinghouse exists: {ch.name}')
        
        # Create Common Insurance Payers
        payers_data = [
            {'code': 'MEDICARE', 'name': 'Medicare', 'payer_id': '99999', 'payer_type': 'MEDICARE', 'edi_enabled': True, 'claim_format': '837P', 'require_auth': False, 'era_enabled': True},
            {'code': 'MEDICAID', 'name': 'Medicaid', 'payer_id': '99997', 'payer_type': 'MEDICAID', 'edi_enabled': True, 'claim_format': '837P', 'require_auth': False, 'era_enabled': True},
            {'code': 'BCBS', 'name': 'Blue Cross Blue Shield', 'payer_id': 'BCBS', 'payer_type': 'COMMERCIAL', 'edi_enabled': True, 'claim_format': '837P', 'require_auth': True, 'era_enabled': True},
            {'code': 'AETNA', 'name': 'Aetna', 'payer_id': 'AETNA', 'payer_type': 'COMMERCIAL', 'edi_enabled': True, 'claim_format': '837P', 'require_auth': True, 'era_enabled': True},
            {'code': 'UHC', 'name': 'UnitedHealthcare', 'payer_id': 'UHC', 'payer_type': 'COMMERCIAL', 'edi_enabled': True, 'claim_format': '837P', 'require_auth': True, 'era_enabled': True},
            {'code': 'CIGNA', 'name': 'Cigna Healthcare', 'payer_id': 'CIGNA', 'payer_type': 'COMMERCIAL', 'edi_enabled': True, 'claim_format': '837P', 'require_auth': True, 'era_enabled': True},
            {'code': 'HUMANA', 'name': 'Humana Inc.', 'payer_id': 'HUMANA', 'payer_type': 'COMMERCIAL', 'edi_enabled': True, 'claim_format': '837P', 'require_auth': True, 'era_enabled': True},
            {'code': 'WORKERS_COMP', 'name': "Workers' Compensation", 'payer_id': 'WC', 'payer_type': 'WORKERS_COMP', 'edi_enabled': False, 'claim_format': 'PAPER', 'require_auth': True, 'era_enabled': False},
            {'code': 'AUTO_INS', 'name': 'Auto Insurance', 'payer_id': 'AUTO', 'payer_type': 'AUTO_INSURANCE', 'edi_enabled': False, 'claim_format': 'PAPER', 'require_auth': False, 'era_enabled': False},
            {'code': 'SELF_PAY', 'name': 'Self Pay Patient', 'payer_id': 'SELF', 'payer_type': 'SELF_PAY', 'edi_enabled': False, 'claim_format': 'PAPER', 'require_auth': False, 'era_enabled': False},
            {'code': 'TRICARE', 'name': 'TRICARE', 'payer_id': 'TRICARE', 'payer_type': 'TRICARE', 'edi_enabled': True, 'claim_format': '837P', 'require_auth': True, 'era_enabled': True},
        ]
        
        created_payers = 0
        for payer_data in payers_data:
            code = payer_data.pop('code')
            payer, created = InsurancePayer.objects.get_or_create(
                code=code,
                tenant=tenant,
                defaults=payer_data
            )
            if created:
                created_payers += 1
                self.stdout.write(self.style.SUCCESS(f'Created payer: {payer.name} ({payer.payer_id})'))
            else:
                self.stdout.write(f'Payer exists: {payer.name}')
        
        self.stdout.write(self.style.SUCCESS(f'\nMaster data load complete!'))
        self.stdout.write(f'  - Created {created_ch} clearinghouses')
        self.stdout.write(f'  - Created {created_payers} insurance payers')
