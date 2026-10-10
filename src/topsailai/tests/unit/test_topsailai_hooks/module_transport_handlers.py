"""Child-only Module transport canaries. Author: DawsonLin."""
import os
import subprocess
import sys
import time
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


def main(mode, value=None, *, marker=None, **kwargs):
    """Exercise normal returns, failures, descendants and input ownership."""
    Path(os.environ['TMPDIR'], 'invoke.pid').write_text(str(os.getpid()))
    if mode == 'awaitable':
        async def answer():
            """Yield a normal value on the worker-owned event loop."""
            return 'awaited'
        return answer()
    if mode == 'echo':
        return {'value': value, 'kwargs': kwargs, 'pid': os.getpid()}
    if mode == 'return':
        return value
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
