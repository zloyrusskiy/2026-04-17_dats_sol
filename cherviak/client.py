import logging
import time
from json import dumps
from importlib.util import find_spec
from collections.abc import Callable
from datetime import datetime, timezone

import httpx
from cherviak.config import Config
from cherviak.models import Arena


logger = logging.getLogger(__name__)
KEEPALIVE_LIMITS = httpx.Limits(max_connections=100, max_keepalive_connections=20, keepalive_expiry=30.0)
HTTP2_ENABLED = find_spec("h2") is not None


class GameClient:
    def __init__(
        self,
        config: Config,
        timeout: float = 0.5,
        log_requests: bool = False,
    ):
        self._client = httpx.Client(
            base_url=config.base_url,
            headers={"X-Auth-Token": config.token},
            http2=HTTP2_ENABLED,
            limits=KEEPALIVE_LIMITS,
            timeout=timeout,
        )
        self._log_requests = log_requests

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
        self._log_request_start(method, path, json_body)
        started_at = time.perf_counter()
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

    def _format_arena_response_details(self, response: httpx.Response) -> str:
        payload = response.json()
        details = (
            f"http={response.http_version} "
            f"turnNo={payload.get('turnNo')} "
            f"nextTurnIn={payload.get('nextTurnIn')}"
        )
        logger.debug(
            "%s == GET /api/arena raw=%s",
            self._timestamp(),
            dumps(payload, ensure_ascii=True, separators=(",", ":")),
        )
        return details

    def get_arena(self) -> Arena:
        r = self._request(
            "GET",
            "/api/arena",
            response_details=self._format_arena_response_details,
        )
        r.raise_for_status()
        return Arena.model_validate(r.json())

    def post_command(self, body: dict) -> dict:
        r = self._request("POST", "/api/command", json_body=body)
        r.raise_for_status()
        return r.json()

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
