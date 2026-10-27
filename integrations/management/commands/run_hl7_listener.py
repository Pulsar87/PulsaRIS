"""Management command: run the HL7 v2 lab/vitals MLLP listener service.

Ported from ``hl7_lab_listener_edan_vitals_postgres_columns.py``; received
messages are stored in the app's own database (Django default connection).

Examples:
    # Standard deployment: instrument opens a TCP/MLLP connection to us
    python manage.py run_hl7_listener --host 0.0.0.0 --port 2575

    # Device hosts the endpoint; we dial out and keep reconnecting
    python manage.py run_hl7_listener --mode connect --device-host 192.168.10.35

    # Non-standard unframed sender: end a message after 1.5s of silence
    python manage.py run_hl7_listener --framing raw-idle --raw-idle-seconds 1.5

    # Import a legacy SQLite file from the standalone receiver, then exit
    python manage.py run_hl7_listener --migrate-sqlite ./hl7_messages.sqlite3

    # Parser self-test (no database required)
    python manage.py run_hl7_listener --self-test
"""

from __future__ import annotations

from django.core.management.base import BaseCommand, CommandError

from integrations.hl7.listener import ListenerConfig, start
from integrations.hl7.migration import migrate_sqlite
from integrations.hl7.services import backfill_existing_vital_columns


class Command(BaseCommand):
    help = "Run the HL7 v2 laboratory/vital-signs MLLP listener (stores into the app database)."

    def add_arguments(self, parser):
        parser.add_argument("--mode", choices=("listen", "connect"), default=None, help="listen for analyzer connections (default) or connect to an analyzer")
        parser.add_argument("--host", default=None, help="local bind address in listen mode (default: settings HL7_LISTENER['HOST'] or 0.0.0.0)")
        parser.add_argument("--port", type=int, default=None, help="local TCP port in listen mode (default: 2575)")
        parser.add_argument("--device-host", default=None, help="analyzer IP/DNS name when --mode connect is used")
        parser.add_argument("--device-port", type=int, default=None, help="analyzer TCP port in connect mode (default: 2575)")
        parser.add_argument("--framing", choices=("mllp", "raw-idle"), default=None, help="HL7 TCP framing; use mllp unless the device manual says otherwise")
        parser.add_argument("--raw-idle-seconds", type=float, default=None, help="raw-idle mode: quiet time that ends a message (default: 1.0)")
        parser.add_argument("--ack-mode", choices=("always", "never"), default=None, help="send ACK/NAK after each inbound message (default: always)")
        parser.add_argument("--dedupe", choices=("control-id", "payload", "none"), default=None, help="duplicate policy (default: sender + MSH-10 control ID)")
        parser.add_argument("--allow-empty-control-id", action="store_true", help="compatibility mode for devices that omit MSH-10")
        parser.add_argument("--encoding", default=None, help="character encoding for inbound/outbound HL7 (default: utf-8)")
        parser.add_argument("--max-message-bytes", type=int, default=None, help="maximum payload size per message (default: 10 MiB)")
        parser.add_argument("--reconnect-seconds", type=float, default=None, help="connect mode reconnect delay (default: 5 seconds)")
        parser.add_argument("--archive-dir", default=None, help="optional directory for exact raw message copies; protect as PHI")
        parser.add_argument("--migrate-sqlite", default=None, metavar="PATH", help="import a legacy SQLite messages database into the app database and exit")
        parser.add_argument("--backfill-vitals", action="store_true", help="rebuild dedicated vital columns for stored rows written by older schema versions, then exit")
        parser.add_argument("--self-test", action="store_true", help="run the HL7 parser/ACK self-test and exit")

    def handle(self, *args, **options):
        if options["self_test"]:
            code = run_self_test()
            if code != 0:
                raise CommandError("Self-test failed")
            self.stdout.write(self.style.SUCCESS("Self-test passed."))
            return

        if options["migrate_sqlite"]:
            imported, skipped = migrate_sqlite(options["migrate_sqlite"])
            self.stdout.write(
                self.style.SUCCESS(f"SQLite migration finished: imported={imported} skipped_existing_ids={skipped}")
            )
            return

        if options["backfill_vitals"]:
            updated = backfill_existing_vital_columns()
            self.stdout.write(self.style.SUCCESS(f"Backfilled vital columns for {updated} stored message(s)."))
            return

        overrides = {
            key: value
            for key, value in options.items()
            if key not in ("self_test", "migrate_sqlite", "backfill_vitals") and value is not None
        }
        # store_true flag defaults to False which would override settings; only pass it when set
        if not options["allow_empty_control_id"]:
            overrides.pop("allow_empty_control_id", None)
        config = ListenerConfig(**overrides)
        try:
            config.validate()
        except ValueError as exc:
            raise CommandError(str(exc))

        self.stdout.write(
            self.style.SUCCESS(
                f"Starting HL7 listener: mode={config.mode} host={config.host} port={config.port} "
                f"framing={config.framing} dedupe={config.dedupe}; storing into the application database.\n"
                "Press Ctrl+C to stop."
            )
        )
        try:
            start(config)
        except KeyboardInterrupt:
            self.stdout.write(self.style.WARNING("\nHL7 listener stopped by user."))
        except Exception as exc:
            raise CommandError(f"Could not start/connect or persist data: {exc}") from exc


def run_self_test() -> int:
    """Parser/ACK regression test (mirrors the standalone script's --self-test)."""
    import json

    from integrations.hl7.parsing import build_vital_storage, parse_message
    from integrations.hl7.protocol import make_ack

    sample = (
        "MSH|^~\\&|ANALYZER|LAB1|LIS|MAIN|20261019073000||ORU^R01^ORU_R01|MSG0001|P|2.5.1\r"
        "PID|1||PAT123^^^HOSP^MR||Doe^Jane^A||19800101|F|||\r"
        "OBR|1|ORD123|FILL456|GLU^Glucose^LN|||20261019072000||||||||SERUM\r"
        "OBX|1|NM|GLU^Glucose^LN||5.4|mmol/L^millimoles per liter^UCUM|3.9-6.1|N|||F|||20261019072500\r"
    )
    parsed, errors = parse_message(sample)
    assert not errors, errors
    assert parsed["message_header"]["message_control_id"] == "MSG0001"
    assert parsed["patient"]["patient_id"] == "PAT123"
    assert parsed["orders"][0]["results"][0]["value"] == "5.4"
    assert parsed["orders"][0]["results"][0]["units"]["identifier"] == "mmol/L"
    ack = make_ack(parsed, "AA", "Message stored")
    assert "MSA|AA|MSG0001|Message stored" in ack
    assert ack.startswith("MSH|^~\\&|HL7_RECEIVER|LAB|ANALYZER|LAB1|")

    edan_sample = "MSH|^~\\&|Vital Signs Monitor||||20261019051435||ORU^R01|||2.3.1\rOBX|1|NM|SPO2^SpO2||98|%|||||F\r"
    edan_parsed, edan_errors = parse_message(edan_sample)
    assert "MSH-10 message control ID is empty" in edan_errors
    edan_errors = [e for e in edan_errors if e != "MSH-10 message control ID is empty"]
    assert not edan_errors, edan_errors
    assert edan_parsed["message_header"]["version_id"] == "2.3.1"
    assert edan_parsed["message_header"]["message_type"] == "ORU"
    assert edan_parsed["vitals"]["spo2"]["numeric_value"] == 98.0
    assert edan_parsed["vitals"]["spo2"]["unit"] == "%"
    _vitals, edan_columns = build_vital_storage(edan_parsed)
    assert edan_columns["spo2"] == 98.0 and edan_columns["spo2_unit"] == "%"
    assert "all_observations" in json.dumps(edan_columns["vitals_json"])
    assert len(edan_parsed["orders"][0]["results"]) == 1

    edan_bp_sample = (
        "MSH|^~\\&|Vital Signs Monitor||||20261019065231+0000||ORU^R01|||2.3.1\r"
        "OBR|1||||||20261019065231+0000\r"
        "OBX|1|ST|24960^EHC_DEV_SW_VERSION^99EHC||V01.09.00.08||||||\r"
        "OBX|2|NM|WEIGHT||95.0|kg|||||\r"
        "OBX|3|NM|HEIGHT||178.0|cm|||||\r"
        "OBX|4|ST|BLOODTYPE||A||||||\r"
        "OBX|5|NM|150021^MDC_PRESS_BLD_NONINV_SYS^MDC||135|266016^MDC_DIM_MMGH^MDC|90-160||||F|||20261019065231+0000\r"
        "OBX|6|NM|150022^MDC_PRESS_BLD_NONINV_DIA^MDC||92|266016^MDC_DIM_MMGH^MDC|50-90||||F|||20261019065231+0000\r"
        "OBX|7|NM|150023^MDC_PRESS_BLD_NONINV_MEAN^MDC||104|266016^MDC_DIM_MMGH^MDC|60-110||||F|||20261019065231+0000\r"
        "OBX|8|NM|NIBP_NIBP_PR||59||50-120||||F|||20261019065231+0000\r"
        "OBX|9|NM|VENDOR_UNKNOWN_CODE||opaque value||||||\r"
    )
    bp_parsed, bp_errors = parse_message(edan_bp_sample)
    bp_errors = [e for e in bp_errors if e != "MSH-10 message control ID is empty"]
    assert not bp_errors, bp_errors
    assert len(bp_parsed["orders"][0]["results"]) == 9
    assert bp_parsed["vitals"]["systolic_blood_pressure"]["numeric_value"] == 135.0
    assert bp_parsed["vitals"]["diastolic_blood_pressure"]["numeric_value"] == 92.0
    assert bp_parsed["vitals"]["mean_blood_pressure"]["unit"] == "mmHg"
    assert bp_parsed["vitals"]["pulse_rate"]["numeric_value"] == 59.0
    assert bp_parsed["vitals"]["nibp_pulse_rate"]["numeric_value"] == 59.0
    assert bp_parsed["vitals"]["weight"]["unit"] == "kg"
    assert len(bp_parsed["vitals"]["all_observations"]) == 9
    assert len(bp_parsed["vitals"]["unmapped_observations"]) == 1
    _bp_vitals, bp_columns = build_vital_storage(bp_parsed)
    assert bp_columns["systolic_bp"] == 135.0
    assert bp_columns["diastolic_bp"] == 92.0
    assert bp_columns["mean_bp"] == 104.0
    assert bp_columns["nibp_pulse_rate"] == 59.0
    assert bp_columns["weight"] == 95.0 and bp_columns["height"] == 178.0
    assert bp_columns["blood_type"] == "A"
    assert len(json.loads(json.dumps(bp_columns["vitals_json"]))["unmapped_observations"]) == 1
    print("Self-test passed: HL7 parsing, dedicated vital columns, full result retention, BP, and unknown-code retention.")
    return 0
