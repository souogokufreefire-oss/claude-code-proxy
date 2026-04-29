"""Global rate limiter for API requests."""

import asyncio
import random
import time
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from typing import Any, ClassVar, TypeVar

import httpx
import openai
from loguru import logger

from core.rate_limit import StrictSlidingWindowLimiter

T = TypeVar("T")
RETRYABLE_STATUS_CODES = frozenset({408, 409, 425, 429, 500, 502, 503, 504})


class GlobalRateLimiter:
    """
    Global singleton rate limiter that blocks all requests
    when a rate limit error is encountered (reactive) and
    throttles requests (proactive) using a strict rolling window.

    Optionally enforces a max_concurrency cap: at most N provider streams
    may be open simultaneously, independent of the sliding window.

    Proactive limits - throttles requests to stay within API limits.
    Reactive limits - pauses all requests when a 429 is hit.
    Concurrency limit - caps simultaneously open streams.
    """

    _instance: ClassVar[GlobalRateLimiter | None] = None
    _scoped_instances: ClassVar[dict[str, GlobalRateLimiter]] = {}

    def __init__(
        self,
        rate_limit: int = 40,
        rate_window: float = 60.0,
        max_concurrency: int = 5,
        max_retries: int = 8,
        retry_base_delay: float = 2.0,
        retry_max_delay: float = 120.0,
    ):
        # Prevent re-initialization on singleton reuse
        if hasattr(self, "_initialized"):
            return

        if rate_limit <= 0:
            raise ValueError("rate_limit must be > 0")
        if rate_window <= 0:
            raise ValueError("rate_window must be > 0")
        if max_concurrency <= 0:
            raise ValueError("max_concurrency must be > 0")
        if max_retries < 0:
            raise ValueError("max_retries must be >= 0")
        if retry_base_delay <= 0:
            raise ValueError("retry_base_delay must be > 0")
        if retry_max_delay <= 0:
            raise ValueError("retry_max_delay must be > 0")

        self._rate_limit = rate_limit
        self._rate_window = float(rate_window)
        self._max_concurrency = max_concurrency
        self._max_retries = max_retries
        self._retry_base_delay = float(retry_base_delay)
        self._retry_max_delay = float(retry_max_delay)
        self._proactive_limiter = StrictSlidingWindowLimiter(
            self._rate_limit, self._rate_window
        )
        self._blocked_until: float = 0
        self._concurrency_sem = asyncio.Semaphore(max_concurrency)
        self._initialized = True

        logger.info(
            f"GlobalRateLimiter (Provider) initialized ({rate_limit} req / {rate_window}s, max_concurrency={max_concurrency})"
        )

    @classmethod
    def get_instance(
        cls,
        rate_limit: int | None = None,
        rate_window: float | None = None,
        max_concurrency: int = 5,
    ) -> GlobalRateLimiter:
        """Get or create the singleton instance.

        Args:
            rate_limit: Requests per window (only used on first creation)
            rate_window: Window in seconds (only used on first creation)
            max_concurrency: Max simultaneous open streams (only used on first creation)
        """
        if cls._instance is None:
            cls._instance = cls(
                rate_limit=rate_limit or 40,
                rate_window=rate_window or 60.0,
                max_concurrency=max_concurrency,
            )
        return cls._instance

    @classmethod
    def get_scoped_instance(
        cls,
        scope: str,
        *,
        rate_limit: int | None = None,
        rate_window: float | None = None,
        max_concurrency: int = 5,
        max_retries: int = 8,
        retry_base_delay: float = 2.0,
        retry_max_delay: float = 120.0,
    ) -> GlobalRateLimiter:
        """Get or create a provider-scoped limiter instance."""
        if not scope:
            raise ValueError("scope must be non-empty")
        desired_rate_limit = rate_limit or 40
        desired_rate_window = float(rate_window or 60.0)
        existing = cls._scoped_instances.get(scope)
        if existing and existing.matches_config(
            desired_rate_limit,
            desired_rate_window,
            max_concurrency,
            max_retries,
            retry_base_delay,
            retry_max_delay,
        ):
            return existing
        if existing:
            logger.info(
                "Rebuilding provider rate limiter for updated scope '{}'", scope
            )
        cls._scoped_instances[scope] = cls(
            rate_limit=desired_rate_limit,
            rate_window=desired_rate_window,
            max_concurrency=max_concurrency,
            max_retries=max_retries,
            retry_base_delay=retry_base_delay,
            retry_max_delay=retry_max_delay,
        )
        return cls._scoped_instances[scope]

    @classmethod
    def reset_instance(cls) -> None:
        """Reset singleton (for testing)."""
        cls._instance = None
        cls._scoped_instances = {}

    async def wait_if_blocked(self) -> bool:
        """
        Wait if currently rate limited or throttle to meet quota.

        Returns:
            True if was reactively blocked and waited, False otherwise.
        """
        # 1. Reactive check: Wait if someone hit a 429
        waited_reactively = False
        now = time.monotonic()
        if now < self._blocked_until:
            wait_time = self._blocked_until - now
            logger.warning(
                f"Global provider rate limit active (reactive), waiting {wait_time:.1f}s..."
            )
            await asyncio.sleep(wait_time)
            waited_reactively = True

        # 2. Proactive check: strict rolling window (no bursts beyond N in last W seconds)
        await self._acquire_proactive_slot()
        return waited_reactively

    async def _acquire_proactive_slot(self) -> None:
        """
        Acquire a proactive slot enforcing a strict rolling window.

        Guarantees: at most `self._rate_limit` acquisitions in any interval of length
        `self._rate_window` (seconds).
        """
        await self._proactive_limiter.acquire()

    def set_blocked(self, seconds: float = 60) -> None:
        """
        Set global block for specified seconds (reactive).

        Args:
            seconds: How long to block (default 60s)
        """
        self._blocked_until = time.monotonic() + seconds
        logger.warning(f"Global provider rate limit set for {seconds:.1f}s (reactive)")

    def is_blocked(self) -> bool:
        """Check if currently reactively blocked."""
        return time.monotonic() < self._blocked_until

    def matches_config(
        self,
        rate_limit: int,
        rate_window: float,
        max_concurrency: int,
        max_retries: int,
        retry_base_delay: float,
        retry_max_delay: float,
    ) -> bool:
        """Return whether this limiter matches the requested runtime config."""
        return (
            self._rate_limit == rate_limit
            and self._rate_window == float(rate_window)
            and self._max_concurrency == max_concurrency
            and self._max_retries == max_retries
            and self._retry_base_delay == float(retry_base_delay)
            and self._retry_max_delay == float(retry_max_delay)
        )

    def remaining_wait(self) -> float:
        """Get remaining reactive wait time in seconds."""
        return max(0.0, self._blocked_until - time.monotonic())

    @asynccontextmanager
    async def concurrency_slot(self) -> AsyncIterator[None]:
        """Async context manager that holds one concurrency slot for a stream.

        Blocks until a slot is available (controlled by max_concurrency).
        """
        await self._concurrency_sem.acquire()
        try:
            yield
        finally:
            self._concurrency_sem.release()

    async def execute_with_retry(
        self,
        fn: Callable[..., Any],
        *args: Any,
        max_retries: int | None = None,
        base_delay: float | None = None,
        max_delay: float | None = None,
        jitter: float = 1.0,
        **kwargs: Any,
    ) -> Any:
        """Execute an async callable with rate limiting and retry on 429.

        Waits for the proactive limiter before each attempt. On 429, applies
        exponential backoff with jitter before retrying.

        Args:
            fn: Async callable to execute.
            max_retries: Maximum number of retry attempts after the first failure.
            base_delay: Base delay in seconds for exponential backoff.
            max_delay: Maximum delay cap in seconds.
            jitter: Maximum random jitter in seconds added to each delay.

        Returns:
            The result of the callable.

        Raises:
            The last exception if all retries are exhausted.
        """
        effective_max_retries = (
            self._max_retries if max_retries is None else max_retries
        )
        effective_base_delay = (
            self._retry_base_delay if base_delay is None else base_delay
        )
        effective_max_delay = self._retry_max_delay if max_delay is None else max_delay
        last_exc: Exception | None = None

        for attempt in range(1 + effective_max_retries):
            await self.wait_if_blocked()

            try:
                return await fn(*args, **kwargs)
            except Exception as e:
                if not self._is_retryable_error(e):
                    raise
                last_exc = e
                if attempt >= effective_max_retries:
                    logger.warning(
                        "Provider retry exhausted after {} retries for {}",
                        effective_max_retries,
                        type(e).__name__,
                    )
                    break

                delay = self._retry_delay(
                    e,
                    attempt=attempt,
                    base_delay=effective_base_delay,
                    max_delay=effective_max_delay,
                )
                delay += random.uniform(0, jitter)
                status = _status_code(e)
                logger.warning(
                    "Retryable provider error status={} exc_type={} attempt {}/{}. Retrying in {:.1f}s...",
                    status,
                    type(e).__name__,
                    attempt + 1,
                    effective_max_retries + 1,
                    delay,
                )
                if status == 429:
                    self.set_blocked(delay)
                await asyncio.sleep(delay)

        assert last_exc is not None
        raise last_exc

    def _is_retryable_error(self, error: Exception) -> bool:
        status = _status_code(error)
        if status is not None:
            return status in RETRYABLE_STATUS_CODES
        return isinstance(
            error,
            (
                httpx.ConnectError,
                httpx.RemoteProtocolError,
                httpx.ReadError,
                httpx.WriteError,
                httpx.PoolTimeout,
                openai.APIConnectionError,
                openai.APITimeoutError,
            ),
        )

    def _retry_delay(
        self,
        error: Exception,
        *,
        attempt: int,
        base_delay: float,
        max_delay: float,
    ) -> float:
        retry_after = _retry_after_seconds(error)
        if retry_after is not None:
            return min(retry_after, max_delay)
        return min(base_delay * (2**attempt), max_delay)


def _status_code(error: Exception) -> int | None:
    response = getattr(error, "response", None)
    status_code = getattr(response, "status_code", None)
    if isinstance(status_code, int):
        return status_code
    status_code = getattr(error, "status_code", None)
    return status_code if isinstance(status_code, int) else None


def _retry_after_seconds(error: Exception) -> float | None:
    response = getattr(error, "response", None)
    headers = getattr(response, "headers", None)
    if headers is None:
        return None
    raw = headers.get("retry-after")
    if raw is None:
        return None
    value = raw.strip()
    if not value:
        return None
    try:
        return max(0.0, float(value))
    except ValueError:
        pass
    try:
        retry_at = parsedate_to_datetime(value)
    except TypeError, ValueError:
        return None
    if retry_at.tzinfo is None:
        retry_at = retry_at.replace(tzinfo=UTC)
    return max(0.0, (retry_at - datetime.now(UTC)).total_seconds())
