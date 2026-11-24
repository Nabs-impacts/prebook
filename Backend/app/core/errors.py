import logging
from typing import Any, cast

from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.types import ExceptionHandler

from app.core.logging import request_id_ctx

logger = logging.getLogger("prebook.errors")

HTTP_ERROR_CODES: dict[int, str] = {
    400: "bad_request",
    401: "unauthorized",
    403: "forbidden",
    404: "not_found",
    405: "method_not_allowed",
    409: "conflict",
    422: "validation_error",
    429: "too_many_requests",
    500: "internal_error",
    503: "service_unavailable",
}


class AppError(Exception):
    status_code: int = 500
    code: str = "internal_error"
    message: str = "Une erreur interne est survenue."

    def __init__(
        self,
        message: str | None = None,
        *,
        code: str | None = None,
        status_code: int | None = None,
        details: Any = None,
    ) -> None:
        self.message = message or self.message
        self.code = code or self.code
        self.status_code = status_code or self.status_code
        self.details = details
        super().__init__(self.message)


class BadRequestError(AppError):
    status_code = 400
    code = "bad_request"
    message = "Requête invalide."


class UnauthorizedError(AppError):
    status_code = 401
    code = "unauthorized"
    message = "Authentification requise."


class ForbiddenError(AppError):
    status_code = 403
    code = "forbidden"
    message = "Accès refusé."


class NotFoundError(AppError):
    status_code = 404
    code = "not_found"
    message = "Ressource introuvable."


class ConflictError(AppError):
    status_code = 409
    code = "conflict"
    message = "Conflit de ressource."


class TooManyRequestsError(AppError):
    status_code = 429
    code = "too_many_requests"
    message = "Trop de tentatives, réessayez plus tard."


class ServiceUnavailableError(AppError):
    status_code = 503
    code = "service_unavailable"
    message = "Service temporairement indisponible."


def current_request_id(request: Request) -> str:
    request_id = getattr(request.state, "request_id", None)
    if isinstance(request_id, str):
        return request_id
    return request_id_ctx.get() or ""


def error_payload(
    code: str,
    message: str,
    request_id: str,
    details: Any = None,
) -> dict[str, Any]:
    return {
        "error": {
            "code": code,
            "message": message,
            "details": details,
            "request_id": request_id,
        }
    }


async def handle_app_error(request: Request, exc: AppError) -> JSONResponse:
    return JSONResponse(
        status_code=exc.status_code,
        content=error_payload(exc.code, exc.message, current_request_id(request), exc.details),
    )


async def handle_http_exception(request: Request, exc: StarletteHTTPException) -> JSONResponse:
    code = HTTP_ERROR_CODES.get(exc.status_code, "http_error")
    message = exc.detail if isinstance(exc.detail, str) else code
    return JSONResponse(
        status_code=exc.status_code,
        content=error_payload(code, message, current_request_id(request)),
        headers=exc.headers,
    )


async def handle_validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
    return JSONResponse(
        status_code=422,
        content=jsonable_encoder(
            error_payload(
                "validation_error",
                "Les données fournies sont invalides.",
                current_request_id(request),
                exc.errors(),
            )
        ),
    )


async def handle_unexpected_error(request: Request, exc: Exception) -> JSONResponse:
    logger.exception(
        "unhandled_exception",
        extra={"extra_fields": {"path": request.url.path, "method": request.method}},
    )
    return JSONResponse(
        status_code=500,
        content=error_payload(
            "internal_error",
            "Une erreur interne est survenue.",
            current_request_id(request),
        ),
    )


def register_exception_handlers(app: FastAPI) -> None:
    app.add_exception_handler(AppError, cast(ExceptionHandler, handle_app_error))
    app.add_exception_handler(StarletteHTTPException, cast(ExceptionHandler, handle_http_exception))
    app.add_exception_handler(
        RequestValidationError, cast(ExceptionHandler, handle_validation_error)
    )
    app.add_exception_handler(Exception, cast(ExceptionHandler, handle_unexpected_error))
