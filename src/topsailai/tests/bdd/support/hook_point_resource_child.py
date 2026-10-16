"""Exercise the public entry inside an isolated committed package. Author: DawsonLin."""

import ctypes
from dataclasses import asdict
import json
import os
from pathlib import Path
import sys
import time


def run():
    """Call the real point, recording reports independently from plugin output."""
    request = json.loads(Path(sys.argv[1]).read_text())
    root = Path(request['root'])
    # Adopt owned descendants so the test can reap them rather than leave zombies.
    if request['mode'] == 'descendant':
        assert ctypes.CDLL(None).prctl(36, 1, 0, 0, 0) == 0
    import topsailai
    from topsailai.hooks import point_entry
    from topsailai.hooks.points.workspace import before_input_message as point
    from topsailai.workspace import input_tool

    rounds = []
    input_value = None
    for number in range(request['rounds']):
        os.environ['HOOK_BDD_INVOCATION'] = str(number)
        if number and request['mode'] == 'snapshot':
            os.environ['TOPSAILAI_HOOK_POINTS'] = 'invalid-after-snapshot'
        if number and request['mode'] == 'membership':
            action = request['mutations'][number - 1]
            path = Path(action['path'])
            if action['action'] == 'add':
                path.write_text(action['content'])
            else:
                path.unlink()
                print('deleted owned resource', path, flush=True)
        if request['mode'].startswith('input'):
            def read_input(*args):
                """Assert the actual checkpoint has finished before acquiring input."""
                events = [json.loads(line) for line in (root / 'trace.jsonl').read_text().splitlines()]
                assert [e['label'] for e in events if e['phase'] == 'start'] == request['expected'][0]
                assert events[-1]['phase'] == 'finish'
                with (root / 'trace.jsonl').open('a') as stream:
                    stream.write(json.dumps({'phase': 'read_input', 'reader': request['mode']}) + '\n')
                return 'input-sentinel'
            if request['mode'] == 'input_multi':
                input_tool.input_multi_line = read_input
            else:
                input_tool.input_one_line = read_input
            input_value = input_tool.input_message()
            rounds.append([])
        else:
            rounds.append([asdict(item) for item in point.hook__workspace__before__input_message()])
    if request['mode'] == 'descendant':
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            try:
                pid, _ = os.waitpid(-1, os.WNOHANG)
            except ChildProcessError:
                break
            if pid == 0:
                time.sleep(.01)
        else:
            raise AssertionError('owned descendant was not reaped')
    report = {'rounds': rounds, 'input': input_value,
              'pending': len(point_entry.pending_cleanup()),
              'paths': [topsailai.__file__, point_entry.__file__, point.__file__, input_tool.__file__]}
    (root / 'report.json').write_text(json.dumps(report))


if __name__ == '__main__':
    run()
