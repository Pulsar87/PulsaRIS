"""
Script to create a tenant and domain for local development.
Run this after starting your PostgreSQL database.

Usage:
    1. Start your PostgreSQL database
    2. Run migrations: python manage.py migrate_schemas --shared
    3. Run this script: python setup_tenant.py
    4. Then run: python manage.py migrate_schemas
"""
import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings.dev')
django.setup()

from tenants.models import Tenant, Domain

# Check if domains already exist
existing_domains = Domain.objects.count()
if existing_domains > 0:
    print(f"Found {existing_domains} existing domains:")
    for d in Domain.objects.all():
        print(f"  - {d.domain} -> {d.tenant.name}")
    print("\nNo new domains created.")
else:
    # Create a test tenant
    print("Creating test tenant...")
    tenant = Tenant.objects.create(
        schema_name='test_tenant',
        name='Test Hospital',
        subdomain='test',
    )
    print(f"Tenant created: {tenant.name}")

    # Create domains for localhost access
    domains_to_create = ['localhost', '127.0.0.1']
    for i, domain_name in enumerate(domains_to_create):
        Domain.objects.create(
            domain=domain_name,
            tenant=tenant,
            is_primary=(i == 0)  # First domain is primary
        )
        print(f"Domain created: {domain_name} -> {tenant.name}")

    print("\n✓ Done! Now you can access the app via http://localhost or http://127.0.0.1")
    print("  The get_tenant(request) function will now return the tenant object.")
