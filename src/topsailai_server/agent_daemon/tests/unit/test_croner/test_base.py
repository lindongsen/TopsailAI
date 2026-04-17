"""
Unit tests for croner base classes and utilities.

Tests:
    - CronJobBase abstract class
    - CircuitBreaker class
    - CircuitBreakerOpenError exception
    - retry_with_backoff utility function
    - CronJob class
    - CronScheduler class
"""

import time
import pytest
from unittest.mock import Mock, MagicMock, patch
from datetime import datetime, timedelta

from topsailai_server.agent_daemon.croner.jobs.__base import CronJobBase
from topsailai_server.agent_daemon.croner.jobs.utils import (
    CircuitBreaker,
    CircuitBreakerOpenError,
    retry_with_backoff,
)
from topsailai_server.agent_daemon.croner.scheduler import CronJob, CronScheduler


class TestCronJobBase:
    """Tests for CronJobBase abstract class."""

    def test_cron_job_base_initialization(self):
        """Test CronJobBase initialization with all parameters."""
        storage = Mock()
        worker_manager = Mock()
        
        class ConcreteJob(CronJobBase):
            def run(self):
                pass
        
        job = ConcreteJob(
            interval_seconds=60,
            storage=storage,
            worker_manager=worker_manager
        )
        assert job.interval_seconds == 60
        assert job.storage is storage
        assert job.worker_manager is worker_manager
        assert job.last_run is None

    def test_cron_job_base_initialization_defaults(self):
        """Test CronJobBase initialization with default values."""
        
        class ConcreteJob(CronJobBase):
            def run(self):
                pass
        
        job = ConcreteJob(interval_seconds=120)
        assert job.interval_seconds == 120
        assert job.storage is None
        assert job.worker_manager is None
        assert job.last_run is None

    def test_should_run_when_never_run(self):
        """Test should_run returns True when job never ran."""
        
        class ConcreteJob(CronJobBase):
            def run(self):
                pass
        
        job = ConcreteJob(interval_seconds=60)
        assert job.should_run() is True

    def test_should_run_within_interval(self):
        """Test should_run returns False when within interval."""
        
        class ConcreteJob(CronJobBase):
            def run(self):
                pass
        
        job = ConcreteJob(interval_seconds=3600)
        job.last_run = datetime.now() - timedelta(seconds=1800)  # 30 min ago
        assert job.should_run() is False

    def test_should_run_after_interval(self):
        """Test should_run returns True when interval has passed."""
        
        class ConcreteJob(CronJobBase):
            def run(self):
                pass
        
        job = ConcreteJob(interval_seconds=60)
        job.last_run = datetime.now() - timedelta(seconds=120)  # 2 min ago
        assert job.should_run() is True

    def test_mark_run_updates_timestamp(self):
        """Test mark_run updates last_run timestamp."""
        
        class ConcreteJob(CronJobBase):
            def run(self):
                pass
        
        job = ConcreteJob(interval_seconds=60)
        assert job.last_run is None
        job.mark_run()
        assert job.last_run is not None
        assert isinstance(job.last_run, datetime)

    def test_get_name_returns_class_name(self):
        """Test get_name returns the class name."""
        
        class ConcreteJob(CronJobBase):
            def run(self):
                pass
        
        job = ConcreteJob(interval_seconds=60)
        assert job.get_name() == "ConcreteJob"


class TestCircuitBreaker:
    """Tests for CircuitBreaker class."""

    def test_initialization(self):
        """Test CircuitBreaker initialization with default values."""
        cb = CircuitBreaker()
        assert cb.failure_threshold == 5
        assert cb.recovery_timeout == 60
        assert cb.consecutive_failures == 0
        assert cb.state.value == "closed"

    def test_initialization_custom_values(self):
        """Test CircuitBreaker initialization with custom values."""
        cb = CircuitBreaker(failure_threshold=3, recovery_timeout=30)
        assert cb.failure_threshold == 3
        assert cb.recovery_timeout == 30

    def test_successful_call(self):
        """Test successful function call through circuit breaker."""
        cb = CircuitBreaker()
        result = cb.call(lambda: "success")
        assert result == "success"
        assert cb.consecutive_failures == 0
        assert cb.state.value == "closed"

    def test_call_with_args_and_kwargs(self):
        """Test function call with arguments."""
        cb = CircuitBreaker()
        func = Mock(return_value=42)
        result = cb.call(func, 1, 2, key="value")
        assert result == 42
        func.assert_called_once_with(1, 2, key="value")

    def test_failure_increments_counter(self):
        """Test that failures increment consecutive_failures counter."""
        cb = CircuitBreaker(failure_threshold=5)
        func = Mock(side_effect=ValueError("test error"))
        
        with pytest.raises(ValueError):
            cb.call(func)
        
        assert cb.consecutive_failures == 1
        assert cb.state.value == "closed"

    def test_circuit_opens_after_threshold(self):
        """Test circuit opens after reaching failure threshold."""
        cb = CircuitBreaker(failure_threshold=3)
        func = Mock(side_effect=ValueError("test error"))
        
        for i in range(3):
            with pytest.raises(ValueError):
                cb.call(func)
        
        assert cb.state.value == "open"
        assert cb.consecutive_failures == 3

    def test_circuit_open_raises_exception(self):
        """Test that calls raise CircuitBreakerOpenError when circuit is open."""
        cb = CircuitBreaker(failure_threshold=1)
        func = Mock(side_effect=ValueError("test error"))
        
        with pytest.raises(ValueError):
            cb.call(func)
        
        assert cb.state.value == "open"
        
        with pytest.raises(CircuitBreakerOpenError):
            cb.call(func)

    def test_half_open_after_recovery_timeout(self):
        """Test circuit transitions to half-open after recovery timeout."""
        cb = CircuitBreaker(failure_threshold=1, recovery_timeout=0)
        
        # Trigger failure to open circuit
        with pytest.raises(ValueError):
            cb.call(lambda: (_ for _ in ()).throw(ValueError("test error")))
        
        assert cb.state.value == "open"
        
        # Wait for recovery timeout (0 seconds)
        time.sleep(0.1)
        
        # Next call should transition to half-open and succeed
        result = cb.call(lambda: "success")
        assert result == "success"
        assert cb.state.value == "closed"
        assert cb.consecutive_failures == 0

    def test_half_open_failure_reopens_circuit(self):
        """Test that failure in half-open state reopens circuit."""
        cb = CircuitBreaker(failure_threshold=1, recovery_timeout=0)
        
        # Open circuit
        with pytest.raises(ValueError):
            cb.call(lambda: (_ for _ in ()).throw(ValueError("test error")))
        
        time.sleep(0.1)
        
        # Half-open call fails
        with pytest.raises(ValueError):
            cb.call(lambda: (_ for _ in ()).throw(ValueError("test error")))
        
        assert cb.state.value == "open"

    def test_get_state(self):
        """Test get_state returns current state."""
        cb = CircuitBreaker()
        assert cb.get_state().value == "closed"

    def test_reset(self):
        """Test manual reset of circuit breaker."""
        cb = CircuitBreaker(failure_threshold=1)
        
        with pytest.raises(ValueError):
            cb.call(lambda: (_ for _ in ()).throw(ValueError("test error")))
        
        assert cb.state.value == "open"
        
        cb.reset()
        
        assert cb.state.value == "closed"
        assert cb.consecutive_failures == 0
        assert cb.last_failure_time is None


class TestCircuitBreakerOpenError:
    """Tests for CircuitBreakerOpenError exception."""

    def test_exception_message(self):
        """Test exception can be created with message."""
        error = CircuitBreakerOpenError("Circuit is open")
        assert str(error) == "Circuit is open"

    def test_exception_inheritance(self):
        """Test exception inherits from Exception."""
        error = CircuitBreakerOpenError()
        assert isinstance(error, Exception)


class TestRetryWithBackoff:
    """Tests for retry_with_backoff utility function."""

    def test_successful_call_no_retry(self):
        """Test successful call without retry."""
        func = Mock(return_value="success")
        result = retry_with_backoff(func)
        assert result == "success"
        func.assert_called_once()

    def test_retry_on_failure(self):
        """Test retry on failure up to max_retries."""
        func = Mock(side_effect=[ValueError("1"), ValueError("2"), "success"])
        result = retry_with_backoff(func, max_retries=3, base_delay=0.01)
        assert result == "success"
        assert func.call_count == 3

    def test_exhausted_retries_raises(self):
        """Test that exhausted retries raises the last exception."""
        func = Mock(side_effect=ValueError("persistent error"))
        
        with pytest.raises(ValueError) as exc_info:
            retry_with_backoff(func, max_retries=2, base_delay=0.01)
        
        assert str(exc_info.value) == "persistent error"
        assert func.call_count == 3  # Initial + 2 retries

    def test_retryable_exceptions_filter(self):
        """Test that only retryable exceptions trigger retry."""
        func = Mock(side_effect=[KeyError("non-retryable"), "success"])
        
        with pytest.raises(KeyError):
            retry_with_backoff(
                func,
                max_retries=3,
                base_delay=0.01,
                retryable_exceptions=(ValueError,)
            )
        
        assert func.call_count == 1  # No retry for non-retryable exception

    def test_backoff_timing(self):
        """Test that backoff delay increases exponentially."""
        # First two calls fail, third succeeds
        func = Mock(side_effect=[ValueError("1"), ValueError("2"), "success"])
        # Patch sleep to avoid actual delays
        with patch("topsailai_server.agent_daemon.croner.jobs.utils.time.sleep") as mock_sleep:
            result = retry_with_backoff(func, max_retries=2, base_delay=0.1)
            assert result == "success"
            # Check sleep was called with increasing delays
            # delay = base_delay * (2 ** attempt)
            # attempt 0: 0.1 * 1 = 0.1
            # attempt 1: 0.1 * 2 = 0.2
            assert mock_sleep.call_count == 2
            assert mock_sleep.call_args_list[0][0][0] == 0.1
            assert mock_sleep.call_args_list[1][0][0] == 0.2


class TestCronJob:
    """Tests for CronJob class."""

    def test_cron_job_initialization(self):
        """Test CronJob initialization."""
        func = Mock()
        job = CronJob("test_job", func, interval_seconds=60, run_at_start=True)
        assert job.name == "test_job"
        assert job.func is func
        assert job.interval_seconds == 60
        assert job.run_at_start is True
        assert job.last_run is None

    def test_should_run_when_never_run(self):
        """Test should_run returns True when never ran."""
        job = CronJob("test", Mock(), 60)
        assert job.should_run() is True

    def test_should_run_within_interval(self):
        """Test should_run returns False when within interval."""
        job = CronJob("test", Mock(), 3600)
        job.last_run = datetime.now() - timedelta(seconds=1800)
        assert job.should_run() is False

    def test_should_run_after_interval(self):
        """Test should_run returns True when interval passed."""
        job = CronJob("test", Mock(), 60)
        job.last_run = datetime.now() - timedelta(seconds=120)
        assert job.should_run() is True

    def test_execute_calls_func(self):
        """Test execute calls the function."""
        func = Mock()
        job = CronJob("test", func, 60)
        job.execute()
        func.assert_called_once()
        assert job.last_run is not None

    def test_execute_handles_exception(self):
        """Test execute handles exceptions gracefully."""
        func = Mock(side_effect=ValueError("test error"))
        job = CronJob("test", func, 60)
        # Should not raise
        job.execute()
        func.assert_called_once()

    def test_stop_sets_event(self):
        """Test stop sets the stop event."""
        job = CronJob("test", Mock(), 60)
        assert job._stop_event.is_set() is False
        job.stop()
        assert job._stop_event.is_set() is True


class TestCronScheduler:
    """Tests for CronScheduler class."""

    def test_scheduler_initialization(self):
        """Test CronScheduler initialization."""
        scheduler = CronScheduler()
        assert scheduler.jobs == {}
        assert scheduler._running is False
        assert scheduler._thread is None

    def test_add_job(self):
        """Test adding a job to scheduler."""
        scheduler = CronScheduler()
        func = Mock()
        scheduler.add_job("test_job", func, interval_seconds=60)
        assert "test_job" in scheduler.jobs
        assert scheduler.jobs["test_job"].name == "test_job"

    def test_remove_job(self):
        """Test removing a job from scheduler."""
        scheduler = CronScheduler()
        func = Mock()
        scheduler.add_job("test_job", func, 60)
        assert "test_job" in scheduler.jobs
        
        scheduler.remove_job("test_job")
        assert "test_job" not in scheduler.jobs

    def test_remove_nonexistent_job(self):
        """Test removing a job that doesn't exist."""
        scheduler = CronScheduler()
        # Should not raise
        scheduler.remove_job("nonexistent")

    def test_start_scheduler(self):
        """Test starting the scheduler."""
        scheduler = CronScheduler()
        scheduler.start()
        assert scheduler._running is True
        assert scheduler._thread is not None
        assert scheduler._thread.daemon is True
        scheduler.stop()

    def test_start_already_running(self):
        """Test starting an already running scheduler."""
        scheduler = CronScheduler()
        scheduler.start()
        thread = scheduler._thread
        scheduler.start()  # Should not create new thread
        assert scheduler._thread is thread
        scheduler.stop()

    def test_stop_scheduler(self):
        """Test stopping the scheduler."""
        scheduler = CronScheduler()
        scheduler.start()
        scheduler.stop()
        assert scheduler._running is False

    def test_stop_not_running(self):
        """Test stopping a scheduler that's not running."""
        scheduler = CronScheduler()
        # Should not raise
        scheduler.stop()
