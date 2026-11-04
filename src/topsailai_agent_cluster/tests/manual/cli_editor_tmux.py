#!/usr/bin/env python3
"""Verify read-only CLI editing in an isolated tmux using configured API credentials."""
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
    parser.add_argument('--exit-case', choices=['quit', 'interrupt', 'eof', 'escape'], default='quit')
    args = parser.parse_args()
    workspace = Path(__file__).resolve().parents[2]
    if not args.binary.is_absolute() or not args.evidence.is_absolute() or not args.evidence.is_relative_to(workspace / '.tmp'):
        parser.error('absolute binary and workspace .tmp evidence required')
    args.evidence.mkdir(parents=True, exist_ok=False)
    base = ['tmux', '-S', str(workspace / '.tmp' / f'editor-{os.getpid()}.sock')]

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

    def keys(*values):
        """Send terminal keys and allow completed output to become observable."""
        tmux('send-keys', '-t', 'owned', *values)
        time.sleep(.25)

    def literal(value):
        """Send literal text without interpreting shell syntax or tmux key names."""
        tmux('send-keys', '-t', 'owned', '-l', '--', value)

    command = shlex.join(['python3', str(Path(__file__).with_name('cli_editor_start.py')), '--binary', str(args.binary), '--evidence', str(args.evidence)])
    tmux('new-session', '-d', '-s', 'owned', '-x', '100', '-y', '40')
    tmux('set-option', '-t', 'owned', 'remain-on-exit', 'on')
    tmux('send-keys', '-t', 'owned', '-l', '--', 'exec ' + command)
    tmux('send-keys', '-t', 'owned', 'Enter')
    try:
        wait_for('cluster>')
        literal('help'); keys('Enter'); wait_for('Current scope:')
        keys('Up')
        assert capture().rstrip().endswith('cluster> help'), capture()
        keys('Enter')
        literal('helx'); keys('BSpace'); literal('p'); keys('Enter')
        assert 'unknown command "helx"' not in capture()
        literal('x' * 8300); keys('Enter')
        wait_for('input line exceeds the maximum length')
        literal('start'); keys('Enter'); wait_for('start.endpoint>')
        keys('Up')
        assert capture().rstrip().endswith('start.endpoint>'), capture()
        literal('cancel'); keys('Enter'); wait_for('start cancelled')
        literal('start'); keys('Enter'); literal('partial'); keys('C-c')
        wait_for('interrupted')
        literal('help'); keys('Enter')
        assert 'unknown command "partial' not in capture()
        if args.exit_case == 'interrupt':
            keys('C-c')
        elif args.exit_case == 'eof':
            keys('C-d')
        elif args.exit_case == 'escape':
            keys('Escape')
        else:
            literal('quit'); keys('Enter')
        for _ in range(100):
            if (args.evidence / 'result.json').exists():
                break
            time.sleep(.1)
        result = json.loads((args.evidence / 'result.json').read_text())
        expected = {'quit': 0, 'interrupt': 130, 'eof': 0, 'escape': 2}[args.exit_case]
        assert result == {'exit': expected, 'restored': True}, result
        (args.evidence / 'pane.txt').write_text(capture())
        print('PASS history, editing, overflow rejection, wizard isolation, Ctrl-C recovery, quit and exact terminal restoration')
    finally:
        subprocess.run(base + ['kill-session', '-t', 'owned'], check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        print('Cleanup: removed owned editor tmux session; existing services untouched')


if __name__ == '__main__':
    main()
