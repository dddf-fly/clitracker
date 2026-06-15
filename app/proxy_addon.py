from __future__ import annotations

import asyncio
import json
import time
import uuid
from urllib.parse import urlsplit

from mitmproxy import http

from .models import CapturedRequest
from .state import WiretapState

DEFAULT_ALLOWED_HOSTS = (
    "api.anthropic.com",
    "api.claude.ai",
    "api.z.ai",
    "api.githubcopilot.com",
)
DEFAULT_TRACKED_PATHS = (
    "/v1/messages",
    "/v1/responses",
    "/v1/chat/completions",
    "/chat/completions",
)


def _now() -> float:
    return time.time()


def _now_ms() -> int:
    return int(_now() * 1000)


def parse_sse_events(raw_text: str) -> list[dict]:
    events: list[dict] = []
    for line in raw_text.splitlines():
        line = line.strip()
        if not line.startswith("data: "):
            continue
        payload = line[6:].strip()
        if not payload or payload == "[DONE]":
            continue
        try:
            parsed = json.loads(payload)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            events.append(parsed)
    return events


def _safe_dict(value: object) -> dict:
    return value if isinstance(value, dict) else {}


def reconstruct_sse_response(events: list[dict]) -> dict | None:
    if any(isinstance(event.get("choices"), list) for event in events):
        return reconstruct_openai_sse_response(events)

    message_start: dict | None = None
    message_delta: dict | None = None
    content_blocks: dict[int, dict] = {}
    text_deltas: dict[int, list[str]] = {}
    json_deltas: dict[int, list[str]] = {}
    thinking_deltas: dict[int, list[str]] = {}
    signature_deltas: dict[int, list[str]] = {}

    for event in events:
        event_type = event.get("type")
        if event_type == "message_start":
            message_start = event
        elif event_type == "content_block_start":
            index = event.get("index")
            block = event.get("content_block", {})
            if not isinstance(index, int) or not isinstance(block, dict):
                continue
            content_blocks[index] = block
            if block.get("type") == "text":
                text_deltas[index] = []
            elif block.get("type") == "tool_use":
                json_deltas[index] = []
            elif block.get("type") == "thinking":
                thinking_deltas[index] = []
                signature_deltas[index] = []
        elif event_type == "content_block_delta":
            index = event.get("index")
            delta = event.get("delta", {})
            if not isinstance(index, int) or not isinstance(delta, dict):
                continue
            delta_type = delta.get("type")
            if delta_type == "text_delta":
                text_deltas.setdefault(index, []).append(str(delta.get("text", "")))
            elif delta_type == "input_json_delta":
                json_deltas.setdefault(index, []).append(str(delta.get("partial_json", "")))
            elif delta_type == "thinking_delta":
                thinking_deltas.setdefault(index, []).append(
                    str(delta.get("thinking", ""))
                )
            elif delta_type == "signature_delta":
                signature_deltas.setdefault(index, []).append(
                    str(delta.get("signature", ""))
                )
        elif event_type == "message_delta":
            message_delta = event

    if not message_start:
        return None

    start_message = _safe_dict(message_start.get("message", {}))
    if not start_message:
        return None

    content: list[dict] = []
    for index in sorted(content_blocks):
        block = content_blocks[index]
        block_type = block.get("type")
        if block_type == "text":
            content.append({"type": "text", "text": "".join(text_deltas.get(index, []))})
        elif block_type == "tool_use":
            json_input: dict = {}
            raw_json = "".join(json_deltas.get(index, []))
            if raw_json:
                try:
                    parsed_json = json.loads(raw_json)
                    if isinstance(parsed_json, dict):
                        json_input = parsed_json
                except json.JSONDecodeError:
                    json_input = {}
            content.append(
                {
                    "type": "tool_use",
                    "id": block.get("id", ""),
                    "name": block.get("name", ""),
                    "input": json_input,
                }
            )
        elif block_type == "thinking":
            thinking_block: dict[str, object] = {
                "type": "thinking",
                "thinking": "".join(thinking_deltas.get(index, [])),
            }
            signature = "".join(signature_deltas.get(index, []))
            if signature:
                thinking_block["signature"] = signature
            content.append(thinking_block)

    delta_block = _safe_dict(message_delta.get("delta", {})) if message_delta else {}
    usage_delta = _safe_dict(message_delta.get("usage", {})) if message_delta else {}
    usage_start = _safe_dict(start_message.get("usage", {}))
    usage = {
        "input_tokens": usage_delta.get(
            "input_tokens",
            usage_start.get("input_tokens", 0),
        ),
        "output_tokens": usage_delta.get(
            "output_tokens",
            usage_start.get("output_tokens", 0),
        ),
        "cache_creation_input_tokens": usage_delta.get(
            "cache_creation_input_tokens",
            usage_start.get("cache_creation_input_tokens"),
        ),
        "cache_read_input_tokens": usage_delta.get(
            "cache_read_input_tokens",
            usage_start.get("cache_read_input_tokens"),
        ),
    }
    if "server_tool_use" in usage_delta:
        usage["server_tool_use"] = usage_delta["server_tool_use"]
    if "service_tier" in usage_delta:
        usage["service_tier"] = usage_delta["service_tier"]

    return {
        "id": start_message.get("id"),
        "type": "message",
        "role": start_message.get("role", "assistant"),
        "content": content,
        "model": start_message.get("model"),
        "stop_reason": delta_block.get("stop_reason"),
        "stop_sequence": delta_block.get("stop_sequence"),
        "usage": usage,
    }


def reconstruct_openai_sse_response(events: list[dict]) -> dict | None:
    chunks = [event for event in events if isinstance(event.get("choices"), list)]
    if not chunks:
        return None

    text_parts: list[str] = []
    reasoning_parts: list[str] = []
    reasoning_opaque: str | None = None
    role = "assistant"
    stop_reason: str | None = None
    response_id: str | None = None
    model: str | None = None
    usage: dict = {}
    tool_calls: dict[int, dict] = {}

    for chunk in chunks:
        response_id = chunk.get("id") or response_id
        model = chunk.get("model") or model
        if isinstance(chunk.get("usage"), dict):
            usage = dict(chunk["usage"])
        if isinstance(chunk.get("copilot_usage"), dict):
            usage["copilot_usage"] = chunk["copilot_usage"]

        for choice in chunk.get("choices", []):
            if not isinstance(choice, dict):
                continue
            if choice.get("finish_reason"):
                stop_reason = str(choice["finish_reason"])

            delta = choice.get("delta", {})
            if not isinstance(delta, dict):
                continue

            role = delta.get("role") or role

            content = delta.get("content")
            if isinstance(content, str) and content:
                text_parts.append(content)

            reasoning_text = delta.get("reasoning_text")
            if isinstance(reasoning_text, str) and reasoning_text:
                reasoning_parts.append(reasoning_text)

            reasoning_content = delta.get("reasoning_content")
            if isinstance(reasoning_content, str) and reasoning_content:
                reasoning_parts.append(reasoning_content)

            opaque = delta.get("reasoning_opaque")
            if isinstance(opaque, str) and opaque:
                reasoning_opaque = opaque

            raw_tool_calls = delta.get("tool_calls")
            if isinstance(raw_tool_calls, list):
                for tc in raw_tool_calls:
                    if not isinstance(tc, dict):
                        continue
                    index = tc.get("index")
                    if not isinstance(index, int):
                        continue
                    if index not in tool_calls:
                        tool_calls[index] = {"id": "", "name": "", "arguments": ""}
                    entry = tool_calls[index]
                    if isinstance(tc.get("id"), str):
                        entry["id"] = tc["id"]
                    function_data = tc.get("function", {})
                    if isinstance(function_data, dict):
                        if isinstance(function_data.get("name"), str):
                            entry["name"] = function_data["name"]
                        if isinstance(function_data.get("arguments"), str):
                            entry["arguments"] += function_data["arguments"]

    content_blocks: list[dict] = []
    if reasoning_parts or reasoning_opaque:
        thinking_block: dict[str, object] = {
            "type": "thinking",
            "thinking": "".join(reasoning_parts),
        }
        if reasoning_opaque:
            thinking_block["signature"] = reasoning_opaque
        content_blocks.append(thinking_block)
    if text_parts:
        content_blocks.append({"type": "text", "text": "".join(text_parts)})

    for index in sorted(tool_calls):
        tc = tool_calls[index]
        json_input: dict = {}
        raw_json = tc.get("arguments", "")
        if raw_json:
            try:
                parsed = json.loads(raw_json)
                if isinstance(parsed, dict):
                    json_input = parsed
            except json.JSONDecodeError:
                json_input = {}
        content_blocks.append({
            "type": "tool_use",
            "id": tc.get("id", ""),
            "name": tc.get("name", ""),
            "input": json_input,
        })

    if not response_id and not content_blocks and not usage:
        return None

    return {
        "id": response_id,
        "type": "message",
        "role": role,
        "content": content_blocks,
        "model": model,
        "stop_reason": stop_reason,
        "stop_sequence": None,
        "usage": usage,
    }


class WiretapAddon:
    def __init__(self, state: WiretapState, loop: asyncio.AbstractEventLoop) -> None:
        self.state = state
        self.loop = loop

    def _schedule(self, coro) -> None:
        asyncio.run_coroutine_threadsafe(coro, self.loop)

    def _broadcast_diagnostics(self) -> None:
        self._schedule(
            self.state.broadcast(
                {
                    "type": "diagnostics_update",
                    "diagnostics": self.state.diagnostics_snapshot(),
                }
            )
        )

    @staticmethod
    def _new_request_id() -> str:
        return str(uuid.uuid4())

    def _matches(self, flow: http.HTTPFlow) -> bool:
        host = flow.request.pretty_host or flow.request.host
        path = flow.request.path or ""
        method = flow.request.method.upper()
        is_post = method == "POST"
        tracked_path = self.state.is_tracked_path(path)
        allowed_host = self.state.is_allowed_host(host)
        diagnostics_changed = False

        if is_post:
            self.state.record_seen_post_target(host, path)
            diagnostics_changed = True

        if tracked_path and allowed_host:
            if diagnostics_changed:
                self._broadcast_diagnostics()
            return True

        if tracked_path and not allowed_host:
            self.state.record_rejected_host(host)
            self.state.record_rejected_path(path)
            diagnostics_changed = True
            self._broadcast_diagnostics()
            return False

        if is_post and path.startswith("/v1/"):
            self.state.record_rejected_path(path)
            diagnostics_changed = True

        if diagnostics_changed:
            self._broadcast_diagnostics()

        if is_post and allowed_host and self.state.get_catch_all_mode():
            return True

        return False

    @staticmethod
    def _decode_json(raw: bytes) -> tuple[object | None, str | None]:
        if not raw:
            return None, None

        text = raw.decode("utf-8", errors="replace")
        try:
            return json.loads(text), text
        except json.JSONDecodeError:
            return None, text

    @staticmethod
    def _request_headers(flow: http.HTTPFlow) -> dict[str, str]:
        return dict(flow.request.headers)

    @staticmethod
    def _response_headers(flow: http.HTTPFlow) -> dict[str, str]:
        return dict(flow.response.headers)

    def request(self, flow: http.HTTPFlow) -> None:
        if not self._matches(flow):
            return

        request_id = self._new_request_id()
        flow.metadata["wiretap_request_id"] = request_id
        flow.metadata["wiretap_started_at"] = _now()

        parsed = urlsplit(flow.request.pretty_url)
        request_body, _ = self._decode_json(flow.request.raw_content or b"")
        timestamp = _now()
        tracked_path = self.state.is_tracked_path(parsed.path)

        captured = CapturedRequest(
            request_id=request_id,
            timestamp=timestamp,
            method=flow.request.method,
            url=flow.request.pretty_url,
            host=parsed.hostname or "",
            path=parsed.path,
            request_headers=self._request_headers(flow),
            request_body=request_body,
            matched=True,
            tags=["tracked" if tracked_path else "catch-all"],
        )

        request_payload = captured.to_dict()
        self._schedule(self.state.upsert_request(captured))
        self._schedule(
            self.state.broadcast(
                {
                    "type": "request_start",
                    "requestId": request_id,
                    "timestamp": int(timestamp * 1000),
                    "method": captured.method,
                    "url": captured.url,
                    "headers": captured.request_headers,
                    "request": request_payload,
                }
            )
        )
        self._schedule(
            self.state.broadcast(
                {
                    "type": "request_body",
                    "requestId": request_id,
                    "body": request_body,
                    "request": request_payload,
                }
            )
        )

    def response(self, flow: http.HTTPFlow) -> None:
        request_id = flow.metadata.get("wiretap_request_id")
        if not request_id:
            return

        started_at = flow.metadata.get("wiretap_started_at", _now())
        response_body, raw_text = self._decode_json(flow.response.raw_content or b"")
        content_type = str(flow.response.headers.get("content-type", ""))
        sse_events: list[dict] = []
        is_streaming = False

        if raw_text and "text/event-stream" in content_type.lower():
            sse_events = parse_sse_events(raw_text)
            is_streaming = True
            reconstructed = reconstruct_sse_response(sse_events)
            if reconstructed is not None:
                response_body = reconstructed

        async def update() -> None:
            captured = await self.state.get_request(request_id)
            if not captured:
                return

            captured.status_code = flow.response.status_code
            captured.response_headers = self._response_headers(flow)
            captured.response_body = response_body
            captured.raw_response_text = raw_text
            captured.sse_events = sse_events
            captured.is_streaming = is_streaming
            captured.duration_ms = int((_now() - started_at) * 1000)
            request_payload = captured.to_dict()

            await self.state.broadcast(
                {
                    "type": "response_start",
                    "requestId": request_id,
                    "timestamp": _now_ms(),
                    "statusCode": captured.status_code,
                    "headers": captured.response_headers,
                    "request": request_payload,
                }
            )
            for event in sse_events:
                await self.state.broadcast(
                    {
                        "type": "response_chunk",
                        "requestId": request_id,
                        "event": event,
                        "request": request_payload,
                    }
                )
            await self.state.upsert_request(captured)
            await self.state.broadcast(
                {
                    "type": "response_complete",
                    "requestId": request_id,
                    "timestamp": _now_ms(),
                    "response": response_body,
                    "durationMs": captured.duration_ms,
                    "request": request_payload,
                }
            )

        self._schedule(update())

    def error(self, flow: http.HTTPFlow) -> None:
        request_id = flow.metadata.get("wiretap_request_id")
        if not request_id:
            return

        async def update() -> None:
            captured = await self.state.get_request(request_id)
            if not captured:
                return

            captured.error = str(flow.error)
            captured.is_streaming = False
            await self.state.upsert_request(captured)
            await self.state.broadcast(
                {
                    "type": "error",
                    "requestId": request_id,
                    "error": captured.error,
                    "timestamp": _now_ms(),
                    "request": captured.to_dict(),
                }
            )

        self._schedule(update())
