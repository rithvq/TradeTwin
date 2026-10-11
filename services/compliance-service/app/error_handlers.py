import uuid

from fastapi import FastAPI, HTTPException, Request, status
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.regulations import (
    RegulationNotFound,
)
from app.schemas import (
    ErrorResponse,
)


def configure_error_handling(app: FastAPI) -> None:
    @app.middleware("http")
    async def add_trace_id(request: Request, call_next):
        trace_id = str(uuid.uuid4())
        request.state.trace_id = trace_id
        response = await call_next(request)
        response.headers["X-Trace-Id"] = trace_id
        return response

    @app.exception_handler(HTTPException)
    def http_exception_handler(request: Request, exc: HTTPException):
        return JSONResponse(
            status_code=exc.status_code,
            content=ErrorResponse(
                error="HTTP_ERROR",
                detail=exc.detail,
                trace_id=getattr(request.state, "trace_id", None),
            ).model_dump(mode="json"),
        )

    @app.exception_handler(RequestValidationError)
    def validation_exception_handler(request: Request, exc: RequestValidationError):
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            content=ErrorResponse(
                error="VALIDATION_ERROR",
                detail=jsonable_encoder(exc.errors(), custom_encoder={ValueError: str}),
                trace_id=getattr(request.state, "trace_id", None),
            ).model_dump(mode="json"),
        )

    @app.exception_handler(Exception)
    def unhandled_exception_handler(request: Request, exc: Exception):
        del exc
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content=ErrorResponse(
                error="INTERNAL_SERVER_ERROR",
                detail="An unexpected server error occurred.",
                trace_id=getattr(request.state, "trace_id", None),
            ).model_dump(mode="json"),
        )

    @app.exception_handler(RegulationNotFound)
    def regulation_not_found_handler(request: Request, exc: RegulationNotFound):
        return JSONResponse(
            status_code=status.HTTP_404_NOT_FOUND,
            content=ErrorResponse(
                error="NOT_FOUND",
                detail=f"Regulation not found: {exc.regulation_id}",
                trace_id=getattr(request.state, "trace_id", None),
            ).model_dump(mode="json"),
        )
