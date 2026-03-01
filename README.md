# CLI Tracker

![CLI Tracker Demo](docs/assets/promo.gif)

CLI Tracker is a small FastAPI + mitmproxy dashboard for inspecting local AI client traffic in real time.

It runs:

- a FastAPI UI on `http://127.0.0.1:3000`
- an in-process `mitmproxy` HTTPS proxy on `http://127.0.0.1:8080`
- a WebSocket feed that streams captured requests into the dashboard

## What It Does

- Captures matching `POST` requests and keeps them in memory.
- Filters traffic by allowed hosts and tracked path fragments.
- Supports a catch-all mode for any `POST` request on allowed hosts.
- Parses JSON request bodies and JSON responses.
- Detects `text/event-stream` responses and reconstructs assistant output from SSE chunks.
- Shows a structured dashboard with message blocks, tool calls, raw JSON toggles, diagnostics, and request metadata.

## Default Tracked Traffic

Default allowed hosts:

- `api.anthropic.com`
- `api.claude.ai`
- `api.z.ai`
- `api.githubcopilot.com`

User config currently also includes:

- `integrate.api.nvidia.com`

Default tracked path fragments:

- `/v1/messages`
- `/v1/responses`
- `/v1/chat/completions`
- `/chat/completions`

## Install

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

## Run

```powershell
python run.py
```

Open:

- UI: `http://127.0.0.1:3000`
- setup script endpoint: `http://127.0.0.1:3000/setup`
- proxy: `http://127.0.0.1:8080`

## Terminal Setup

PowerShell:

```powershell
Invoke-Expression (Invoke-RestMethod "http://127.0.0.1:3000/setup?shell=powershell")
```

Bash:

```bash
eval "$(curl -s http://127.0.0.1:3000/setup)"
```

The generated setup script exports proxy variables plus CA-related variables pointing to the mitmproxy CA:

- Windows: `%USERPROFILE%\.mitmproxy\mitmproxy-ca-cert.pem`
- Unix: `~/.mitmproxy/mitmproxy-ca-cert.pem`

## Windows Go / Crush Certificate Note

Go clients on Windows use the Windows system trust store, not environment variables such as `SSL_CERT_FILE`.

If a Go-based client like Crush fails TLS validation through the proxy, import the mitmproxy CA into Trusted Root Certification Authorities:

```powershell
Import-Certificate -FilePath "$env:USERPROFILE\.mitmproxy\mitmproxy-ca-cert.pem" -CertStoreLocation Cert:\LocalMachine\Root
```

Without admin rights:

```powershell
Import-Certificate -FilePath "$env:USERPROFILE\.mitmproxy\mitmproxy-ca-cert.pem" -CertStoreLocation Cert:\CurrentUser\Root
```

To remove it later:

```powershell
Get-ChildItem Cert:\LocalMachine\Root | Where-Object { $_.Subject -like "*mitmproxy*" } | Remove-Item
```

Adding the mitmproxy CA to the trusted root store allows local HTTPS interception. Use it only if that is intentional.

## HTTP / WS Endpoints

- `GET /` renders the dashboard UI
- `GET /setup` returns a shell setup script
- `GET /status` returns basic runtime stats plus settings
- `GET /api/settings` returns current settings and diagnostics
- `GET /api/bootstrap` returns UI display metadata
- `POST /api/settings` updates allowed hosts, tracked paths, and catch-all mode
- `POST /api/rejected/clear` clears diagnostics counters
- `POST /clear` clears captured request history
- `WS /ws` streams request history and live updates

## Project Layout

- `run.py`: simple local entry point for `uvicorn`
- `app/main.py`: FastAPI app, routes, startup/shutdown, setup script generation
- `app/proxy_addon.py`: mitmproxy addon, request matching, response parsing, SSE reconstruction
- `app/state.py`: in-memory request store, diagnostics counters, WebSocket fanout
- `app/models.py`: captured request model
- `app/ui_display.py`: labels and field metadata for the UI
- `app/templates/index.html`: main page shell
- `app/static/js/index.js`: client-side rendering and interactions
- `app/static/css/index.css`: dashboard layout and styles
- `app/data/allowed_hosts.json`: persisted host/path configuration

## Documentation

- `docs/README.md`
- `docs/architecture.md`
- `docs/function-map.md`

## Limitations

- In-memory storage only; restarting the app clears captured requests.
- No automated test suite is included.
- `run.py` binds the UI to port `3000`; use `uvicorn app.main:app ...` if you need custom server flags.
