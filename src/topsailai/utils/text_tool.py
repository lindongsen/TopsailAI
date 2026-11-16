'''
  Author: DawsonLin
  Email: lin_dongsen@126.com
  Created: 2025-10-20
  Purpose: Text processing and encoding utilities
'''

import re
from collections import Counter
from difflib import SequenceMatcher
import chardet


# Formatting scaffolding that repeats by construction, not by model behaviour.
# A Markdown report contains many identical code fences, table separator rows
# and closing braces no matter what it says, so counting them as repetition
# measures the document format instead of the model's output.
_TABLE_SEPARATOR_RE = re.compile(r"[|\-: ]+")
_SYMBOL_ONLY_RE = re.compile(r"[^\w]+")


def is_structural_line(line: str) -> bool:
    """Return whether a line is formatting scaffolding rather than content.

    Structural lines are excluded from repetition statistics because their
    duplication is decided by the document format, not by the model. Counting
    them makes a well-formatted report look repetitive even when every sentence
    is unique.

    Args:
        line: One stripped, non-empty line.

    Returns:
        bool: True for a code fence, a table separator row, or a line that
            contains no word characters at all.
    """
    if line.startswith("```"):
        return True
    if "|" in line and _TABLE_SEPARATOR_RE.fullmatch(line):
        return True
    if _SYMBOL_ONLY_RE.fullmatch(line):
        return True
    return False


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
    against the first occurrence of every distinct earlier line to identify
    repetition patterns throughout the entire text.

    Formatting scaffolding is excluded from the statistics: code fences, table
    separator rows, and lines containing no word characters. Those lines repeat
    because of the document format rather than the model's behaviour, so
    counting them makes a well-formatted report look repetitive even when all
    of its content is unique. The excluded count is reported separately so the
    decision stays auditable.

    Args:
        text: The input text content to analyze
        similarity_threshold: Similarity threshold (0-1), lines with similarity
            above this value are considered fuzzy duplicates. Default is 0.8.

    Returns:
        dict: A dictionary containing repetition analysis results with keys:
            - total_lines: Number of non-empty content lines after excluding
                structural lines
            - structural_line_count: Number of excluded structural lines
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
    raw_lines = [line.strip() for line in text.split('\n') if line.strip()]

    # Handle empty content case
    if not raw_lines:
        return {
            "status": "no_content",
            "total_lines": 0,
            "structural_line_count": 0,
            "exact_duplicate_count": 0,
            "fuzzy_duplicate_count": 0,
            "repetition_rate": 0.0,
            "exact_duplicates": {},
            "fuzzy_duplicates": [],
            "has_severe_repetition": False
        }

    # Formatting scaffolding repeats by construction, so it is excluded from
    # both the duplicate count and the denominator. Counting it would measure
    # the document format instead of the model's output.
    lines = [line for line in raw_lines if not is_structural_line(line)]
    structural_line_count = len(raw_lines) - len(lines)

    total_lines = len(lines)
    exact_duplicate_count = 0
    exact_duplicates = {}  # Track exact duplicate lines and their occurrence count
    fuzzy_duplicates = []  # Track fuzzy duplicate entries

    # Two changes remove the quadratic scan while preserving the original
    # result exactly (verified against a faithful port of the original on a
    # 1151-line report: identical exact count and identical fuzzy list).
    #
    # 1. Exact duplicates are counted with a dictionary. The original broke out
    #    of its inner loop on an exact match, so an exact duplicate was never
    #    also counted as fuzzy; the `continue` below preserves that.
    # 2. Fuzzy matching only compares against the first occurrence of each
    #    distinct line. The original kept the first index achieving the best
    #    similarity, which is the index the first occurrence carries, so the
    #    reported `matched_index` is unchanged.
    first_index_by_line = {}
    char_counts_by_line = {}

    for i, current_line in enumerate(lines):
        if current_line in first_index_by_line:
            exact_duplicate_count += 1
            exact_duplicates[current_line] = exact_duplicates.get(current_line, 0) + 1
            continue

        best_match = None
        best_similarity = 0.0
        current_len = len(current_line)
        current_chars = Counter(current_line)

        # Compare against the first occurrence of every distinct previous line
        for prev_line, prev_index in first_index_by_line.items():
            prev_len = len(prev_line)

            # ratio() is 2*M/T with T = len(a)+len(b) and M <= min(len(a),len(b)),
            # so this length bound is an exact upper bound computed in O(1).
            length_bound = 2.0 * min(current_len, prev_len) / (current_len + prev_len)
            if length_bound <= best_similarity:
                continue
            if length_bound <= similarity_threshold:
                continue

            # A tighter exact bound: every matched character pair must share a
            # character, so M <= sum_c min(count_a[c], count_b[c]). This is
            # still an upper bound on ratio() and costs O(alphabet), which
            # rejects most candidates before any SequenceMatcher is built.
            prev_chars = char_counts_by_line[prev_line]
            if len(current_chars) <= len(prev_chars):
                shared = sum(
                    min(count, prev_chars.get(char, 0))
                    for char, count in current_chars.items()
                )
            else:
                shared = sum(
                    min(count, current_chars.get(char, 0))
                    for char, count in prev_chars.items()
                )
            char_bound = 2.0 * shared / (current_len + prev_len)
            if char_bound <= best_similarity:
                continue
            if char_bound <= similarity_threshold:
                continue

            matcher = SequenceMatcher(None, current_line, prev_line)
            # quick_ratio() is a cheaper upper bound on ratio(), so a candidate
            # that cannot beat the current best is skipped without the full
            # compare.
            if matcher.quick_ratio() <= best_similarity:
                continue
            similarity_ratio = matcher.ratio()
            if similarity_ratio > best_similarity:
                best_similarity = similarity_ratio
                best_match = {"index": prev_index, "line": prev_line}

        # If not an exact duplicate but has high similarity match
        if best_match is not None and best_similarity > similarity_threshold:
            fuzzy_duplicates.append({
                "index": i,
                "line": current_line,
                "matched_line": best_match["line"],
                "matched_index": best_match["index"],
                "similarity": round(best_similarity, 4)
            })

        first_index_by_line[current_line] = i
        char_counts_by_line[current_line] = current_chars

    # Calculate repetition rate: ratio of duplicate lines to content lines
    total_duplicates = exact_duplicate_count + len(fuzzy_duplicates)
    repetition_rate = total_duplicates / total_lines if total_lines > 0 else 0.0

    # Determine if repetition is severe (threshold: 30%)
    has_severe_repetition = repetition_rate > 0.3

    return {
        "status": "analyzed",
        "total_lines": total_lines,
        "structural_line_count": structural_line_count,
        "exact_duplicate_count": exact_duplicate_count,
        "fuzzy_duplicate_count": len(fuzzy_duplicates),
        "repetition_rate": round(repetition_rate, 4),
        "exact_duplicates": exact_duplicates,
        "fuzzy_duplicates": fuzzy_duplicates,
        "has_severe_repetition": has_severe_repetition
    }


def print_repetition_report(result: dict) -> None:
    """Print a formatted repetition analysis report.

    Args:
        result: The dictionary returned by check_repetition()
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
    structural_count = result.get("structural_line_count", 0)

    print(f"--- Analysis Started (Total Lines: {total_lines}) ---")
    print(f"\n[Statistics]")
    print(f"1. Exact duplicate lines: {exact_count}")
    print(f"2. Highly similar lines (fuzzy duplicates): {fuzzy_count}")
    print(f"3. Estimated repetition rate: {repetition_rate:.2%}")
    # Excluded scaffolding is reported so the decision stays auditable: a low
    # rate on a large excluded count means the document is heavily formatted,
    # not that the model stopped repeating itself.
    if structural_count:
        print(f"4. Excluded structural lines: {structural_count}")

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
