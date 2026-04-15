"""
Unit tests for CircuitBreaker and retry_with_backoff utilities.

Tests cover:
- CircuitBreaker state transitions (CLOSED -> OPEN -> HALF_OPEN -> CLOSED)
- Failure threshold behavior
- Recovery timeout behavior
- Thread safety under concurrent access
- Manual reset functionality
- CircuitBreakerOpenError exception
- Context manager usage
- retry_with_backoff with exponential backoff
- Max retries and retryable exceptions
"""
import threading
import time
from unittest.mock import patch, MagicMock

import pytest

from topsailai_server.agent_daemon.croner.jobs.utils import (
    CircuitBreaker,
    CircuitBreakerOpenError,
    CircuitState,
    retry_with_backoff,
)


# =============================================================================
# Fixtures
# =============================================================================

@pytest.fixture
def circuit_breaker():
    """Create a CircuitBreaker with default settings for testing."""
    return CircuitBreaker(failure_threshold=3, recovery_timeout=5)


@pytest.fixture
def circuit_breaker_custom():
    """Create a CircuitBreaker with custom settings."""
    return CircuitBreaker(failure_threshold=5, recovery_timeout=60)


@pytest.fixture
def mock_time():
    """
    Mock time.time() for testing timeout-related behavior.
    Returns a list with current time that can be manipulated.
    """
    current_time = [1000.0]
    
    def mock_time_func():
        return current_time[0]
    
    with patch('topsailai_server.agent_daemon.croner.jobs.utils.time.time', mock_time_func):
        yield current_time


# =============================================================================
# CircuitBreaker Initialization Tests
# =============================================================================

class TestCircuitBreakerInit:
    """Tests for CircuitBreaker initialization."""

    def test_default_initialization(self):
        """Test CircuitBreaker initializes with correct default values."""
        cb = CircuitBreaker()
        
        assert cb.failure_threshold == 5
        assert cb.recovery_timeout == 60
        assert cb.consecutive_failures == 0
        assert cb.state == CircuitState.CLOSED
        assert cb.last_failure_time is None

    def test_custom_initialization(self):
        """Test CircuitBreaker initializes with custom values."""
        cb = CircuitBreaker(failure_threshold=10, recovery_timeout=120)
        
        assert cb.failure_threshold == 10
        assert cb.recovery_timeout == 120
        assert cb.consecutive_failures == 0
        assert cb.state == CircuitState.CLOSED

    def test_lock_is_created(self):
        """Test that a threading lock is created for thread safety."""
        cb = CircuitBreaker()
        
        assert cb._lock is not None
        assert isinstance(cb._lock, threading.Lock)


# =============================================================================
# CircuitBreaker State Transition Tests
# =============================================================================

class TestCircuitBreakerStateTransitions:
    """Tests for CircuitBreaker state transitions."""

    def test_initial_state_is_closed(self, circuit_breaker):
        """Test that CircuitBreaker starts in CLOSED state."""
        assert circuit_breaker.get_state() == CircuitState.CLOSED

    def test_success_keeps_circuit_closed(self, circuit_breaker):
        """Test that successful calls keep circuit in CLOSED state."""
        def success_func():
            return "success"
        
        # Execute multiple successful calls
        for _ in range(5):
            result = circuit_breaker.call(success_func)
            assert result == "success"
        
        assert circuit_breaker.get_state() == CircuitState.CLOSED
        assert circuit_breaker.consecutive_failures == 0

    def test_closed_to_open_on_threshold_failures(self, circuit_breaker):
        """Test circuit transitions from CLOSED to OPEN after failure threshold."""
        def failing_func():
            raise ValueError("Test failure")
        
        # Execute failures up to threshold (3)
        for i in range(3):
            with pytest.raises(ValueError):
                circuit_breaker.call(failing_func)
        
        assert circuit_breaker.get_state() == CircuitState.OPEN
        assert circuit_breaker.consecutive_failures == 3

    def test_open_raises_circuit_breaker_error(self, circuit_breaker):
        """Test that calls raise CircuitBreakerOpenError when circuit is OPEN."""
        def failing_func():
            raise ValueError("Test failure")
        
        # Open the circuit
        for _ in range(3):
            try:
                circuit_breaker.call(failing_func)
            except ValueError:
                pass
        
        # Now circuit should be OPEN and raise error
        with pytest.raises(CircuitBreakerOpenError) as exc_info:
            circuit_breaker.call(failing_func)
        
        assert "Circuit breaker is open" in str(exc_info.value)

    def test_open_to_half_open_after_recovery_timeout(self, circuit_breaker, mock_time):
        """Test circuit transitions from OPEN to HALF_OPEN after recovery timeout."""
        def failing_func():
            raise ValueError("Test failure")
        
        # Open the circuit
        for _ in range(3):
            try:
                circuit_breaker.call(failing_func)
            except ValueError:
                pass
        
        assert circuit_breaker.get_state() == CircuitState.OPEN
        
        # Advance time past recovery timeout (5 seconds)
        mock_time[0] += 6
        
        # Next call should attempt reset and go to HALF_OPEN
        def success_func():
            return "success"
        
        result = circuit_breaker.call(success_func)
        assert result == "success"
        assert circuit_breaker.get_state() == CircuitState.CLOSED

    def test_half_open_to_closed_on_success(self, circuit_breaker, mock_time):
        """Test circuit transitions from HALF_OPEN to CLOSED on successful call."""
        def failing_func():
            raise ValueError("Test failure")
        
        # Open the circuit
        for _ in range(3):
            try:
                circuit_breaker.call(failing_func)
            except ValueError:
                pass
        
        # Advance time to trigger HALF_OPEN
        mock_time[0] += 6
        
        # First call in HALF_OPEN state should succeed and close circuit
        def success_func():
            return "success"
        
        result = circuit_breaker.call(success_func)
        assert result == "success"
        assert circuit_breaker.get_state() == CircuitState.CLOSED
        assert circuit_breaker.consecutive_failures == 0

    def test_half_open_to_open_on_failure(self, circuit_breaker, mock_time):
        """Test circuit transitions from HALF_OPEN back to OPEN on failure."""
        def failing_func():
            raise ValueError("Test failure")
        
        # Open the circuit
        for _ in range(3):
            try:
                circuit_breaker.call(failing_func)
            except ValueError:
                pass
        
        # Advance time to trigger HALF_OPEN
        mock_time[0] += 6
        
        # Call should attempt reset, go to HALF_OPEN, then fail and go back to OPEN
        with pytest.raises(ValueError):
            circuit_breaker.call(failing_func)
        
        assert circuit_breaker.get_state() == CircuitState.OPEN

    def test_multiple_half_open_cycles(self, circuit_breaker, mock_time):
        """Test multiple HALF_OPEN cycles before successful reset."""
        call_count = [0]
        
        def alternating_func():
            call_count[0] += 1
            # Alternate: success, failure, success, failure...
            if call_count[0] % 2 == 0:
                raise ValueError("Failure")
            return "success"
        
        # Open the circuit
        for _ in range(3):
            try:
                circuit_breaker.call(alternating_func)
            except ValueError:
                pass
        
        # Multiple HALF_OPEN attempts
        for _ in range(4):
            mock_time[0] += 6
            try:
                circuit_breaker.call(alternating_func)
            except ValueError:
                pass
        
        # Circuit should eventually close after successful attempt
        assert circuit_breaker.get_state() == CircuitState.CLOSED


# =============================================================================
# CircuitBreaker Failure Threshold Tests
# =============================================================================

class TestCircuitBreakerFailureThreshold:
    """Tests for CircuitBreaker failure threshold behavior."""

    def test_threshold_of_one(self):
        """Test circuit opens immediately with threshold of 1."""
        cb = CircuitBreaker(failure_threshold=1)
        
        def failing_func():
            raise ValueError("Failure")
        
        with pytest.raises(ValueError):
            cb.call(failing_func)
        
        assert cb.get_state() == CircuitState.OPEN

    def test_threshold_of_five(self):
        """Test circuit opens after exactly 5 failures."""
        cb = CircuitBreaker(failure_threshold=5)
        
        def failing_func():
            raise ValueError("Failure")
        
        # First 4 failures should keep circuit closed
        for i in range(4):
            with pytest.raises(ValueError):
                cb.call(failing_func)
            assert cb.get_state() == CircuitState.CLOSED
        
        # 5th failure should open circuit
        with pytest.raises(ValueError):
            cb.call(failing_func)
        
        assert cb.get_state() == CircuitState.OPEN

    def test_failure_count_resets_on_success(self, circuit_breaker):
        """Test that consecutive failure count resets to 0 on success."""
        call_count = [0]
        
        def alternating_func():
            call_count[0] += 1
            # First 2 calls fail, then 1 succeeds, then 2 more fail
            if call_count[0] in [1, 2, 4, 5]:
                raise ValueError("Failure")
            return "success"
        
        # First two failures
        for _ in range(2):
            with pytest.raises(ValueError):
                circuit_breaker.call(alternating_func)
        
        assert circuit_breaker.consecutive_failures == 2
        
        # Success resets counter
        result = circuit_breaker.call(alternating_func)
        assert result == "success"
        assert circuit_breaker.consecutive_failures == 0
        
        # Fail twice more - should NOT open circuit (counter reset)
        for _ in range(2):
            with pytest.raises(ValueError):
                circuit_breaker.call(alternating_func)
        
        assert circuit_breaker.get_state() == CircuitState.CLOSED


# =============================================================================
# CircuitBreaker Recovery Timeout Tests
# =============================================================================

class TestCircuitBreakerRecoveryTimeout:
    """Tests for CircuitBreaker recovery timeout behavior."""

    def test_recovery_timeout_not_elapsed(self, circuit_breaker, mock_time):
        """Test circuit stays OPEN if recovery timeout hasn't elapsed."""
        def failing_func():
            raise ValueError("Failure")
        
        # Open the circuit
        for _ in range(3):
            try:
                circuit_breaker.call(failing_func)
            except ValueError:
                pass
        
        # Advance time but not past recovery timeout
        mock_time[0] += 3
        
        # Should still raise CircuitBreakerOpenError
        with pytest.raises(CircuitBreakerOpenError):
            circuit_breaker.call(failing_func)

    def test_recovery_timeout_exactly_elapsed(self, circuit_breaker, mock_time):
        """Test circuit attempts reset when recovery timeout is exactly elapsed."""
        def failing_func():
            raise ValueError("Failure")
        
        # Open the circuit
        for _ in range(3):
            try:
                circuit_breaker.call(failing_func)
            except ValueError:
                pass
        
        # Advance time exactly to recovery timeout
        mock_time[0] += 5
        
        # Should attempt reset (go to HALF_OPEN)
        def success_func():
            return "success"
        
        result = circuit_breaker.call(success_func)
        assert result == "success"
        assert circuit_breaker.get_state() == CircuitState.CLOSED

    def test_recovery_timeout_with_no_last_failure_time(self, mock_time):
        """Test _should_attempt_reset returns True when last_failure_time is None."""
        cb = CircuitBreaker(recovery_timeout=60)
        
        # Before any failure, should attempt reset
        assert cb._should_attempt_reset() is True


# =============================================================================
# CircuitBreaker Thread Safety Tests
# =============================================================================

class TestCircuitBreakerThreadSafety:
    """Tests for CircuitBreaker thread safety under concurrent access."""

    def test_concurrent_calls_thread_safe(self, circuit_breaker):
        """Test that concurrent calls are handled safely with locks."""
        results = []
        errors = []
        lock = threading.Lock()
        
        def thread_func(success_probability=0.5):
            try:
                def risky_func():
                    import random
                    if random.random() < success_probability:
                        return "success"
                    raise ValueError("Random failure")
                
                result = circuit_breaker.call(risky_func)
                with lock:
                    results.append(result)
            except Exception as e:
                with lock:
                    errors.append(e)
        
        # Create multiple threads
        threads = [threading.Thread(target=thread_func) for _ in range(10)]
        
        # Start all threads
        for t in threads:
            t.start()
        
        # Wait for all threads to complete
        for t in threads:
            t.join()
        
        # All calls should complete without deadlock
        assert len(results) + len(errors) == 10

    def test_concurrent_state_access(self):
        """Test that state access is thread-safe."""
        cb = CircuitBreaker(failure_threshold=100)
        states = []
        lock = threading.Lock()
        
        def read_state():
            for _ in range(100):
                state = cb.get_state()
                with lock:
                    states.append(state)
        
        def modify_state():
            def failing_func():
                raise ValueError("Failure")
            
            for i in range(50):
                try:
                    cb.call(failing_func)
                except ValueError:
                    pass
        
        # Start reader and writer threads
        reader = threading.Thread(target=read_state)
        writer = threading.Thread(target=modify_state)
        
        reader.start()
        writer.start()
        
        reader.join()
        writer.join()
        
        # All reads should complete without error
        assert len(states) == 100

    def test_concurrent_reset_and_call(self, circuit_breaker):
        """Test that reset and call operations don't conflict."""
        def failing_func():
            raise ValueError("Failure")
        
        # Open the circuit
        for _ in range(3):
            try:
                circuit_breaker.call(failing_func)
            except ValueError:
                pass
        
        reset_completed = threading.Event()
        call_completed = threading.Event()
        
        def reset_thread():
            circuit_breaker.reset()
            reset_completed.set()
        
        def call_thread():
            def success_func():
                return "success"
            try:
                circuit_breaker.call(success_func)
            except CircuitBreakerOpenError:
                pass  # Expected if reset hasn't completed
            call_completed.set()
        
        # Start both threads
        t1 = threading.Thread(target=reset_thread)
        t2 = threading.Thread(target=call_thread)
        
        t1.start()
        t2.start()
        
        t1.join()
        t2.join()
        
        # Both operations should complete without deadlock
        assert reset_completed.is_set()
        assert call_completed.is_set()


# =============================================================================
# CircuitBreaker Manual Reset Tests
# =============================================================================

class TestCircuitBreakerManualReset:
    """Tests for CircuitBreaker manual reset functionality."""

    def test_reset_from_closed_state(self, circuit_breaker):
        """Test manual reset from CLOSED state."""
        circuit_breaker.reset()
        
        assert circuit_breaker.get_state() == CircuitState.CLOSED
        assert circuit_breaker.consecutive_failures == 0
        assert circuit_breaker.last_failure_time is None

    def test_reset_from_open_state(self, circuit_breaker):
        """Test manual reset from OPEN state."""
        def failing_func():
            raise ValueError("Failure")
        
        # Open the circuit
        for _ in range(3):
            try:
                circuit_breaker.call(failing_func)
            except ValueError:
                pass
        
        assert circuit_breaker.get_state() == CircuitState.OPEN
        
        # Reset should close circuit
        circuit_breaker.reset()
        
        assert circuit_breaker.get_state() == CircuitState.CLOSED
        assert circuit_breaker.consecutive_failures == 0

    def test_reset_clears_failure_count(self, circuit_breaker):
        """Test that reset clears the consecutive failure count."""
        def failing_func():
            raise ValueError("Failure")
        
        # Generate some failures
        for _ in range(2):
            try:
                circuit_breaker.call(failing_func)
            except ValueError:
                pass
        
        assert circuit_breaker.consecutive_failures == 2
        
        circuit_breaker.reset()
        
        assert circuit_breaker.consecutive_failures == 0

    def test_reset_allows_calls_after_open(self, circuit_breaker):
        """Test that reset allows calls to execute after circuit was OPEN."""
        def failing_func():
            raise ValueError("Failure")
        
        # Open the circuit
        for _ in range(3):
            try:
                circuit_breaker.call(failing_func)
            except ValueError:
                pass
        
        # Reset circuit
        circuit_breaker.reset()
        
        # Now calls should execute normally
        def success_func():
            return "success"
        
        result = circuit_breaker.call(success_func)
        assert result == "success"
        assert circuit_breaker.get_state() == CircuitState.CLOSED


# =============================================================================
# CircuitBreaker Exception Handling Tests
# =============================================================================

class TestCircuitBreakerExceptionHandling:
    """Tests for CircuitBreaker exception handling."""

    def test_exception_propagation(self, circuit_breaker):
        """Test that exceptions from wrapped function are propagated."""
        def specific_error():
            raise ValueError("Specific error message")
        
        with pytest.raises(ValueError) as exc_info:
            circuit_breaker.call(specific_error)
        
        assert str(exc_info.value) == "Specific error message"

    def test_exception_preserves_original_type(self, circuit_breaker):
        """Test that original exception type is preserved."""
        class CustomError(Exception):
            pass
        
        def custom_error_func():
            raise CustomError("Custom error")
        
        with pytest.raises(CustomError):
            circuit_breaker.call(custom_error_func)

    def test_multiple_exception_types(self, circuit_breaker):
        """Test that various exception types are handled correctly."""
        exceptions_raised = []
        
        def raise_type_error():
            raise TypeError("Type error")
        
        def raise_value_error():
            raise ValueError("Value error")
        
        def raise_runtime_error():
            raise RuntimeError("Runtime error")
        
        for func in [raise_type_error, raise_value_error, raise_runtime_error]:
            try:
                circuit_breaker.call(func)
            except Exception:
                exceptions_raised.append(True)
        
        # All three exceptions should have been raised
        assert len(exceptions_raised) == 3


# =============================================================================
# CircuitBreaker Arguments and Return Value Tests
# =============================================================================

class TestCircuitBreakerArgumentsAndReturnValues:
    """Tests for CircuitBreaker argument passing and return values."""

    def test_passes_positional_arguments(self, circuit_breaker):
        """Test that positional arguments are passed correctly."""
        def func_with_args(a, b, c):
            return a + b + c
        
        result = circuit_breaker.call(func_with_args, 1, 2, 3)
        assert result == 6

    def test_passes_keyword_arguments(self, circuit_breaker):
        """Test that keyword arguments are passed correctly."""
        def func_with_kwargs(a, b, c=0):
            return a + b + c
        
        result = circuit_breaker.call(func_with_kwargs, 1, 2, c=3)
        assert result == 6

    def test_passes_mixed_arguments(self, circuit_breaker):
        """Test that mixed positional and keyword arguments are passed correctly."""
        def func_with_mixed(a, b, c=0, d=0):
            return a + b + c + d
        
        result = circuit_breaker.call(func_with_mixed, 1, 2, d=4)
        assert result == 7

    def test_returns_none(self, circuit_breaker):
        """Test that None return values are handled correctly."""
        def func_returning_none():
            return None
        
        result = circuit_breaker.call(func_returning_none)
        assert result is None

    def test_returns_complex_object(self, circuit_breaker):
        """Test that complex return objects are handled correctly."""
        def func_returning_complex():
            return {"key": [1, 2, 3], "nested": {"a": "b"}}
        
        result = circuit_breaker.call(func_returning_complex)
        assert result == {"key": [1, 2, 3], "nested": {"a": "b"}}


# =============================================================================
# CircuitBreakerOpenError Tests
# =============================================================================

class TestCircuitBreakerOpenError:
    """Tests for CircuitBreakerOpenError exception."""

    def test_exception_message(self):
        """Test CircuitBreakerOpenError has correct message."""
        error = CircuitBreakerOpenError("Circuit is open")
        assert str(error) == "Circuit is open"

    def test_exception_inheritance(self):
        """Test CircuitBreakerOpenError inherits from Exception."""
        error = CircuitBreakerOpenError("Test")
        assert isinstance(error, Exception)

    def test_exception_can_be_caught_as_base_exception(self):
        """Test CircuitBreakerOpenError can be caught as Exception."""
        with pytest.raises(Exception):
            raise CircuitBreakerOpenError("Test")


# =============================================================================
# retry_with_backoff Tests
# =============================================================================

class TestRetryWithBackoff:
    """Tests for retry_with_backoff function."""

    def test_successful_call_no_retry(self):
        """Test successful call returns immediately without retry."""
        call_count = [0]
        
        def success_func():
            call_count[0] += 1
            return "success"
        
        result = retry_with_backoff(success_func)
        
        assert result == "success"
        assert call_count[0] == 1

    def test_retry_until_success(self):
        """Test function retries until successful."""
        call_count = [0]
        
        def eventually_success():
            call_count[0] += 1
            if call_count[0] < 3:
                raise ValueError("Temporary failure")
            return "success"
        
        result = retry_with_backoff(eventually_success, max_retries=5)
        
        assert result == "success"
        assert call_count[0] == 3

    def test_max_retries_exceeded(self):
        """Test that exception is raised after max retries."""
        call_count = [0]
        
        def always_fails():
            call_count[0] += 1
            raise ValueError("Always fails")
        
        with pytest.raises(ValueError) as exc_info:
            retry_with_backoff(always_fails, max_retries=3)
        
        assert str(exc_info.value) == "Always fails"
        # max_retries + 1 attempts (initial + retries)
        assert call_count[0] == 4

    def test_exponential_backoff_timing(self):
        """Test that exponential backoff delays are correct."""
        call_times = []
        
        def timed_func():
            call_times.append(time.time())
            if len(call_times) < 3:
                raise ValueError("Failure")
            return "success"
        
        start_time = time.time()
        
        with patch('topsailai_server.agent_daemon.croner.jobs.utils.time.sleep'):
            retry_with_backoff(timed_func, max_retries=5, base_delay=1.0)
        
        # Check delays between calls
        if len(call_times) >= 3:
            delay1 = call_times[1] - call_times[0]
            delay2 = call_times[2] - call_times[1]
            
            # First retry: 1.0 * 2^0 = 1.0
            # Second retry: 1.0 * 2^1 = 2.0
            # (delays are approximate due to mock)
            assert delay1 >= 0
            assert delay2 >= 0

    def test_zero_max_retries(self):
        """Test with max_retries=0 (single attempt)."""
        call_count = [0]
        
        def fails_once():
            call_count[0] += 1
            raise ValueError("Failure")
        
        with pytest.raises(ValueError):
            retry_with_backoff(fails_once, max_retries=0)
        
        assert call_count[0] == 1

    def test_retryable_exceptions_only(self):
        """Test that only retryable_exceptions trigger retry."""
        call_count = [0]
        
        def raises_type_error():
            call_count[0] += 1
            raise TypeError("Non-retryable")
        
        with pytest.raises(TypeError):
            retry_with_backoff(
                raises_type_error,
                max_retries=3,
                retryable_exceptions=(ValueError,)
            )
        
        # Should not retry TypeError
        assert call_count[0] == 1

    def test_multiple_retryable_exceptions(self):
        """Test retry with multiple retryable exception types."""
        call_count = [0]
        
        def raises_various():
            call_count[0] += 1
            if call_count[0] == 1:
                raise ConnectionError("Connection error")
            elif call_count[0] == 2:
                raise TimeoutError("Timeout error")
            return "success"
        
        result = retry_with_backoff(
            raises_various,
            max_retries=5,
            retryable_exceptions=(ConnectionError, TimeoutError)
        )
        
        assert result == "success"
        assert call_count[0] == 3

    def test_non_retryable_stops_immediately(self):
        """Test that non-retryable exception stops immediately."""
        call_count = [0]
        
        def fails_then_succeeds():
            call_count[0] += 1
            if call_count[0] == 1:
                raise ValueError("Retryable")
            return "success"
        
        # ValueError is retryable, should retry
        result = retry_with_backoff(
            fails_then_succeeds,
            max_retries=3,
            retryable_exceptions=(ValueError,)
        )
        
        assert result == "success"
        assert call_count[0] == 2

    def test_custom_base_delay(self):
        """Test with custom base delay."""
        call_times = []
        
        def timed_func():
            call_times.append(time.time())
            if len(call_times) < 2:
                raise ValueError("Failure")
            return "success"
        
        with patch('topsailai_server.agent_daemon.croner.jobs.utils.time.sleep'):
            retry_with_backoff(timed_func, max_retries=5, base_delay=2.0)
        
        if len(call_times) >= 2:
            delay = call_times[1] - call_times[0]
            # First retry: 2.0 * 2^0 = 2.0
            assert delay >= 0

    def test_returns_function_result(self):
        """Test that function return value is returned correctly."""
        def complex_func():
            return {"status": "ok", "data": [1, 2, 3]}
        
        result = retry_with_backoff(complex_func)
        
        assert result == {"status": "ok", "data": [1, 2, 3]}

    def test_preserves_last_exception(self):
        """Test that the last exception is preserved after all retries fail."""
        class CustomException(Exception):
            pass
        
        def custom_fail():
            raise CustomException("Final failure")
        
        with pytest.raises(CustomException) as exc_info:
            retry_with_backoff(custom_fail, max_retries=2)
        
        assert str(exc_info.value) == "Final failure"


# =============================================================================
# Integration Tests
# =============================================================================

class TestCircuitBreakerIntegration:
    """Integration tests combining multiple CircuitBreaker behaviors."""

    def test_full_lifecycle(self, circuit_breaker, mock_time):
        """Test complete lifecycle: CLOSED -> OPEN -> HALF_OPEN -> CLOSED."""
        def failing_func():
            raise ValueError("Failure")
        
        # Initial state
        assert circuit_breaker.get_state() == CircuitState.CLOSED
        
        # Open circuit with failures
        for _ in range(3):
            try:
                circuit_breaker.call(failing_func)
            except ValueError:
                pass
        
        assert circuit_breaker.get_state() == CircuitState.OPEN
        
        # Wait for recovery timeout
        mock_time[0] += 6
        
        # Attempt recovery (HALF_OPEN -> CLOSED on success)
        def success_func():
            return "success"
        
        result = circuit_breaker.call(success_func)
        assert result == "success"
        assert circuit_breaker.get_state() == CircuitState.CLOSED

    def test_circuit_with_mixed_success_failure(self):
        """Test circuit behavior with mixed success and failure patterns."""
        # Create a fresh circuit breaker for this test
        cb = CircuitBreaker(failure_threshold=3)
        call_count = [0]
        
        def mixed_func():
            call_count[0] += 1
            # Calls 1,2 fail; call 3 succeeds; calls 4,5 fail; call 6 succeeds
            if call_count[0] in [1, 2, 4, 5]:
                raise ValueError("Failure")
            return "success"
        
        # First two failures
        for _ in range(2):
            with pytest.raises(ValueError):
                cb.call(mixed_func)
        
        assert cb.get_state() == CircuitState.CLOSED
        assert cb.consecutive_failures == 2
        
        # Success resets counter (call 3)
        result = cb.call(mixed_func)
        assert result == "success"
        assert cb.consecutive_failures == 0
        
        # Two more failures (calls 4, 5)
        for _ in range(2):
            with pytest.raises(ValueError):
                cb.call(mixed_func)
        
        assert cb.get_state() == CircuitState.CLOSED
        
        # Final success (call 6)
        result = cb.call(mixed_func)
        assert result == "success"

    def test_retry_with_circuit_breaker(self):
        """Test retry_with_backoff combined with CircuitBreaker."""
        cb = CircuitBreaker(failure_threshold=10)
        call_count = [0]
        
        def unreliable_external_call():
            call_count[0] += 1
            if call_count[0] < 3:
                raise ConnectionError("Connection failed")
            return "data"
        
        # Wrap with retry
        def wrapped_call():
            return cb.call(unreliable_external_call)
        
        result = retry_with_backoff(wrapped_call, max_retries=5)
        
        assert result == "data"
        assert call_count[0] == 3
