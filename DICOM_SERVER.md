# DICOM Server Configuration

## Overview

The RIS Platform includes a DICOM Modality Worklist (MWL) SCP server that allows radiology modalities (CT, MR, X-Ray, etc.) to query patient worklists from the system.

## Running the DICOM Server

### As a Django Management Command (Recommended)

```bash
# Start with default settings (0.0.0.0:11112, AE Title: RIS_SCP)
python manage.py run_dicom_server

# Custom port
python manage.py run_dicom_server --port 11112

# Custom host and port
python manage.py run_dicom_server --host 0.0.0.0 --port 11112

# Full customization
python manage.py run_dicom_server --host 0.0.0.0 --port 11112 --ae-title RIS_SCP
```

### Using the Standalone Script

The standalone script `tenants/dicom_server.py` can also be run directly:

```bash
python tenants/dicom_server.py
```

## Configuration Options

| Option | Default | Description |
|--------|---------|-------------|
| `--host` | `0.0.0.0` | Network interface to bind to |
| `--port` | `11112` | DICOM port number |
| `--ae-title` | `RIS_SCP` | Application Entity Title |

## Integration with Docker

### Option 1: Add as a Separate Service in docker-compose.yml

Add this service to your `docker-compose.yml`:

```yaml
services:
  # ... existing services ...

  dicom-server:
    build: .
    env_file: .env
    depends_on: [django, postgres]
    ports:
      - "11112:11112"  # DICOM port
    command: python manage.py run_dicom_server --host 0.0.0.0 --port 11112
    volumes:
      - .:/app
```

Then start with:
```bash
docker-compose up dicom-server
```

### Option 2: Run Alongside Django Container

If you want to run it in an existing container:

```bash
docker-compose exec django python manage.py run_dicom_server --host 0.0.0.0 --port 11112
```

## Testing the Server

Use the included emulator script to test the server:

```bash
# Make sure the server is running first, then:
python tenants/dicom_emulator.py
```

Or use any DICOM MWL client (e.g., DCMTK's `findscu`):

```bash
findscu -W -k PatientName -k PatientID -k Modality \
  --aetitle MODALITY_AE \
  localhost 11112
```

## How It Works

1. **C-FIND Requests**: The server listens for DICOM C-FIND requests on the configured port
2. **Database Query**: When a request arrives, it queries the `ExamOrder` model for matching scheduled/registered orders
3. **Filter Support**: Supports filtering by:
   - Modality (CT, MR, CR, etc.)
   - Scheduled Station AE Title
   - Patient Name (with wildcard support)
   - Patient ID/MRN (with wildcard support)
4. **Response**: Returns matching worklist items in DICOM format

## Schema Configuration

The server uses `schema_context("moas")` to access the ExamOrder table. Update this in the code if your schema name differs.

## Production Considerations

1. **Security**: In production, consider:
   - Binding to specific interfaces (not 0.0.0.0)
   - Using firewall rules to restrict access
   - Implementing AE Title whitelisting

2. **Process Management**: Use a process supervisor like:
   - systemd
   - supervisord
   - Docker restart policies

3. **Logging**: Consider redirecting output to log files:
   ```bash
   python manage.py run_dicom_server >> /var/log/dicom_server.log 2>&1
   ```

4. **High Availability**: For HA setups, consider:
   - Load balancer in front of multiple instances
   - Shared database backend (already supported)

## Troubleshooting

### Port Already in Use
```bash
# Check what's using the port
lsof -i :11112
# or
netstat -tlnp | grep 11112
```

### Connection Refused
- Ensure the server is running
- Check firewall rules
- Verify the host binding (0.0.0.0 vs 127.0.0.1)

### No Results Returned
- Verify ExamOrder records exist with status REGISTERED or SCHEDULED
- Check the schema name in the code matches your database
- Verify modality codes match DICOM standards
