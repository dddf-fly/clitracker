from __future__ import annotations

import asyncio
import os
from pathlib import Path

from fastapi import FastAPI, Query, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from mitmproxy.options import Options
from mitmproxy.tools.dump import DumpMaster
from pydantic import BaseModel

from .proxy_addon import DEFAULT_ALLOWED_HOSTS, DEFAULT_TRACKED_PATHS, WiretapAddon
from .state import WiretapState
from .ui_display import display_config

UI_PORT = int(os.getenv("WIRETAP_UI_PORT", "3000"))
PROXY_PORT = int(os.getenv("WIRETAP_PROXY_PORT", "8080"))
TEMPLATE_DIR = Path(__file__).resolve().parent / "templates"
STATIC_DIR = Path(__file__).resolve().parent / "static"
CONFIG_DIR = Path(__file__).resolve().parent / "data"
ALLOWED_HOSTS_CONFIG_PATH = CONFIG_DIR / "allowed_hosts.json"
PROXY_URL = f"http://localhost:{PROXY_PORT}"
NO_PROXY = "localhost,127.0.0.1,::1"
CA_ENV_VARS = (
    "NODE_EXTRA_CA_CERTS",
    "SSL_CERT_FILE",
    "REQUESTS_CA_BUNDLE",
    "CURL_CA_BUNDLE",
    "GIT_SSL_CAINFO",
    "AWS_CA_BUNDLE",
)
PROXY_ENV_VARS = (
    "HTTP_PROXY",
    "HTTPS_PROXY",
    "ALL_PROXY",
    "http_proxy",
    "https_proxy",
    "all_proxy",
)
NO_PROXY_ENV_VARS = ("NO_PROXY", "no_proxy")

app = FastAPI(title="CLI Tracker")
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
state = WiretapState(
    allowed_hosts=list(DEFAULT_ALLOWED_HOSTS),
    tracked_paths=list(DEFAULT_TRACKED_PATHS),
    config_path=ALLOWED_HOSTS_CONFIG_PATH,
    catch_all_mode=True,
)
dump_master: DumpMaster | None = None
proxy_task: asyncio.Task[None] | None = None


class SettingsUpdate(BaseModel):
    allowed_hosts: list[str]
    tracked_paths: list[str]
    clear_rejected_hosts: bool = False
    catch_all_mode: bool | None = None

def default_ca_path() -> str:
    return str(Path.home() / ".mitmproxy" / "mitmproxy-ca-cert.pem")


def render_template(name: str) -> str:
    return (TEMPLATE_DIR / name).read_text(encoding="utf-8")


def json_payload(data: dict[str, object]) -> JSONResponse:
    return JSONResponse(data)


def settings_snapshot() -> dict[str, object]:
    return {
        "allowed_hosts": state.get_allowed_hosts(),
        "tracked_paths": state.get_tracked_paths(),
        "rejected_hosts": state.get_rejected_hosts(),
        "rejected_paths": state.get_rejected_paths(),
        "seen_post_targets": state.get_seen_post_targets(),
        "catch_all_mode": state.get_catch_all_mode(),
        "proxy_port": PROXY_PORT,
        "ui_port": UI_PORT,
        "ca_path": default_ca_path(),
        "allowed_hosts_config_path": str(ALLOWED_HOSTS_CONFIG_PATH),
    }


def bootstrap_snapshot() -> dict[str, object]:
    return {
        "ui_port": UI_PORT,
        "proxy_port": PROXY_PORT,
        "display_config": display_config(),
    }


def _shell_exports(shell: str) -> list[str]:
    ca_path = default_ca_path()
    exports = [f'{name} = "{PROXY_URL}"' for name in PROXY_ENV_VARS]
    exports.extend(f'{name} = "{ca_path}"' for name in CA_ENV_VARS)
    exports.extend(f'{name} = "{NO_PROXY}"' for name in NO_PROXY_ENV_VARS)
    if shell == "powershell":
        return [f"$env:{entry}" for entry in exports]
    return [f"export {entry}" for entry in exports]


def _powershell_unset() -> list[str]:
    vars_to_clear = (*PROXY_ENV_VARS, *CA_ENV_VARS, *NO_PROXY_ENV_VARS)
    lines = [f"  $env:{name} = $null" for name in vars_to_clear]
    lines.append('  Write-Host "Wiretap disabled"')
    return [
        "function global:unset-wiretap {",
        *lines,
        "}",
    ]


def _bash_unset() -> list[str]:
    vars_to_clear = " ".join((*PROXY_ENV_VARS, *CA_ENV_VARS, *NO_PROXY_ENV_VARS))
    return [
        "unset-wiretap() {",
        f"  unset {vars_to_clear}",
        '  echo "Wiretap disabled"',
        "}",
    ]


def setup_script(shell: str) -> str:
    if shell == "powershell":
        lines = [*_shell_exports(shell), *_powershell_unset(), f'Write-Host "Wiretap enabled via {PROXY_URL}"']
        return "\n".join(lines) + "\n"

    lines = [*_shell_exports(shell), *_bash_unset(), f'echo "Wiretap enabled via {PROXY_URL}"']
    return "\n".join(lines) + "\n"


async def run_proxy_server() -> None:
    global dump_master

    options = Options(listen_host="127.0.0.1", listen_port=PROXY_PORT, http2=True)
    dump_master = DumpMaster(options, with_termlog=False, with_dumper=False)
    dump_master.addons.add(WiretapAddon(state, asyncio.get_running_loop()))

    try:
        await dump_master.run()
    except asyncio.CancelledError:
        if dump_master is not None:
            dump_master.shutdown()
        raise


@app.on_event("startup")
async def startup() -> None:
    global proxy_task
    proxy_task = asyncio.create_task(run_proxy_server())


@app.on_event("shutdown")
async def shutdown() -> None:
    global proxy_task
    if dump_master is not None:
        dump_master.shutdown()
    if proxy_task is not None:
        proxy_task.cancel()
        try:
            await proxy_task
        except asyncio.CancelledError:
            pass


@app.get("/", response_class=HTMLResponse)
async def index() -> str:
    return render_template("index.html")


@app.get("/setup")
async def setup(
    shell: str = Query(default="bash"),
    client: str = Query(default="claude"),
) -> PlainTextResponse:
    _ = client.lower()
    resolved = "powershell" if shell.lower() in {"powershell", "pwsh", "ps"} else "bash"
    return PlainTextResponse(setup_script(resolved))


@app.get("/status")
async def status() -> JSONResponse:
    payload = await state.stats()
    payload.update(settings_snapshot())
    return json_payload(payload)


@app.get("/api/settings")
async def get_settings() -> JSONResponse:
    return json_payload(settings_snapshot())


@app.get("/api/bootstrap")
async def get_bootstrap() -> JSONResponse:
    return json_payload(bootstrap_snapshot())


@app.post("/api/settings")
async def update_settings(payload: SettingsUpdate) -> JSONResponse:
    state.set_allowed_hosts(payload.allowed_hosts)
    state.set_tracked_paths(payload.tracked_paths)
    if payload.catch_all_mode is not None:
        state.set_catch_all_mode(payload.catch_all_mode)
    if payload.clear_rejected_hosts:
        state.clear_diagnostics()
    return json_payload(settings_snapshot())


@app.post("/api/rejected/clear")
async def clear_rejected() -> JSONResponse:
    state.clear_diagnostics()
    return json_payload(settings_snapshot())


@app.post("/clear")
async def clear() -> JSONResponse:
    await state.clear()
    return json_payload({"ok": True})


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket) -> None:
    await state.add_socket(websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        await state.remove_socket(websocket)
