from __future__ import annotations

from typing import Any


DISPLAY_CONFIG: dict[str, Any] = {
    "labels": {
        "system_prompt": "System Prompt",
        "available_tools": "Available Tools",
        "input_schema": "Input Schema",
        "thinking": "THINKING",
        "tool_call": "TOOL CALL",
        "tool_result": "TOOL RESULT",
        "image": "IMAGE",
        "assistant": "ASSISTANT",
        "assistant_error": "ASSISTANT (ERROR)",
        "raw_request": "Raw Request",
        "streaming_events": "Streaming Events",
        "full_json": "Full JSON",
        "system_blocks_count": "blocks",
        "events": "events",
    },
    "keys": {
        "type": "type",
        "cache_control": "cache_control",
        "text": "text",
        "thinking": "thinking",
        "signature": "signature",
        "name": "name",
        "id": "id",
        "input": "input",
        "tool_use_id": "tool_use_id",
        "content": "content",
        "is_error": "is_error",
        "source": "source",
        "model": "model",
        "max_tokens": "max_tokens",
        "stream": "stream",
        "tool_choice": "tool_choice",
        "stop_sequences": "stop_sequences",
        "temperature": "temperature",
        "top_p": "top_p",
        "top_k": "top_k",
        "metadata": "metadata",
        "messages": "messages",
        "tools": "tools",
    },
    "raw_request_fields": [
        {"key": "model", "kind": "pill"},
        {"key": "max_tokens", "kind": "pill"},
        {"key": "stream", "kind": "bool"},
        {"key": "tool_choice", "kind": "json"},
        {"key": "stop_sequences", "kind": "json"},
        {"key": "temperature", "kind": "pill"},
        {"key": "top_p", "kind": "pill"},
        {"key": "top_k", "kind": "pill"},
        {"key": "metadata", "kind": "json"},
        {"key": "messages", "kind": "count"},
        {"key": "tools", "kind": "count"},
    ],
}


def display_config() -> dict[str, Any]:
    return DISPLAY_CONFIG
