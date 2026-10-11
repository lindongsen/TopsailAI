"""Bounded captured Module addresses, independent of host imports. Author: DawsonLin."""
from dataclasses import dataclass
from pathlib import Path

from topsailai.hooks.contracts import ValidationError
from topsailai.hooks.module_invocation_protocol import build_module_request, parse_module_request
from topsailai.hooks.validation import freeze_json
from topsailai.hooks.worker_protocol import ProtocolLimits

CAPTURED_MODULE_PROTOCOL_VERSION = 3


@dataclass(frozen=True, slots=True)
class CapturedModuleLocator:
    """Own an exact child address without treating it as an import reference."""
    path: str
    logical_name: str
    kind: str
    content_sha256: str

    def __post_init__(self):
        """Validate metadata shape before path or string-dependent operations."""
        if type(self.path) is not str or not self.path or len(self.path) > 32768 or '\x00' in self.path:
            raise ValidationError('invalid captured path')
        if not Path(self.path).is_absolute():
            raise ValidationError('captured path must be absolute')
        if type(self.logical_name) is not str or not self.logical_name.isidentifier():
            raise ValidationError('invalid captured logical name')
        if type(self.kind) is not str or self.kind not in ('python_source', 'python_extension'):
            raise ValidationError('invalid captured module kind')
        digest = self.content_sha256
        if type(digest) is not str or len(digest) != 64 or any(c not in '0123456789abcdef' for c in digest):
            raise ValidationError('invalid captured module digest')


def build_captured_module_request(*, locator, limits=ProtocolLimits(), **fields):
    """Extend a validated v2 invocation within the same aggregate request budget."""
    if type(locator) is not CapturedModuleLocator:
        raise ValidationError('invalid captured locator record')
    wire = build_module_request(limits=limits, **fields)
    wire['protocol_version'] = CAPTURED_MODULE_PROTOCOL_VERSION
    wire['captured'] = dict(path=locator.path, logical_name=locator.logical_name,
                            kind=locator.kind, content_sha256=locator.content_sha256)
    parse_captured_module_request(wire, limits=limits)
    return wire


def parse_captured_module_request(value, *, limits=ProtocolLimits()):
    """Detach all fields before adapting the exact legacy invocation envelope."""
    safe = freeze_json(value, max_bytes=limits.request_bytes)
    if type(safe) is not dict or type(safe.get('protocol_version')) is not int or safe['protocol_version'] != 3:
        raise ValidationError('invalid captured module version')
    raw = safe.pop('captured', None)
    if type(raw) is not dict or set(raw) != {'path', 'logical_name', 'kind', 'content_sha256'}:
        raise ValidationError('invalid captured module envelope')
    locator = CapturedModuleLocator(**raw)
    safe['protocol_version'] = 2
    parsed = parse_module_request(safe, limits=limits)
    if parsed[2].split(':')[0].split('.')[-1] != locator.logical_name:
        raise ValidationError('uncorrelated captured logical name')
    return (*parsed, locator)
