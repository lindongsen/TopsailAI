import pytest
import sys
import os
import tempfile
import shutil
from unittest.mock import patch, MagicMock

# Add the source directory to Python path
sys.path.insert(0, '/root/ai/TopsailAI/src')

from topsailai.utils.module_tool import (
    get_mod,
    get_var,
    list_sub_mods_name,
    get_function_map,
    is_valid_module_name,
    get_path_for_sys_and_package,
    get_external_function_map
)


def test_get_mod_existing_module():
    """Test get_mod with an existing module."""
    # Test with a standard library module
    module = get_mod('os')
    assert module is not None
    assert module.__name__ == 'os'


def test_get_mod_nonexistent_module():
    """Test get_mod with a non-existent module."""
    module = get_mod('nonexistent_module_12345')
    assert module is None


def test_get_var_existing_variable():
    """Test get_var with an existing variable."""
    # Test with os.path from os module
    result = get_var('os', 'path')
    assert result is not None
    assert hasattr(result, 'join')


def test_get_var_nonexistent_variable():
    """Test get_var with a non-existent variable."""
    result = get_var('os', 'nonexistent_variable_12345')
    assert result is None


def test_get_var_with_path_including_name():
    """Test get_var with path including variable name."""
    result = get_var('os.path', None)
    assert result is not None
    assert hasattr(result, 'join')


def test_list_sub_mods_name_existing_package():
    """Test list_sub_mods_name with an existing package."""
    # Test with a standard library package that has submodules
    submodules = list_sub_mods_name('json')
    assert submodules is not None
    assert isinstance(submodules, list)


def test_list_sub_mods_name_nonexistent_package():
    """Test list_sub_mods_name with a non-existent package."""
    submodules = list_sub_mods_name('nonexistent_package_12345')
    assert submodules is None


def test_is_valid_module_name_valid():
    """Test is_valid_module_name with valid names."""
    assert is_valid_module_name('valid_name')
    assert is_valid_module_name('_valid_name')
    assert is_valid_module_name('valid_name123')
    assert is_valid_module_name('ValidName')


def test_is_valid_module_name_invalid():
    """Test is_valid_module_name with invalid names."""
    assert not is_valid_module_name('123invalid')
    assert not is_valid_module_name('invalid-name')
    assert not is_valid_module_name('invalid.name')
    assert not is_valid_module_name('')


def test_get_path_for_sys_and_package_filesystem_path():
    """Test get_path_for_sys_and_package with filesystem path."""
    # Test with a path that should be in sys.path
    test_path = '/usr/lib/python3.10'  # Common Python library path
    sys_path, pkg_path = get_path_for_sys_and_package(test_path)
    
    # The result depends on the system configuration
    assert sys_path is not None or pkg_path is not None


def test_get_path_for_sys_and_package_package_path():
    """Test get_path_for_sys_and_package with package path."""
    # Test with a dot-separated package path
    sys_path, pkg_path = get_path_for_sys_and_package('os.path')
    assert sys_path is None
    assert pkg_path == 'os.path'


def test_get_function_map_basic():
    """Test get_function_map basic functionality."""
    # This is a complex function that requires specific module structure
    # We'll test that it returns a dictionary
    result = get_function_map('json')
    assert result is not None
    assert isinstance(result, dict)


def test_get_external_function_map_basic():
    """Test get_external_function_map basic functionality."""
    # Test with a standard library module
    result = get_external_function_map('json')
    assert result is not None
    assert isinstance(result, dict)


def test_module_import_consistency():
    """Test that all functions can be imported and are callable."""
    # Test that all imported functions exist and are callable
    from topsailai.utils.module_tool import (
        get_mod, get_var, list_sub_mods_name, get_function_map,
        is_valid_module_name, get_path_for_sys_and_package, get_external_function_map
    )
    
    assert callable(get_mod)
    assert callable(get_var)
    assert callable(list_sub_mods_name)
    assert callable(get_function_map)
    assert callable(is_valid_module_name)
    assert callable(get_path_for_sys_and_package)
    assert callable(get_external_function_map)


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
