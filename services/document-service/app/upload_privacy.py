"""Bound request bodies before multipart parsing can spill private files to disk."""

from starlette.exceptions import HTTPException
from starlette.responses import JSONResponse


class UploadBodyLimit:
    def __init__(self, app, limit):
        self.app = app
        self.limit = limit

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        headers = dict(scope.get("headers", []))
        try:
            length = int(headers.get(b"content-length", b"0"))
        except ValueError:
            length = self.limit + 1
        if length > self.limit:
            response = JSONResponse({"detail": "Request exceeds upload limit"}, status_code=413)
            return await response(scope, receive, send)
        consumed = 0

        async def bounded_receive():
            nonlocal consumed
            message = await receive()
            consumed += len(message.get("body", b""))
            if consumed > self.limit:
                raise HTTPException(413, "Request exceeds upload limit")
            return message

        return await self.app(scope, bounded_receive, send)
