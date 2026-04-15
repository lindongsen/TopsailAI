"""
Utility classes for cron jobs.
"""
import threading
import time
from enum import Enum

from topsailai_server.agent_daemon import logger


class CircuitState(Enum):
    """Circuit breaker states."""
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


class CircuitBreaker:
    """
    Circuit breaker pattern implementation for external script failures.
    
    Thread-safe implementation that tracks consecutive failures and
    opens the circuit after threshold is reached.
    """
    
    def __init__(self, failure_threshold=5, recovery_timeout=60):
        """
        Initialize circuit breaker.
        
        Args:
            failure_threshold: Number of consecutive failures before opening circuit
            recovery_timeout: Seconds to wait before attempting recovery (half-open)
        """
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.consecutive_failures = 0
        self.state = CircuitState.CLOSED
        self.last_failure_time = None
        self._lock = threading.Lock()
    
    def call(self, func, *args, **kwargs):
        """
        Execute function through circuit breaker.
        
        Args:
            func: Function to execute
            *args: Positional arguments for function
            **kwargs: Keyword arguments for function
            
        Returns:
            Result of function execution
            
        Raises:
            Exception: Re-raises any exception from the function
        """
        with self._lock:
            if self.state == CircuitState.OPEN:
                if self._should_attempt_reset():
                    logger.info("Circuit breaker: transitioning from OPEN to HALF_OPEN")
                    self.state = CircuitState.HALF_OPEN
                else:
                    logger.warning("Circuit breaker: circuit is OPEN, skipping execution")
                    raise CircuitBreakerOpenError("Circuit breaker is open")
        
        try:
            result = func(*args, **kwargs)
            self._on_success()
            return result
        except Exception as e:
            self._on_failure()
            raise
    
    def _should_attempt_reset(self):
        """Check if enough time has passed to attempt reset."""
        if self.last_failure_time is None:
            return True
        return (time.time() - self.last_failure_time) >= self.recovery_timeout
    
    def _on_success(self):
        """Handle successful execution."""
        with self._lock:
            if self.state == CircuitState.HALF_OPEN:
                logger.info("Circuit breaker: HALF_OPEN execution succeeded, closing circuit")
            self.consecutive_failures = 0
            self.state = CircuitState.CLOSED
    
    def _on_failure(self):
        """Handle failed execution."""
        with self._lock:
            self.consecutive_failures += 1
            self.last_failure_time = time.time()
            
            if self.consecutive_failures >= self.failure_threshold:
                if self.state != CircuitState.OPEN:
                    logger.warning("Circuit breaker: threshold reached (%d failures), opening circuit", 
                                   self.consecutive_failures)
                self.state = CircuitState.OPEN
    
    def get_state(self):
        """Get current circuit state."""
        with self._lock:
            return self.state
    
    def reset(self):
        """Manually reset circuit breaker to closed state."""
        with self._lock:
            self.consecutive_failures = 0
            self.state = CircuitState.CLOSED
            self.last_failure_time = None
            logger.info("Circuit breaker: manually reset to CLOSED")


class CircuitBreakerOpenError(Exception):
    """Exception raised when circuit breaker is open."""
    pass


def retry_with_backoff(func, max_retries=3, base_delay=1.0, retryable_exceptions=(Exception,)):
    """
    Retry decorator with exponential backoff.
    
    Args:
        func: Function to execute
        max_retries: Maximum number of retry attempts
        base_delay: Base delay in seconds (doubles each retry)
        retryable_exceptions: Tuple of exceptions that trigger retry
        
    Returns:
        Result of function execution
        
    Raises:
        Last exception if all retries fail
    """
    last_exception = None
    
    for attempt in range(max_retries + 1):
        try:
            return func()
        except retryable_exceptions as e:
            last_exception = e
            if attempt < max_retries:
                delay = base_delay * (2 ** attempt)
                logger.warning("Retry attempt %d/%d failed: %s, waiting %.1fs", 
                               attempt + 1, max_retries + 1, e, delay)
                time.sleep(delay)
            else:
                logger.error("All %d retry attempts failed", max_retries + 1)
    
    raise last_exception
