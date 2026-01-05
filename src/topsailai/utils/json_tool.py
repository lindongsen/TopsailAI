import simplejson
from .print_tool import print_error

def convert_code_block_to_json_str(content:str):
    """Convert markdown code blocks containing JSON to valid JSON string.

    This function extracts JSON content from markdown code blocks and converts
    it to a valid JSON string. It handles both single and multiple JSON objects
    within code blocks.

    Args:
        content: String containing markdown code blocks with JSON content

    Returns:
        str: Valid JSON string if code blocks are found, None otherwise

    Examples:
        Input: "```json\n{1:1}\n```" -> Output: "{1:1}"
        Input: "```json\n{1:1}\n```\n```json\n{2:2}\n```" -> Output: "[{1:1},{2:2}]"
    """
    content = content.strip()
    if content.startswith("```json"):
        content = content.replace("```json", "")
        content = content.replace("```", ",")
        if content[-1] == ",":
            return f"[{content[:-1]}]"
    if content.startswith("```"):
        content = content.replace("```", "", 1)
        if content.endswith("```"):
            return content[:-3]
    if content.endswith("```"):
        return content[:-3]
    return None

def fix_llm_mistakes_on_json(content):
    """Fix common JSON formatting mistakes made by language models.

    This function attempts to correct various JSON formatting errors that
    language models might produce, such as missing brackets, incorrect
    structure, or markdown code block artifacts.

    Args:
        content: String containing potentially malformed JSON

    Returns:
        str: Corrected JSON string

    Note:
        The function will print error messages when fixing issues to help
        with debugging and monitoring LLM behavior.
    """
    if not isinstance(content, str):
        return content

    content = content.strip()

    if safe_json_load(content):
        return content

    # LLM can make mistakes

    # case: "\n  }\n  }\n"
    case_dup1 = "\n  }\n  }\n"
    if case_dup1 in content:
        try:
            _new_content = content.replace(case_dup1, "\n  }\n", 1)
            simplejson.loads(_new_content)
            return _new_content
        except Exception:
            pass

    # case1: Missing closing bracket for array
    if content[0] == '[' and content[-1] != ']' and "]\n" not in content:
        print_error("!!! LLM makes a mistake, trying to fix it: no found ']'")

        # case: missing one '}' too.
        if content.endswith("\n}") \
            or content[-1] in ('"', '}') \
            :
            try:
                simplejson.loads(content + "}]")
                return content + "}]"
            except Exception:
                pass

        return content + "]"

    # case2: Extra newline before closing bracket
    if content[0] == '[' and "]\n" in content:
        print_error("!!! LLM makes a mistake, trying to fix it: found ']\\n'")
        i = content.find("\n]")
        if i > 0:
            return content[:i+2]
        i = content.find("  ]\n")
        if i > 0:
            return content[:i+3]
        if content.endswith("]\n}"):
            return content[:-2]

    # case3: JSON wrapped in markdown code blocks
    _new_content = convert_code_block_to_json_str(content)
    if _new_content:
        print_error("!!! LLM makes a mistake, fix it: found code block")
        content = _new_content
        return content

    # case4: Missing closing brace in array of objects
    if content[0] == '[':
        # case, "\n}\n]"
        i = content.find("\n}\n]")
        fixed_i = content.find("\n}\n}\n]")
        if i > 0 and fixed_i < 0:
            content = content[:i] + "\n}" + content[i:]
            print_error("!!! LLM makes a mistake, fix it: found '\\n}\\n]'")
            return content

        # case, "\n]}]"
        i = content.find("\n]")
        if i > 0:
            content_tail = content[i+2:].strip()
            if content_tail and len(content_tail) < 11:
                print_error(f"!!! LLM makes a mistake, fix it: found error on tail '{content_tail}'")
                return content[:i+2]

    # case, \-
    if "\\-" in content:
        content = content.replace("\\-", "\\n-")

    return content

def to_json_str(content, indent=2):
    """Convert Python objects to JSON string with error handling.

    This function converts Python objects (dict, list, etc.) to JSON strings.
    It also handles string inputs by attempting to fix common LLM mistakes
    before returning the result.

    Args:
        content: Python object or string to convert to JSON
        indent: Number of spaces for indentation (default: 2)

    Returns:
        str: JSON formatted string

    Raises:
        Prints error message if conversion fails but returns string representation
    """
    if isinstance(content, str):
        content = fix_llm_mistakes_on_json(content)
        new_content = convert_code_block_to_json_str(content)
        if new_content:
            return new_content
        return content
    try:
        return simplejson.dumps(content, indent=indent, ensure_ascii=False, default=str)
    except Exception as e:
        print_error(f"format_content error: {e}, content: {content}")
        return str(content)

def json_dump(obj, indent=2):
    """Serialize Python object to JSON string.

    This is a convenience wrapper around to_json_str that handles
    set and tuple objects by converting them to lists first.

    Args:
        obj: Python object to serialize
        indent: Number of spaces for indentation (default: 2)

    Returns:
        str: JSON formatted string
    """
    if isinstance(obj, (set, tuple)):
        obj = list(obj)
    return to_json_str(obj, indent=indent)

def json_load(content):
    """Deserialize JSON string to Python object.

    Args:
        content: JSON string to parse

    Returns:
        object: Python object (dict, list, etc.) parsed from JSON

    Note:
        Returns the input unchanged if it's not a string
    """
    if not isinstance(content, str):
        return content
    return simplejson.loads(content)

def safe_json_dump(obj, indent=2, ensure_ascii=False, default=None) -> str:
    """Safely serialize Python object to JSON string with fallback to string representation.

    This function attempts to convert a Python object to a JSON string. If the input is already a string, it is returned unchanged. If JSON serialization fails, the function falls back to converting the object to a string using str().

    Args:
        obj: Python object to serialize
        indent: Number of spaces for indentation (default: 2)
        ensure_ascii: If True, output is ASCII-only (default: False)
        default: Function to handle non-serializable objects; defaults to str

    Returns:
        str: JSON string representation of the object, or its string representation
            if serialization fails
    """
    if isinstance(obj, str):
        return obj

    try:
        return simplejson.dumps(
            obj, indent=indent, ensure_ascii=ensure_ascii, default=default or str,
        )
    except Exception:
        pass

    return str(obj)

def safe_json_load(s) -> str|None:
    """Safely deserialize JSON string with error handling.

    This function attempts to parse a JSON string. If parsing fails due to
    invalid JSON syntax or other exceptions, it returns None instead of raising.

    Args:
        s: JSON string to parse

    Returns:
        str|None: Parsed Python object if successful, None otherwise

    Example:
        >>> safe_json_load('{"key": "value"}')
        {'key': 'value'}
        >>> safe_json_load('invalid')
        None
    """
    try:
        return json_load(s)
    except Exception:
        pass
    return None
