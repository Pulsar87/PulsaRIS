"""Asyncio MLLP/TCP listener for HL7 v2 laboratory & vital-sign devices.

This is the service loop from ``hl7_lab_listener_edan_vitals_postgres_columns``
re-hosted inside Django: transport handling stays asyncio, persistence goes
through ``integrations.hl7.services.persist_payload`` into the app database.

Run it with::

    python manage.py run_hl7_listener --host 0.0.0.0 --port 2575
    python manage.py run_hl7_listener --mode connect --device-host 192.168.10.35

Modes / framing mirror the standalone receiver:

* ``listen``  – instrument connects to us (default, standard MLLP deployment)
* ``connect`` – we dial the analyzer when it hosts the TCP endpoint
* ``mllp`` / ``raw-idle`` framing for non-standard unframed senders
"""

from __future__ import annotations

import asyncio
import logging
from typing import Optional

from django.db import close_old_connections

from integrations.hl7.protocol import ack_framing, make_ack, pack_message
from integrations.hl7.parsing import MLLP_START, MLLP_END
from integrations.hl7.services import hl7_setting, persist_payload

logger = logging.getLogger("integrations.hl7.listener")


class ListenerConfig:
    """Runtime options resolved from settings.HL7_LISTENER + CLI overrides."""

    def __init__(self, **overrides):
        self.host = overrides.get("host", hl7_setting("HOST", "0.0.0.0"))
        self.port = int(overrides.get("port", hl7_setting("PORT", 2575)))
        self.mode = overrides.get("mode", hl7_setting("MODE", "listen"))
        self.device_host = overrides.get("device_host", hl7_setting("DEVICE_HOST", ""))
        self.device_port = int(overrides.get("device_port", hl7_setting("DEVICE_PORT", 2575)))
        self.framing = overrides.get("framing", hl7_setting("FRAMING", "mllp"))
        self.raw_idle_seconds = float(
            overrides.get("raw_idle_seconds", hl7_setting("RAW_IDLE_SECONDS", 1.0))
        )
        self.ack_mode = overrides.get("ack_mode", hl7_setting("ACK_MODE", "always"))
        self.dedupe = overrides.get("dedupe", hl7_setting("DEDUPE", "control-id"))
        self.allow_empty_control_id = bool(
            overrides.get("allow_empty_control_id", hl7_setting("ALLOW_EMPTY_CONTROL_ID", False))
        )
        self.encoding = str(overrides.get("encoding", hl7_setting("ENCODING", "utf-8")))
        self.max_message_bytes = int(
            overrides.get("max_message_bytes", hl7_setting("MAX_MESSAGE_BYTES", 10 * 1024 * 1024))
        )
        self.reconnect_seconds = float(
            overrides.get("reconnect_seconds", hl7_setting("RECONNECT_SECONDS", 5.0))
        )
        self.archive_dir = overrides.get("archive_dir", hl7_setting("ARCHIVE_DIR"))

    def validate(self) -> None:
        if not 1 <= self.port <= 65535:
            raise ValueError("--port must be between 1 and 65535")
        if not 1 <= self.device_port <= 65535:
            raise ValueError("--device-port must be between 1 and 65535")
        if self.max_message_bytes < 1024:
            raise ValueError("--max-message-bytes must be at least 1024")
        if self.raw_idle_seconds <= 0:
            raise ValueError("--raw-idle-seconds must be positive")
        if self.reconnect_seconds < 0.2:
            raise ValueError("--reconnect-seconds must be at least 0.2")
        if self.mode == "connect" and not self.device_host:
            raise ValueError("--device-host is required when mode=connect")


async def send_ack(writer: asyncio.StreamWriter, parsed: dict, code: str, detail: str, config: ListenerConfig) -> None:
    if config.ack_mode == "never":
        return
    try:
        text = make_ack(parsed, code, detail)
        writer.write(pack_message(text.encode(config.encoding, errors="replace"), ack_framing(config.framing)))
        await writer.drain()
    except (ConnectionError, OSError, asyncio.CancelledError):
        raise
    except Exception:
        logger.exception("Could not send HL7 ACK")


async def handle_payload(payload: bytes, writer: asyncio.StreamWriter, remote_host: str, remote_port: Optional[int], config: ListenerConfig) -> None:
    # Long-lived listener connections hold DB cursors open across awaits; make
    # sure every message starts on a fresh, valid database connection.
    close_old_connections()
    try:
        outcome = persist_payload(
            payload,
            remote_host=remote_host,
            remote_port=remote_port,
            dedupe=config.dedupe,
            allow_empty_control_id=config.allow_empty_control_id,
            archive_dir=config.archive_dir,
        )
    except Exception as exc:
        logger.exception("Storage failed for incoming message from %s:%s (%s)", remote_host, remote_port, exc)
        await send_ack(writer, {}, "AE", "Receiver storage failure; please retry", config)
        return

    status = outcome["status"]
    if status in {"accepted", "duplicate"}:
        await send_ack(writer, outcome["parsed"], "AA", "Message stored" if status == "accepted" else "Duplicate already received", config)
    else:
        await send_ack(writer, outcome["parsed"], "AE", outcome["error"] or "Message rejected", config)


async def handle_connection(reader: asyncio.StreamReader, writer: asyncio.StreamWriter, config: ListenerConfig) -> None:
    peer = writer.get_extra_info("peername") or ("unknown", 0)
    remote_host = str(peer[0]) if isinstance(peer, tuple) and len(peer) > 0 else "unknown"
    try:
        remote_port = int(peer[1]) if isinstance(peer, tuple) and len(peer) > 1 else None
    except (TypeError, ValueError):
        remote_port = None
    logger.info("Connection opened from %s:%s", remote_host, remote_port)
    try:
        if config.framing == "mllp":
            buffer = bytearray()
            while True:
                chunk = await reader.read(8192)
                if not chunk:
                    if buffer:
                        logger.warning("Connection closed with %s unframed bytes buffered from %s:%s", len(buffer), remote_host, remote_port)
                    break
                buffer.extend(chunk)
                while True:
                    start = buffer.find(MLLP_START)
                    if start < 0:
                        if len(buffer) > config.max_message_bytes:
                            logger.warning("Discarding oversized non-MLLP input from %s:%s", remote_host, remote_port)
                            buffer.clear()
                        elif buffer:
                            # Retain a final VT if it could be split across reads; otherwise discard noise.
                            if buffer[-1:] == MLLP_START:
                                buffer[:] = MLLP_START
                            else:
                                logger.warning("Discarding %s byte(s) outside MLLP frame from %s:%s", len(buffer), remote_host, remote_port)
                                buffer.clear()
                        break
                    if start > 0:
                        logger.warning("Discarding %s byte(s) before MLLP frame from %s:%s", start, remote_host, remote_port)
                        del buffer[:start]
                    end = buffer.find(MLLP_END, 1)
                    if end < 0:
                        if len(buffer) > config.max_message_bytes + len(MLLP_START) + len(MLLP_END):
                            logger.error("MLLP message exceeds max size; closing %s:%s", remote_host, remote_port)
                            return
                        break
                    payload = bytes(buffer[1:end])
                    del buffer[: end + len(MLLP_END)]
                    if not payload:
                        logger.warning("Ignoring empty MLLP frame from %s:%s", remote_host, remote_port)
                        continue
                    if len(payload) > config.max_message_bytes:
                        logger.error("Message exceeds max size; not processing it")
                        continue
                    await handle_payload(payload, writer, remote_host, remote_port, config)
        else:
            # raw-idle: an interval with no received bytes ends one message. Only
            # use it when the device's transport manual confirms this behaviour.
            buffer = bytearray()
            while True:
                try:
                    chunk = await asyncio.wait_for(reader.read(8192), timeout=config.raw_idle_seconds)
                except asyncio.TimeoutError:
                    chunk = None
                if chunk:
                    buffer.extend(chunk)
                    if len(buffer) > config.max_message_bytes:
                        logger.error("Unframed message exceeds max size; closing %s:%s", remote_host, remote_port)
                        return
                    continue
                if buffer:
                    await handle_payload(bytes(buffer), writer, remote_host, remote_port, config)
                    buffer.clear()
                if chunk == b"":
                    break
                # `None` means the idle timeout elapsed; keep the connection open.
    except asyncio.CancelledError:
        raise
    except (ConnectionResetError, BrokenPipeError):
        logger.info("Connection reset by %s:%s", remote_host, remote_port)
    except Exception:
        logger.exception("Unhandled error on connection from %s:%s", remote_host, remote_port)
    finally:
        logger.info("Connection closed from %s:%s", remote_host, remote_port)
        writer.close()
        try:
            await writer.wait_closed()
        except Exception:
            pass


async def run_listener(config: ListenerConfig) -> None:
    server = await asyncio.start_server(
        lambda reader, writer: handle_connection(reader, writer, config),
        host=config.host,
        port=config.port,
        limit=config.max_message_bytes + 65536,
        reuse_address=True,
    )
    sockets = server.sockets or []
    bound = ", ".join(str(sock.getsockname()) for sock in sockets) or f"{config.host}:{config.port}"
    logger.info("HL7 listener listening on %s using %s framing; database=Django default", bound, config.framing)
    async with server:
        await server.serve_forever()


async def run_client(config: ListenerConfig) -> None:
    """Dial out to an analyzer that hosts the TCP endpoint, reconnecting forever."""
    while True:
        writer: Optional[asyncio.StreamWriter] = None
        try:
            logger.info("Connecting to analyzer at %s:%s", config.device_host, config.device_port)
            reader, writer = await asyncio.open_connection(
                config.device_host, config.device_port, limit=config.max_message_bytes + 65536
            )
            await handle_connection(reader, writer, config)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.warning("Analyzer connection failed (%s); retrying in %.1f seconds", exc, config.reconnect_seconds)
            if writer is not None:
                writer.close()
                try:
                    await writer.wait_closed()
                except Exception:
                    pass
        await asyncio.sleep(config.reconnect_seconds)


async def serve(config: ListenerConfig) -> None:
    config.validate()
    if config.mode == "listen":
        await run_listener(config)
    else:
        await run_client(config)


def start(config: ListenerConfig) -> None:
    """Blocking entry point used by the management command."""
    asyncio.run(serve(config))
