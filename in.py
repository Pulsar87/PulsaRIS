from tenants.models import Tenant, Domain

# 1. Find the invalid tenant with empty subdomain
bad_tenant = Tenant.objects.filter(subdomain='').first()

if bad_tenant:
    print(f"Found invalid tenant: {bad_tenant.schema_name}")
    # Delete the tenant and its schema
    bad_tenant.delete()
    print("Invalid tenant deleted.")
else:
    print("No invalid tenant found.")

# 2. Now create your new tenant correctly
# Replace 'moas' with your desired schema name and subdomain
tenant = Tenant(schema_name='pulsar', name='Pulsar')
tenant.save()  # This creates the schema

# Create the domain (replace 'localhost' with your actual domain if different)
domain = Domain.objects.create(domain='localhost', tenant=tenant, is_primary=True)

print(f"Tenant '{tenant.name}' and Schema 'pulsar' created successfully!")
