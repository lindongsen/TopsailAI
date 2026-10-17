"""Owned live-tree fixtures for point_entry resource edge BDD. Author: DawsonLin."""

import json
import logging
import os
from pathlib import Path
import subprocess
import sys

NAME = 'hook__workspace__before__input_message'
WORKSPACE = Path(__file__).resolve().parents[2]
SOURCE_IMPORT_ROOT = WORKSPACE.parent


class ResourceEdgeScenario:
    """Own one live point tree, its symlink/ordering fixtures and real invocation evidence."""

    def __init__(self, root):
        """Create a private external resource tree that never edits the real point directory."""
        self.root = root
        self.internal_root = root / 'points'
        self.internal_root.mkdir(parents=True)
        self.modules = root / 'external-modules'
        self.modules.mkdir(parents=True)
        self.case = None
        self.config = {NAME: {}}
        self.expected = []
        self.diagnostic = None
        self.process = None
        self.report = None
        self.logs = ''

    def write_source(self, path, body='def main():\n    return None\n'):
        """Write one direct source-module fixture into the private external tree."""
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(body, encoding='utf-8')
        return path

    def prepare(self, case):
        """Build each approved resource edge with explicit expected effects."""
        self.case = case
        if case == 'symlink-inside':
            target = self.write_source(self.root / 'targets' / 'real.py')
            link = self.modules / 'link_inside.py'
            link.symlink_to(target)
            self.config[NAME]['modules'] = str(self.modules)
            self.expected = [('module', 'link_inside.py', 'success')]
        elif case == 'symlink-escape':
            target = self.write_source(self.root / 'outside' / 'escaped.py')
            link = self.modules / 'link_escape.py'
            link.symlink_to(target)
            self.config[NAME]['modules'] = str(self.modules)
            self.expected = [('module', 'link_escape.py', 'success')]
        elif case == 'symlink-directory':
            (self.root / 'sub').mkdir()
            link = self.modules / 'link_dir'
            link.symlink_to(self.root / 'sub')
            self.config[NAME]['modules'] = str(self.modules)
            self.expected = []
        elif case == 'ordering-logical':
            self.write_source(self.modules / 'a-b.py')
            (self.modules / 'a.so').write_bytes(b'\x7fELF')
            self.config[NAME]['modules'] = str(self.modules)
            self.expected = [('module', 'a-b.py', 'success'), ('module', 'a.so', 'error')]
        else:
            raise AssertionError(case)

    def execute(self):
        """Run the real decode_points/execute_point path against the live working tree."""
        request = {'root': str(self.root), 'name': NAME, 'config': self.config,
                   'internal_root': str(self.internal_root)}
        (self.root / 'request.json').write_text(json.dumps(request))
        env = {key: os.environ[key] for key in ('PATH', 'LANG', 'LD_LIBRARY_PATH') if key in os.environ}
        home = self.root / 'home'
        home.mkdir()
        env.update(HOME=str(home), TOPSAILAI_HOME=str(home), TMPDIR=str(self.root),
                   PYTHONPATH=str(SOURCE_IMPORT_ROOT), PYTHONDONTWRITEBYTECODE='1',
                   TOPSAILAI_EVENTS_ENABLED='0', TOPSAILAI_AUTO_SESSION_NAME_ENABLED='0',
                   TOPSAILAI_DISABLE_ROOT_LOGGER_CONFIG='1', NO_COLOR='1')
        child = WORKSPACE / 'tests/bdd/support/point_entry_resource_edges_child.py'
        with (self.root / 'host.log').open('w') as log:
            self.process = subprocess.Popen([sys.executable, str(child), str(self.root / 'request.json')],
                                            cwd=self.root, env=env, stdout=log, stderr=subprocess.STDOUT)
            code = self.process.wait()
        self.logs = (self.root / 'host.log').read_text()
        assert code == 0, self.logs
        self.report = json.loads((self.root / 'report.json').read_text())

    def verify(self):
        """Assert live-tree origin, exact edge results and settled ownership."""
        assert self.report['pending'] == 0
        for path in self.report['paths'].values():
            assert Path(path).resolve().is_relative_to(WORKSPACE.resolve()), path
        observed = [(item['kind'], item['name'], item['status']) for item in self.report['results']]
        assert observed == self.expected, (observed, self.logs)
        if self.diagnostic:
            assert self.diagnostic in self.logs
        else:
            assert 'discovery failed' not in self.logs

    def close(self):
        """Settle the owned child process without leaving an orphan."""
        if self.process is None or self.process.poll() is not None:
            return
        self.process.terminate()
        try:
            self.process.wait(timeout=3)
        except subprocess.TimeoutExpired:
            self.process.kill()
            self.process.wait(timeout=3)
        logging.getLogger(__name__).info('settled resource edge child %s', self.process.pid)
