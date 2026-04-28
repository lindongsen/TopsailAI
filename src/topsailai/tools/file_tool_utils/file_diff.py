'''
Author: DawsonLin
Email: lin_dongsen@126.com
Created: 2026-04-28
Purpose:
'''

import difflib

def compare_files(file1_path, file2_path, context_lines=3):
    """
    Compare two code files and display differences in a user-friendly format

    Args:
        file1_path (str): Path to the first file
        file2_path (str): Path to the second file
        context_lines (int): Number of context lines to show around differences
    """
    # Read file contents
    with open(file1_path, 'r', encoding='utf-8') as f1:
        lines1 = f1.readlines()
    with open(file2_path, 'r', encoding='utf-8') as f2:
        lines2 = f2.readlines()

    # Create diff comparator
    differ = difflib.Differ()
    diff = list(differ.compare(lines1, lines2))

    # Generate diff report
    result = ["---"]
    # result.append(f"Comparing files: '{file1_path}' and '{file2_path}'")
    # result.append("=" * 60)

    current_block = []
    in_diff_block = False

    for i, line in enumerate(diff):
        if line.startswith('  '):  # Unchanged lines
            if in_diff_block and len(current_block) > 0:
                # Output diff block
                result.extend(format_diff_block(current_block, context_lines))
                current_block = []
            in_diff_block = False
        else:  # Changed lines
            in_diff_block = True
            current_block.append((i, line))

        # If current block is too large, output in segments
        if len(current_block) >= 10:
            result.extend(format_diff_block(current_block, context_lines))
            current_block = []

    # Output final diff block
    if current_block:
        result.extend(format_diff_block(current_block, context_lines))

    # If no differences found
    if len(result) == 2:
        result.append("Files are identical")

    # Output results
    return ('\n'.join(result))


def format_diff_block(block, context_lines):
    """Format diff block for output"""
    result = []
    start_idx = max(0, block[0][0] - context_lines)
    end_idx = min(len(block) + context_lines * 2, len(block) + block[-1][0])

    # Add context lines
    for i in range(start_idx, block[0][0]):
        if i < len(block):
            result.append(f"  {i+1:4d}| {block[i][1].rstrip()}")

    # Add diff lines
    for idx, line in block:
        prefix = ""
        if line.startswith('- '):
            prefix = "-"
        elif line.startswith('+ '):
            prefix = "+"
        elif line.startswith('? '):
            prefix = "?"

        line_content = line[2:].rstrip() if len(line) > 2 else ""
        result.append(f"{prefix} {idx+1:4d}| {line_content}")

    # Add separator line
    if result:
        result.append("---")

    return result

def get_unified_diff(file1_path, file2_path):
    """
    Get unified diff format for the file comparison

    Args:
        file1_path (str): Path to the first file
        file2_path (str): Path to the second file

    Returns:
        str: Unified diff format string
    """
    with open(file1_path, 'r', encoding='utf-8') as f1:
        lines1 = f1.readlines()
    with open(file2_path, 'r', encoding='utf-8') as f2:
        lines2 = f2.readlines()

    diff = difflib.unified_diff(
        lines1, lines2,
        fromfile=file1_path,
        tofile=file2_path,
        lineterm=''
    )

    return ''.join(diff)


def compare_files_strived(file1_path, file2_path, context_lines=3) -> str:
    try:
        return compare_files(file1_path=file1_path, file2_path=file2_path, context_lines=context_lines)
    except Exception:
        pass

    try:
        return get_unified_diff(file1_path=file1_path, file2_path=file2_path)
    except Exception:
        pass

    return ""


# Usage example
if __name__ == "__main__":
    # Compare two files
    compare_files('file1.py', 'file2.py')

    # Get unified diff format
    diff_output = get_unified_diff('file1.py', 'file2.py')
    print("\nUnified Diff format:")
    print(diff_output)
