# Function Map

This file is a concise inventory of the main functions and methods in the project.

## `run.py`

- `__main__`: starts `uvicorn` with `app.main:app` on `127.0.0.1:3000`

## `app/main.py`

- `default_ca_path()`: returns the default mitmproxy CA path in the current user profile
- `render_template(name)`: reads an HTML template from `app/templates`
- `json_payload(data)`: wraps a dict in `JSONResponse`
- `settings_snapshot()`: returns current settings plus diagnostics and runtime ports
- `bootstrap_snapshot()`: returns UI bootstrap metadata for the frontend
- `_shell_exports(shell)`: builds proxy and CA export lines for shell setup scripts
- `_powershell_unset()`: generates a PowerShell helper function to clear proxy-related env vars
- `_bash_unset()`: generates a shell helper function to clear proxy-related env vars
- `setup_script(shell)`: assembles the final shell bootstrap script
- `run_proxy_server()`: starts mitmproxy `DumpMaster` and attaches the wiretap addon
- `startup()`: FastAPI startup hook that launches the proxy task
- `shutdown()`: FastAPI shutdown hook that stops the proxy task cleanly
- `index()`: serves the dashboard page
- `setup()`: serves a shell bootstrap script
- `status()`: returns runtime counters plus settings
- `get_settings()`: returns editable settings and diagnostics
- `get_bootstrap()`: returns frontend display config
- `update_settings(payload)`: updates allowed hosts, tracked paths, and catch-all mode
- `clear_rejected()`: clears diagnostics counters
- `clear()`: clears captured request history
- `websocket_endpoint(websocket)`: registers a client socket and keeps it open until disconnect

## `app/models.py`

- `CapturedRequest.to_dict()`: converts the dataclass into the JSON shape expected by the frontend

## `app/proxy_addon.py`

Top-level helpers:

- `_now()`: current UNIX time in seconds
- `_now_ms()`: current UNIX time in milliseconds
- `parse_sse_events(raw_text)`: extracts JSON payloads from SSE `data:` lines
- `_safe_dict(value)`: normalizes unknown values to dict-or-empty-dict
- `reconstruct_sse_response(events)`: rebuilds an Anthropic-style streamed message into a final response shape
- `reconstruct_openai_sse_response(events)`: rebuilds an OpenAI-style streamed message into a final response shape

`WiretapAddon` methods:

- `__init__(state, loop)`: stores shared state and the event loop used for async handoff
- `_schedule(coro)`: submits a coroutine from mitmproxy callbacks to the main asyncio loop
- `_broadcast_diagnostics()`: pushes fresh diagnostics to the UI
- `_new_request_id()`: generates a UUID for a captured request
- `_matches(flow)`: applies allowlist, tracked path, catch-all, and diagnostics logic
- `_decode_json(raw)`: decodes bytes into JSON when possible and also returns the raw text
- `_request_headers(flow)`: normalizes request headers to a plain dict
- `_response_headers(flow)`: normalizes response headers to a plain dict
- `request(flow)`: captures and broadcasts the request start payload
- `response(flow)`: parses the response, reconstructs SSE when needed, and broadcasts completion
- `error(flow)`: records a request error and broadcasts it

## `app/state.py`

Internal helpers:

- `_trim_ordered_dict(items, max_size)`: removes oldest entries when capacity is exceeded
- `_record_counter(items, key, max_size)`: increments a diagnostics counter and keeps insertion order
- `_counter_snapshot(items, value_key)`: converts ordered counters to newest-first API payloads
- `_normalize_hosts(hosts)`: canonicalizes hostnames for allowlist matching
- `_normalize_paths(paths)`: canonicalizes tracked path fragments
- `_load_allowed_hosts()`: loads persisted config from disk
- `_save_allowed_hosts_locked()`: writes persisted config to disk

Async state methods:

- `add_socket(websocket)`: accepts a WebSocket and sends initial request history
- `remove_socket(websocket)`: removes a disconnected WebSocket
- `upsert_request(request)`: inserts or updates a captured request
- `get_request(request_id)`: fetches a single captured request
- `clear()`: clears captured request history and broadcasts `clear_all`
- `stats()`: returns counts for requests and connected clients
- `broadcast(message)`: fans out a message to all active WebSockets and prunes stale sockets

Configuration / diagnostics methods:

- `is_allowed_host(host)`: checks host against the allowlist
- `get_allowed_hosts()`: returns current allowlist
- `get_tracked_paths()`: returns current tracked paths
- `get_catch_all_mode()`: returns catch-all state
- `set_catch_all_mode(enabled)`: updates catch-all state
- `set_allowed_hosts(hosts)`: stores normalized allowlist and persists it
- `set_tracked_paths(paths)`: stores normalized tracked paths and persists them
- `record_rejected_host(host)`: increments rejected-host diagnostics
- `get_rejected_hosts()`: returns rejected-host diagnostics
- `clear_rejected_hosts()`: clears rejected-host diagnostics
- `record_rejected_path(path)`: increments rejected-path diagnostics
- `get_rejected_paths()`: returns rejected-path diagnostics
- `clear_rejected_paths()`: clears rejected-path diagnostics
- `record_seen_post_target(host, path)`: increments seen-target diagnostics
- `is_tracked_path(path)`: checks whether the path contains any tracked fragment
- `get_seen_post_targets()`: returns seen-target diagnostics
- `clear_seen_post_targets()`: clears seen-target diagnostics
- `clear_diagnostics()`: clears all diagnostics counters
- `diagnostics_snapshot()`: returns all diagnostics as one payload

## `app/ui_display.py`

- `display_config()`: returns the frontend label/key metadata used by the browser renderer

## `app/static/js/index.js`

This file is the entire browser application. It is not practical to mirror every local helper here, but the major responsibilities are:

- fetch bootstrap and settings data
- maintain an in-memory map of captured requests in the browser
- render the request list and detail panels
- render structured assistant/user/tool content blocks
- support local raw JSON views for individual blocks
- manage diagnostics tabs and settings persistence
- listen to `WS /ws` and apply live updates
