#!/usr/bin/env python3
"""Run all test files sequentially or concurrently and capture results."""
import subprocess
import os
import sys
import time
import argparse
import threading
import json
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed


# Resolve directories relative to this script's location.
SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent
TEST_DIR = SCRIPT_DIR / "unit"
OUTPUT_FILE = (PROJECT_ROOT / ".tmp" / "test_results.txt").resolve()
RUN_TEMP_ROOT = (PROJECT_ROOT / ".tmp" / "unit-runner").resolve()


def resolve_src_root(start_dir=None, package_name=None):
    """Return the folder that the project package can be imported from.

    The folder is discovered by walking up from this script instead of being
    hardcoded, so the runner keeps working for any checkout layout.

    Args:
        start_dir: Directory to start the search from; defaults to this script's folder.
        package_name: Package folder name to look for; defaults to the name of the
            parent of ``start_dir`` (the package that owns ``tests``).

    Returns:
        Path: The first ancestor containing ``package_name/__init__.py``, or the
        parent of ``start_dir`` as a fallback.
    """
    start = Path(start_dir) if start_dir is not None else SCRIPT_DIR
    name = package_name or start.parent.name
    for candidate in start.parents:
        if (candidate / name / "__init__.py").is_file():
            return candidate
    return start.parent


# Import roots used by isolated child pytest processes.
SRC_ROOT = resolve_src_root()


def build_child_env(base_env=None, src_root=None):
    """Return a child environment with deterministic project import roots.

    Per-file subprocesses run from ``tests/unit``. The project root is needed
    for imports from ``tests.*`` while the source root is needed for imports
    from ``topsailai``. Required roots are prepended without duplicates, and
    the caller's mapping is never modified in place.
    """
    env = dict(os.environ if base_env is None else base_env)
    raw_source = SRC_ROOT if src_root is None else src_root
    required = [os.path.normpath(str(PROJECT_ROOT))]
    if str(raw_source):
        required.append(os.path.normpath(str(raw_source)))

    inherited = env.get("PYTHONPATH", "")
    required_keys = {os.path.normcase(path) for path in required}
    kept = [
        entry
        for entry in inherited.split(os.pathsep)
        if entry
        and os.path.normcase(os.path.normpath(entry)) not in required_keys
    ]
    env["PYTHONPATH"] = os.pathsep.join(required + kept)
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    return env


# Default configuration values.
DEFAULT_TIMEOUT = 120
DEFAULT_SLOW_THRESHOLD = 10.0
DEFAULT_WORKERS = 20
DEFAULT_RETRIES = 1


def get_test_files(selected=None):
    """Return sorted list of test file paths in TEST_DIR, recursively.

    Paths are returned relative to TEST_DIR so nested files keep their
    subdirectory prefix (e.g. ``utils/test_state_visualizer.py``).

    If ``selected`` is provided, only keep files that are present in the
    directory and in the selection.
    """
    all_files = sorted(
        str(p.relative_to(TEST_DIR))
        for p in TEST_DIR.rglob("*.py")
        if p.name.startswith("test_")
    )
    if not selected:
        return all_files

    selected_set = set(selected)
    return [f for f in all_files if f in selected_set]


def _suite_case_counts(suite):
    """Validate one pytest leaf suite and reconcile its declared outcome counters."""
    cases = suite.findall("testcase")
    if any(child.tag not in {"testcase", "properties", "system-out", "system-err"}
           for child in suite):
        raise ValueError("Unsupported JUnit suite structure")
    counts = dict(records=len(cases), passed=0, failures=0, errors=0, skipped=0)
    for case in cases:
        outcomes = {tag: case.findall(tag) for tag in ("failure", "error", "skipped")}
        failures, errors, skipped = (outcomes[tag] for tag in outcomes)
        if len(failures) > 1 or len(skipped) > 1 or (failures and (errors or skipped)):
            raise ValueError("Conflicting testcase outcomes")
        if len(errors) > 1:
            messages = [error.get("message", "") for error in errors]
            if (len(errors) != 2 or not messages[0].startswith("failed on setup with ")
                    or not messages[1].startswith("failed on teardown with ")):
                raise ValueError("Unsupported multiple phase errors")
        if skipped and errors and (len(errors) != 1 or not errors[0].get("message", "").startswith("failed on teardown with ")):
            raise ValueError("Conflicting skip and error outcomes")
        counts["failures"] += len(failures)
        counts["errors"] += len(errors)
        counts["skipped"] += len(skipped)
        counts["passed"] += not any(outcomes.values())
    for attribute, key in (("tests", "records"), ("failures", "failures"),
                           ("errors", "errors"), ("skipped", "skipped")):
        value = suite.get(attribute, "")
        if not value.isascii() or not value.isdecimal() or int(value) != counts[key]:
            raise ValueError("Missing or inconsistent JUnit suite counter")
    return counts


def read_case_counts(path):
    """Validate pytest leaf suites without double-counting container counters."""
    empty = {"records": 0, "passed": 0, "failures": 0, "errors": 0, "skipped": 0}
    if not path.is_file():
        return dict(empty, evidence="missing")
    try:
        root = ET.parse(path).getroot()
        if root.tag == "testsuite":
            suites = [root]
        elif root.tag == "testsuites" and all(child.tag == "testsuite" for child in root):
            suites = list(root)
        else:
            raise ValueError("Unsupported JUnit root structure")
        totals = dict(empty)
        for suite in suites:
            counts = _suite_case_counts(suite)
            for key in totals:
                totals[key] += counts[key]
        return dict(totals, evidence="valid" if totals["records"] else "incomplete")
    except (ET.ParseError, OSError, ValueError):
        return dict(empty, evidence="malformed")


def _output_text(value):
    """Normalize captured timeout bytes or text without dropping partial output."""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return value or ""


def run_test(test_file, timeout, retries=0, *, temp_root=None):
    """Run one file and retain complete evidence for each existing-policy attempt."""
    test_path = TEST_DIR / test_file
    root = Path(RUN_TEMP_ROOT if temp_root is None else temp_root).resolve()
    root.mkdir(parents=True, exist_ok=True)
    root.chmod(0o755)
    file_root = Path(tempfile.mkdtemp(prefix="file-", dir=root))
    file_root.chmod(0o755)

    for attempt in range(retries + 1):
        evidence = file_root / f"attempt-{attempt}"
        evidence.mkdir()
        evidence.chmod(0o755)
        basetemp = evidence / "basetemp"
        junit = evidence / "junit.xml"
        command = [sys.executable, "-B", "-m", "pytest", str(test_path),
                   "-v", "-rA", "--tb=short", "--color=no", "-p", "no:cacheprovider",
                   f"--basetemp={basetemp}", f"--junitxml={junit}"]
        start = time.perf_counter()
        stdout, stderr, returncode, exception = "", "", None, None
        try:
            result = subprocess.run(
                command, capture_output=True, text=True, timeout=timeout,
                cwd=TEST_DIR, env=build_child_env(), stdin=subprocess.DEVNULL,
            )
            stdout, stderr, returncode = result.stdout, result.stderr, result.returncode
            status = "PASS" if returncode == 0 else "FAIL"
            details = "All tests passed" if status == "PASS" else "Child pytest failed"
            if status == "PASS" and attempt:
                details += f" after {attempt} retry(s)"
        except subprocess.TimeoutExpired as error:
            stdout, stderr = _output_text(error.stdout), _output_text(error.stderr)
            status, exception = "TIMEOUT", type(error).__name__
            details = f"Test timed out after {timeout} seconds"
        except Exception as error:
            status, exception = "ERROR", type(error).__name__
            details = str(error)
        elapsed = time.perf_counter() - start
        cases = read_case_counts(junit)
        if status == "PASS" and (cases["evidence"] != "valid" or cases["failures"] or cases["errors"]):
            status = "ERROR"
            details = f"Unverified case evidence: {cases['evidence']}"
        (evidence / "stdout.txt").write_text(_output_text(stdout), encoding="utf-8")
        (evidence / "stderr.txt").write_text(_output_text(stderr), encoding="utf-8")
        metadata = dict(command=command, file=test_file, attempt=attempt,
                        returncode=returncode, exception_category=exception,
                        status=status, elapsed=elapsed, cases=cases,
                        stdout=str(evidence / "stdout.txt"), stderr=str(evidence / "stderr.txt"),
                        junit=str(junit), basetemp=str(basetemp))
        (evidence / "metadata.json").write_text(json.dumps(metadata, indent=2), encoding="utf-8")
        details += f"; evidence: {evidence}"
        if status == "PASS":
            return status, details, elapsed
    return status, details, elapsed


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
    parser.add_argument(
        "--sequential-yes-do-it",
        action="store_true",
        help="Acknowledge that running all tests sequentially without specifying files takes a very long time.",
    )
    parser.add_argument("--output-file", type=Path, default=OUTPUT_FILE,
                        help="Result report path (default: %(default)s).")
    parser.add_argument("--temp-root", type=Path, default=RUN_TEMP_ROOT,
                        help="Root for unique invocation evidence (default: %(default)s).")
    args = parser.parse_args(argv)
    if args.sequential and not args.files and not args.sequential_yes_do_it:
        parser.error(
            "Running all tests sequentially without specifying files takes an excessively long time. "
            "Pass --sequential-yes-do-it if you really want to do this."
        )
    return args


def _print_result(index, total, test_file, status, elapsed, threshold, print_lock):
    """Print a test completion result in a thread-safe manner with index/total counter."""
    slow_marker = " [SLOW]" if elapsed > threshold else ""
    with print_lock:
        print(f"  [{index}/{total}] {test_file}: {status} ({elapsed:.3f}s){slow_marker}")


def execute_sequentially(test_files, timeout, threshold, print_lock, retries=0, *, temp_root=None):
    """Run test files one by one and return ordered results."""
    results = []
    total = len(test_files)
    for idx, test_file in enumerate(test_files, 1):
        status, details, elapsed = run_test(test_file, timeout, retries, temp_root=temp_root)
        _print_result(idx, total, test_file, status, elapsed, threshold, print_lock)
        results.append({
            "file": test_file,
            "status": status,
            "details": details,
            "elapsed": elapsed,
        })
    return results


def execute_concurrently(test_files, workers, timeout, threshold, print_lock, retries=0, *, temp_root=None):
    """Run test files concurrently and return ordered results."""
    results = [None] * len(test_files)
    file_to_index = {name: idx for idx, name in enumerate(test_files)}
    total = len(test_files)
    completed_count = 0
    count_lock = threading.Lock()

    def run_and_report(test_file):
        nonlocal completed_count
        status, details, elapsed = run_test(test_file, timeout, retries, temp_root=temp_root)
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

    # Resolve explicit paths once at the CLI boundary.
    output_file = args.output_file.resolve()
    temp_root = args.temp_root.resolve()
    output_file.parent.mkdir(parents=True, exist_ok=True)
    temp_root.mkdir(parents=True, exist_ok=True)
    temp_root.chmod(0o755)
    invocation_root = Path(tempfile.mkdtemp(prefix="invocation-", dir=temp_root))
    invocation_root.chmod(0o755)

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
    print(f"  output:     {output_file}             # result file path")
    print(f"  evidence:   {invocation_root}")
    print(f"  test files: {total}                   # number of tests to run")
    print(f"  mode:       {mode}                    # execution mode")
    print("=" * 60)
    print(f"\nResults will save to {output_file}\n")

    # Write header.
    with open(output_file, "w") as f:
        f.write("=" * 80 + "\n")
        f.write("TEST RESULTS - Concurrent Execution\n")
        f.write("=" * 80 + "\n\n")

    print_lock = threading.Lock()
    overall_start = time.perf_counter()
    if args.sequential:
        results = execute_sequentially(test_files, args.timeout, args.threshold, print_lock, args.retries, temp_root=invocation_root)
    else:
        results = execute_concurrently(test_files, args.workers, args.timeout, args.threshold, print_lock, args.retries, temp_root=invocation_root)

    passed = 0
    failed = 0
    errors = []
    slow_tests = []

    # Write results in original order.
    with open(output_file, "a") as f:
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

    # Reconcile final-attempt case records independently from file totals.
    records = [json.loads(path.read_text(encoding="utf-8"))
               for path in invocation_root.glob("file-*/attempt-*/metadata.json")]
    final_attempts = {}
    for record in records:
        previous = final_attempts.get(record["file"])
        if previous is None or record["attempt"] > previous["attempt"]:
            final_attempts[record["file"]] = record
    case_totals = {key: sum(record["cases"][key] for record in final_attempts.values()
                           if record["cases"]["evidence"] == "valid")
                   for key in ("records", "passed", "failures", "errors", "skipped")}
    case_summary = dict(case_totals, evidence_files=len(final_attempts),
                        incomplete_files=total - sum(record["cases"]["evidence"] == "valid"
                                                     for record in final_attempts.values()),
                        limitation="Skipped includes xfail; reconcile xfail/XPASS/deselection with full -rA logs")
    (invocation_root / "cases.json").write_text(json.dumps(case_summary, indent=2), encoding="utf-8")
    print(f"CASES: {json.dumps(case_summary, sort_keys=True)}")
    total_elapsed = time.perf_counter() - overall_start

    # Summary.
    with open(output_file, "a") as f:
        f.write("\n" + "=" * 80 + "\n")
        f.write("SUMMARY\n")
        f.write("=" * 80 + "\n")
        f.write(f"Total: {total}, Passed: {passed}, Failed: {failed}\n")
        f.write(f"Case evidence: {json.dumps(case_summary, sort_keys=True)}\n")
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
    print(f"Results saved to: {output_file}")

    return 0 if total > 0 and not errors else 1


if __name__ == "__main__":
    sys.exit(main())
