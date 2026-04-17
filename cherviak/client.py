import logging
import time
from collections.abc import Callable
from datetime import datetime, timezone

import httpx
from tenacity import (
    retry,
    retry_if_exception,
    retry_if_exception_type,
    stop_after_attempt,
    wait_fixed,
)
from cherviak.config import Config
from cherviak.models import Arena


logger = logging.getLogger(__name__)


def _is_retryable_http_error(exc: BaseException) -> bool:
    if not isinstance(exc, httpx.HTTPError):
        return False
    if not isinstance(exc, httpx.HTTPStatusError):
        return True

    status_code = exc.response.status_code
    return status_code in {408, 425} or status_code >= 500


class GameClient:
    def __init__(
        self,
        config: Config,
        timeout: float = 0.5,
        log_requests: bool = False,
        min_request_interval: float = 0.35,
    ):
        self._client = httpx.Client(
            base_url=config.base_url,
            headers={"X-Auth-Token": config.token},
            timeout=timeout,
        )
        self._log_requests = log_requests
        self._min_request_interval = max(min_request_interval, 0.0)
        self._last_request_started_at: float | None = None

    def _timestamp(self) -> str:
        return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3]

    def _log_request_start(self, method: str, path: str, json_body: dict | None = None) -> None:
        if not self._log_requests:
            return
        suffix = "" if json_body is None else f" body={json_body}"
        logger.debug("%s -> %s %s%s", self._timestamp(), method, path, suffix)

    def _log_request_finish(
        self,
        method: str,
        path: str,
        started_at: float,
        *,
        response: httpx.Response | None = None,
        status_code: int | None = None,
        error: Exception | None = None,
        details: str | None = None,
    ) -> None:
        if not self._log_requests:
            return
        elapsed_ms = (time.perf_counter() - started_at) * 1000
        detail_suffix = "" if not details else f" {details}"
        if error is not None:
            logger.warning(
                "%s <- %s %s failed in %.1f ms: %s: %s",
                self._timestamp(),
                method,
                path,
                elapsed_ms,
                type(error).__name__,
                error,
            )
            return
        if response is not None and response.is_error:
            body = response.text.strip()
            logger.warning(
                "%s <- %s %s status=%s in %.1f ms%s error=%s",
                self._timestamp(),
                method,
                path,
                status_code,
                elapsed_ms,
                detail_suffix,
                body or "<empty body>",
            )
            return
        logger.debug(
            "%s <- %s %s status=%s in %.1f ms%s",
            self._timestamp(),
            method,
            path,
            status_code,
            elapsed_ms,
            detail_suffix,
        )

    def _request(
        self,
        method: str,
        path: str,
        *,
        json_body: dict | None = None,
        response_details: Callable[[httpx.Response], str | None] | None = None,
    ) -> httpx.Response:
        if self._last_request_started_at is not None and self._min_request_interval > 0:
            elapsed = time.monotonic() - self._last_request_started_at
            remaining = self._min_request_interval - elapsed
            if remaining > 0:
                time.sleep(remaining)
        self._log_request_start(method, path, json_body)
        started_at = time.perf_counter()
        self._last_request_started_at = time.monotonic()
        try:
            response = self._client.request(method, path, json=json_body)
            details = None
            if response_details is not None and not response.is_error:
                try:
                    details = response_details(response)
                except Exception:
                    details = None
            self._log_request_finish(
                method,
                path,
                started_at,
                response=response,
                status_code=response.status_code,
                details=details,
            )
            return response
        except Exception as exc:
            self._log_request_finish(method, path, started_at, error=exc)
            raise

    @retry(
        stop=stop_after_attempt(2),
        wait=wait_fixed(0.1),
        retry=retry_if_exception_type(httpx.HTTPError)
        & retry_if_exception(_is_retryable_http_error),
        reraise=True,
    )
    def get_arena(self) -> Arena:
        r = self._request(
            "GET",
            "/api/arena",
            response_details=lambda response: f"turnNo={response.json().get('turnNo')}",
        )
        r.raise_for_status()
        return Arena.model_validate(r.json())

    @retry(
        stop=stop_after_attempt(2),
        wait=wait_fixed(0.1),
        retry=retry_if_exception_type(httpx.HTTPError)
        & retry_if_exception(_is_retryable_http_error),
        reraise=True,
    )
    def post_command(self, body: dict) -> dict:
        r = self._request("POST", "/api/command", json_body=body)
        r.raise_for_status()
        return r.json()

    @retry(
        stop=stop_after_attempt(2),
        wait=wait_fixed(0.1),
        retry=retry_if_exception_type(httpx.HTTPError)
        & retry_if_exception(_is_retryable_http_error),
        reraise=True,
    )
    def get_logs(self) -> list[dict]:
        r = self._request("GET", "/api/logs")
        r.raise_for_status()
        payload = r.json()
        if not isinstance(payload, list):
            raise httpx.HTTPError(f"Unexpected logs payload: {payload!r}")
        return payload

    def close(self) -> None:
        self._client.close()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()
