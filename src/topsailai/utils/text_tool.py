'''
  Author: DawsonLin
  Email: lin_dongsen@126.com
  Created: 2025-10-20
  Purpose: Text processing and encoding utilities
'''

from difflib import SequenceMatcher
import chardet


def safe_decode(data):
    """Safely decode bytes to string with automatic encoding detection.

    This function attempts to decode bytes data to a string using automatic
    encoding detection. If the detected encoding fails, it falls back to
    UTF-8 with error replacement.

    Args:
        data: Input data to decode (bytes or string)

    Returns:
        str: Decoded string

    Note:
        - If input is already a string, returns it unchanged
        - If input is empty or None, returns empty string
        - Uses chardet for encoding detection with UTF-8 fallback
        - Uses 'replace' error handling to avoid decoding failures
    """
    if isinstance(data, str):
        return data

    if not data:
        return ""

    # Detect encoding
    detected = chardet.detect(data)
    encoding = detected.get('encoding', 'utf-8')

    if not encoding:
        try:
            return data.decode('utf-8', errors='replace')
        except Exception:
            return str(data)

    try:
        return data.decode(encoding)
    except UnicodeDecodeError:
        # Fallback to UTF-8 with error replacement
        return data.decode('utf-8', errors='replace')


def check_repetition(text: str, similarity_threshold: float = 0.8) -> dict:
    """Analyze text for repetition patterns and similarity issues.

    This function detects both exact duplicate lines and fuzzy duplicates
    (lines with high similarity) in the input text. It compares each line
    against all previous lines to identify repetition patterns throughout
    the entire text.

    Args:
        text: The input text content to analyze
        similarity_threshold: Similarity threshold (0-1), lines with similarity
            above this value are considered fuzzy duplicates. Default is 0.8.

    Returns:
        dict: A dictionary containing repetition analysis results with keys:
            - total_lines: Total number of non-empty lines
            - exact_duplicate_count: Number of exactly duplicate lines
            - fuzzy_duplicate_count: Number of fuzzy duplicate lines
            - repetition_rate: Estimated repetition ratio (0-1)
            - exact_duplicates: Dict mapping duplicate lines to their occurrence count
            - fuzzy_duplicates: List of fuzzy duplicate entries with index, line,
                                matched_line, and similarity
            - has_severe_repetition: Boolean indicating if repetition rate exceeds 30%
            - status: String status message ("no_content", "analyzed")

    Example:
        >>> result = check_repetition("Line 1\\nLine 1\\nLine 2")
        >>> print(result['repetition_rate'])
    """
    # Preprocess: split by lines and strip whitespace, filter out empty lines
    lines = [line.strip() for line in text.split('\n') if line.strip()]

    # Handle empty content case
    if not lines:
        return {
            "status": "no_content",
            "total_lines": 0,
            "exact_duplicate_count": 0,
            "fuzzy_duplicate_count": 0,
            "repetition_rate": 0.0,
            "exact_duplicates": {},
            "fuzzy_duplicates": [],
            "has_severe_repetition": False
        }

    total_lines = len(lines)
    exact_duplicate_count = 0
    exact_duplicates = {}  # Track exact duplicate lines and their occurrence count
    fuzzy_duplicates = []  # Track fuzzy duplicate entries
    processed_lines = []   # Store lines that have been processed

    # Detection logic: compare each line against all previous lines
    for i, current_line in enumerate(lines):
        current_line = lines[i]
        is_exact_duplicate = False
        best_match = None
        best_similarity = 0.0

        # Compare against all previously processed lines
        for j, prev_line in enumerate(processed_lines):
            # A. Exact match detection
            if current_line == prev_line:
                exact_duplicate_count += 1
                exact_duplicates[current_line] = exact_duplicates.get(current_line, 0) + 1
                is_exact_duplicate = True
                break  # Found exact match, no need to check further

            # B. Fuzzy match detection - find the best matching previous line
            similarity_ratio = SequenceMatcher(None, current_line, prev_line).ratio()
            if similarity_ratio > best_similarity:
                best_similarity = similarity_ratio
                best_match = {"index": j, "line": prev_line}

        # If not an exact duplicate but has high similarity match
        if not is_exact_duplicate and best_similarity > similarity_threshold:
            fuzzy_duplicates.append({
                "index": i,
                "line": current_line,
                "matched_line": best_match["line"],
                "matched_index": best_match["index"],
                "similarity": round(best_similarity, 4)
            })

        # Add current line to processed lines
        processed_lines.append(current_line)

    # Calculate repetition rate: ratio of duplicate lines to total lines
    total_duplicates = exact_duplicate_count + len(fuzzy_duplicates)
    repetition_rate = total_duplicates / total_lines if total_lines > 0 else 0.0

    # Determine if repetition is severe (threshold: 30%)
    has_severe_repetition = repetition_rate > 0.3

    return {
        "status": "analyzed",
        "total_lines": total_lines,
        "exact_duplicate_count": exact_duplicate_count,
        "fuzzy_duplicate_count": len(fuzzy_duplicates),
        "repetition_rate": round(repetition_rate, 4),
        "exact_duplicates": exact_duplicates,
        "fuzzy_duplicates": fuzzy_duplicates,
        "has_severe_repetition": has_severe_repetition
    }


def print_repetition_report(result: dict, similarity_threshold: float = 0.8) -> None:
    """Print a formatted repetition analysis report.

    Args:
        result: The dictionary returned by check_repetition()
        similarity_threshold: The similarity threshold used for fuzzy matching
    """
    if result["status"] == "no_content":
        print("No content to analyze.")
        return

    total_lines = result["total_lines"]
    exact_count = result["exact_duplicate_count"]
    fuzzy_count = result["fuzzy_duplicate_count"]
    repetition_rate = result["repetition_rate"]
    exact_duplicates = result["exact_duplicates"]
    fuzzy_duplicates = result["fuzzy_duplicates"]

    print(f"--- Analysis Started (Total Lines: {total_lines}) ---")
    print(f"\n[Statistics]")
    print(f"1. Exact duplicate lines: {exact_count}")
    print(f"2. Highly similar lines (fuzzy duplicates): {fuzzy_count}")
    print(f"3. Estimated repetition rate: {repetition_rate:.2%}")

    # Display top 3 most frequent exact duplicates
    if exact_duplicates:
        print(f"\n[Top 3 Frequent Exact Duplicates]")
        sorted_lines = sorted(exact_duplicates.items(), key=lambda x: x[1], reverse=True)
        for line, count in sorted_lines[:3]:
            print(f"- Occurs {count} times: \"{line}\"")

    # Display first 3 fuzzy duplicate examples
    if fuzzy_duplicates:
        print(f"\n[Fuzzy Duplicate Examples (First 3)]")
        for item in fuzzy_duplicates[:3]:
            print(f"- Line {item['index']}: \"{item['line'][:50]}...\"")
            print(f"  matches Line {item['matched_index']} with similarity {item['similarity']:.2%}")

    # Final conclusion
    if result["has_severe_repetition"]:
        print("\n⚠️  Warning: Severe repetition loop pattern detected!")
    else:
        print("\n✅ Text repetition is within normal range.")


# Test execution
if __name__ == "__main__":
    # --- Test data (based on provided log snippets) ---
    log_data = """
    Let me check the API routes to see if there's any blocking issue:

    Let me check the API routes to understand the issue better:

    Let me check the API routes:

    Let me check the API routes to understand the blocking issue:

    Let me check the API routes:

    Let me check the API routes to understand the blocking issue:

    Let me check the API routes:
    """

    # Run analysis and print report
    analysis_result = check_repetition(log_data)
    print_repetition_report(analysis_result)
