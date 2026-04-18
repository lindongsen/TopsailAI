import threading
import time
import pytest

from src.topsailai.utils.thread_tool import wait_thrs, is_main_thread


def test_wait_thrs_basic():
    """Test that wait_thrs waits for all threads to complete."""
    results = []
    
    def worker_func(index):
        time.sleep(0.1)
        results.append(index)
    
    threads = []
    for i in range(3):
        thread = threading.Thread(target=worker_func, args=(i,))
        threads.append(thread)
        thread.start()
    
    # Before waiting, results should be empty
    assert len(results) == 0
    
    # Wait for all threads
    wait_thrs(threads)
    
    # After waiting, all threads should have completed
    assert len(results) == 3
    assert set(results) == {0, 1, 2}


def test_wait_thrs_empty_list():
    """Test that wait_thrs handles empty thread list gracefully."""
    # Should not raise any exception
    wait_thrs([])


def test_wait_thrs_already_finished():
    """Test that wait_thrs works with already finished threads."""
    results = []
    
    def quick_worker():
        results.append("done")
    
    thread = threading.Thread(target=quick_worker)
    thread.start()
    thread.join()  # Wait for it to finish first
    
    # Thread is already finished, wait_thrs should handle this
    wait_thrs([thread])
    
    assert results == ["done"]


def test_is_main_thread_in_main():
    """Test is_main_thread returns True when called from main thread."""
    assert is_main_thread() is True


def test_is_main_thread_in_child_thread():
    """Test is_main_thread returns False when called from child thread."""
    result = []
    
    def thread_func():
        result.append(is_main_thread())
    
    thread = threading.Thread(target=thread_func)
    thread.start()
    thread.join()
    
    assert result == [False]


def test_is_main_thread_multiple_threads():
    """Test is_main_thread behavior across multiple threads."""
    main_results = []
    child_results = []
    
    def child_thread_func():
        child_results.append(is_main_thread())
    
    # Check in main thread first
    main_results.append(is_main_thread())
    
    # Create and run child threads
    threads = []
    for _ in range(3):
        thread = threading.Thread(target=child_thread_func)
        threads.append(thread)
        thread.start()
    
    wait_thrs(threads)
    
    # Verify results
    assert main_results == [True]
    assert child_results == [False, False, False]


def test_thread_combinations():
    """Test combination of wait_thrs and is_main_thread functionality."""
    main_thread_checks = []
    child_thread_checks = []
    
    def worker():
        child_thread_checks.append(is_main_thread())
        time.sleep(0.05)
    
    # Check in main thread
    main_thread_checks.append(is_main_thread())
    
    # Create multiple threads
    threads = []
    for _ in range(4):
        thread = threading.Thread(target=worker)
        threads.append(thread)
        thread.start()
    
    # Wait for all threads
    wait_thrs(threads)
    
    # Verify all checks
    assert main_thread_checks == [True]
    assert child_thread_checks == [False, False, False, False]


if __name__ == "__main__":
    pytest.main([__file__, "-v"])