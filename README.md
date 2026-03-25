# openclaw-openwebui-pipe

An [Open WebUI](https://github.com/open-webui/open-webui) **Pipe function** that connects Open WebUI's chat interface to an [OpenClaw](https://openclaw.io) main agent via the ACP WebSocket protocol.

Once installed, a new model option called **"OpenClaw (main)"** appears in your Open WebUI chat. Messages go directly to your OpenClaw agent and stream back in real time.

---

## What you need

| Requirement | Notes |
|---|---|
| Open WebUI | v0.5.0 or later |
| OpenClaw | Any install (official or Hostinger image) |
| Docker network | Both containers must be on the same Docker network |

---

## How it works

Open WebUI sends your message to the pipe function, which opens a WebSocket connection to OpenClaw's ACP gateway, authenticates using Ed25519 device credentials, sends the message to the main agent session, and streams the response back token by token.

The authentication protocol is ACP V3 — the same protocol used by OpenClaw's own desktop client.

---

## Installation

### Step 1 — Get your OpenClaw credentials

You need four values from your OpenClaw data folder. They are created automatically when OpenClaw first starts.

**File 1:** `.openclaw/openclaw.json`
- `gateway → auth → token` → this is your `gateway_token`

**File 2:** `.openclaw/identity/device.json`
- `deviceId` → this is your `device_id`
- `privateKeyPem` → this is your `private_key_b64` (paste only the base64 line, no headers)
- `publicKeyPem` → this is your `public_key_b64` (paste only the base64 line, no headers)

See `config.example.json` in this repo for a detailed guide to each field.

### Step 2 — Install the pipe in Open WebUI

1. Sign in to Open WebUI as admin
2. Go to **Admin Panel** → **Functions**
3. Click **+** to create a new function
4. Delete the placeholder code, paste the entire contents of `openclaw_pipe.py`
5. Click **Save**

### Step 3 — Configure the Valves

After saving, click the **gear icon (⚙️)** next to the function to open the Valves panel.

Fill in:

| Valve | Where to find it |
|---|---|
| `gateway_url` | `ws://your-openclaw-container-name:48146` (Hostinger) or `ws://your-openclaw-container-name:18789` (official) |
| `gateway_token` | `.openclaw/openclaw.json` → `gateway.auth.token` |
| `device_id` | `.openclaw/identity/device.json` → `deviceId` |
| `private_key_b64` | `.openclaw/identity/device.json` → `privateKeyPem` (base64 only) |
| `public_key_b64` | `.openclaw/identity/device.json` → `publicKeyPem` (base64 only) |

### Step 4 — Enable and use

Toggle the function on in the Functions list, then go to chat and select **"OpenClaw (main)"** from the model dropdown.

---

## Docker network setup

Open WebUI must be able to reach OpenClaw by container name. Both must be on the same Docker network.

In each `docker-compose.yml`, add:

```yaml
networks:
  - shared-network-name

# at the bottom:
networks:
  shared-network-name:
    external: true
```

Create the network once on the host:
```bash
docker network create shared-network-name
```

Then use the OpenClaw container name as the hostname in `gateway_url`:
```
ws://openclaw-myproject-openclaw-1:48146
```

To find your container name:
```bash
docker ps | grep openclaw
```

---

## Troubleshooting

| What you see | Cause | Fix |
|---|---|---|
| "OpenClaw (main)" not in model list | Function not enabled | Admin Panel → Functions → toggle on |
| "Configuration required" | Valves empty | Click ⚙️ and fill in all fields |
| "Connect rejected: invalid connect params" | Wrong or missing keys | Double-check all Valve values |
| "Connect rejected: device signature invalid" | Key mismatch | Ensure private and public keys are from the same `device.json` |
| "Timed out waiting for connect" | Wrong `gateway_url` or OpenClaw not running | Check the URL and that OpenClaw is up (`docker ps`) |
| "Timed out waiting for agent response" | Agent or model is slow/stuck | Check OpenClaw logs; try restarting |
| Spins forever, no response | OpenClaw received the message but the model did not reply | Check which model OpenClaw is using; check API key / Ollama status |

---

## Notes

- The pipe connects to OpenClaw's **main agent** session (`agent:main:main`). This is OpenClaw's default primary agent.
- Each message opens a new WebSocket connection. This is stateless by design — conversation history is managed by Open WebUI and sent in each request.
- The pipe uses Ed25519 signing. The `cryptography` library handles this; no extra tools needed.
- Key input accepts either bare base64 or full PEM blocks. The pipe reconstructs PEM internally.

---

## Files

| File | Purpose |
|---|---|
| `openclaw_pipe.py` | The pipe — paste this into Open WebUI Functions |
| `config.example.json` | Reference template for all required values |
| `README.md` | This guide |
| `LICENSE` | MIT |

---

## License

MIT — see [LICENSE](LICENSE).
