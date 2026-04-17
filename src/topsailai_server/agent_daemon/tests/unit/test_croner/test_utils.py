"""
Unit tests for croner/jobs/utils.py - CircuitBreaker and retry utilities
"""

import pytest
import time
from unittest.mock import Mock, patch
import threading

from topsailai_server.agent_daemon.croner.jobs.utils import (
    CircuitBreaker,
    CircuitBreakerOpenError,
    CircuitState,
    retry_with_backoff,
)


class TestCircuitBreaker:
    """Test suite for CircuitBreaker class."""
    
    def test_init_default_values(self):
        """Test initialization with default values."""
        cb = CircuitBreaker()
        
        assert cb.failure_threshold == 5
        assert cb.recovery_timeout == 60
        assert cb.consecutive_failures == 0
        assert cb.state == CircuitState.CLOSED
        assert cb.last_failure_time is None
    
    def test_init_custom_values(self):
        """Test initialization with custom values."""
        cb = CircuitBreaker(failure_threshold=3, recovery_timeout=30)
        
        assert cb.failure_threshold == 3
        assert cb.recovery_timeout == 30
    
    def test_call_success_closes_circuit(self):
        """Test successful call keeps circuit closed."""
        cb = CircuitBreaker(failure_threshold=5)
        func = Mock(return_value="success")
        
        result = cb.call(func)
        
        assert result == "success"
        assert cb.state == CircuitState.CLOSED
        assert cb.consecutive_failures == 0
        func.assert_called_once()
    
    def test_call_failure_increments_counter(self):
        """Test failure increments consecutive failures."""
        cb = CircuitBreaker(failure_threshold=5)
        func = Mock(side_effect=ValueError("test error"))
        
        with pytest.raises(ValueError):
            cb.call(func)
        
        assert cb.consecutive_failures == 1
        assert cb.state == CircuitState.CLOSED
    
    def test_call_threshold_reached_opens_circuit(self):
        """Test circuit opens after threshold failures."""
        cb = CircuitBreaker(failure_threshold=3)
        func = Mock(side_effect=ValueError("test error"))
        
        for _ in range(3):
            with pytest.raises(ValueError):
                cb.call(func)
        
        assert cb.consecutive_failures == 3
        assert cb.state == CircuitState.OPEN
    
    def test_open_circuit_raises_error(self):
        """Test open circuit raises CircuitBreakerOpenError."""
        cb = CircuitBreaker(failure_threshold=1)
        func = Mock(side_effect=ValueError("test error"))
        
        # Trigger circuit open
        with pytest.raises(ValueError):
            cb.call(func)
        
        # Now circuit is open
        with pytest.raises(CircuitBreakerOpenError):
            cb.call(func)
    
    def test_recovery_timeout_transitions_to_half_open(self):
        """Test circuit transitions to HALF_OPEN after recovery timeout."""
        cb = CircuitBreaker(failure_threshold=1, recovery_timeout=0)
        func = Mock(return_value="success")
        
        # Trigger circuit open
        func_fail = Mock(side_effect=ValueError("test error"))
        with pytest.raises(ValueError):
            cb.call(func_fail)
        
        assert cb.state == CircuitState.OPEN
        
        # Immediate retry should transition to HALF_OPEN and succeed
        result = cb.call(func)
        
        assert cb.state == CircuitState.CLOSED
        assert result == "success"
    
    def test_half_open_success_closes_circuit(self):
        """Test successful call in HALF_OPEN closes circuit."""
        cb = CircuitBreaker(failure_threshold=1, recovery_timeout=0)
        func_fail = Mock(side_effect=ValueError("test error"))
        
        # Trigger circuit open
        with pytest.raises(ValueError):
            cb.call(func_fail)
        
        # Change to success function
        success_func = Mock(return_value="success")
        result = cb.call(success_func)
        
        assert result == "success"
        assert cb.state == CircuitState.CLOSED
        assert cb.consecutive_failures == 0
    
    def test_half_open_failure_reopens_circuit(self):
        """Test failure in HALF_OPEN reopens circuit."""
        cb = CircuitBreaker(failure_threshold=1, recovery_timeout=0)
        func_fail = Mock(side_effect=ValueError("test error"))
        
        # Trigger circuit open
        with pytest.raises(ValueError):
            cb.call(func_fail)
        
        # Failure in HALF_OPEN should reopen
        with pytest.raises(ValueError):
            cb.call(func_fail)
        
        assert cb.state == CircuitState.OPEN
    
    def test_get_state_returns_current_state(self):
        """Test get_state returns current circuit state."""
        cb = CircuitBreaker()
        
        assert cb.get_state() == CircuitState.CLOSED
        
        cb.state = CircuitState.OPEN
        assert cb.get_state() == CircuitState.OPEN
    
    def test_reset_closes_circuit(self):
        """Test reset closes circuit and resets counters."""
        cb = CircuitBreaker(failure_threshold=2)
        func = Mock(side_effect=ValueError("test error"))
        
        # Trigger some failures
        with pytest.raises(ValueError):
            cb.call(func)
        
        assert cb.consecutive_failures == 1
        
        # Reset
        cb.reset()
        
        assert cb.state == CircuitState.CLOSED
        assert cb.consecutive_failures == 0
        assert cb.last_failure_time is None
    
    def test_thread_safety(self):
        """Test circuit breaker is thread-safe."""
        cb = CircuitBreaker(failure_threshold=100)
        call_count = [0]
        lock = threading.Lock()
        
        def incrementing_func():
            with lock:
                call_count[0] += 1
            return "result"
        
        threads = [threading.Thread(target=cb.call, args=(incrementing_func,)) 
                   for _ in range(10)]
        
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        
        assert call_count[0] == 10
        assert cb.state == CircuitState.CLOSED
    
    def test_call_with_args_and_kwargs(self):
        """Test calling function with arguments."""
        cb = CircuitBreaker()
        
        def func_with_args(a, b, c=None):
            return f"{a}-{b}-{c}"
        
        result = cb.call(func_with_args, 1, 2, c=3)
        
        assert result == "1-2-3"
    
    def test_multiple_successive_failures(self):
        """Test multiple successive failures."""
        cb = CircuitBreaker(failure_threshold=5)
        func = Mock(side_effect=ValueError("test error"))
        
        for i in range(5):
            with pytest.raises(ValueError):
                cb.call(func)
            assert cb.consecutive_failures == i + 1
        
        assert cb.state == CircuitState.OPEN
    
    def test_failure_threshold_one(self):
        """Test with failure threshold of 1."""
        cb = CircuitBreaker(failure_threshold=1)
        func = Mock(side_effect=ValueError("test error"))
        
        with pytest.raises(ValueError):
            cb.call(func)
        
        assert cb.state == CircuitState.OPEN
        
        with pytest.raises(CircuitBreakerOpenError):
            cb.call(func)
    
    def test_large_failure_threshold(self):
        """Test with large failure threshold."""
        cb = CircuitBreaker(failure_threshold=1000)
        func = Mock(side_effect=ValueError("test error"))
        
        # Fail 999 times, should still be CLOSED
        for _ in range(999):
            with pytest.raises(ValueError):
                cb.call(func)
        
        assert cb.state == CircuitState.CLOSED
        assert cb.consecutive_failures == 999
        
        # 1000th failure opens circuit
        with pytest.raises(ValueError):
            cb.call(func)
        
        assert cb.state == CircuitState.OPEN


class TestCircuitBreakerOpenError:
    """Test suite for CircuitBreakerOpenError exception."""
    
    def test_exception_message(self):
        """Test exception can be created with message."""
        error = CircuitBreakerOpenError("Circuit is open")
        
        assert str(error) == "Circuit is open"
    
    def test_exception_inheritance(self):
        """Test exception inherits from Exception."""
        error = CircuitBreakerOpenError()
        
        assert isinstance(error, Exception)


class TestRetryWithBackoff:
    """Test suite for retry_with_backoff function."""
    
    def test_success_first_try(self):
        """Test successful call on first try."""
        func = Mock(return_value="success")
        
        result = retry_with_backoff(func)
        
        assert result == "success"
        func.assert_called_once()
    
    def test_success_after_retries(self):
        """Test successful call after some retries."""
        func = Mock(side_effect=[ValueError("error1"), ValueError("error2"), "success"])
        
        result = retry_with_backoff(func, max_retries=3)
        
        assert result == "success"
        assert func.call_count == 3
    
    def test_all_retries_fail(self):
        """Test all retries fail and exception is raised."""
        func = Mock(side_effect=ValueError("persistent error"))
        
        with pytest.raises(ValueError, match="persistent error"):
            retry_with_backoff(func, max_retries=2)
        
        assert func.call_count == 3  # Initial + 2 retries
    
    def test_custom_max_retries(self):
        """Test custom max_retries value."""
        func = Mock(side_effect=ValueError("error"))
        
        with pytest.raises(ValueError):
            retry_with_backoff(func, max_retries=5)
        
        assert func.call_count == 6  # Initial + 5 retries
    
    def test_custom_base_delay(self):
        """Test custom base_delay affects wait time."""
        func = Mock(side_effect=[ValueError("e1"), "success"])
        
        start = time.time()
        retry_with_backoff(func, max_retries=1, base_delay=0.1)
        elapsed = time.time() - start
        
        # Should wait at least base_delay (0.1s)
        assert elapsed >= 0.1
    
    def test_exponential_backoff(self):
        """Test exponential backoff timing."""
        func = Mock(side_effect=[ValueError("e1"), ValueError("e2"), "success"])
        
        start = time.time()
        retry_with_backoff(func, max_retries=2, base_delay=0.1)
        elapsed = time.time() - start
        
        # Should wait base_delay + 2*base_delay = 0.3s minimum
        assert elapsed >= 0.3
    
    def test_custom_retryable_exceptions(self):
        """Test custom retryable exceptions."""
        func = Mock(side_effect=[TypeError("not retryable"), "success"])
        
        # TypeError is not in default retryable exceptions
        with pytest.raises(TypeError):
            retry_with_backoff(func, retryable_exceptions=(ValueError,))
        
        assert func.call_count == 1
    
    def test_zero_max_retries(self):
        """Test with zero max_retries (no retries)."""
        func = Mock(side_effect=ValueError("error"))
        
        with pytest.raises(ValueError):
            retry_with_backoff(func, max_retries=0)
        
        assert func.call_count == 1
    
    def test_retry_with_counter(self):
        """Test retry with internal counter."""
        call_count = [0]
        
        def func_with_counter():
            call_count[0] += 1
            if call_count[0] < 2:
                raise ValueError("retry")
            return "success"
        
        result = retry_with_backoff(func_with_counter, max_retries=2)
        
        assert result == "success"
        assert call_count[0] == 2
    
    def test_last_exception_raised(self):
        """Test that last exception is raised after all retries."""
        class CustomError(Exception):
            pass
        
        func = Mock(side_effect=[
            CustomError("error1"),
            CustomError("error2"),
            CustomError("error3"),
        ])
        
        with pytest.raises(CustomError, match="error3"):
            retry_with_backoff(func, max_retries=2)
    
    def test_no_delay_on_success(self):
        """Test no delay when successful on first try."""
        func = Mock(return_value="success")
        
        start = time.time()
        retry_with_backoff(func, base_delay=1.0)
        elapsed = time.time() - start
        
        # Should complete quickly with no retries
        assert elapsed < 0.5
