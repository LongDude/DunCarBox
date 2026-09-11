import logging

from fastapi import FastAPI, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException
from starlette.middleware.base import RequestResponseEndpoint

from app.domain.errors import BoxConflictError, BoxNotFoundError, EngineNotImplementedError
from app.schemas.errors import ErrorBody, ErrorDetail, ErrorResponse

logger = logging.getLogger(__name__)


def error_response(
    status: int,
    code: str,
    message: str,
    details: list[ErrorDetail] | None = None,
) -> JSONResponse:
    body = ErrorResponse(error=ErrorBody(code=code, message=message, details=details or []))
    return JSONResponse(status_code=status, content=body.model_dump())


def register_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(RequestValidationError)
    async def validation_error(_request: Request, exc: RequestValidationError) -> JSONResponse:
        return error_response(
            422,
            "VALIDATION_ERROR",
            "Запрос не прошёл проверку.",
            [
                ErrorDetail(
                    field=".".join(map(str, entry["loc"])), message=entry["msg"], type=entry["type"]
                )
                for entry in exc.errors()
            ],
        )

    @app.exception_handler(BoxNotFoundError)
    async def box_not_found(_request: Request, _exc: BoxNotFoundError) -> JSONResponse:
        return error_response(404, "NOT_FOUND", "Тип коробки не найден.")

    @app.exception_handler(BoxConflictError)
    async def box_conflict(_request: Request, _exc: BoxConflictError) -> JSONResponse:
        return error_response(409, "CONFLICT", "Тип коробки с таким id уже существует.")

    @app.exception_handler(EngineNotImplementedError)
    async def stub_error(_request: Request, exc: EngineNotImplementedError) -> JSONResponse:
        return error_response(503, "ENGINE_NOT_IMPLEMENTED", str(exc))

    @app.exception_handler(HTTPException)
    async def http_error(_request: Request, exc: HTTPException) -> JSONResponse:
        code = {404: "NOT_FOUND", 422: "VALIDATION_ERROR", 405: "METHOD_NOT_ALLOWED"}.get(
            exc.status_code, "HTTP_ERROR"
        )
        response = error_response(exc.status_code, code, str(exc.detail))
        response.headers.update(exc.headers or {})
        return response

    @app.exception_handler(Exception)
    async def internal_error(_request: Request, exc: Exception) -> JSONResponse:
        logger.error("Unhandled application error", exc_info=exc)
        return error_response(500, "INTERNAL_ERROR", "Не удалось обработать запрос.")

    @app.middleware("http")
    async def catch_unhandled_errors(
        request: Request,
        call_next: RequestResponseEndpoint,
    ) -> Response:
        # Return errors inside the outer CORS middleware so clients can read the envelope.
        try:
            return await call_next(request)
        except Exception as exc:
            return await internal_error(request, exc)
