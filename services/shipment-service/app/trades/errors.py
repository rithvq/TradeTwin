from uuid import uuid4

from fastapi import Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy.exc import SQLAlchemyError


class TradeError(Exception):
    def __init__(self, code, message, status=422, fields=None):
        self.code, self.message, self.status = code, message, status
        self.fields = fields or []


def field(path, message, code="INVALID"):
    return {"path": path, "code": code, "message": message}


def pydantic_fields(errors):
    return [
        field(
            ".".join(str(part) for part in error["loc"] if part != "body"),
            error["msg"],
            "REQUIRED" if error["type"] == "missing" else "INVALID",
        )
        for error in errors
    ]


def error_response(request, code, message, status, fields=None):
    return JSONResponse(
        {
            "error": {
                "code": code,
                "message": message,
                "request_id": str(getattr(request.state, "request_id", uuid4())),
                "field_errors": fields or [],
                "retryable": status in {412, 503},
            }
        },
        status_code=status,
    )


def install_handlers(app):
    @app.exception_handler(SQLAlchemyError)
    async def database_error(request: Request, exc: SQLAlchemyError):
        if request.url.path.startswith("/api/v1/"):
            return error_response(
                request,
                "STORAGE_UNAVAILABLE",
                "Commercial storage unavailable. Retry the same request key.",
                503,
            )
        return JSONResponse({"detail": "Storage unavailable"}, status_code=503)

    @app.exception_handler(TradeError)
    async def trade_error(request: Request, exc: TradeError):
        return error_response(request, exc.code, exc.message, exc.status, exc.fields)

    @app.exception_handler(RequestValidationError)
    async def validation_error(request: Request, exc: RequestValidationError):
        if request.url.path.startswith("/api/v1/"):
            return error_response(
                request,
                "VALIDATION_ERROR"
                if "Trade operations - Phase 2" in getattr(request.scope.get("route"), "tags", [])
                else "VALIDATION_FAILED",
                "Check the marked fields.",
                422,
                pydantic_fields(exc.errors()),
            )
        from fastapi.exception_handlers import request_validation_exception_handler

        return await request_validation_exception_handler(request, exc)
