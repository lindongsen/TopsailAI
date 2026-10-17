"""Owned live-tree fixtures for point_entry Module admission BDD. Author: DawsonLin."""

import importlib.machinery
import json
import logging
import os
from pathlib import Path
import shutil
import subprocess
import sys
import sysconfig

NAME = 'hook__workspace__before__input_message'
WORKSPACE = Path(__file__).resolve().parents[2]
SOURCE_IMPORT_ROOT = WORKSPACE.parent
EXTENSION_SUFFIX = importlib.machinery.EXTENSION_SUFFIXES[0]

_EXTENSION_C = '''#include <Python.h>

static PyObject *main_entry(PyObject *self, PyObject *args, PyObject *kwargs) {
    Py_RETURN_NONE;
}

static PyMethodDef methods[] = {
    {"main", (PyCFunction)(void(*)(void))main_entry, METH_VARARGS | METH_KEYWORDS, NULL},
    {NULL, NULL, 0, NULL}
};

static struct PyModuleDef module = {
    PyModuleDef_HEAD_INIT, "MODULE_NAME", NULL, -1, methods
};

PyMODINIT_FUNC PyInit_MODULE_NAME(void) { return PyModule_Create(&module); }
'''


class AdmissionScenario:
    """Own one live point tree, its compiled artifacts and real invocation evidence."""

    def __init__(self, root):
        """Create a private point tree that never edits the real point directory."""
        self.root = root
        self.internal_root = root / 'points'
        self.modules = self.internal_root / 'workspace' / 'before_input_message' / 'modules'
        self.modules.mkdir(parents=True)
        self.case = None
        self.config = {NAME: {}}
        self.expected = []
        self.diagnostic = None
        self.process = None
        self.report = None
        self.logs = ''

    def compile_extension(self, name):
        """Build one real loadable CPython extension exposing a callable main entry."""
        compiler = shutil.which('cc')
        include_directory = sysconfig.get_paths().get('include')
        if not compiler or not include_directory:
            import pytest
            pytest.skip('C compiler or Python development headers unavailable')
        source = self.root / f'{name}.c'
        output = self.modules / f'{name}{EXTENSION_SUFFIX}'
        source.write_text(_EXTENSION_C.replace('MODULE_NAME', name), encoding='utf-8')
        completed = subprocess.run(
            [compiler, '-shared', '-fPIC', f'-I{include_directory}', str(source), '-o', str(output)],
            check=False, capture_output=True, text=True, timeout=60)
        assert completed.returncode == 0, completed.stderr
        return output

    def write_source(self, name, body='def main():\n    return None\n'):
        """Write one direct source-module fixture into the private point tree."""
        path = self.modules / name
        path.write_text(body, encoding='utf-8')
        return path

    def prepare(self, case):
        """Build each approved admission boundary with explicit expected effects."""
        self.case = case
        if case == 'compiled':
            self.compile_extension('compiled_plugin')
            self.expected = [('module', f'compiled_plugin{EXTENSION_SUFFIX}', 'success')]
        elif case == 'duplicate-logical':
            self.write_source('same.py')
            self.compile_extension('same')
            self.expected = []
            self.diagnostic = 'discovery failed'
        elif case == 'source-and-init':
            self.write_source('plain.py')
            self.write_source('__init__.py')
            self.expected = [('module', 'plain.py', 'success')]
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
        child = WORKSPACE / 'tests/bdd/support/point_entry_module_admission_child.py'
        with (self.root / 'host.log').open('w') as log:
            self.process = subprocess.Popen([sys.executable, str(child), str(self.root / 'request.json')],
                                            cwd=self.root, env=env, stdout=log, stderr=subprocess.STDOUT)
            code = self.process.wait()
        self.logs = (self.root / 'host.log').read_text()
        assert code == 0, self.logs
        self.report = json.loads((self.root / 'report.json').read_text())

    def verify(self):
        """Assert live-tree origin, exact admission results and settled ownership."""
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
        logging.getLogger(__name__).info('settled admission child %s', self.process.pid)
