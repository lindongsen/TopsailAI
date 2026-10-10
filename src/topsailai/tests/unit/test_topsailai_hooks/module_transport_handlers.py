"""Child-only Module transport canaries. Author: DawsonLin."""
import os
import subprocess
import sys
import time
import types
from pathlib import Path

Path(os.environ['TMPDIR'], 'import.pid').write_text(str(os.getpid()))


class Hostile:
    """Record any forbidden observation of an opaque return."""
    def observed(self, *args, **kwargs):
        """Fail visibly if any payload protocol is invoked."""
        Path(os.environ['TMPDIR'], 'observed').write_text('unsafe')
        raise RuntimeError('opaque payload observed')
    __repr__ = __str__ = __bool__ = __eq__ = __hash__ = observed
    __reduce__ = __reduce_ex__ = __deepcopy__ = observed


class HostileClass(Hostile):
    """Reject even class spoofing observations of a normal opaque return."""
    @property
    def __class__(self):
        """Record forbidden instance class inspection."""
        return self.observed()


class HostileMeta(type):
    """Reject dynamic class-level protocol inspection."""
    def __getattribute__(cls, name):
        """Record class observations while allowing Python's implicit slots."""
        Path(os.environ['TMPDIR'], 'observed').write_text('metaclass')
        raise RuntimeError('metaclass observed')

    @property
    def __mro__(cls):
        """Reject descriptor-based dynamic MRO access too."""
        Path(os.environ['TMPDIR'], 'observed').write_text('mro descriptor')
        raise RuntimeError('metaclass MRO observed')


class HostileMetaReturn(HostileClass, metaclass=HostileMeta):
    """Remain an opaque normal return even with a hostile metaclass."""


class CustomAwaitable(HostileClass):
    """Complete a real await protocol despite hostile instance class inspection."""
    def __await__(self):
        """Run only after the worker has selected actual awaiting."""
        if False:
            yield
        return 'awaited'


class InheritedAwaitable(CustomAwaitable):
    """Exercise inherited special-method resolution."""


class ShadowedAwaitable(CustomAwaitable):
    """An explicit None masks the inherited await protocol."""
    __await__ = None


@types.coroutine
def generator_answer():
    """Supply a native iterable-coroutine generator."""
    if False:
        yield
    return 'awaited'


def main(mode, value=None, *, marker=None, **kwargs):
    """Exercise normal returns, failures, descendants and input ownership."""
    Path(os.environ['TMPDIR'], 'invoke.pid').write_text(str(os.getpid()))
    if mode == 'awaitable':
        async def answer():
            """Yield a normal value on the worker-owned event loop."""
            return 'awaited'
        return answer()
    if mode == 'generator_awaitable':
        return generator_answer()
    if mode == 'plain_generator':
        return (item for item in ())
    if mode == 'custom_awaitable':
        return InheritedAwaitable()
    if mode == 'shadowed_awaitable':
        return ShadowedAwaitable()
    if mode == 'await_error':
        async def failed():
            """Raise from actual child-owned awaiting rather than classification."""
            raise RuntimeError('private await exception')
        return failed()
    if mode == 'echo':
        return {'value': value, 'kwargs': kwargs, 'pid': os.getpid()}
    if mode == 'return':
        return value
    if mode == 'hostile_meta':
        return HostileMetaReturn()
    if mode == 'hostile_class':
        return HostileClass()
    if mode == 'hostile':
        return Hostile()
    if mode == 'nested':
        return {'opaque': Hostile()}
    if mode == 'cycle':
        result = []
        result.append(result)
        return result
    if mode == 'oversize':
        return 'x' * 100000
    if mode == 'mutate':
        value.append('child')
        raise RuntimeError('private exception')
    if mode == 'error':
        raise RuntimeError('private exception')
    if mode in ('descendant', 'sleep'):
        child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'])
        Path(os.environ['TMPDIR'], 'descendant.pid').write_text(str(child.pid))
        if mode == 'sleep':
            time.sleep(60)
        return value
    raise RuntimeError('unknown fixture mode')
