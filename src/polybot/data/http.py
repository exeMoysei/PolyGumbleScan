"""Shared HTTP client: concurrency limit, retries with exponential backoff + jitter, Retry-After."""

from __future__ import annotations

import asyncio
import logging
import random
import re
from typing import Any

import httpx

log = logging.getLogger(__name__)

_SECRET_QS = re.compile(r"(apiKey|api_key|token|key)=[^&\s]+", re.IGNORECASE)
RETRY_STATUS = {408, 425, 429, 500, 502, 503, 504}


def mask_url(url: str) -> str:
    return _SECRET_QS.sub(r"\1=***", url)


class HttpError(RuntimeError):
    def __init__(self, status: int | None, url: str, message: str) -> None:
        super().__init__(f"{status} {mask_url(url)}: {message}")
        self.status = status


class HttpClient:
    def __init__(
        self,
        base_url: str,
        *,
        concurrency: int = 4,
        timeout: float = 15.0,
        retries: int = 4,
        backoff: float = 0.5,
        max_backoff: float = 30.0,
        headers: dict[str, str] | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._client = httpx.AsyncClient(
            base_url=base_url, timeout=timeout, headers=headers or {}, transport=transport, follow_redirects=True
        )
        self._sem = asyncio.Semaphore(concurrency)
        self.retries = retries
        self.backoff = backoff
        self.max_backoff = max_backoff
        self.last_headers: httpx.Headers = httpx.Headers()

    async def get_json(self, path: str, params: dict[str, Any] | None = None) -> Any:
        return await self.request_json("GET", path, params=params)

    async def request_json(
        self, method: str, path: str, *, params: dict[str, Any] | None = None, json: Any = None
    ) -> Any:
        attempt = 0
        while True:
            attempt += 1
            try:
                async with self._sem:
                    resp = await self._client.request(method, path, params=params, json=json)
            except (httpx.TransportError, httpx.TimeoutException) as exc:
                if attempt > self.retries:
                    raise HttpError(None, path, f"transport: {exc}") from exc
                await asyncio.sleep(self._delay(attempt, None))
                continue
            self.last_headers = resp.headers
            if resp.status_code in RETRY_STATUS and attempt <= self.retries:
                delay = self._delay(attempt, resp.headers.get("Retry-After"))
                log.warning(
                    "http retry",
                    extra={
                        "status": resp.status_code,
                        "url": mask_url(str(resp.url)),
                        "delay": delay,
                        "attempt": attempt,
                    },
                )
                await asyncio.sleep(delay)
                continue
            if resp.status_code >= 400:
                raise HttpError(resp.status_code, str(resp.url), resp.text[:300])
            return resp.json()

    def _delay(self, attempt: int, retry_after: str | None) -> float:
        if retry_after:
            try:
                return min(float(retry_after), self.max_backoff)
            except ValueError:
                pass
        base = float(min(self.backoff * (2 ** (attempt - 1)), self.max_backoff))
        return base / 2 + random.uniform(0, base / 2)

    async def aclose(self) -> None:
        await self._client.aclose()
