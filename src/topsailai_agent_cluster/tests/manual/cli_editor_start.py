#!/usr/bin/env python3
"""Launch a prebuilt CLI and record exact terminal restoration without exposing secrets."""
import argparse
import json
import os
from pathlib import Path
import signal
import subprocess
import termios


def main():
    """Keep startup independent of terminal interaction and assertions."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--binary', required=True, type=Path)
    parser.add_argument('--evidence', required=True, type=Path)
    args = parser.parse_args()
    if not args.binary.is_absolute() or not args.evidence.is_absolute():
        parser.error('absolute binary and evidence paths required')
    workspace = Path(__file__).resolve().parents[2]
    if not args.evidence.is_relative_to(workspace / '.tmp'):
        parser.error('evidence must be under workspace .tmp')
    args.evidence.mkdir(parents=True, exist_ok=True)
    before = termios.tcgetattr(0)
    signal.signal(signal.SIGINT, lambda *_: None)
    result = subprocess.run([str(args.binary), 'interactive'], check=False)
    restored = termios.tcgetattr(0) == before
    (args.evidence / 'result.json').write_text(json.dumps({'exit': result.returncode, 'restored': restored}))
    if not restored:
        termios.tcsetattr(0, termios.TCSANOW, before)
        print('Restored task terminal after detected mismatch', flush=True)
    return result.returncode


if __name__ == '__main__':
    raise SystemExit(main())
