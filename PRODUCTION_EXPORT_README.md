# Production Export v0.1 - Django Application

This directory contains the production export package for version 0.1 of the Django application.

## What's Included

### 🔒 Compiled Python Code
- All Python source files have been compiled to `.pyc` bytecode
- No readable `.py` files are included in the export
- Source code is protected while maintaining full functionality

### 📦 Export Package Contents
```
django_app_v0.1/
├── app/                    # Compiled application code
│   ├── audit/             # Audit app (compiled)
│   ├── billing/           # Billing app (compiled)
│   ├── config/            # Django configuration (compiled)
│   ├── core/              # Core app (compiled)
│   ├── integrations/      # Integrations app (compiled)
│   ├── license/           # License management (compiled)
│   ├── orders/            # Orders app (compiled)
│   ├── patients/          # Patients app (compiled)
│   ├── reports/           # Reports app (compiled)
│   ├── users/             # Users app (compiled)
│   ├── templates/         # HTML templates
│   ├── static/            # Static assets
│   └── locale/            # Internationalization files
├── install.sh             # Installation script
├── requirements.txt       # Python dependencies
├── entrypoint.sh          # Docker entrypoint
├── systemd.service        # Systemd service configuration
├── docker-compose.yml     # Docker Compose configuration
├── Dockerfile.export      # Dockerfile for containerized deployment
└── DEPLOYMENT.md          # Detailed deployment guide
```

## Deployment Options

### Option 1: Direct Installation (VM/Bare Metal)
```bash
# Copy the tarball to target server
scp django_app_v0.1.tar.gz user@server:/tmp/

# On target server
cd /tmp
tar -xzf django_app_v0.1.tar.gz
cd django_app_v0.1
sudo ./install.sh
```

### Option 2: Docker Deployment
```bash
tar -xzf django_app_v0.1.tar.gz
cd django_app_v0.1
cp .env.example .env  # Configure your environment
docker-compose up -d --build
```

### Option 3: Build Production Docker Image
```bash
# From the project root
docker build -f Dockerfile.production -t django_app:0.1 .

# Run the container
docker run -d \
  -p 8000:8000 \
  -e SECRET_KEY=your-secret \
  -e DATABASE_URL=postgresql://user:pass@host:5432/db \
  django_app:0.1
```

## Files in This Directory

| File | Description |
|------|-------------|
| `Dockerfile.production` | Multi-stage Dockerfile that compiles Python code |
| `export_production.sh` | Script to generate installable packages |
| `dist/django_app_v0.1.tar.gz` | Ready-to-deploy package (1.4 MB) |
| `dist/django_app_v0.1/` | Extracted package contents |

## For Future Development

The original source code remains in `/workspace` with the following structure:
- Keep developing in `/workspace` with full source code access
- When ready to export a new version:
  1. Update version number in `export_production.sh`
  2. Run `./export_production.sh`
  3. Distribute the new `dist/django_app_v*.tar.gz`

## Version History

- **v0.1** (Current): Initial production release
  - Compiled Python bytecode only
  - Full Django application with all apps
  - Multiple deployment options (direct, Docker, systemd)

## Support

See `DEPLOYMENT.md` for detailed deployment instructions and troubleshooting.
