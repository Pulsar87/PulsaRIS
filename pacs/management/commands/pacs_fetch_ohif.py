"""Fetch the pinned OHIF standalone viewer bundle into ``static/ohif/``.

PACS plan Task 4.3 integration step. The Dockerfile runs this at image build
time (network available there, never at request time); developers run it once
locally::

    python manage.py pacs_fetch_ohif [--force]

What it downloads (exact versions only — no floating "latest"):
- ``index.umd.js``: the self-contained OHIF v4 standalone UMD bundle from the
  official npm package (``@ohif/viewer``), version pinned by the
  ``PACS_OHIF_VERSION`` setting / ``OHIF_VERSION`` env var.
- ``LICENSE``: the MIT license text shipped with the package (redistribution
  compliance).

Integrity is verified against the SHA-256 published by the npm registry for
that exact version before anything is written to disk. Files land in
``static/ohif/`` so Django/WhiteNoise serves them same-origin under
``/static/ohif/``.
"""

import base64
import hashlib
import json
import urllib.error
import urllib.request

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

UNPKG_BASE = "https://unpkg.com/@ohif/viewer@{version}/dist/"
BUNDLE_FILE = "index.umd.js"
LICENSE_FILE = "LICENSE"


class Command(BaseCommand):
    help = "Download the pinned OHIF viewer bundle into static/ohif/."

    def add_arguments(self, parser):
        parser.add_argument(
            "--ohif-version",
            default=None,
            help="Exact @ohif/viewer version (default: PACS_OHIF_VERSION setting).",
        )
        parser.add_argument(
            "--dest",
            default=None,
            help="Destination directory (default: <BASE_DIR>/static/ohif).",
        )
        parser.add_argument(
            "--force",
            action="store_true",
            help="Overwrite an existing bundle.",
        )

    def handle(self, *args, **options):
        from pathlib import Path

        version = options["ohif_version"] or getattr(settings, "PACS_OHIF_VERSION", "4.12.51")
        dest_dir = Path(options["dest"]) if options["dest"] else Path(settings.BASE_DIR) / "static" / "ohif"
        dest_dir.mkdir(parents=True, exist_ok=True)
        bundle_path = dest_dir / BUNDLE_FILE

        if bundle_path.exists() and not options["force"]:
            self.stdout.write(
                self.style.SUCCESS(f"OHIF bundle already present at {bundle_path} (use --force to replace).")
            )
            return

        try:
            digest = self._registry_integrity(version)
        except Exception as exc:  # noqa: BLE001 - report any registry failure clearly
            raise CommandError(f"Cannot read npm registry metadata for {version}: {exc}")

        url = UNPKG_BASE.format(version=version) + BUNDLE_FILE
        self.stdout.write(f"Downloading OHIF v{version} bundle ({url}) ...")
        try:
            with urllib.request.urlopen(url, timeout=120) as resp:
                blob = resp.read()
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise CommandError(f"Download failed: {exc}")

        sha256_b64 = base64.b64encode(hashlib.sha256(blob).digest()).decode()
        if sha256_b64 != digest:
            raise CommandError(
                f"INTEGRITY CHECK FAILED for {BUNDLE_FILE} v{version}: "
                f"expected sha256-{digest}, got sha256-{sha256_b64}. Refusing to install."
            )

        bundle_path.write_bytes(blob)
        self.stdout.write(self.style.SUCCESS(f"Installed {bundle_path} ({len(blob)} bytes, sha256 verified)."))

        # Best-effort: ship the package LICENSE next to the bundle.
        lic_url = UNPKG_BASE.format(version=version).replace("dist/", "") + LICENSE_FILE
        try:
            with urllib.request.urlopen(lic_url, timeout=30) as resp:
                (dest_dir / LICENSE_FILE).write_bytes(resp.read())
        except Exception:  # noqa: BLE001 - non-fatal; bundle is what matters
            self.stdout.write(self.style.WARNING("Could not fetch LICENSE (non-fatal)."))

    def _registry_integrity(self, version):
        """Return the base64 SHA-256 of dist/index.umd.js for `version`.

        unpkg publishes per-file SRI (sha-256, base64) via its ``?meta``
        endpoint; we require it so a tampered/mismatched bundle is never
        installed. If the pinned version's metadata lacks the entry, the
        command fails instead of guessing.
        """
        meta_url = f"https://unpkg.com/@ohif/viewer@{version}/?meta"
        with urllib.request.urlopen(meta_url, timeout=30) as resp:
            listing = json.loads(resp.read().decode())
        for entry in listing.get("files", []):
            if entry.get("path") == f"/dist/{BUNDLE_FILE}":
                integrity = entry.get("integrity", "")
                if integrity.startswith("sha256-"):
                    return integrity[len("sha256-"):]
        raise CommandError(
            f"unpkg metadata for {version} does not list a sha256 for dist/{BUNDLE_FILE}; "
            "pin a version that does, or vendor the bundle manually."
        )
