#!/usr/bin/env python3
"""Verify that a long interactive input stays visible as a wrapped block."""
import argparse
import json
import os
from pathlib import Path
import shlex
import subprocess
import time


def main():
    """Drive only the owned tmux and capture reproducible terminal evidence."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--binary', required=True, type=Path)
    parser.add_argument('--evidence', required=True, type=Path)
    args = parser.parse_args()
    workspace = Path(__file__).resolve().parents[2]
    if not args.binary.is_absolute() or not args.evidence.is_absolute() or not args.evidence.is_relative_to(workspace / '.tmp'):
        parser.error('absolute binary and workspace .tmp evidence required')
    args.evidence.mkdir(parents=True, exist_ok=False)
    base = ['tmux', '-S', str(workspace / '.tmp' / f'multiline-{os.getpid()}.sock')]

    def tmux(*parts):
        """Invoke a command against this test's dedicated socket only."""
        return subprocess.check_output(base + list(parts), text=True)

    def capture():
        """Capture current terminal evidence without token-bearing process arguments."""
        return tmux('capture-pane', '-p', '-S', '-1000', '-t', 'owned')

    def wait_for(text):
        """Wait for visible readiness rather than sending to an unready terminal."""
        for _ in range(150):
            pane = capture()
            if text in pane:
                return pane
            time.sleep(.1)
        raise AssertionError(f'missing {text!r}: {capture()}')

    def literal(value):
        """Send literal text without interpreting shell syntax or tmux key names."""
        tmux('send-keys', '-t', 'owned', '-l', '--', value)
        time.sleep(.4)

    def keys(*values):
        """Send terminal keys and allow completed output to become observable."""
        tmux('send-keys', '-t', 'owned', *values)
        time.sleep(.25)

    command = shlex.join(['python3', str(Path(__file__).with_name('cli_editor_start.py')), '--binary', str(args.binary), '--evidence', str(args.evidence)])
    tmux('new-session', '-d', '-s', 'owned', '-x', '60', '-y', '30')
    tmux('set-option', '-t', 'owned', 'remain-on-exit', 'on')
    tmux('send-keys', '-t', 'owned', '-l', '--', 'exec ' + command)
    tmux('send-keys', '-t', 'owned', 'Enter')
    try:
        wait_for('workspace>')
        # A 200-character input on a 60-column terminal must wrap into several
        # rows, and the head of the text must remain on screen.
        head = 'HEAD-MARKER-'
        body = 'abcdefghij' * 19
        literal(head + body)
        pane = capture()
        if head not in pane:
            raise AssertionError(f'head of the long input is not visible: {pane}')
        if body[:20] not in pane:
            raise AssertionError(f'early input text is not visible: {pane}')
        rows = [line for line in pane.splitlines() if 'abcdefghij' in line or head in line]
        if len(rows) < 2:
            raise AssertionError(f'input did not wrap into multiple rows: {pane}')
        # Backspacing to empty must clear every wrapped row, leaving no stale text.
        for _ in range(len(head + body)):
            keys('BSpace')
        pane = capture()
        if 'abcdefghij' in pane or head in pane:
            raise AssertionError(f'stale input rows remain after clearing: {pane}')
        literal('quit')
        keys('Enter')
        for _ in range(100):
            if (args.evidence / 'result.json').exists():
                break
            time.sleep(.1)
        result = json.loads((args.evidence / 'result.json').read_text())
        if result != {'exit': 0, 'restored': True}:
            raise AssertionError(f'unexpected exit result: {result}')
        (args.evidence / 'pane.txt').write_text(capture())
        print('PASS long input wraps into visible rows, head stays visible, clearing leaves no stale rows')
    finally:
        subprocess.run(base + ['kill-session', '-t', 'owned'], check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        print('Cleanup: removed owned multiline tmux session; existing services untouched')


if __name__ == '__main__':
    main()
