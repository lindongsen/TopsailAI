"""Child-only loading of exact captured entries. Author: DawsonLin."""
import hashlib
import importlib.util
from importlib.machinery import ExtensionFileLoader
from pathlib import Path
from types import BuiltinFunctionType, FunctionType, ModuleType

from topsailai.hooks.contracts import ValidationError

_MAX_MODULE_BYTES = 16 * 1024 * 1024


def resolve_captured_handler(locator):
    """Validate bytes before executing source or loading a compiled extension."""
    path = Path(locator.path)
    with path.open('rb') as stream:
        content = stream.read(_MAX_MODULE_BYTES + 1)
    if len(content) > _MAX_MODULE_BYTES or hashlib.sha256(content).hexdigest() != locator.content_sha256:
        raise ValidationError('captured module content mismatch')
    if locator.kind == 'python_source':
        module = ModuleType(locator.logical_name)
        module.__file__ = locator.path
        module.__package__ = ''
        exec(compile(content, locator.path, 'exec'), module.__dict__)
    else:
        spec = importlib.util.spec_from_file_location(locator.logical_name, path)
        if spec is None or not isinstance(spec.loader, ExtensionFileLoader):
            raise ValidationError('invalid captured extension loader')
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
    handler = ModuleType.__dict__['__dict__'].__get__(module).get('main')
    if type(handler) not in (FunctionType, BuiltinFunctionType):
        raise ValidationError('captured main must be a function')
    return handler
