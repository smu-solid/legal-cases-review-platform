"""Stable problem-detail errors and exception mapping."""

from __future__ import annotations

from typing import Any

from fastapi import Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict
from starlette.exceptions import HTTPException as StarletteHTTPException


class FieldProblem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    path: list[str | int]
    code: str
    message: str


class Problem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: str
    title: str
    status: int
    code: str
    detail: str
    instance: str
    request_id: str
    errors: list[FieldProblem] | None = None
    diagnostics: dict[str, int] | None = None


class APIError(Exception):
    def __init__(
        self,
        status: int,
        code: str,
        title: str,
        detail: str,
        *,
        headers: dict[str, str] | None = None,
        errors: list[FieldProblem] | None = None,
        diagnostics: dict[str, int] | None = None,
    ) -> None:
        super().__init__(detail)
        self.status = status
        self.code = code
        self.title = title
        self.detail = detail
        self.headers = headers
        self.errors = errors
        self.diagnostics = diagnostics


def problem_response(
    request: Request,
    *,
    status: int,
    code: str,
    title: str,
    detail: str,
    errors: list[FieldProblem] | None = None,
    diagnostics: dict[str, int] | None = None,
    headers: dict[str, str] | None = None,
) -> JSONResponse:
    request_id = getattr(request.state, "request_id", "unavailable")
    body = Problem(
        type=f"https://errors.review.invalid/{code.replace('_', '/')}",
        title=title,
        status=status,
        code=code,
        detail=detail,
        instance=request.url.path,
        request_id=request_id,
        errors=errors,
        diagnostics=diagnostics,
    )
    return JSONResponse(
        status_code=status,
        content=body.model_dump(exclude_none=True),
        media_type="application/problem+json",
        headers=headers,
    )


async def api_error_handler(request: Request, exc: APIError) -> JSONResponse:
    return problem_response(
        request,
        status=exc.status,
        code=exc.code,
        title=exc.title,
        detail=exc.detail,
        errors=exc.errors,
        diagnostics=exc.diagnostics,
        headers=dict(exc.headers) if exc.headers is not None else None,
    )


async def http_error_handler(request: Request, exc: StarletteHTTPException) -> JSONResponse:
    if exc.status_code == 404:
        code, title, detail = "not_found", "Not found", "The resource was not found."
    elif exc.status_code == 405:
        code, title, detail = (
            "method_not_allowed",
            "Method not allowed",
            "The HTTP method is not supported for this resource.",
        )
    else:
        code, title, detail = "http_error", "Request failed", "The request could not be completed."
    return problem_response(
        request,
        status=exc.status_code,
        code=code,
        title=title,
        detail=detail,
        headers=dict(exc.headers) if exc.headers is not None else None,
    )


async def validation_error_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    errors = [
        FieldProblem(
            path=list(error["loc"]),
            code=str(error["type"]),
            message="Invalid value.",
        )
        for error in exc.errors()
    ]
    return problem_response(
        request,
        status=422,
        code="validation_failed",
        title="Request validation failed",
        detail="One or more request fields are invalid.",
        errors=errors,
    )


async def unhandled_error_handler(request: Request, _exc: Exception) -> JSONResponse:
    return problem_response(
        request,
        status=500,
        code="internal_error",
        title="Internal server error",
        detail="The request could not be completed.",
    )


def safe_error_context(exc: Exception) -> dict[str, Any]:
    return {"exception_type": type(exc).__name__}
