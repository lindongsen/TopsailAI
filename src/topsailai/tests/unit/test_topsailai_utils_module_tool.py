import importlib.machinery
from unittest.mock import patch

import pytest

import topsailai.utils.module_tool as module_tool
from topsailai.utils.module_tool import (
    _has_package_initializer,
    get_external_function_map,
    get_function_map,
    get_mod,
    get_path_for_sys_and_package,
    get_var,
    is_valid_module_name,
    list_sub_mods_name,
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


@pytest.mark.parametrize(
    ("initializer", "expected"),
    [
        ("__init__.py", True),
        ("__init__.pyc", True),
        (f"__init__{importlib.machinery.EXTENSION_SUFFIXES[0]}", True),
        (None, False),
        ("__init__.txt", False),
        ("__init__.foo", False),
    ],
)
def test_has_package_initializer(tmp_path, initializer, expected):
    """Recognize only initializer suffixes supported by Python imports."""
    if initializer:
        (tmp_path / initializer).touch()

    assert _has_package_initializer(str(tmp_path)) is expected


@pytest.mark.parametrize("initializer", ["__init__.py", "__init__.pyc"])
def test_get_path_for_sys_and_package_source_or_bytecode_initializer(
    tmp_path, initializer
):
    """Resolve a package with a deterministic source or bytecode initializer."""
    package = tmp_path / "outer_package"
    target = package / "inner_package"
    target.mkdir(parents=True)
    (package / initializer).touch()

    with patch.object(module_tool.sys, "path", []):
        sys_path, pkg_path = get_path_for_sys_and_package(str(target))

    assert sys_path == str(tmp_path)
    assert pkg_path == "outer_package.inner_package"


def test_get_path_for_sys_and_package_non_package_parent(tmp_path):
    """Stop package traversal when the parent has no valid initializer."""
    parent = tmp_path / "plain_directory"
    target = parent / "candidate_package"
    target.mkdir(parents=True)
    (parent / "__init__.unknown").touch()

    with patch.object(module_tool.sys, "path", []):
        sys_path, pkg_path = get_path_for_sys_and_package(str(target))

    assert sys_path == str(parent)
    assert pkg_path == "candidate_package"


def test_get_path_for_sys_and_package_multilevel_extension_initializers(tmp_path):
    """Resolve every level of a nested extension-only package path."""
    suffix = importlib.machinery.EXTENSION_SUFFIXES[0]
    outer = tmp_path / "compiled_outer"
    inner = outer / "compiled_inner"
    target = inner / "plugin_package"
    target.mkdir(parents=True)
    (outer / f"__init__{suffix}").touch()
    (inner / f"__init__{suffix}").touch()

    with patch.object(module_tool.sys, "path", []):
        sys_path, pkg_path = get_path_for_sys_and_package(str(target))

    assert sys_path == str(tmp_path)
    assert pkg_path == "compiled_outer.compiled_inner.plugin_package"


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


def test_get_external_function_map_delegates_extension_only_path(tmp_path):
    """Resolve an extension-only path before delegating function discovery."""
    suffix = importlib.machinery.EXTENSION_SUFFIXES[0]
    outer = tmp_path / "compiled_outer"
    package = outer / "compiled_inner"
    package.mkdir(parents=True)
    (outer / f"__init__{suffix}").touch()
    expected = {"plugin.run": object()}
    isolated_sys_path = []

    with (
        patch.object(module_tool.sys, "path", isolated_sys_path),
        patch.object(module_tool, "get_function_map", return_value=expected) as discover,
    ):
        result = get_external_function_map(
            str(package),
            key="FUNCTIONS",
            prefix_name="external",
            conn_char="-",
            need_module_log=False,
        )

    assert result is expected
    assert isolated_sys_path == [str(tmp_path)]
    discover.assert_called_once_with(
        "compiled_outer.compiled_inner",
        "FUNCTIONS",
        "external",
        conn_char="-",
        hook_check=None,
        need_module_log=False,
    )

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
