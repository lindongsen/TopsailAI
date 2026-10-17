"""Exercise live point_entry resource edges in an isolated child. Author: DawsonLin."""

from dataclasses import asdict
import json
from pathlib import Path
import sys


def run():
    """Call the real decode_points/execute_point path and record its public results."""
    request = json.loads(Path(sys.argv[1]).read_text())
    root = Path(request['root'])
    import topsailai
    from topsailai.hooks import point_entry

    points = point_entry.decode_points(request['config'])
    results = point_entry.execute_point(request['name'], points, payload={},
                                        internal_root=Path(request['internal_root']))
    report = {
        'results': [asdict(item) for item in results],
        'pending': len(point_entry.pending_cleanup()),
        'paths': {'package': topsailai.__file__, 'point_entry': point_entry.__file__},
    }
    (root / 'report.json').write_text(json.dumps(report))


if __name__ == '__main__':
    run()
