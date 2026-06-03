"""
Retry helpers for external calls (LLM APIs, Hevy, Telegram).

Retries only transient failures — rate limits (429) and 5xx / connection /
timeout errors — with exponential backoff + jitter. Honors a Retry-After
header when the API provides one. Permanent errors (400/401/403/404/422)
are re-raised immediately so real bugs aren't masked.
"""

import asyncio
import logging
import random
import time
from functools import wraps
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

DEFAULT_ATTEMPTS = 4
DEFAULT_BASE = 1.0   # seconds
DEFAULT_CAP = 30.0   # seconds


def _status_of(exc: Exception) -> Optional[int]:
    """Best-effort extraction of an HTTP status code across httpx / groq / genai."""
    for attr in ("status_code", "code"):
        val = getattr(exc, attr, None)
        if isinstance(val, int):
            return val
    resp = getattr(exc, "response", None)
    if resp is not None:
        sc = getattr(resp, "status_code", None)
        if isinstance(sc, int):
            return sc
    return None


def is_transient(exc: Exception) -> bool:
    """True if the error is worth retrying (rate limit / 5xx / connection / timeout)."""
    # All httpx connection/timeout transport errors (ConnectError, ReadError,
    # ConnectTimeout, ReadTimeout, PoolTimeout, etc.) inherit from TransportError.
    if isinstance(exc, httpx.TransportError):
        return True
    status = _status_of(exc)
    if isinstance(status, int) and (status == 429 or status >= 500):
        return True
    name = type(exc).__name__.lower()
    return any(tok in name for tok in ("timeout", "connection", "ratelimit", "serviceunavailable"))


def _retry_after(exc: Exception) -> Optional[float]:
    """Read a Retry-After header (seconds) if present."""
    resp = getattr(exc, "response", None)
    headers = getattr(resp, "headers", None)
    if not headers:
        return None
    raw = headers.get("retry-after") or headers.get("Retry-After")
    try:
        return float(raw) if raw is not None else None
    except (TypeError, ValueError):
        return None


def _delay(attempt: int, exc: Exception, base: float, cap: float) -> float:
    ra = _retry_after(exc)
    if ra is not None:
        return min(cap, ra)
    backoff = min(cap, base * (2 ** (attempt - 1)))
    return backoff + random.uniform(0, backoff * 0.25)  # jitter


def with_retry(attempts: int = DEFAULT_ATTEMPTS, base: float = DEFAULT_BASE, cap: float = DEFAULT_CAP):
    """Decorator: retry a SYNC function on transient errors with backoff."""
    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            for attempt in range(1, attempts + 1):
                try:
                    return fn(*args, **kwargs)
                except Exception as e:
                    if attempt == attempts or not is_transient(e):
                        raise
                    d = _delay(attempt, e, base, cap)
                    logger.warning(
                        "Transient error in %s (attempt %d/%d): %s — retrying in %.1fs",
                        fn.__name__, attempt, attempts, e, d,
                    )
                    time.sleep(d)
        return wrapper
    return decorator


def with_retry_async(attempts: int = DEFAULT_ATTEMPTS, base: float = DEFAULT_BASE, cap: float = DEFAULT_CAP):
    """Decorator: retry an ASYNC function on transient errors with backoff."""
    def decorator(fn):
        @wraps(fn)
        async def wrapper(*args, **kwargs):
            for attempt in range(1, attempts + 1):
                try:
                    return await fn(*args, **kwargs)
                except Exception as e:
                    if attempt == attempts or not is_transient(e):
                        raise
                    d = _delay(attempt, e, base, cap)
                    logger.warning(
                        "Transient error in %s (attempt %d/%d): %s — retrying in %.1fs",
                        fn.__name__, attempt, attempts, e, d,
                    )
                    await asyncio.sleep(d)
        return wrapper
    return decorator
