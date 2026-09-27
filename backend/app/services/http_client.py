from __future__ import annotations

import time

import httpx


TRANSIENT_STATUS = {408, 409, 425, 429, 500, 502, 503, 504}


def post_json(
    url: str,
    *,
    headers: dict[str, str],
    payload: dict,
    timeout: float = 30.0,
    retries: int = 3,
    backoff: float = 0.6,
) -> httpx.Response:
    """POST JSON, retrying transient network errors and 5xx/429 responses.

    Non-transient responses (for example 401 or 400) are returned as-is so the
    caller can surface the provider's error body. Transient failures are retried
    with exponential backoff and finally re-raised.
    """
    attempts = max(1, retries)
    last_error: Exception | None = None

    for attempt in range(attempts):
        try:
            response = httpx.post(url, headers=headers, json=payload, timeout=timeout)
            if response.status_code not in TRANSIENT_STATUS:
                return response
            last_error = httpx.HTTPStatusError(
                f"transient status {response.status_code}",
                request=response.request,
                response=response,
            )
        except (httpx.TimeoutException, httpx.TransportError) as exc:
            last_error = exc

        if attempt < attempts - 1:
            time.sleep(backoff * (2**attempt))

    if last_error is not None:
        raise last_error
    raise RuntimeError(f"request to {url} failed without a response")
