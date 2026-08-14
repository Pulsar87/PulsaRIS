#!/bin/bash
# Export Production Version 0.1 - Installable Package Generator
# This script creates an installable production package with compiled Python code

set -e

APP_VERSION="0.1"
EXPORT_DIR="./dist"
PACKAGE_NAME="pulsaris_v${APP_VERSION}"

echo "🚀 Building Production Export Package v${APP_VERSION}..."

# Clean previous exports
rm -rf "${EXPORT_DIR}"
mkdir -p "${EXPORT_DIR}/${PACKAGE_NAME}"

# Create the export directory structure
cd "$(dirname "$0")"

echo "📦 Creating installation package..."

# Create app directory structure
mkdir -p "${EXPORT_DIR}/${PACKAGE_NAME}/app"

# Copy requirements
cp requirements.txt "${EXPORT_DIR}/${PACKAGE_NAME}/"

# Copy entrypoint
cp entrypoint.sh "${EXPORT_DIR}/${PACKAGE_NAME}/"
chmod +x "${EXPORT_DIR}/${PACKAGE_NAME}/entrypoint.sh"

# Compile Python files and copy application code
echo "🔒 Compiling Python code to bytecode..."
#cd dist

# List of Django apps and modules to include
APPS="audit billing config core integrations license orders patients reports users"

for app in $APPS; do
    if [ -d "$app" ]; then
        mkdir -p "${EXPORT_DIR}/${PACKAGE_NAME}/app/$app"
        # Compile all .py files first
        find "$app" -name "*.py" -exec python -m py_compile {} \; 2>/dev/null || true
        # Copy everything (including __pycache__ with .pyc files)
        cp -r "$app"/* "${EXPORT_DIR}/${PACKAGE_NAME}/app/$app/" 2>/dev/null || true
    fi
done

# Copy templates, static, locale
cp -r templates "${EXPORT_DIR}/${PACKAGE_NAME}/app/" 2>/dev/null || true
cp -r static "${EXPORT_DIR}/${PACKAGE_NAME}/app/" 2>/dev/null || true
cp -r locale "${EXPORT_DIR}/${PACKAGE_NAME}/app/" 2>/dev/null || true

# Copy manage.py and compile it
cp manage.py "${EXPORT_DIR}/${PACKAGE_NAME}/app/"
python -m py_compile "${EXPORT_DIR}/${PACKAGE_NAME}/app/manage.py" 2>/dev/null || true

# Remove .py files from exported package (keep only .pyc in __pycache__)
echo "🔒 Removing source .py files (keeping only compiled bytecode)..."
find "${EXPORT_DIR}/${PACKAGE_NAME}/app" -name "*.py" -type f -delete

# Create install script
cat > "${EXPORT_DIR}/${PACKAGE_NAME}/install.sh" << 'INSTALL_SCRIPT'
#!/bin/bash
# Installation script for PulsarRIS v0.1
set -e

INSTALL_DIR="${INSTALL_DIR:-/opt/pulsaris}"
VENV_DIR="${INSTALL_DIR}/venv"
APP_DIR="${INSTALL_DIR}/app"

echo "📦 Installing PulsarRIS v0.1 to ${INSTALL_DIR}..."

# Create installation directory
mkdir -p "${INSTALL_DIR}"

# Copy application files (excluding this install script temporarily)
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
# Copy app directory and other files separately
if [ -d "${SCRIPT_DIR}/app" ]; then
    cp -r "${SCRIPT_DIR}/app" "${INSTALL_DIR}/"
fi
# Copy other config files
for file in requirements.txt entrypoint.sh systemd.service docker-compose.yml Dockerfile.export DEPLOYMENT.md; do
    if [ -f "${SCRIPT_DIR}/${file}" ]; then
        cp "${SCRIPT_DIR}/${file}" "${INSTALL_DIR}/"
    fi
done
cp "${SCRIPT_DIR}/install.sh" "${INSTALL_DIR}/"

# Create virtual environment
echo "🐍 Creating virtual environment..."
python3 -m venv "${VENV_DIR}"

# Install dependencies
echo "⬇️  Installing dependencies..."
"${VENV_DIR}/bin/pip" install --upgrade pip
"${VENV_DIR}/bin/pip" install -r "${INSTALL_DIR}/requirements.txt"

# Make scripts executable
chmod +x "${INSTALL_DIR}/entrypoint.sh"

# Create .env example if not exists
if [ ! -f "${INSTALL_DIR}/.env" ]; then
    cat > "${INSTALL_DIR}/.env.example" << 'EOF'
SECRET_KEY=your-secret-key-here
DEBUG=False
DATABASE_URL=postgresql://user:password@localhost:5432/dbname
ALLOWED_HOSTS=localhost,127.0.0.1
EOF
    echo "✅ Created .env.example - Please configure your environment variables"
fi

# Run migrations
echo "🔄 Running database migrations..."
cd "${APP_DIR}"
export PYTHONPATH="${APP_DIR}"
"${VENV_DIR}/bin/python" __pycache__/manage.cpython-312.pyc migrate --noinput 2>/dev/null || \
"${VENV_DIR}/bin/python" -c "import sys; sys.path.insert(0, '${APP_DIR}'); import django; django.setup(); from django.core.management import execute_from_command_line; execute_from_command_line(['manage.py', 'migrate', '--noinput'])" 2>/dev/null || echo "⚠️  Database migration skipped (database may not be configured yet)"

# Collect static files
echo "📁 Collecting static files..."
"${VENV_DIR}/bin/python" __pycache__/manage.cpython-312.pyc collectstatic --noinput 2>/dev/null || \
"${VENV_DIR}/bin/python" -c "import sys; sys.path.insert(0, '${APP_DIR}'); import django; django.setup(); from django.core.management import execute_from_command_line; execute_from_command_line(['manage.py', 'collectstatic', '--noinput'])" 2>/dev/null || echo "⚠️  Static collection skipped"

echo ""
echo "✅ Installation complete!"
echo ""
echo "To start the application:"
echo "  cd ${INSTALL_DIR}"
echo "  source venv/bin/activate"
echo "  export PYTHONPATH=${APP_DIR}"
echo "  cd app && ../venv/bin/gunicorn config.wsgi:application --bind 0.0.0.0:8000 --workers 4"
echo ""
echo "Or use systemd service (recommended for production):"
echo "  sudo cp ${INSTALL_DIR}/systemd.service /etc/systemd/system/pulsaris.service"
echo "  sudo systemctl daemon-reload"
echo "  sudo systemctl enable pulsaris"
echo "  sudo systemctl start pulsaris"
INSTALL_SCRIPT

chmod +x "${EXPORT_DIR}/${PACKAGE_NAME}/install.sh"

# Create systemd service file
cat > "${EXPORT_DIR}/${PACKAGE_NAME}/systemd.service" << 'SYSTEMD_SERVICE'
[Unit]
Description=PulsarRIS Production Service
After=network.target postgresql.service redis.service

[Service]
Type=notify
User=www-data
Group=www-data
WorkingDirectory=/opt/pulsaris
Environment="PATH=/opt/pulsaris/venv/bin"
ExecStart=/opt/pulsaris/venv/bin/gunicorn config.wsgi:application --bind 0.0.0.0:8000 --workers 4 --timeout 120
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
SYSTEMD_SERVICE

# Create Docker Compose for easy deployment
cat > "${EXPORT_DIR}/${PACKAGE_NAME}/docker-compose.yml" << 'DOCKER_COMPOSE'
version: '3.8'

services:
  web:
    image: pulsaris:0.1
    build:
      context: .
      dockerfile: Dockerfile.export
    ports:
      - "8000:8000"
    environment:
      - SECRET_KEY=${SECRET_KEY}
      - DATABASE_URL=${DATABASE_URL}
      - DEBUG=False
    volumes:
      - static_volume:/app/staticfiles
      - media_volume:/app/media
    depends_on:
      - db
      - redis
    restart: unless-stopped

  db:
    image: postgres:15-alpine
    environment:
      - POSTGRES_DB=${POSTGRES_DB:-pulsaris}
      - POSTGRES_USER=${POSTGRES_USER:-pulsaris}
      - POSTGRES_PASSWORD=${POSTGRES_PASSWORD:-changeme}
    volumes:
      - postgres_data:/var/lib/postgresql/data
    restart: unless-stopped

  redis:
    image: redis:7-alpine
    restart: unless-stopped

volumes:
  postgres_data:
  static_volume:
  media_volume:
DOCKER_COMPOSE

# Create Dockerfile for exported package
cat > "${EXPORT_DIR}/${PACKAGE_NAME}/Dockerfile.export" << 'DOCKERFILE_EXPORT'
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=/app
ENV APP_VERSION=0.1

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq5 curl \
    && rm -rf /var/lib/apt/lists/* \
    && useradd -m -u 1000 appuser

COPY requirements.txt .
RUN python -m venv /venv && \
    /venv/bin/pip install --no-cache-dir -r requirements.txt

COPY . .

RUN chmod +x /app/entrypoint.sh && \
    chown -R appuser:appuser /app

EXPOSE 8000

USER appuser

ENTRYPOINT ["/app/entrypoint.sh"]
CMD ["gunicorn", "config.wsgi:application", "--bind", "0.0.0.0:8000", "--workers", "4", "--timeout", "120"]

LABEL version="0.1" \
      description="Production PulsarRIS - Installable Package"
DOCKERFILE_EXPORT

# Create README for deployment instructions
cat > "${EXPORT_DIR}/${PACKAGE_NAME}/DEPLOYMENT.md" << 'README_MD'
# Django App Production Deployment Guide v0.1

## Quick Start

### Option 1: Direct Installation (Recommended for VMs)

```bash
# Run the installation script
sudo ./install.sh

# Configure environment variables
sudo cp /opt/pulsaris/.env.example /opt/pulsaris/.env
sudo nano /opt/pulsaris/.env  # Edit with your values

# Install systemd service
sudo cp /opt/pulsaris/systemd.service /etc/systemd/system/pulsaris.service
sudo systemctl daemon-reload
sudo systemctl enable pulsaris
sudo systemctl start pulsaris
```

### Option 2: Docker Deployment

```bash
# Build and run with Docker Compose
cp .env.example .env
docker-compose up -d --build
```

### Option 3: Using Pre-built Docker Image

```bash
# Pull and run (if image is published)
docker run -d \
  -p 8000:8000 \
  -e SECRET_KEY=your-secret \
  -e DATABASE_URL=postgresql://... \
  pulsaris:0.1
```

## Environment Variables Required

- `SECRET_KEY`: Pul$@ri$ $ecret key
- `DATABASE_URL`: PostgreSQL connection string
- `DEBUG`: Set to False in production
- `ALLOWED_HOSTS`: Comma-separated list of allowed hosts

## Health Check

```bash
curl http://localhost:8000/health/
```

## Logs

```bash
# Systemd
journalctl -u pulsaris -f

# Docker
docker-compose logs -f web
```

## Support

For issues, check logs and ensure all environment variables are properly configured.
README_MD

# Create a tarball
cd "${EXPORT_DIR}"
tar -czf "${PACKAGE_NAME}.tar.gz" "${PACKAGE_NAME}"

echo ""
echo "✅ Export package created successfully!"
echo ""
echo "📦 Package location: ${EXPORT_DIR}/${PACKAGE_NAME}.tar.gz"
echo "📁 Package contents: ${EXPORT_DIR}/${PACKAGE_NAME}/"
echo ""
echo "To deploy on another server:"
echo "  1. Copy ${PACKAGE_NAME}.tar.gz to the target server"
echo "  2. Extract: tar -xzf ${PACKAGE_NAME}.tar.gz"
echo "  3. cd ${PACKAGE_NAME}"
echo "  4. sudo ./install.sh"
echo ""
echo "🔒 Note: All Python code is compiled to .pyc bytecode for protection."
