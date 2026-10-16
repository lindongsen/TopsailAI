"""Owned real-process fixtures for generic Hook Point BDD. Author: DawsonLin."""

import json
import logging
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import time

NAME = 'hook__workspace__before__input_message'
BASELINE = '7c6eae69b65757528afd227646858af57dcd1a5a'
WORKSPACE = Path(__file__).resolve().parents[2]
NAMES = {'MI': ['b_internal.py', 'd_internal.py'], 'ME': ['A_external.py', 'c_external.py'],
         'SI': ['b_internal.sh', 'd_internal.sh'], 'SE': ['A_external.sh', 'c_external.sh']}
ORDER = ['ME1', 'MI1', 'ME2', 'MI2', 'SE1', 'SI1', 'SE2', 'SI2']


def identity(pid):
    """Read Linux process identity without granting signaling authority to old PIDs."""
    try:
        tail = Path(f'/proc/{pid}/stat').read_text().rsplit(')', 1)[1].split()
        return tail[19], tail[0]
    except FileNotFoundError:
        return None


class ResourceScenario:
    """Own one copied package, resource inventory and real invocation evidence."""

    def __init__(self, root, snapshot):
        """Copy the frozen source and initialize a completely private fixture tree."""
        self.root = root
        self.package = root / 'src' / 'topsailai'
        shutil.copytree(snapshot, self.package)
        self.local = self.package / 'hooks/points/workspace/before_input_message'
        self.config = {NAME: {}}
        self.expected = [[]]
        self.statuses = None
        self.mode = 'normal'
        self.rounds = 1
        self.diagnostic = None
        self.resources = []
        self.mutations = []
        self.process = None
        self.report = None
        self.logs = ''
        self.known = []
        self.result_labels = None

    def source(self, label, kind, behavior='normal'):
        """Generate real plugins that close each evidence write immediately."""
        prelude = f'''import json, os, time, subprocess, sys
from pathlib import Path
ROOT = Path({str(self.root)!r})
LABEL = {label!r}
KIND = {kind!r}
def emit(phase):
    """Persist exact process identity and phase for one resource."""
    stat = Path('/proc/self/stat').read_text().rsplit(')', 1)[1].split()
    event = dict(label=LABEL, kind=KIND, origin=LABEL[:2], name=Path(__file__).name,
                 scenario_id=ROOT.name, invocation_id=os.environ['HOOK_BDD_INVOCATION'],
                 pid=os.getpid(), ppid=os.getppid(), start_identity=stat[19], phase=phase)
    with (ROOT / 'trace.jsonl').open('a') as stream:
        stream.write(json.dumps(event) + '\\n')
def main():
    """Execute the scenario-owned resource body."""
    emit('start')
'''
        if behavior == 'error':
            body = "    raise RuntimeError('fixture ordinary failure')\n"
        elif behavior == 'timeout':
            body = '    time.sleep(60)\n'
        elif behavior == 'descendant':
            child = "import os,time,json; from pathlib import Path; p=Path('/proc/self/stat').read_text().rsplit(')',1)[1].split(); Path(" + repr(str(self.root / 'descendant.json')) + ").write_text(json.dumps(dict(pid=os.getpid(), start_identity=p[19]))); time.sleep(60)"
            body = f"    subprocess.Popen([sys.executable, '-c', {child!r}])\n    deadline = time.monotonic() + 3\n    while not (ROOT / 'descendant.json').exists():\n        if time.monotonic() > deadline: raise RuntimeError('descendant not ready')\n        time.sleep(.01)\n    emit('finish')\n"
        else:
            body = "    emit('finish')\n"
        return (f'#!{sys.executable}\n' if kind == 'script' else '') + prelude + body + ('main()\n' if kind == 'script' else '')

    def add(self, group, index=1, name=None, directory=None, behavior='normal', executable=True):
        """Create one inventory member without ever editing the real point directory."""
        kind = 'module' if group[0] == 'M' else 'script'
        folder = directory or (self.local / (kind + 's') if group[1] == 'I'
                               else self.root / ('external-' + kind + 's'))
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / (name or NAMES[group][index - 1])
        path.write_text(self.source(f'{group}{index}', kind, behavior))
        path.chmod(0o755 if kind == 'script' and executable else 0o644)
        self.resources.append({'path': str(path), 'label': f'{group}{index}', 'kind': kind,
                               'permission': oct(path.stat().st_mode & 0o777)})
        if group[1] == 'E':
            self.config[NAME][kind + 's'] = str(folder)
        return path

    def matrix(self, counts):
        """Create inverse-order members and derive expectations from fixed declarations."""
        selected = []
        for group, count in zip(('MI', 'ME', 'SI', 'SE'), counts):
            for index in reversed(range(1, count + 1)):
                self.add(group, index)
                selected.append(f'{group}{index}')
        self.expected = [[label for label in ORDER if label in selected]]

    def shape(self, group, form):
        """Select files or folders explicitly and leave an unselected side-effect canary."""
        count = 1 if form in ('file', 'single_list') else 2
        files = [self.add(group, i, directory=self.root / f'choice-{i}') for i in range(1, count + 1)]
        self.add(group, 3, name='unselected.py' if group == 'ME' else 'unselected.sh',
                 directory=self.root / 'unselected')
        values = {'file': str(files[0]), 'single_list': [str(files[0])],
                  'files': [str(p) for p in reversed(files)],
                  'folders': [str(p.parent) for p in reversed(files)],
                  'mixed': [str(files[-1].parent), str(files[0])]}
        self.config[NAME]['modules' if group == 'ME' else 'scripts'] = values[form]
        self.expected = [[f'{group}{i}' for i in range(1, count + 1)]]

    def edge(self, case):
        """Prepare each approved boundary independently, retaining explicit expected effects."""
        if case.startswith('duplicate'):
            _, group, placement = case.split('-')
            first = self.add(group, name='same.py')
            other = ('MI' if group == 'ME' else 'SI') if placement == 'internal' else group
            second = self.add(other, name='same.py', directory=None if placement == 'internal' else self.root / 'second')
            if placement == 'external':
                self.config[NAME]['modules' if group == 'ME' else 'scripts'] = [str(first.parent), str(second.parent)]
            self.add('SI' if group == 'ME' else 'MI')
            self.diagnostic = 'discovery failed'
        elif case == 'cross_kind':
            self.add('MI', name='same.py')
            self.add('SE', name='same.py')
            self.expected = [['MI1', 'SE1']]
        elif case.startswith('permission'):
            group = case.split('-')[1]
            self.add(group, executable=False)
            self.add(group, 2)
            self.expected = [[group + '2']]
        elif case.startswith('missing'):
            self.matrix((1, 0, 1, 0))
            self.config[NAME][case.split('-')[1]] = str(self.root / 'missing')
            self.expected = [[]]
            self.diagnostic = 'discovery failed'
        elif case == 'empty_dirs':
            for kind in ('modules', 'scripts'):
                (self.local / kind).mkdir()
                folder = self.root / ('external-' + kind)
                folder.mkdir()
                self.config[NAME][kind] = str(folder)
        elif case == 'unset':
            self.config = None
        elif case.startswith('direct'):
            group = case.split('-')[1]
            direct = self.add(group)
            self.add(group, 2, directory=direct.parent / 'nested')
            if group == 'ME':
                self.add(group, 3, name='__init__.py', directory=direct.parent)
                self.add(group, 4, name='ignored.txt', directory=direct.parent)
            self.config[NAME]['modules' if group == 'ME' else 'scripts'] = str(direct.parent)
            self.expected = [[group + '1']]
        elif case.startswith('config'):
            variant = case.split('-')[1]
            self.config = 'not-json' if variant == 'json' else {NAME: {'scripts': 'relative'}} if variant == 'relative' else {NAME: {'unknown': []}}
            self.diagnostic = 'initialization failed'
        elif case.startswith('failure'):
            kind = case.split('-')[1]
            self.matrix((1, 0, 1, 0))
            group = 'ME' if kind == 'module' else 'SE'
            bad = self.add(group, behavior='error')
            self.expected = [['ME1', 'MI1', 'SI1']] if group == 'ME' else [['MI1', 'SE1', 'SI1']]
            self.statuses = ['error', 'success', 'success'] if group == 'ME' else ['success', 'error', 'success']
            self.result_labels = list(self.expected[0])
            if kind == 'format':
                bad.write_text('invalid executable format\n')
                self.expected = [['MI1', 'SI1']]
        elif case == 'snapshot':
            self.matrix((1, 1, 1, 1))
            self.rounds, self.mode = 2, 'snapshot'
            self.expected *= 2
        elif case == 'membership':
            path = self.add('MI')
            extra = path.with_name(NAMES['MI'][1])
            self.mutations = [{'action': 'add', 'path': str(extra), 'content': self.source('MI2', 'module')},
                              {'action': 'remove', 'path': str(path)}]
            self.resources.append({'path': str(extra), 'label': 'MI2', 'kind': 'module', 'permission': '0o644'})
            self.expected = [['MI1'], ['MI1', 'MI2'], ['MI2']]
            self.rounds, self.mode = 3, 'membership'
        elif case.startswith('input'):
            self.matrix((1, 1, 1, 1))
            self.mode = case
        elif case.startswith('timeout'):
            group = case.split('-')[1]
            self.add(group, behavior='timeout')
            self.add('SI', name='z_sentinel.sh')
            self.expected = [[group + '1']]
            self.statuses = ['timeout']
            self.result_labels = [group + '1']
        elif case == 'descendant':
            self.add('SE', behavior='descendant')
            self.mode = 'descendant'
            self.expected = [['SE1']]
        else:
            raise AssertionError(case)

    def execute(self):
        """Launch an environment-only public invocation from the frozen package."""
        request = {'root': str(self.root), 'mode': self.mode, 'rounds': self.rounds,
                   'expected': self.expected, 'mutations': self.mutations}
        (self.root / 'request.json').write_text(json.dumps(request))
        (self.root / 'inventory.json').write_text(json.dumps(self.resources, indent=2))
        env = {key: os.environ[key] for key in ('PATH', 'LANG', 'LD_LIBRARY_PATH') if key in os.environ}
        home = self.root / 'home'
        home.mkdir()
        env.update(HOME=str(home), TOPSAILAI_HOME=str(home), TMPDIR=str(self.root),
                   PYTHONPATH=str(self.package.parent), PYTHONDONTWRITEBYTECODE='1',
                   TOPSAILAI_EVENTS_ENABLED='0', TOPSAILAI_AUTO_SESSION_NAME_ENABLED='0',
                   TOPSAILAI_DISABLE_ROOT_LOGGER_CONFIG='1', NO_COLOR='1',
                   TOPSAILAI_CHAT_MULTI_LINE='1' if self.mode == 'input_multi' else '0')
        if self.config is not None:
            env['TOPSAILAI_HOOK_POINTS'] = self.config if isinstance(self.config, str) else json.dumps(self.config)
        child = WORKSPACE / 'tests/bdd/support/hook_point_resource_child.py'
        with (self.root / 'host.log').open('w') as log:
            self.process = subprocess.Popen([sys.executable, str(child), str(self.root / 'request.json')],
                                            cwd=self.root, env=env, stdout=log, stderr=subprocess.STDOUT)
            code = self.process.wait()
        self.logs = (self.root / 'host.log').read_text()
        assert code == 0, self.logs
        self.report = json.loads((self.root / 'report.json').read_text())

    def verify(self):
        """Assert real trace cardinality, order, process identity and public results."""
        trace = self.root / 'trace.jsonl'
        events = [json.loads(line) for line in trace.read_text().splitlines()] if trace.exists() else []
        for number, expected in enumerate(self.expected):
            starts = [e for e in events if e['phase'] == 'start' and e['invocation_id'] == str(number)]
            assert [e['label'] for e in starts] == expected, (events, self.logs)
            phases = [e for e in events if e.get('invocation_id') == str(number)]
            for event in starts:
                assert event['scenario_id'] == self.root.name
                assert event['pid'] != self.process.pid
                current = identity(event['pid'])
                assert current is None or current[0] != event['start_identity']
                self.known.append((event['pid'], event['start_identity']))
            unfinished = set()
            if self.statuses:
                unfinished = {label for label, status in zip(self.result_labels, self.statuses)
                              if status != 'success'}
            expected_phases = [(label, phase) for label in expected
                               for phase in (('start',) if label in unfinished else ('start', 'finish'))]
            assert [(e['label'], e['phase']) for e in phases] == expected_phases
            if not self.mode.startswith('input'):
                results = self.report['rounds'][number]
                assert [r['status'] for r in results] == (self.statuses or ['success'] * len(expected))
                declared = {r['label']: (r['kind'], Path(r['path']).name) for r in self.resources}
                labels = self.result_labels if self.result_labels is not None else expected
                assert [(r['kind'], r['name']) for r in results] == [declared[label] for label in labels]
        assert self.report['pending'] == 0
        for loaded in self.report['paths']:
            assert Path(loaded).is_relative_to(self.package), loaded
        if self.diagnostic:
            assert self.diagnostic in self.logs
            if 'duplicate' in self.case:
                assert 'Duplicate Hook resource name' in self.logs
        else:
            assert 'discovery failed' not in self.logs and 'initialization failed' not in self.logs
        if self.mode.startswith('input'):
            assert self.report['input'] == 'input-sentinel'
            assert [e['reader'] for e in events if e['phase'] == 'read_input'] == [self.mode]
        descendant = self.root / 'descendant.json'
        if descendant.exists():
            data = json.loads(descendant.read_text())
            current = identity(data['pid'])
            assert current is None or current[0] != data['start_identity'], data

    def _save_evidence(self, failures):
        """Copy every available diagnostic before any fallible process cleanup."""
        evidence = self.root.parent / 'evidence'
        try:
            evidence.mkdir(exist_ok=True)
        except Exception as error:
            failures.append(error)
            return
        for name in ('trace.jsonl', 'descendant.json', 'report.json', 'host.log',
                     'inventory.json', 'request.json'):
            try:
                source = self.root / name
                if source.exists():
                    shutil.copyfile(source, evidence / (self.root.name + '-' + name))
            except Exception as error:
                failures.append(error)

    def _stop_host(self):
        """Settle the owned Popen even if graceful termination times out."""
        if self.process is None or self.process.poll() is not None:
            return
        try:
            self.process.terminate()
            self.process.wait(timeout=3)
        except Exception:
            # Popen retains child ownership until wait confirms its exit.
            if self.process.poll() is None:
                self.process.kill()
            self.process.wait(timeout=3)
            raise

    def _owned_identities(self, failures):
        """Collect all recorded plugin and descendant identities despite malformed entries."""
        owned = set(self.known)
        trace = self.root / 'trace.jsonl'
        try:
            lines = trace.read_text().splitlines() if trace.exists() else []
        except Exception as error:
            failures.append(error)
            lines = []
        for line in lines:
            try:
                event = json.loads(line)
                if 'pid' in event:
                    owned.add((event['pid'], event['start_identity']))
            except Exception as error:
                failures.append(error)
        try:
            descendant = self.root / 'descendant.json'
            if descendant.exists():
                event = json.loads(descendant.read_text())
                owned.add((event['pid'], event['start_identity']))
        except Exception as error:
            failures.append(error)
        return sorted(owned)

    @staticmethod
    def _settle_identity(pid, start):
        """Kill only a matching recorded identity and confirm its bounded retirement."""
        current = identity(pid)
        if current is None or current[0] != start:
            return False
        if current[1] != 'Z':
            try:
                os.kill(pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        deadline = time.monotonic() + 3
        while True:
            try:
                os.waitpid(pid, os.WNOHANG)
            except ChildProcessError:
                pass
            current = identity(pid)
            if current is None or current[0] != start:
                return True
            if time.monotonic() >= deadline:
                raise AssertionError(f'owned process exit unconfirmed: {pid} start={start}')
            time.sleep(.01)

    def close(self):
        """Preserve evidence first, settle every owned process, then aggregate failures."""
        failures = []
        self._save_evidence(failures)
        try:
            self._stop_host()
        except Exception as error:
            failures.append(error)
        # A stopped host can have produced more identity records during shutdown.
        for pid, start in self._owned_identities(failures):
            try:
                if self._settle_identity(pid, start):
                    failures.append(AssertionError(f'leaked owned process recovered: {pid} start={start}'))
            except Exception as error:
                failures.append(error)
        self._save_evidence(failures)
        if failures:
            logging.getLogger(__name__).error('Cleanup incomplete; retained scenario %s: %s',
                                             self.root, [repr(e) for e in failures])
            raise ExceptionGroup('Hook BDD cleanup failed; scenario retained', failures)
        logging.getLogger(__name__).info('Owned scenario inspected: %s', self.root)
