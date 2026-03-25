"""
title: OpenClaw Agent Pipe
author: github (D-jai) (D. Raol;  Deej)
author_url: https://github.com/D-jai/openclaw-openwebui-pipe
git_url: https://github.com/D-jai/openclaw-openwebui-pipe
description: >
  Routes Open WebUI chat messages to an OpenClaw main agent via the ACP WebSocket protocol.
  Uses Ed25519 device authentication. Works with any OpenClaw installation.
  See config.example.json and README.md for setup instructions.
required_open_webui_version: 0.5.0
requirements: cryptography>=41.0,websockets>=12.0
version: 0.3.0
licence: MIT
"""

import asyncio
import base64
import json
import time
import uuid
from typing import AsyncGenerator

import websockets
from cryptography.hazmat.primitives.serialization import (
    Encoding,
    PublicFormat,
    load_pem_private_key,
    load_pem_public_key,
)
from pydantic import BaseModel, Field


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _to_pem(b64_content: str, key_type: str) -> str:
    """Wrap a bare base64 string in PEM headers.

    Accepts either:
    - A bare base64 string (just the key data, no headers)
    - A full PEM block (will extract the base64 body)
    """
    content = b64_content.strip()
    if "-----" in content:
        lines = content.replace("\\n", "\n").splitlines()
        content = "".join(
            line.strip() for line in lines if "-----" not in line
        )
    return f"-----BEGIN {key_type}-----\n{content}\n-----END {key_type}-----\n"


def _pub_key_b64url(public_key_b64: str) -> str:
    pem = _to_pem(public_key_b64, "PUBLIC KEY")
    pub = load_pem_public_key(pem.encode())
    return _b64url(pub.public_bytes(Encoding.Raw, PublicFormat.Raw))


def _sign(private_key_b64: str, payload: str) -> str:
    pem = _to_pem(private_key_b64, "PRIVATE KEY")
    key = load_pem_private_key(pem.encode(), password=None)
    return _b64url(key.sign(payload.encode("utf-8")))


def _build_v3_payload(
    device_id: str,
    nonce: str,
    signed_at_ms: int,
    token: str,
    platform: str = "linux",
) -> str:
    """Build the ACP V3 device auth signing payload (pipe-delimited)."""
    return "|".join([
        "v3",
        device_id,
        "cli",                                          # clientId
        "cli",                                          # clientMode
        "operator",                                     # role
        "operator.admin,operator.read,operator.write",  # scopes
        str(signed_at_ms),
        token,
        nonce,
        platform.lower(),                               # platform
        "desktop",                                      # deviceFamily
    ])


class Pipe:
    class Valves(BaseModel):
        gateway_url: str = Field(
            default="ws://localhost:18789",
            description=(
                "OpenClaw gateway WebSocket URL. "
                "Official install: ws://<host>:18789  |  "
                "Hostinger image: ws://<container-name>:48146. "
                "If Open WebUI and OpenClaw are in the same Docker network, "
                "use the container name instead of localhost."
            ),
        )
        gateway_token: str = Field(
            default="",
            description=(
                "Gateway auth token. "
                "Find it in: .openclaw/openclaw.json → gateway → auth → token"
            ),
        )
        device_id: str = Field(
            default="",
            description=(
                "Device ID (hex string). "
                "Find it in: .openclaw/identity/device.json → deviceId"
            ),
        )
        private_key_b64: str = Field(
            default="",
            description=(
                "Ed25519 private key. "
                "Find it in: .openclaw/identity/device.json → privateKeyPem. "
                "Paste ONLY the base64 line (no BEGIN/END headers). "
                "Example: MC4CAQAwBQYDK2VwBCIE..."
            ),
        )
        public_key_b64: str = Field(
            default="",
            description=(
                "Ed25519 public key. "
                "Find it in: .openclaw/identity/device.json → publicKeyPem. "
                "Paste ONLY the base64 line (no BEGIN/END headers). "
                "Example: MCowBQYDK2VwAyEA..."
            ),
        )
        timeout_connect: int = Field(
            default=15,
            description="Seconds to wait for the auth handshake to complete.",
        )
        timeout_response: int = Field(
            default=180,
            description="Seconds to wait for the agent to finish responding.",
        )

    def __init__(self):
        self.valves = self.Valves()

    def pipes(self):
        return [{"id": "openclaw-main", "name": "OpenClaw (main)"}]

    def _validate_valves(self):
        missing = [
            name
            for name in ("gateway_token", "device_id", "private_key_b64", "public_key_b64")
            if not getattr(self.valves, name, "").strip()
        ]
        if missing:
            raise ValueError(
                f"OpenClaw pipe not configured. Fill in Valves: {', '.join(missing)}"
            )

    async def _stream(self, message: str, session_key: str) -> AsyncGenerator[str, None]:
        self._validate_valves()

        token = self.valves.gateway_token.strip()
        device_id = self.valves.device_id.strip()
        private_key_b64 = self.valves.private_key_b64.strip()
        public_key_b64 = self.valves.public_key_b64.strip()
        pub_b64url = _pub_key_b64url(public_key_b64)
        signed_at_ms = int(time.time() * 1000)

        async with websockets.connect(self.valves.gateway_url) as ws:

            # ── 1. Wait for connect.challenge ──────────────────────────────────
            raw = await asyncio.wait_for(ws.recv(), timeout=self.valves.timeout_connect)
            frame = json.loads(raw)
            if frame.get("type") != "event" or frame.get("event") != "connect.challenge":
                raise RuntimeError(f"Expected connect.challenge, got: {frame}")
            nonce = frame["payload"]["nonce"]

            # ── 2. Sign the V3 device auth payload ────────────────────────────
            v3_payload = _build_v3_payload(device_id, nonce, signed_at_ms, token)
            signature = _sign(private_key_b64, v3_payload)

            # ── 3. Send connect (auth) request ────────────────────────────────
            connect_id = str(uuid.uuid4())
            await ws.send(json.dumps({
                "type": "req",
                "id": connect_id,
                "method": "connect",
                "params": {
                    "minProtocol": 3,
                    "maxProtocol": 3,
                    "client": {
                        "id": "cli",
                        "displayName": "Open WebUI Pipe",
                        "version": "1.0.0",
                        "platform": "linux",
                        "deviceFamily": "desktop",
                        "mode": "cli",
                        "instanceId": "open-webui-pipe",
                    },
                    "caps": [],
                    "auth": {"token": token},
                    "role": "operator",
                    "scopes": ["operator.admin", "operator.read", "operator.write"],
                    "device": {
                        "id": device_id,
                        "publicKey": pub_b64url,
                        "signature": signature,
                        "signedAt": signed_at_ms,
                        "nonce": nonce,
                    },
                },
            }))

            # ── 4. Wait for connect response ───────────────────────────────────
            deadline = time.monotonic() + self.valves.timeout_connect
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise RuntimeError("Timed out waiting for connect response")
                raw = await asyncio.wait_for(ws.recv(), timeout=remaining)
                frame = json.loads(raw)
                if frame.get("id") == connect_id:
                    if not frame.get("ok"):
                        err = frame.get("error", {})
                        raise RuntimeError(
                            f"Connect rejected: {err.get('message', frame)}"
                        )
                    break  # authenticated

            # ── 5. Send message ────────────────────────────────────────────────
            chat_req_id = str(uuid.uuid4())
            await ws.send(json.dumps({
                "type": "req",
                "id": chat_req_id,
                "method": "chat.send",
                "params": {
                    "sessionKey": session_key,
                    "message": message,
                    "idempotencyKey": str(uuid.uuid4()),
                },
            }))

            # ── 6. Stream the agent's response ────────────────────────────────
            sent_len = 0
            deadline = time.monotonic() + self.valves.timeout_response
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise RuntimeError("Timed out waiting for agent response")
                raw = await asyncio.wait_for(ws.recv(), timeout=remaining)
                frame = json.loads(raw)

                if frame.get("type") == "event" and frame.get("event") == "chat":
                    payload = frame.get("payload", {})
                    state = payload.get("state")
                    msg_data = payload.get("message")

                    if msg_data and state in ("delta", "final"):
                        content = msg_data.get("content") or []
                        full_text = next(
                            (c["text"] for c in content if c.get("type") == "text"), ""
                        )
                        if len(full_text) > sent_len:
                            yield full_text[sent_len:]
                            sent_len = len(full_text)

                    if state in ("final", "aborted", "error"):
                        return

                if frame.get("id") == chat_req_id:
                    if not frame.get("ok"):
                        err = frame.get("error", {})
                        raise RuntimeError(
                            f"chat.send failed: {err.get('message', frame)}"
                        )
                    payload = frame.get("payload") or {}
                    if payload.get("status") not in ("accepted", "started", None):
                        return

    async def pipe(self, body: dict, __user__: dict = None, __event_emitter__=None) -> AsyncGenerator[str, None]:
        messages = body.get("messages", [])
        # Routes to the OpenClaw main agent session
        session_key = "agent:main:main"

        async def status(text: str, done: bool = False):
            if __event_emitter__:
                await __event_emitter__({"type": "status", "data": {"description": text, "done": done}})

        last_msg = ""
        for msg in reversed(messages):
            if msg.get("role") == "user":
                content = msg.get("content", "")
                if isinstance(content, str):
                    last_msg = content
                elif isinstance(content, list):
                    last_msg = " ".join(
                        c.get("text", "")
                        for c in content
                        if c.get("type") == "text"
                    )
                break

        if not last_msg:
            yield "No message provided."
            return

        try:
            await status("Connecting to OpenClaw...")
            async for chunk in self._stream(last_msg, session_key):
                await status("Thinking...", done=False)
                yield chunk
            await status("", done=True)
        except ValueError as e:
            await status("Configuration error", done=True)
            yield f"**Configuration required**\n\n{e}\n\nSee the Valves panel (gear icon) for this function."
        except Exception as e:
            await status("Error", done=True)
            yield f"\n\n[OpenClaw error: {e}]"
