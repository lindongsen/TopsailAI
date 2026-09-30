"""
Author: DawsonLin
Email: lin_dongsen@126.com
Created: 2026-08-10
Purpose: Subprocess-based runner for model-specific LLM mistake hook scripts.

Each model may ship a folder of hook modules (e.g. ``deepseek_hook_scripts/``).
The runner discovers eligible Python source and compiled extension modules on
every call, then spawns each as an independent subprocess using a resolved
Python interpreter. A valid JSON list on stdout is the handled result. Empty
stdout means "not handled"; invalid JSON, oversized output, or timeout means
"failure" (the caller continues to the next hook or falls back to its parser).

Environment contract passed to each hook:
    - TOPSAILAI_LLM_MISTAKE_MODEL: resolved model name (empty if unknown).
    - TOPSAILAI_LLM_MISTAKE_RESPONSE: raw response when small enough.
    - TOPSAILAI_LLM_MISTAKE_RESPONSE_FILE: temp file path for larger responses.
    - TOPSAILAI_LLM_MISTAKE_SCRIPT: absolute path of the executed hook artifact.
    - TOPSAILAI_LLM_MISTAKE_SCRIPT_DIR: absolute path of the hook folder.

The child environment is a minimal curated set (PATH, PYTHONPATH, LANG,
LC_ALL, HOME plus the TOPSAILAI_LLM_MISTAKE_* variables) so secrets from the
parent environment are not leaked into arbitrary child processes.
"""

import hashlib
import importlib.machinery
import importlib.resources
import os
import pkgutil
import signal
import subprocess
import tempfile
import time
import uuid
from typing import NamedTuple

import simplejson

from topsailai.logger.log_chat import logger
from topsailai.utils.env_tool import resolve_python_interpreter


# Default configuration values (overridable via environment variables).
DEFAULT_SCRIPT_TIMEOUT = 5
DEFAULT_RESPONSE_MAX_ENV = 65536
DEFAULT_RESPONSE_MAX_FILE = 10485760
DEFAULT_OUTPUT_MAX = 1048576

# File extensions that are never treated as case scripts.
IGNORED_SUFFIXES = (".tmp", ".new", ".bak", "~", ".swp", ".pyc")

SCRIPT_KIND_SOURCE = "source"
SCRIPT_KIND_EXTENSION = "extension"
EXTENSION_BOOTSTRAP = """\
import importlib
import os
import sys

sys.path.insert(0, os.getcwd())
module = importlib.import_module(sys.argv[1])
main = getattr(module, "main", None)
if not callable(main):
    raise TypeError("compiled hook module must expose callable main()")
main()
"""


class HookScript(NamedTuple):
    """Describe one importable hook script artifact."""

    module_name: str
    path: str
    kind: str


def _env_int(name, default):
    """Read an integer environment variable with a fallback default.

    Args:
        name (str): The environment variable name.
        default (int): The fallback value when unset or invalid.

    Returns:
        int: The parsed integer value.
    """
    raw = os.environ.get(name)
    if raw is None:
        return default
    try:
        return int(raw)
    except (TypeError, ValueError):
        return default


def _get_script_timeout():
    """Return the per-script subprocess timeout in seconds."""
    return _env_int("TOPSAILAI_LLM_MISTAKE_SCRIPT_TIMEOUT", DEFAULT_SCRIPT_TIMEOUT)


def _get_response_max_env():
    """Return the max response bytes passed via environment variable."""
    return _env_int("TOPSAILAI_LLM_MISTAKE_RESPONSE_MAX_ENV", DEFAULT_RESPONSE_MAX_ENV)


def _get_response_max_file():
    """Return the hard cap for response bytes before fail-open."""
    return _env_int("TOPSAILAI_LLM_MISTAKE_RESPONSE_MAX_FILE", DEFAULT_RESPONSE_MAX_FILE)


def _get_output_max():
    """Return the max stdout bytes accepted from a script."""
    return _env_int("TOPSAILAI_LLM_MISTAKE_OUTPUT_MAX", DEFAULT_OUTPUT_MAX)


def _script_kind(path):
    """Return the supported execution kind for an artifact path."""
    if path.endswith(tuple(importlib.machinery.SOURCE_SUFFIXES)):
        return SCRIPT_KIND_SOURCE
    if path.endswith(tuple(importlib.machinery.EXTENSION_SUFFIXES)):
        return SCRIPT_KIND_EXTENSION
    return None


def _discover_scripts(script_dir):
    """Discover eligible source or extension hook modules, sorted by name.

    The folder is rescanned on every call so that scripts added, removed, or
    changed between responses take effect immediately without a restart.

    Args:
        script_dir (str): Absolute path to the model script folder.

    Returns:
        list[HookScript]: Sorted descriptors of eligible hook modules.
    """
    if not script_dir or not os.path.isdir(script_dir):
        return []
    scripts = []
    script_dir_real = os.path.realpath(script_dir)
    try:
        # Python's finder emits one entry per module name and applies its normal
        # import precedence, so a same-name extension artifact wins over source.
        modules = sorted(pkgutil.iter_modules([script_dir]), key=lambda item: item.name)
    except Exception as exc:
        logger.warning(
            "LLM mistake hook script directory discovery failed (%s)",
            type(exc).__name__,
        )
        return []

    for module in modules:
        if module.ispkg or module.name.startswith("_"):
            continue
        try:
            spec = module.module_finder.find_spec(module.name)
            path = getattr(spec, "origin", None)
            if not path or not os.path.isfile(path):
                continue
            kind = _script_kind(path)
            if kind is None or any(path.endswith(suffix) for suffix in IGNORED_SUFFIXES):
                continue
            real = os.path.realpath(path)
            if not real.startswith(script_dir_real + os.sep):
                logger.warning(
                    "LLM mistake hook script %s resolves outside the script folder; skipped",
                    module.name,
                )
                continue
            scripts.append(HookScript(module.name, path, kind))
        except Exception as exc:
            logger.warning(
                "LLM mistake hook module %s discovery failed (%s); skipped",
                module.name,
                type(exc).__name__,
            )
    return scripts


def _build_child_env(model_name, response, script_path, script_dir):
    """Build the minimal curated environment for a child script process.

    Args:
        model_name (str): The resolved model name (may be empty).
        response (str | None): The raw response text, or ``None`` when it is
            too large to pass via the environment.
        script_path (str): Absolute path of the script being executed.
        script_dir (str): Absolute path of the script folder.

    Returns:
        dict: The child environment mapping.
    """
    env = {
        "PATH": os.environ.get("PATH", ""),
        "PYTHONPATH": os.environ.get("PYTHONPATH", ""),
        "LANG": os.environ.get("LANG", "C.UTF-8"),
        "LC_ALL": os.environ.get("LC_ALL", "C.UTF-8"),
        "HOME": os.environ.get("HOME", ""),
        "TOPSAILAI_LLM_MISTAKE_MODEL": model_name or "",
        "TOPSAILAI_LLM_MISTAKE_SCRIPT": script_path,
        "TOPSAILAI_LLM_MISTAKE_SCRIPT_DIR": script_dir,
    }
    if response is not None:
        env["TOPSAILAI_LLM_MISTAKE_RESPONSE"] = response
    return env


def _validate_result(data):
    """Validate parsed script output against the agent step schema.

    Args:
        data (any): The parsed JSON value from the script stdout.

    Returns:
        list | None: The normalized list of steps, or ``None`` when invalid.
    """
    if isinstance(data, dict):
        data = [data]
    if not isinstance(data, list) or not data:
        return None
    for item in data:
        if not isinstance(item, dict):
            return None
        step_name = item.get("step_name")
        if not isinstance(step_name, str) or not step_name:
            return None
        if step_name == "action":
            tool_call = item.get("tool_call")
            tool_args = item.get("tool_args")
            if not isinstance(tool_call, str) or not tool_call:
                return None
            if not isinstance(tool_args, dict):
                return None
        else:
            if "raw_text" not in item:
                return None
    return data


def _short_hash(text):
    """Return a short sha256 hash for logging without leaking content.

    Args:
        text (str): The text to hash.

    Returns:
        str: The first 12 hex characters of the sha256 digest.
    """
    return hashlib.sha256(text.encode("utf-8", errors="replace")).hexdigest()[:12]


def _run_single_script(script, script_dir, model_name, response, response_file):
    """Run one case script and return its validated result.

    Args:
        script (HookScript): The hook module descriptor.
        script_dir (str): Absolute path of the script folder.
        model_name (str): The resolved model name.
        response (str | None): The raw response when passed via env.
        response_file (str | None): Temp file path when response is too large.

    Returns:
        tuple: ``(outcome, result)`` where ``outcome`` is one of
        ``"handled"``, ``"not_handled"``, or ``"failure"``, and ``result``
        is the validated list on success or ``None`` otherwise.
    """
    env = _build_child_env(model_name, response, script.path, script_dir)
    if response_file:
        env["TOPSAILAI_LLM_MISTAKE_RESPONSE_FILE"] = response_file

    timeout = _get_script_timeout()
    output_max = _get_output_max()
    start = time.time()
    proc = None
    try:
        interpreter = resolve_python_interpreter()
        command = [interpreter, script.path]
        if script.kind == SCRIPT_KIND_EXTENSION:
            command = [interpreter, "-c", EXTENSION_BOOTSTRAP, script.module_name]
        proc = subprocess.Popen(
            command,
            env=env,
            cwd=script_dir,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            start_new_session=True,
        )
        try:
            stdout, stderr = proc.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except OSError:
                pass
            proc.wait()
            logger.warning(
                "LLM mistake hook script %s timed out after %ss",
                os.path.basename(script.path),
                timeout,
            )
            return "failure", None

        elapsed_ms = int((time.time() - start) * 1000)
        if stderr:
            logger.debug(
                "LLM mistake hook script %s stderr: %s",
                os.path.basename(script.path),
                stderr.decode("utf-8", errors="replace")[:500],
            )

        if len(stdout) > output_max:
            logger.warning(
                "LLM mistake hook script %s output exceeded %s bytes; treated as failure",
                os.path.basename(script.path),
                output_max,
            )
            return "failure", None

        text = stdout.decode("utf-8", errors="replace").strip()
        if not text:
            logger.debug(
                "LLM mistake hook script %s returned no output (not handled) in %sms",
                os.path.basename(script.path),
                elapsed_ms,
            )
            return "not_handled", None

        try:
            parsed = simplejson.loads(text, strict=False)
        except Exception as exc:
            logger.warning(
                "LLM mistake hook script %s returned invalid JSON: %s",
                os.path.basename(script.path),
                exc,
            )
            return "failure", None

        result = _validate_result(parsed)
        if result is None:
            logger.warning(
                "LLM mistake hook script %s returned output failing schema validation",
                os.path.basename(script.path),
            )
            return "failure", None

        if proc.returncode != 0:
            logger.warning(
                "LLM mistake hook script %s exited with code %s but produced valid output; accepted",
                os.path.basename(script.path),
                proc.returncode,
            )
        logger.debug(
            "LLM mistake hook script %s handled response in %sms",
            os.path.basename(script.path),
            elapsed_ms,
        )
        return "handled", result
    except Exception as exc:
        logger.warning(
            "LLM mistake hook script %s failed to run: %s",
            os.path.basename(script.path),
            exc,
        )
        return "failure", None
    finally:
        if proc is not None and proc.poll() is None:
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except OSError:
                pass
            proc.wait()


def run_hook_scripts(script_dir, model_name, response):
    """Run all eligible hook scripts in order and return the first result.

    Args:
        script_dir (str): Absolute path to the model script folder.
        model_name (str): The resolved model name.
        response (str): The raw LLM response string.

    Returns:
        list | None: The first validated result, or ``None`` when no script
        handled the response (caller falls back to its parser).
    """
    if not isinstance(response, str) or not response:
        return None

    scripts = _discover_scripts(script_dir)
    if not scripts:
        return None

    response_len = len(response.encode("utf-8", errors="replace"))
    max_env = _get_response_max_env()
    max_file = _get_response_max_file()

    response_env = None
    response_file = None
    if response_len <= max_env:
        response_env = response
    elif response_len <= max_file:
        try:
            fd, response_file = tempfile.mkstemp(
                prefix=f"mistake.{os.getpid()}.{uuid.uuid4().hex}.",
                suffix=".txt",
            )
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                fh.write(response)
        except OSError as exc:
            logger.warning(
                "LLM mistake hook script temp file creation failed: %s; skipping scripts",
                exc,
            )
            return None
    else:
        logger.warning(
            "LLM mistake response too large (%s bytes > %s); skipping hook scripts and using parser fallback",
            response_len,
            max_file,
        )
        return None

    try:
        for script in scripts:
            outcome, result = _run_single_script(
                script, script_dir, model_name, response_env, response_file
            )
            if outcome == "handled":
                return result
    finally:
        if response_file:
            try:
                os.remove(response_file)
            except OSError:
                pass

    logger.debug(
        "LLM mistake hook scripts did not handle response (type=%s len=%s hash=%s)",
        type(response).__name__,
        response_len,
        _short_hash(response),
    )
    return None


def get_model_script_dir(package_name, folder_name):
    """Resolve the model script folder via importlib.resources.

    This works identically in source, editable, and wheel installs without
    hardcoding absolute paths.

    Args:
        package_name (str): The package path, e.g.
            ``topsailai.ai_base.llm_control.llm_mistakes.deepseek_hook_scripts``.
        folder_name (str): The folder name (used for validation only).

    Returns:
        str: The absolute path to the script folder.
    """
    try:
        return str(importlib.resources.files(package_name))
    except Exception as exc:
        logger.warning("Failed to resolve hook script folder %s: %s", folder_name, exc)
        return ""
