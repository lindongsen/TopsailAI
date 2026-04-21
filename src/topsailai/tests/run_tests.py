#!/usr/bin/env python3
"""Run all test files one by one and capture results."""
import subprocess
import os
from pathlib import Path

TEST_DIR = "/root/ai/TopsailAI/src/topsailai/tests/unit"
OUTPUT_FILE = "/root/ai/TopsailAI/src/topsailai/_tmp/test_results.txt"

# Get all test files from the directory
def get_test_files():
    files = []
    for f in os.listdir(TEST_DIR):
        if f.startswith("test_") and f.endswith(".py"):
            files.append(f)
    return sorted(files)

def run_test(test_file):
    """Run a single test file and return result."""
    test_path = os.path.join(TEST_DIR, test_file)
    
    try:
        result = subprocess.run(
            ["python", "-m", "pytest", test_path, "-v", "--tb=short"],
            capture_output=True,
            text=True,
            timeout=120,
            cwd=TEST_DIR
        )
        
        if result.returncode == 0:
            return "PASS", "All tests passed"
        else:
            output = result.stdout + result.stderr
            lines = output.split('\n')
            error_lines = lines[-50:] if len(lines) > 50 else lines
            error_summary = '\n'.join(error_lines)
            return "FAIL", error_summary
    except subprocess.TimeoutExpired:
        return "TIMEOUT", "Test timed out after 120 seconds"
    except Exception as e:
        return "ERROR", str(e)

def main():
    test_files = get_test_files()
    results = []
    passed = 0
    failed = 0
    errors = []
    
    # Write header
    with open(OUTPUT_FILE, 'w') as f:
        f.write("=" * 80 + "\n")
        f.write("TEST RESULTS - One by One Execution\n")
        f.write("=" * 80 + "\n\n")
    
    total = len(test_files)
    print(f"Found {total} test files\n")
    
    for i, test_file in enumerate(test_files, 1):
        print(f"[{i}/{total}] Testing: {test_file}")
        status, details = run_test(test_file)
        
        result_entry = {
            'file': test_file,
            'status': status,
            'details': details
        }
        results.append(result_entry)
        
        if status == "PASS":
            passed += 1
            print(f"  ✓ PASS")
        else:
            failed += 1
            errors.append(result_entry)
            print(f"  ✗ {status}")
        
        # Write to file
        with open(OUTPUT_FILE, 'a') as f:
            f.write(f"\n{'='*80}\n")
            f.write(f"[{i}/{total}] {test_file}\n")
            f.write(f"Status: {status}\n")
            f.write(f"{'='*80}\n")
            f.write(f"{details}\n")
    
    # Summary
    with open(OUTPUT_FILE, 'a') as f:
        f.write("\n" + "=" * 80 + "\n")
        f.write("SUMMARY\n")
        f.write("=" * 80 + "\n")
        f.write(f"Total: {total}, Passed: {passed}, Failed: {failed}\n\n")
        
        if errors:
            f.write("FAILED TESTS:\n")
            f.write("-" * 80 + "\n")
            for r in errors:
                f.write(f"\nFile: {r['file']}\n")
                f.write(f"Status: {r['status']}\n")
                f.write(f"Details:\n{r['details'][:3000]}\n")
    
    print(f"\n{'='*80}")
    print(f"COMPLETE: Total={total}, Passed={passed}, Failed={failed}")
    print(f"Results saved to: {OUTPUT_FILE}")
    
    return results

if __name__ == "__main__":
    main()
