"""Retry utilities for handling rate limits and transient errors in model calls."""

from __future__ import annotations

import asyncio
import logging
import os
import time
from functools import wraps
from typing import Any, Callable, TypeVar

from utils import str2bool

logger = logging.getLogger(__name__)

# Configuration from environment variables
MAX_RETRIES = int(os.getenv("MODEL_MAX_RETRIES", "5"))
INITIAL_BACKOFF = float(os.getenv("MODEL_INITIAL_BACKOFF", "1.0"))
MAX_BACKOFF = float(os.getenv("MODEL_MAX_BACKOFF", "60.0"))
BACKOFF_MULTIPLIER = float(os.getenv("MODEL_BACKOFF_MULTIPLIER", "2.0"))
JITTER_ENABLED = str2bool(os.getenv("MODEL_RETRY_JITTER", "true"), True)

T = TypeVar("T")


def is_rate_limit_error(error: Exception) -> bool:
    """Check if an error is related to rate limiting."""
    error_str = str(error).lower()

    # Common rate limit indicators across different providers
    rate_limit_indicators = [
        "rate limit",
        "rate_limit",
        "ratelimit",
        "too many requests",
        "429",
        "throttl",
        "quota exceeded",
        "usage limit",
        "request limit",
        "calls per minute",
        "tokens per minute",
        "requests per minute",
    ]

    # Azure-specific content filter errors should NOT be retried
    if any(marker in error_str for marker in ["content filter", "content_filter", "responsibleai"]):
        return False

    return any(indicator in error_str for indicator in rate_limit_indicators)


def calculate_backoff(attempt: int, initial: float, max_wait: float, multiplier: float, jitter: bool) -> float:
    """Calculate backoff time with optional jitter."""
    # Exponential backoff: initial * (multiplier ^ attempt)
    backoff = min(initial * (multiplier ** attempt), max_wait)

    # Add jitter to prevent thundering herd problem
    if jitter:
        import random
        backoff = backoff * (0.5 + random.random() * 0.5)  # Randomize between 50-100% of backoff

    return backoff


def retry_on_rate_limit(
        func: Callable[..., T] | None = None,
        *,
        max_retries: int | None = None,
        initial_backoff: float | None = None,
        max_backoff: float | None = None,
        backoff_multiplier: float | None = None,
        jitter: bool | None = None,
) -> Callable[..., T]:
    """
    Decorator to retry function calls on rate limit errors with exponential backoff.
    
    Args:
        func: Function to wrap (used when decorator is applied without arguments)
        max_retries: Maximum number of retry attempts (default: MODEL_MAX_RETRIES env var or 5)
        initial_backoff: Initial backoff time in seconds (default: MODEL_INITIAL_BACKOFF env var or 1.0)
        max_backoff: Maximum backoff time in seconds (default: MODEL_MAX_BACKOFF env var or 60.0)
        backoff_multiplier: Multiplier for exponential backoff (default: MODEL_BACKOFF_MULTIPLIER env var or 2.0)
        jitter: Whether to add randomness to backoff (default: MODEL_RETRY_JITTER env var or true)
    
    Returns:
        Wrapped function with retry logic
        
    Example:
        @retry_on_rate_limit(max_retries=3, initial_backoff=2.0)
        def call_model():
            return model.invoke(messages)
    """
    # Use environment defaults if not specified
    retries = max_retries if max_retries is not None else MAX_RETRIES
    init_backoff = initial_backoff if initial_backoff is not None else INITIAL_BACKOFF
    max_bo = max_backoff if max_backoff is not None else MAX_BACKOFF
    mult = backoff_multiplier if backoff_multiplier is not None else BACKOFF_MULTIPLIER
    jit = jitter if jitter is not None else JITTER_ENABLED

    def decorator(fn: Callable[..., T]) -> Callable[..., T]:
        @wraps(fn)
        def sync_wrapper(*args: Any, **kwargs: Any) -> T:
            last_exception: Exception | None = None

            for attempt in range(retries + 1):  # +1 for the initial attempt
                try:
                    return fn(*args, **kwargs)
                except Exception as e:
                    last_exception = e

                    # Don't retry if it's not a rate limit error
                    if not is_rate_limit_error(e):
                        logger.error(f"Non-retryable error in {fn.__name__}: {e}")
                        raise

                    # If we've exhausted retries, raise the last exception
                    if attempt >= retries:
                        logger.error(
                            f"Rate limit error persisted after {retries} retries in {fn.__name__}. "
                            f"Last error: {e}"
                        )
                        raise

                    # Calculate backoff and wait
                    backoff_time = calculate_backoff(attempt, init_backoff, max_bo, mult, jit)
                    logger.warning(
                        f"Rate limit hit in {fn.__name__} (attempt {attempt + 1}/{retries + 1}). "
                        f"Retrying in {backoff_time:.2f}s... Error: {e}"
                    )
                    time.sleep(backoff_time)

            # This should never be reached, but just in case
            raise last_exception  # type: ignore[misc]

        @wraps(fn)
        async def async_wrapper(*args: Any, **kwargs: Any) -> T:
            last_exception: Exception | None = None

            for attempt in range(retries + 1):  # +1 for the initial attempt
                try:
                    return await fn(*args, **kwargs)
                except Exception as e:
                    last_exception = e

                    # Don't retry if it's not a rate limit error
                    if not is_rate_limit_error(e):
                        logger.error(f"Non-retryable error in {fn.__name__}: {e}")
                        raise

                    # If we've exhausted retries, raise the last exception
                    if attempt >= retries:
                        logger.error(
                            f"Rate limit error persisted after {retries} retries in {fn.__name__}. "
                            f"Last error: {e}"
                        )
                        raise

                    # Calculate backoff and wait
                    backoff_time = calculate_backoff(attempt, init_backoff, max_bo, mult, jit)
                    logger.warning(
                        f"Rate limit hit in {fn.__name__} (attempt {attempt + 1}/{retries + 1}). "
                        f"Retrying in {backoff_time:.2f}s... Error: {e}"
                    )
                    await asyncio.sleep(backoff_time)

            # This should never be reached, but just in case
            raise last_exception  # type: ignore[misc]

        # Return appropriate wrapper based on whether function is async
        import inspect
        if inspect.iscoroutinefunction(fn):
            return async_wrapper  # type: ignore[return-value]
        return sync_wrapper

    # Handle both @retry_on_rate_limit and @retry_on_rate_limit(...) usage
    if func is not None:
        return decorator(func)
    return decorator


class RetryConfig:
    """Configuration class for retry behavior."""

    def __init__(
            self,
            max_retries: int = MAX_RETRIES,
            initial_backoff: float = INITIAL_BACKOFF,
            max_backoff: float = MAX_BACKOFF,
            backoff_multiplier: float = BACKOFF_MULTIPLIER,
            jitter: bool = JITTER_ENABLED,
    ):
        self.max_retries = max_retries
        self.initial_backoff = initial_backoff
        self.max_backoff = max_backoff
        self.backoff_multiplier = backoff_multiplier
        self.jitter = jitter

    @classmethod
    def from_env(cls) -> "RetryConfig":
        """Create config from environment variables."""
        return cls(
            max_retries=int(os.getenv("MODEL_MAX_RETRIES", "5")),
            initial_backoff=float(os.getenv("MODEL_INITIAL_BACKOFF", "1.0")),
            max_backoff=float(os.getenv("MODEL_MAX_BACKOFF", "60.0")),
            backoff_multiplier=float(os.getenv("MODEL_BACKOFF_MULTIPLIER", "2.0")),
            jitter=str2bool(os.getenv("MODEL_RETRY_JITTER", "true"), True),
        )

    def get_retry_decorator(self) -> Callable:
        """Get a retry decorator with this configuration."""
        return lambda fn: retry_on_rate_limit(
            fn,
            max_retries=self.max_retries,
            initial_backoff=self.initial_backoff,
            max_backoff=self.max_backoff,
            backoff_multiplier=self.backoff_multiplier,
            jitter=self.jitter,
        )
