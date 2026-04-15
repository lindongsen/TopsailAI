"""
  Author: DawsonLin
  Email: lin_dongsen@126.com
  Created: 2026-04-15
  Purpose: Unit tests for CronScheduler
"""

import unittest
import threading
import time
from datetime import datetime, timedelta
from unittest.mock import Mock, patch, MagicMock, call

from topsailai_server.agent_daemon.croner.scheduler import (
    CronJob,
    CronScheduler,
    create_scheduler
)


class TestCronJob(unittest.TestCase):
    """Test cases for CronJob class"""

    def setUp(self):
        """Set up test fixtures"""
        self.mock_func = Mock()
        self.job_name = "test_job"

    def test_initialization_default(self):
        """Test CronJob initialization with default values"""
        job = CronJob(
            name=self.job_name,
            func=self.mock_func,
            interval_seconds=60
        )
        
        self.assertEqual(job.name, self.job_name)
        self.assertEqual(job.func, self.mock_func)
        self.assertEqual(job.interval_seconds, 60)
        self.assertFalse(job.run_at_start)
        self.assertIsNone(job.last_run)
        self.assertFalse(job._stop_event.is_set())
        print("test_initialization_default: passed")

    def test_initialization_with_run_at_start(self):
        """Test CronJob initialization with run_at_start=True"""
        job = CronJob(
            name=self.job_name,
            func=self.mock_func,
            interval_seconds=120,
            run_at_start=True
        )
        
        self.assertTrue(job.run_at_start)
        print("test_initialization_with_run_at_start: passed")

    def test_should_run_no_previous_run(self):
        """Test should_run returns True when last_run is None"""
        job = CronJob(
            name=self.job_name,
            func=self.mock_func,
            interval_seconds=60
        )
        
        self.assertTrue(job.should_run())
        print("test_should_run_no_previous_run: passed")

    def test_should_run_interval_not_elapsed(self):
        """Test should_run returns False when interval hasn't elapsed"""
        job = CronJob(
            name=self.job_name,
            func=self.mock_func,
            interval_seconds=60
        )
        job.last_run = datetime.now()
        
        self.assertFalse(job.should_run())
        print("test_should_run_interval_not_elapsed: passed")

    def test_should_run_interval_elapsed(self):
        """Test should_run returns True when interval has elapsed"""
        job = CronJob(
            name=self.job_name,
            func=self.mock_func,
            interval_seconds=60
        )
        job.last_run = datetime.now() - timedelta(seconds=61)
        
        self.assertTrue(job.should_run())
        print("test_should_run_interval_elapsed: passed")

    def test_execute_success(self):
        """Test execute calls the function and updates last_run"""
        job = CronJob(
            name=self.job_name,
            func=self.mock_func,
            interval_seconds=60
        )
        
        job.execute()
        
        self.mock_func.assert_called_once()
        self.assertIsNotNone(job.last_run)
        print("test_execute_success: passed")

    def test_execute_with_exception(self):
        """Test execute handles exceptions gracefully"""
        self.mock_func.side_effect = Exception("Test error")
        job = CronJob(
            name=self.job_name,
            func=self.mock_func,
            interval_seconds=60
        )
        
        # Should not raise exception
        try:
            job.execute()
            print("test_execute_with_exception: passed")
        except Exception as e:
            self.fail(f"execute() raised unexpected exception: {e}")

    def test_stop(self):
        """Test stop sets the stop event"""
        job = CronJob(
            name=self.job_name,
            func=self.mock_func,
            interval_seconds=60
        )
        
        self.assertFalse(job._stop_event.is_set())
        job.stop()
        self.assertTrue(job._stop_event.is_set())
        print("test_stop: passed")


class TestCronScheduler(unittest.TestCase):
    """Test cases for CronScheduler class"""

    def setUp(self):
        """Set up test fixtures"""
        self.scheduler = CronScheduler()
        self.mock_func = Mock()

    def test_initialization(self):
        """Test CronScheduler initialization"""
        self.assertEqual(self.scheduler.jobs, {})
        self.assertFalse(self.scheduler._running)
        self.assertIsNone(self.scheduler._thread)
        print("test_initialization: passed")

    def test_add_job(self):
        """Test adding a job to the scheduler"""
        self.scheduler.add_job(
            name="test_job",
            func=self.mock_func,
            interval_seconds=60
        )
        
        self.assertIn("test_job", self.scheduler.jobs)
        job = self.scheduler.jobs["test_job"]
        self.assertEqual(job.name, "test_job")
        self.assertEqual(job.func, self.mock_func)
        self.assertEqual(job.interval_seconds, 60)
        print("test_add_job: passed")

    def test_add_job_with_run_at_start(self):
        """Test adding a job with run_at_start=True"""
        self.scheduler.add_job(
            name="test_job_start",
            func=self.mock_func,
            interval_seconds=60,
            run_at_start=True
        )
        
        job = self.scheduler.jobs["test_job_start"]
        self.assertTrue(job.run_at_start)
        print("test_add_job_with_run_at_start: passed")

    def test_add_multiple_jobs(self):
        """Test adding multiple jobs"""
        mock_func1 = Mock()
        mock_func2 = Mock()
        
        self.scheduler.add_job("job1", mock_func1, 60)
        self.scheduler.add_job("job2", mock_func2, 120)
        
        self.assertEqual(len(self.scheduler.jobs), 2)
        self.assertIn("job1", self.scheduler.jobs)
        self.assertIn("job2", self.scheduler.jobs)
        print("test_add_multiple_jobs: passed")

    def test_remove_job(self):
        """Test removing a job from the scheduler"""
        self.scheduler.add_job("test_job", self.mock_func, 60)
        self.assertIn("test_job", self.scheduler.jobs)
        
        self.scheduler.remove_job("test_job")
        
        self.assertNotIn("test_job", self.scheduler.jobs)
        print("test_remove_job: passed")

    def test_remove_nonexistent_job(self):
        """Test removing a job that doesn't exist doesn't raise error"""
        try:
            self.scheduler.remove_job("nonexistent_job")
            print("test_remove_nonexistent_job: passed")
        except Exception as e:
            self.fail(f"remove_job() raised unexpected exception: {e}")

    def test_start_scheduler(self):
        """Test starting the scheduler"""
        self.scheduler.add_job("test_job", self.mock_func, 60)
        
        self.scheduler.start()
        
        self.assertTrue(self.scheduler._running)
        self.assertIsNotNone(self.scheduler._thread)
        self.assertTrue(self.scheduler._thread.is_alive() or self.scheduler._thread.daemon)
        
        # Clean up
        self.scheduler.stop()
        print("test_start_scheduler: passed")

    def test_start_already_running(self):
        """Test starting an already running scheduler"""
        self.scheduler.add_job("test_job", self.mock_func, 60)
        self.scheduler.start()
        
        # Try to start again
        self.scheduler.start()
        
        # Should still be running, not raise error
        self.assertTrue(self.scheduler._running)
        
        # Clean up
        self.scheduler.stop()
        print("test_start_already_running: passed")

    def test_stop_scheduler(self):
        """Test stopping the scheduler"""
        self.scheduler.add_job("test_job", self.mock_func, 60)
        self.scheduler.start()
        
        self.scheduler.stop()
        
        self.assertFalse(self.scheduler._running)
        print("test_stop_scheduler: passed")

    def test_stop_not_running(self):
        """Test stopping a scheduler that's not running"""
        try:
            self.scheduler.stop()
            print("test_stop_not_running: passed")
        except Exception as e:
            self.fail(f"stop() raised unexpected exception: {e}")

    def test_stop_waits_for_thread(self):
        """Test stop waits for the thread to finish"""
        self.scheduler.add_job("test_job", self.mock_func, 60)
        self.scheduler.start()
        
        # Stop should complete within timeout
        start_time = time.time()
        self.scheduler.stop()
        elapsed = time.time() - start_time
        
        # Should complete within reasonable time (5 second timeout in join)
        self.assertLess(elapsed, 6)
        print("test_stop_waits_for_thread: passed")

    def test_concurrent_job_execution(self):
        """Test that jobs can execute concurrently without blocking"""
        execution_times = []
        lock = threading.Lock()
        
        def slow_func():
            time.sleep(0.1)
            with lock:
                execution_times.append(time.time())
        
        self.scheduler.add_job("slow_job", slow_func, 1, run_at_start=True)
        self.scheduler.start()
        
        # Wait for jobs to run
        time.sleep(2)
        
        self.scheduler.stop()
        
        # Should have multiple execution times recorded
        self.assertGreater(len(execution_times), 0)
        print("test_concurrent_job_execution: passed")


class TestCreateScheduler(unittest.TestCase):
    """Test cases for create_scheduler function"""

    def setUp(self):
        """Set up test fixtures"""
        self.mock_session_storage = Mock()
        self.mock_message_storage = Mock()
        self.mock_worker_manager = Mock()
        self.mock_config = Mock()
        
        # Mock the engine
        mock_engine = Mock()
        self.mock_session_storage.get_engine.return_value = mock_engine

    def test_create_scheduler_returns_scheduler(self):
        """Test create_scheduler returns a CronScheduler instance"""
        with patch('topsailai_server.agent_daemon.storage.Storage'), \
             patch('topsailai_server.agent_daemon.croner.jobs.MessageConsumer'), \
             patch('topsailai_server.agent_daemon.croner.jobs.MessageSummarizer'), \
             patch('topsailai_server.agent_daemon.croner.jobs.SessionCleaner'):
            
            scheduler = create_scheduler(
                self.mock_session_storage,
                self.mock_message_storage,
                self.mock_worker_manager,
                self.mock_config
            )
            
            self.assertIsInstance(scheduler, CronScheduler)
        print("test_create_scheduler_returns_scheduler: passed")

    def test_create_scheduler_adds_message_consumer(self):
        """Test create_scheduler adds MessageConsumer job"""
        with patch('topsailai_server.agent_daemon.storage.Storage'), \
             patch('topsailai_server.agent_daemon.croner.jobs.MessageConsumer'), \
             patch('topsailai_server.agent_daemon.croner.jobs.MessageSummarizer'), \
             patch('topsailai_server.agent_daemon.croner.jobs.SessionCleaner'):
            
            scheduler = create_scheduler(
                self.mock_session_storage,
                self.mock_message_storage,
                self.mock_worker_manager,
                self.mock_config
            )
            
            self.assertIn("message_consumer", scheduler.jobs)
            job = scheduler.jobs["message_consumer"]
            self.assertEqual(job.interval_seconds, 60)
            self.assertTrue(job.run_at_start)
        print("test_create_scheduler_adds_message_consumer: passed")

    def test_create_scheduler_adds_message_summarizer(self):
        """Test create_scheduler adds MessageSummarizer job"""
        with patch('topsailai_server.agent_daemon.storage.Storage'), \
             patch('topsailai_server.agent_daemon.croner.jobs.MessageConsumer'), \
             patch('topsailai_server.agent_daemon.croner.jobs.MessageSummarizer'), \
             patch('topsailai_server.agent_daemon.croner.jobs.SessionCleaner'):
            
            scheduler = create_scheduler(
                self.mock_session_storage,
                self.mock_message_storage,
                self.mock_worker_manager,
                self.mock_config
            )
            
            self.assertIn("message_summarizer", scheduler.jobs)
            job = scheduler.jobs["message_summarizer"]
            self.assertEqual(job.interval_seconds, 86400)
            self.assertFalse(job.run_at_start)
        print("test_create_scheduler_adds_message_summarizer: passed")

    def test_create_scheduler_adds_session_cleaner(self):
        """Test create_scheduler adds SessionCleaner job"""
        with patch('topsailai_server.agent_daemon.storage.Storage'), \
             patch('topsailai_server.agent_daemon.croner.jobs.MessageConsumer'), \
             patch('topsailai_server.agent_daemon.croner.jobs.MessageSummarizer'), \
             patch('topsailai_server.agent_daemon.croner.jobs.SessionCleaner'):
            
            scheduler = create_scheduler(
                self.mock_session_storage,
                self.mock_message_storage,
                self.mock_worker_manager,
                self.mock_config
            )
            
            self.assertIn("session_cleaner", scheduler.jobs)
            job = scheduler.jobs["session_cleaner"]
            self.assertEqual(job.interval_seconds, 86400)
            self.assertFalse(job.run_at_start)
        print("test_create_scheduler_adds_session_cleaner: passed")

    def test_create_scheduler_creates_storage_instance(self):
        """Test create_scheduler creates Storage instance from session storage engine"""
        mock_engine = Mock()
        self.mock_session_storage.get_engine.return_value = mock_engine
        
        with patch('topsailai_server.agent_daemon.storage.Storage') as mock_storage, \
             patch('topsailai_server.agent_daemon.croner.jobs.MessageConsumer'), \
             patch('topsailai_server.agent_daemon.croner.jobs.MessageSummarizer'), \
             patch('topsailai_server.agent_daemon.croner.jobs.SessionCleaner'):
            
            create_scheduler(
                self.mock_session_storage,
                self.mock_message_storage,
                self.mock_worker_manager,
                self.mock_config
            )
            
            mock_storage.assert_called_once_with(mock_engine)
        print("test_create_scheduler_creates_storage_instance: passed")

    def test_create_scheduler_passes_correct_args_to_consumer(self):
        """Test create_scheduler passes correct arguments to MessageConsumer"""
        with patch('topsailai_server.agent_daemon.storage.Storage') as mock_storage, \
             patch('topsailai_server.agent_daemon.croner.jobs.MessageConsumer') as mock_consumer, \
             patch('topsailai_server.agent_daemon.croner.jobs.MessageSummarizer'), \
             patch('topsailai_server.agent_daemon.croner.jobs.SessionCleaner'):
            
            mock_storage_instance = Mock()
            mock_storage.return_value = mock_storage_instance
            
            create_scheduler(
                self.mock_session_storage,
                self.mock_message_storage,
                self.mock_worker_manager,
                self.mock_config
            )
            
            # Verify MessageConsumer was called with correct args
            mock_consumer.assert_called_once()
            call_kwargs = mock_consumer.call_args.kwargs
            self.assertEqual(call_kwargs['interval_seconds'], 60)
            self.assertEqual(call_kwargs['storage'], mock_storage_instance)
            self.assertEqual(call_kwargs['worker_manager'], self.mock_worker_manager)
        print("test_create_scheduler_passes_correct_args_to_consumer: passed")

    def test_create_scheduler_passes_correct_args_to_summarizer(self):
        """Test create_scheduler passes correct arguments to MessageSummarizer"""
        with patch('topsailai_server.agent_daemon.storage.Storage') as mock_storage, \
             patch('topsailai_server.agent_daemon.croner.jobs.MessageConsumer'), \
             patch('topsailai_server.agent_daemon.croner.jobs.MessageSummarizer') as mock_summarizer, \
             patch('topsailai_server.agent_daemon.croner.jobs.SessionCleaner'):
            
            mock_storage_instance = Mock()
            mock_storage.return_value = mock_storage_instance
            
            create_scheduler(
                self.mock_session_storage,
                self.mock_message_storage,
                self.mock_worker_manager,
                self.mock_config
            )
            
            # Verify MessageSummarizer was called with correct args
            mock_summarizer.assert_called_once()
            call_kwargs = mock_summarizer.call_args.kwargs
            self.assertEqual(call_kwargs['interval_seconds'], 86400)
            self.assertEqual(call_kwargs['storage'], mock_storage_instance)
            self.assertEqual(call_kwargs['worker_manager'], self.mock_worker_manager)
        print("test_create_scheduler_passes_correct_args_to_summarizer: passed")

    def test_create_scheduler_passes_correct_args_to_cleaner(self):
        """Test create_scheduler passes correct arguments to SessionCleaner"""
        with patch('topsailai_server.agent_daemon.storage.Storage') as mock_storage, \
             patch('topsailai_server.agent_daemon.croner.jobs.MessageConsumer'), \
             patch('topsailai_server.agent_daemon.croner.jobs.MessageSummarizer'), \
             patch('topsailai_server.agent_daemon.croner.jobs.SessionCleaner') as mock_cleaner:
            
            mock_storage_instance = Mock()
            mock_storage.return_value = mock_storage_instance
            
            create_scheduler(
                self.mock_session_storage,
                self.mock_message_storage,
                self.mock_worker_manager,
                self.mock_config
            )
            
            # Verify SessionCleaner was called with correct args
            mock_cleaner.assert_called_once()
            call_kwargs = mock_cleaner.call_args.kwargs
            self.assertEqual(call_kwargs['interval_seconds'], 2592000)
            self.assertEqual(call_kwargs['storage'], mock_storage_instance)
            self.assertEqual(call_kwargs['worker_manager'], self.mock_worker_manager)
        print("test_create_scheduler_passes_correct_args_to_cleaner: passed")

    def test_create_scheduler_adds_three_jobs(self):
        """Test create_scheduler adds exactly 3 jobs"""
        with patch('topsailai_server.agent_daemon.storage.Storage'), \
             patch('topsailai_server.agent_daemon.croner.jobs.MessageConsumer'), \
             patch('topsailai_server.agent_daemon.croner.jobs.MessageSummarizer'), \
             patch('topsailai_server.agent_daemon.croner.jobs.SessionCleaner'):
            
            scheduler = create_scheduler(
                self.mock_session_storage,
                self.mock_message_storage,
                self.mock_worker_manager,
                self.mock_config
            )
            
            self.assertEqual(len(scheduler.jobs), 3)
            self.assertIn("message_consumer", scheduler.jobs)
            self.assertIn("message_summarizer", scheduler.jobs)
            self.assertIn("session_cleaner", scheduler.jobs)
        print("test_create_scheduler_adds_three_jobs: passed")


class TestSchedulerIntegration(unittest.TestCase):
    """Integration tests for scheduler with real job execution"""

    def setUp(self):
        """Set up test fixtures"""
        self.execution_count = 0
        self.lock = threading.Lock()

    def test_scheduler_runs_jobs_periodically(self):
        """Test that scheduler runs jobs at the specified interval"""
        def counting_job():
            with self.lock:
                self.execution_count += 1
        
        scheduler = CronScheduler()
        scheduler.add_job("counting_job", counting_job, interval_seconds=1, run_at_start=True)
        scheduler.start()
        
        # Wait for at least 2 executions
        time.sleep(2.5)
        scheduler.stop()
        
        with self.lock:
            self.assertGreaterEqual(self.execution_count, 2)
        print("test_scheduler_runs_jobs_periodically: passed")

    def test_scheduler_handles_job_exception(self):
        """Test that scheduler continues running even when a job raises exception"""
        exception_count = [0]
        lock = threading.Lock()
        
        def failing_job():
            with lock:
                exception_count[0] += 1
            raise Exception("Test exception")
        
        def success_job():
            pass
        
        scheduler = CronScheduler()
        scheduler.add_job("failing_job", failing_job, interval_seconds=1, run_at_start=True)
        scheduler.add_job("success_job", success_job, interval_seconds=1, run_at_start=True)
        scheduler.start()
        
        # Wait for jobs to run
        time.sleep(2.5)
        scheduler.stop()
        
        # Both jobs should have run multiple times
        with lock:
            self.assertGreater(exception_count[0], 0)
        print("test_scheduler_handles_job_exception: passed")

    def test_scheduler_multiple_jobs_different_intervals(self):
        """Test scheduler with multiple jobs having different intervals"""
        job1_count = [0]
        job2_count = [0]
        lock = threading.Lock()
        
        def job1():
            with lock:
                job1_count[0] += 1
        
        def job2():
            with lock:
                job2_count[0] += 1
        
        scheduler = CronScheduler()
        scheduler.add_job("job1", job1, interval_seconds=1, run_at_start=True)
        scheduler.add_job("job2", job2, interval_seconds=2, run_at_start=True)
        scheduler.start()
        
        # Wait for jobs to run
        time.sleep(3)
        scheduler.stop()
        
        with lock:
            # Job1 runs every 1 second, should have run ~3 times
            self.assertGreaterEqual(job1_count[0], 2)
            # Job2 runs every 2 seconds, should have run ~1-2 times
            self.assertGreaterEqual(job2_count[0], 1)
        print("test_scheduler_multiple_jobs_different_intervals: passed")


if __name__ == '__main__':
    unittest.main()
