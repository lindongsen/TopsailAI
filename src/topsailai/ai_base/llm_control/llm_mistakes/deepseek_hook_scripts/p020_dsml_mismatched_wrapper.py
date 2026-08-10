"""
Author: DawsonLin
Email: lin_dongsen@126.com
Created: 2026-08-10
Purpose: Case script for DeepSeek DSML mismatched wrapper.

Handles the malformed format where a single ``<｜DSML｜tool_call>`` opening tag is
paired with a plural ``</｜DSML｜tool_calls>`` closing tag (see dsml-4.txt).

Contract:
    - Reads the raw response from TOPSAILAI_LLM_MISTAKE_RESPONSE, or from
      TOPSAILAI_LLM_MISTAKE_RESPONSE_FILE when the env var is unset.
    - On success prints a canonical JSON list to stdout.
    - On "not this case" prints nothing (empty stdout = not handled).
"""

import os
import sys

import simplejson

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _dsml import parse_singular_wrapper  # noqa: E402


CLOSE_TAG = "</｜DSML｜tool_calls>"


def _read_response():
    """Read the raw response from the environment contract.

    Returns:
        str | None: The raw response text, or ``None`` if unavailable.
    """
    response = os.environ.get("TOPSAILAI_LLM_MISTAKE_RESPONSE")
    if response is not None:
        return response
    response_file = os.environ.get("TOPSAILAI_LLM_MISTAKE_RESPONSE_FILE")
    if response_file:
        try:
            with open(response_file, "r", encoding="utf-8") as fh:
                return fh.read()
        except OSError:
            return None
    return None


def main():
    """Entry point: parse the mismatched wrapper and print JSON or nothing."""
    response = _read_response()
    if not response:
        return
    result = parse_singular_wrapper(response, CLOSE_TAG)
    if not result:
        return
    print(simplejson.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
