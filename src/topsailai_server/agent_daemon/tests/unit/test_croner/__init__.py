"""
Test Croner Module

This package contains unit tests for the agent_daemon croner module.
The croner module provides scheduled task execution for the agent daemon service.

Test Files:
    - test_base.py: Tests for CronJobBase and utility classes (CircuitBreaker, retry_with_backoff)
    - test_scheduler.py: Tests for CronScheduler and CronJob
    - test_message_consumer.py: Tests for MessageConsumer job
    - test_message_summarizer.py: Tests for MessageSummarizer job
    - test_session_cleaner.py: Tests for SessionCleaner job

Usage:
    Run all croner tests:
        pytest tests/unit/test_croner/ -v

    Run specific test file:
        pytest tests/unit/test_croner/test_base.py -v
"""
