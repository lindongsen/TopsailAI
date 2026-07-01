#!/usr/bin/env python3
"""Run all test files sequentially or concurrently and capture results."""
import subprocess
import os
import sys
import time
import argparse
import threading
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed


# Resolve directories relative to this script's location.
SCRIPT_DIR = Path(__file__).resolve().parent
TEST_DIR = SCRIPT_DIR / "unit"
OUTPUT_FILE = (SCRIPT_DIR.parent / ".tmp" / "test_results.txt").resolve()
print(f"Results will save to {OUTPUT_FILE}")

# Default configuration values.
DEFAULT_TIMEOUT = 120
DEFAULT_SLOW_THRESHOLD = 10.0
DEFAULT_WORKERS = 20
DEFAULT_RETRIES = 1


def get_test_files(selected=None):
    """Return sorted list of test file names in TEST_DIR.

    If ``selected`` is provided, only keep files that are present in the
    directory and in the selection.
    """
    all_files = sorted(
        f for f in os.listdir(TEST_DIR)
        if f.startswith("test_") and f.endswith(".py")
    )
    if not selected:
        return all_files

    selected_set = set(selected)
    return [f for f in all_files if f in selected_set]


def run_test(test_file, timeout, retries=0):
    """Run a single test file with optional retries and return (status, details, elapsed_seconds)."""
    test_path = TEST_DIR / test_file
    last_status = None
    last_details = None

    for attempt in range(retries + 1):
        start = time.perf_counter()
        try:
            result = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "pytest",
                    str(test_path),
                    "-v",
                    "--tb=short",
                    "--color=no",
                ],
                capture_output=True,
                text=True,
                timeout=timeout,
                cwd=TEST_DIR,
            )
            elapsed = time.perf_counter() - start

            if result.returncode == 0:
                details = "All tests passed"
                if attempt > 0:
                    details = f"All tests passed after {attempt} retry(s)"
                return "PASS", details, elapsed

            output = result.stdout + result.stderr
            lines = output.split("\n")
            error_lines = lines[-50:] if len(lines) > 50 else lines
            last_details = "\n".join(error_lines)
            last_status = "FAIL"
        except subprocess.TimeoutExpired:
            elapsed = time.perf_counter() - start
            last_status = "TIMEOUT"
            last_details = f"Test timed out after {timeout} seconds"
        except Exception as e:
            elapsed = time.perf_counter() - start
            last_status = "ERROR"
            last_details = str(e)

    return last_status, last_details, elapsed


def parse_args(argv=None):
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        description="Run all unit test files sequentially or concurrently and capture results."
    )
    parser.add_argument(
        "files",
        nargs="*",
        help="Specific test file names to run. If omitted, all test files are executed.",
    )
    parser.add_argument(
        "-t",
        "--threshold",
        type=float,
        default=DEFAULT_SLOW_THRESHOLD,
        help="Threshold in seconds above which a slow test is reported (default: %(default)s).",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=DEFAULT_TIMEOUT,
        help=f"Per-test timeout in seconds (default: {DEFAULT_TIMEOUT}).",
    )
    parser.add_argument(
        "-w",
        "--workers",
        type=int,
        default=DEFAULT_WORKERS,
        help=f"Maximum number of concurrent test workers (default: {DEFAULT_WORKERS}).",
    )
    parser.add_argument(
        "-r",
        "--retries",
        type=int,
        default=DEFAULT_RETRIES,
        help=f"Number of retries for failed tests (default: {DEFAULT_RETRIES}).",
    )
    parser.add_argument(
        "--sequential",
        action="store_true",
        help="Run tests one by one sequentially instead of concurrently.",
    )
    return parser.parse_args(argv)


def _print_result(index, total, test_file, status, elapsed, threshold, print_lock):
    """Print a test completion result in a thread-safe manner with index/total counter."""
    slow_marker = " [SLOW]" if elapsed > threshold else ""
    with print_lock:
        print(f"  [{index}/{total}] {test_file}: {status} ({elapsed:.3f}s){slow_marker}")


def execute_sequentially(test_files, timeout, threshold, print_lock, retries=0):
    """Run test files one by one and return ordered results."""
    results = []
    total = len(test_files)
    for idx, test_file in enumerate(test_files, 1):
        status, details, elapsed = run_test(test_file, timeout, retries)
        _print_result(idx, total, test_file, status, elapsed, threshold, print_lock)
        results.append({
            "file": test_file,
            "status": status,
            "details": details,
            "elapsed": elapsed,
        })
    return results


def execute_concurrently(test_files, workers, timeout, threshold, print_lock, retries=0):
    """Run test files concurrently and return ordered results."""
    results = [None] * len(test_files)
    file_to_index = {name: idx for idx, name in enumerate(test_files)}
    total = len(test_files)
    completed_count = 0
    count_lock = threading.Lock()

    def run_and_report(test_file):
        nonlocal completed_count
        status, details, elapsed = run_test(test_file, timeout, retries)
        with count_lock:
            completed_count += 1
            current_index = completed_count
        _print_result(current_index, total, test_file, status, elapsed, threshold, print_lock)
        return file_to_index[test_file], {
            "file": test_file,
            "status": status,
            "details": details,
            "elapsed": elapsed,
        }

    with ThreadPoolExecutor(max_workers=workers) as executor:
        future_to_file = {
            executor.submit(run_and_report, test_file): test_file
            for test_file in test_files
        }

        for future in as_completed(future_to_file):
            try:
                idx, result = future.result()
                results[idx] = result
            except Exception as exc:
                test_file = future_to_file[future]
                idx = file_to_index[test_file]
                results[idx] = {
                    "file": test_file,
                    "status": "ERROR",
                    "details": str(exc),
                    "elapsed": 0.0,
                }
    return results


def write_result_block(f, index, total, result):
    """Write a single test result block to the output file."""
    f.write(f"\n{'='*80}\n")
    f.write(f"[{index}/{total}] {result['file']}\n")
    f.write(f"Status: {result['status']}\n")
    f.write(f"Elapsed: {result['elapsed']:.3f}s\n")
    f.write(f"{'='*80}\n")
    f.write(f"{result['details']}\n")


def main():
    args = parse_args()

    # Ensure the output directory exists.
    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)

    test_files = get_test_files(selected=args.files)
    total = len(test_files)
    mode = "sequential" if args.sequential else f"concurrent (workers={args.workers})"

    # Print configuration summary at startup.
    print("=" * 60)
    print("Test Runner Configuration:")
    print(f"  timeout:    {args.timeout} seconds    # max execution time per test")
    print(f"  threshold:  {args.threshold} seconds  # SLOW warning threshold")
    print(f"  workers:    {args.workers}            # max concurrent workers")
    print(f"  retries:    {args.retries}            # retries for failed tests")
    print(f"  sequential: {args.sequential}         # run tests one by one")
    print(f"  output:     {OUTPUT_FILE}             # result file path")
    print(f"  test files: {total}                   # number of tests to run")
    print(f"  mode:       {mode}                    # execution mode")
    print("=" * 60)
    print(f"\nResults will save to {OUTPUT_FILE}\n")

    # Write header.
    with open(OUTPUT_FILE, "w") as f:
        f.write("=" * 80 + "\n")
        f.write("TEST RESULTS - Concurrent Execution\n")
        f.write("=" * 80 + "\n\n")

    print_lock = threading.Lock()
    overall_start = time.perf_counter()
    if args.sequential:
        results = execute_sequentially(test_files, args.timeout, args.threshold, print_lock, args.retries)
    else:
        results = execute_concurrently(test_files, args.workers, args.timeout, args.threshold, print_lock, args.retries)

    passed = 0
    failed = 0
    errors = []
    slow_tests = []

    # Write results in original order.
    with open(OUTPUT_FILE, "a") as f:
        for i, result in enumerate(results, 1):
            test_file = result["file"]
            status = result["status"]
            elapsed = result["elapsed"]

            if status == "PASS":
                passed += 1
            else:
                failed += 1
                errors.append(result)

            if elapsed > args.threshold:
                slow_tests.append(result)

            write_result_block(f, i, total, result)

    total_elapsed = time.perf_counter() - overall_start

    # Summary.
    with open(OUTPUT_FILE, "a") as f:
        f.write("\n" + "=" * 80 + "\n")
        f.write("SUMMARY\n")
        f.write("=" * 80 + "\n")
        f.write(f"Total: {total}, Passed: {passed}, Failed: {failed}\n")
        f.write(f"Total elapsed: {total_elapsed:.3f}s\n\n")

        if slow_tests:
            f.write("SLOW TESTS:\n")
            f.write("-" * 80 + "\n")
            for r in slow_tests:
                f.write(f"  {r['file']}: {r['elapsed']:.3f}s\n")
            f.write("\n")

        if errors:
            f.write("FAILED TESTS:\n")
            f.write("-" * 80 + "\n")
            for r in errors:
                f.write(f"\nFile: {r['file']}\n")
                f.write(f"Status: {r['status']}\n")
                f.write(f"Elapsed: {r['elapsed']:.3f}s\n")
                f.write(f"Details:\n{r['details'][:3000]}\n")

    print(f"\n{'='*80}")
    print(f"COMPLETE: Total={total}, Passed={passed}, Failed={failed}")
    print(f"Total elapsed: {total_elapsed:.3f}s")
    print(f"Results saved to: {OUTPUT_FILE}")

    return results


if __name__ == "__main__":
    main()
