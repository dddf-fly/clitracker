from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class CapturedRequest:
    request_id: str
    timestamp: float
    method: str
    url: str
    host: str
    path: str
    request_headers: dict[str, str]
    request_body: Any | None = None
    status_code: int | None = None
    response_headers: dict[str, str] | None = None
    response_body: Any | None = None
    error: str | None = None
    duration_ms: int | None = None
    raw_response_text: str | None = None
    sse_events: list[dict[str, Any]] = field(default_factory=list)
    is_streaming: bool = False
    matched: bool = False
    tags: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.request_id,
            "timestamp": self.timestamp,
            "method": self.method,
            "url": self.url,
            "host": self.host,
            "path": self.path,
            "request_headers": self.request_headers,
            "request_body": self.request_body,
            "status_code": self.status_code,
            "response_headers": self.response_headers,
            "response_body": self.response_body,
            "error": self.error,
            "duration_ms": self.duration_ms,
            "raw_response_text": self.raw_response_text,
            "sse_events": self.sse_events,
            "is_streaming": self.is_streaming,
            "matched": self.matched,
            "tags": self.tags,
        }
