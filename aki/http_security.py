"""Optional shared API key and bounded request bodies for demo integration."""

import hmac
import os
from typing import Annotated

from fastapi import HTTPException, Security
from fastapi.responses import JSONResponse
from fastapi.security import APIKeyHeader

MAX_REQUEST_BYTES = 2_000_000
api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


def require_api_key(value: Annotated[str | None, Security(api_key_header)]):
    expected = os.environ.get("AKI_API_KEY")
    if expected and (
        not value
        or not hmac.compare_digest(expected.encode("utf-8"), value.encode("utf-8"))
    ):
        raise HTTPException(401, "Valid X-API-Key required")


class BodyLimitMiddleware:
    def __init__(self, app, limit=MAX_REQUEST_BYTES):
        self.app, self.limit = app, limit

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        headers = dict(scope.get("headers", []))
        size = headers.get(b"content-length")
        if size is not None:
            try:
                if int(size) < 0:
                    raise ValueError("Negative size")
                oversized = int(size) > self.limit
            except ValueError:
                return await JSONResponse(
                    {"detail": "Invalid Content-Length"}, status_code=400
                )(scope, receive, send)
            if oversized:
                return await JSONResponse(
                    {"detail": "Request exceeds 2 MB"}, status_code=413
                )(scope, receive, send)
        total = 0

        async def limited_receive():
            nonlocal total
            message = await receive()
            if message["type"] == "http.request":
                total += len(message.get("body", b""))
                if total > self.limit:
                    raise HTTPException(413, "Request exceeds 2 MB")
            return message

        return await self.app(scope, limited_receive, send)
