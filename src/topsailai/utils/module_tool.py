'''
  Author: DawsonLin
  Email: lin_dongsen@126.com
  Created: 2025-10-18
  Purpose: Module introspection and dynamic import utilities
'''

import os
import sys
import re
import pkgutil

from topsailai.logger import logger


DEFAULT_CONN_CHAR = "."


def get_mod(path):
    """Dynamically import a module by its path.

    Args:
        path: Module path as string, e.g. 'base.internal_handlers'

    Returns:
        module: Imported module object
    """
    return __import__(path, None, None, [path.split('.')[-1]])

def get_var(path:str, name):
    """Get a variable from a module by path and name.

    Args:
        path: Module path or full path including variable name
        name: Variable name (optional if included in path)

    Returns:
        object: The variable value, or None if not found

    Note:
        If name is not provided, it will be extracted from the path
    """
    if not name:
        path, name = path.rsplit('.', 1)
    sub_mod = get_mod(path)
    var = None
    try:
        var = getattr(sub_mod, name)
    except Exception as e:
        logger.warning(f"{sub_mod}, {name}, {e}")
    return var

def list_sub_mods_name(path):
    """List all non-package submodule names in a package.

    Args:
        path: Package path, e.g. 'base.internal_handlers'

    Returns:
        list: List of submodule names, or None if package not found

    Note:
        Only returns modules that are not packages and don't start with '__'
    """
    mod = get_mod(path)
    if not mod:
        return None
    #
    mod_name_set = []
    for _, modname, ispkg in pkgutil.iter_modules(mod.__path__):
        if not ispkg and not modname.startswith('__'):
            mod_name_set.append(modname)
    return mod_name_set

def get_function_map(path, key="TOOLS", prefix_name="", conn_char=DEFAULT_CONN_CHAR):
    """Create a mapping of function names to functions from modules.

    This function scans modules in a package and collects functions
    stored in a specific variable (typically used for tool registration).

    Args:
        path: Package path to search for modules
        key: Variable name to look for in each module (default: "TOOLS")
        prefix_name: Prefix for function names in the map
            - If None: uses 'path' as prefix
            - If "": uses module name as prefix
            - Otherwise: uses the specified prefix

    Returns:
        dict: Mapping of function names (with prefixes) to function objects

    Example:
        {
            "cmd_tool.exec_cmd": exec_cmd_function
        }
    """
    if not conn_char:
        conn_char = DEFAULT_CONN_CHAR
    assert len(conn_char) == 1

    if prefix_name is None:
        prefix_name = path

    modules_map = {}
    for sub_modname in list_sub_mods_name(path):
        values = get_var("%s.%s" % (path, sub_modname), key)
        if not values:
            continue

        iter_values = None
        if isinstance(values, dict):
            iter_values = values.items()
        elif isinstance(values, (list, set, tuple)):
            iter_values = enumerate(values)
        if iter_values is None:
            print(f"BUG? module={sub_modname}, values={values}")
            continue

        for v_name, v_func in iter_values:
            if not isinstance(v_name, str):
                v_name = v_func.__name__
            m_key = f"{sub_modname}{conn_char}{v_name}"
            if prefix_name:
                m_key = f"{prefix_name}{conn_char}{m_key}"
            modules_map[m_key] = v_func
    return modules_map

def is_valid_module_name(name):
    """Check if a string is a valid Python module name.

    Valid module names follow Python identifier rules: start with a letter or
    underscore, followed by letters, digits, or underscores.

    Args:
        name (str): The string to validate.

    Returns:
        bool: True if the string is a valid module name, False otherwise.
    """
    pattern = r'^[a-zA-Z_][a-zA-Z0-9_]*$'
    return bool(re.match(pattern, name))

def get_path_for_sys_and_package(path:str) -> tuple[str|None, str|None]:
    """Split a filesystem path into a sys.path entry and a Python package path.

    This function attempts to match the given path against entries in sys.path.
    If a match is found, returns the matched sys.path entry and the remainder
    as a dot‑separated package path. If no match is found, it walks up the
    directory tree to find the outermost directory that is a Python package.

    Args:
        path (str): A filesystem path that may be inside a Python package.

    Returns:
        tuple[str|None, str|None]:
            - sys_path: The matched sys.path entry (or directory containing the
              outermost package). None if not applicable.
            - pkg_path: The dot‑separated Python package path relative to
              sys_path. If sys_path is None, pkg_path is the original path.
    """
    sys_path = None
    pkg_path = path
    if '/' in path:
        for _curr_sys_path in sys.path:
            if not _curr_sys_path:
                continue
            if _curr_sys_path[0] == ".":
                continue
            if not path.startswith(_curr_sys_path):
                continue
            if _curr_sys_path[-1] == "/":
                _curr_sys_path = _curr_sys_path[:-1]

            if len(path) != len(_curr_sys_path):
                # path:           /tmp/m1/m2
                # _curr_sys_path: /tmp/m
                if path[len(_curr_sys_path)] != '/':
                    continue

            # matched
            sys_path = _curr_sys_path
            pkg_path = path.replace(sys_path, "").replace("/", ".")
            if pkg_path[0] == ".":
                pkg_path = pkg_path[1:]
            return (sys_path, pkg_path)

        # debug
        # print(">>> no match with sys.path")

        # path:     /libs/a/b/c
        # sys_path: /libs/a/b
        # pkg_path: c
        sys_path = os.path.dirname(path)
        pkg_path = os.path.basename(path)
        for _ in range(100):
            if not os.path.exists(f"{sys_path}/__init__.py") \
                and not os.path.exists(f"{sys_path}/__init__.pyc"):
                break
            _base_name = os.path.basename(sys_path)
            if not is_valid_module_name(_base_name):
                break
            pkg_path = _base_name + "." + pkg_path
            sys_path = os.path.dirname(sys_path)
        # end for
        return (sys_path, pkg_path)
    else:
        # from xxx.topsailai.tools import TOOLS
        pass
    return (sys_path, pkg_path)

def get_external_function_map(path:str, key:str="TOOLS", prefix_name:str="", conn_char=DEFAULT_CONN_CHAR):
    """Create a mapping of function names to functions from modules.

    This function scans modules in a package and collects functions
    stored in a specific variable (typically used for tool registration).

    Args:
        path: Package path to search for modules
        key: Variable name to look for in each module (default: "TOOLS")
        prefix_name: Prefix for function names in the map
            - If None: uses 'path' as prefix
            - If "": uses module name as prefix
            - Otherwise: uses the specified prefix

    Returns:
        dict: Mapping of function names (with prefixes) to function objects

    Example:
        {
            "cmd_tool.exec_cmd": exec_cmd_function
        }
    """
    path = path.strip()
    if not path:
        return

    sys_path, pkg_path = get_path_for_sys_and_package(path)
    logger.info(
        "loading external functions: path=[%s], pkg=[%s], key=[%s], prefix=[%s]",
        path, pkg_path, key, prefix_name,
    )

    if sys_path and sys_path not in sys.path:
        sys.path.append(sys_path)

    assert pkg_path, f"no found pkg_path for this path: [{path}]"
    return get_function_map(pkg_path, key, prefix_name, conn_char=conn_char)
