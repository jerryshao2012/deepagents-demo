"""Retry utilities for handling rate limits and transient errors in model calls."""

from __future__ import annotations

import asyncio
import os
import time
from functools import wraps
from typing import Any, Callable, TypeVar, List, Tuple

import tiktoken
from dotenv import load_dotenv

from logger_utils import setup_logger
from utils import str2bool

# Load environment variables
load_dotenv()

logger = setup_logger(__name__)

# Configuration from environment variables
MAX_RETRIES = int(os.getenv("MODEL_MAX_RETRIES", "5"))
INITIAL_BACKOFF = float(os.getenv("MODEL_INITIAL_BACKOFF", "1.0"))
MAX_BACKOFF = float(os.getenv("MODEL_MAX_BACKOFF", "60.0"))
BACKOFF_MULTIPLIER = float(os.getenv("MODEL_BACKOFF_MULTIPLIER", "2.0"))
JITTER_ENABLED = str2bool(os.getenv("MODEL_RETRY_JITTER", "true"), True)

# Proactive Rate Limiting Configuration
MODEL_TPM = int(os.getenv("MODEL_TPM", "120000"))
MODEL_RPM = int(os.getenv("MODEL_RPM", "500"))

T = TypeVar("T")
TOKEN_USAGE_KEYS = (
    "input_tokens",
    "output_tokens",
    "total_tokens",
    "prompt_tokens",
    "completion_tokens",
)


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


def _coerce_usage_metadata(value: Any) -> dict[str, int]:
    """Extract the token usage fields we care about from any mapping-like object."""
    if not isinstance(value, dict):
        return {}

    usage = {key: value.get(key) for key in TOKEN_USAGE_KEYS if value.get(key) is not None}
    if not usage:
        return {}

    normalized = {key: int(raw_value) for key, raw_value in usage.items()}
    if "prompt_tokens" not in normalized and "input_tokens" in normalized:
        normalized["prompt_tokens"] = normalized["input_tokens"]
    if "input_tokens" not in normalized and "prompt_tokens" in normalized:
        normalized["input_tokens"] = normalized["prompt_tokens"]
    if "completion_tokens" not in normalized and "output_tokens" in normalized:
        normalized["completion_tokens"] = normalized["output_tokens"]
    if "output_tokens" not in normalized and "completion_tokens" in normalized:
        normalized["output_tokens"] = normalized["completion_tokens"]
    if "total_tokens" not in normalized:
        normalized["total_tokens"] = normalized.get("input_tokens", 0) + normalized.get("output_tokens", 0)
    return normalized


def _normalize_message_token_usage(message: Any) -> Any:
    """
    Copy token usage onto fields that survive downstream serialization.

    LangGraph can strip `usage_metadata` from state messages, but `eval_tracking`
    already knows how to read `response_metadata["token_usage"]` and direct token
    attributes. This keeps token accounting available for server metrics.
    """
    if message is None:
        return message

    usage = _coerce_usage_metadata(getattr(message, "usage_metadata", None))
    response_metadata = getattr(message, "response_metadata", None)
    if not usage and isinstance(response_metadata, dict):
        usage = _coerce_usage_metadata(
            response_metadata.get("token_usage")
            or response_metadata.get("usage")
            or response_metadata.get("usage_details")
        )

    if not usage:
        direct_usage = {
            key: getattr(message, key, None)
            for key in TOKEN_USAGE_KEYS
            if getattr(message, key, None) is not None
        }
        usage = _coerce_usage_metadata(direct_usage)

    if not usage:
        return message

    if not isinstance(response_metadata, dict):
        response_metadata = {}
    else:
        response_metadata = dict(response_metadata)
    response_metadata.setdefault("token_usage", usage)
    object.__setattr__(message, "response_metadata", response_metadata)

    existing_usage_metadata = _coerce_usage_metadata(getattr(message, "usage_metadata", None))
    if not existing_usage_metadata:
        object.__setattr__(message, "usage_metadata", usage)

    for key, value in usage.items():
        object.__setattr__(message, key, value)

    return message


def wrap_model_with_rate_limiting(model: Any) -> Any:
    """
    Apply both proactive rate shaping and reactive retries to a model.
    """
    # 1. Reactive Retries (Decorator)
    # Wrap invoke methods with retry logic using object.__setattr__ to bypass Pydantic validation
    retry_wrapped_invoke = retry_on_rate_limit(model.invoke)
    retry_wrapped_ainvoke = retry_on_rate_limit(model.ainvoke)

    def invoke_with_usage(*args, **kwargs):
        return _normalize_message_token_usage(retry_wrapped_invoke(*args, **kwargs))

    async def ainvoke_with_usage(*args, **kwargs):
        return _normalize_message_token_usage(await retry_wrapped_ainvoke(*args, **kwargs))

    object.__setattr__(model, 'invoke', invoke_with_usage)
    object.__setattr__(model, 'ainvoke', ainvoke_with_usage)

    # 2. Proactive Rate Shaping (if limits are configured)
    if MODEL_TPM > 0 and MODEL_RPM > 0:
        rate_limiter = AsyncRateLimiter(tpm=MODEL_TPM, rpm=MODEL_RPM)
        original_ainvoke = model.ainvoke

        async def ainvoke_with_shaping(*args, **kwargs):
            # Extract prompt from messages/input to estimate tokens
            # This is a simplification; LangChain inputs vary
            prompt_str = str(args[0]) if args else str(kwargs.get("input", ""))
            max_tokens = kwargs.get("max_tokens", 1000) or 1000

            tokens = rate_limiter.estimate_tokens(prompt_str, max_tokens)
            await rate_limiter.wait_for_capacity(tokens)
            return await original_ainvoke(*args, **kwargs)

        object.__setattr__(model, 'ainvoke', ainvoke_with_shaping)

    return model


class AsyncRateLimiter:
    """
    Proactive rate shaping to avoid 429s by controlling request flow.
    Supports both Token Per Minute (TPM) and Request Per Minute (RPM) limits.
    """

    def __init__(self, tpm: int, rpm: int, safe_margin: float = 0.8):
        # Configuration
        self.safe_tpm = int(tpm * safe_margin)
        self.min_interval = 60.0 / (rpm * safe_margin)  # Calculated from RPM
        self.window_seconds = 60.0

        # State
        self.token_window: List[Tuple[float, int]] = []
        self.last_request_time = 0.0
        self.lock = asyncio.Lock()

        # Tokenizer (optional, for accuracy)
        try:
            self.tokenizer = tiktoken.get_encoding("cl100k_base")
        except Exception:
            self.tokenizer = None

    def estimate_tokens(self, prompt: str, max_tokens: int) -> int:
        """Estimate total tokens for a request."""
        if self.tokenizer:
            prompt_tokens = len(self.tokenizer.encode(prompt))
        else:
            prompt_tokens = int(len(prompt) / 4)
        return prompt_tokens + max_tokens

    async def wait_for_capacity(self, estimated_tokens: int) -> None:
        """Blocks until capacity is available under the TPM and RPM limits."""
        async with self.lock:
            while True:
                now = time.time()

                # 1. Enforce Token Quota (TPM) rolling window
                self.token_window = [
                    (t, tok) for (t, tok) in self.token_window
                    if now - t < self.window_seconds
                ]
                used_tokens = sum(tok for _, tok in self.token_window)

                # 2. Enforce Micro-burst Protection (RPM/Interval)
                elapsed = now - self.last_request_time

                if used_tokens + estimated_tokens <= self.safe_tpm and (
                        self.last_request_time == 0.0 or elapsed >= self.min_interval):
                    # Capacity available: Record and proceed
                    self.token_window.append((now, estimated_tokens))
                    self.last_request_time = now
                    return

                # Calculate required sleep time (pacing)
                sleep_time = max(0.1, self.min_interval - elapsed)
                await asyncio.sleep(sleep_time)


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
