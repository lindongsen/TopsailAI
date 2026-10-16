"""Gherkin bindings for real Hook Point resource composition. Author: DawsonLin."""

import hashlib
import io
import json
import posixpath
from pathlib import Path
import logging
import shutil
import subprocess
import tarfile

import pytest
from pytest_bdd import given, parsers, then, when

from tests.bdd.hook_point_resource_harness import BASELINE, WORKSPACE, ResourceScenario
from tests.bdd.temp_storage import BDDTempStorage


@pytest.fixture(scope='session')
def hook_resource_snapshot():
    """Freeze the committed complete package once without including dirty neighbors."""
    storage = BDDTempStorage(WORKSPACE / '.tmp/hook-point-bdd')
    root = storage.create_directory('snapshot-')
    archive = subprocess.check_output(['git', '-C', str(WORKSPACE), 'archive', BASELINE])
    with tarfile.open(fileobj=io.BytesIO(archive)) as bundle:
        members = [m for m in bundle.getmembers() if (m.isfile() or m.isdir())
                   and not any(part in {'.git', '.tmp', '__pycache__', '.env', '.env.local'}
                               for part in Path(m.name).parts)]
        bundle.extractall(root, members=members, filter='data')
        for member in bundle.getmembers():
            if not member.issym() or member.linkname.startswith('/'):
                continue
            target = posixpath.normpath(posixpath.join(posixpath.dirname(member.name), member.linkname))
            if target.startswith('../'):
                continue
            source = root / target
            if source.is_file():
                shutil.copyfile(source, root / member.name)
    # git archive from a subdirectory produces that directory as its root.
    assert (root / 'hooks/point_entry.py').is_file()
    manifest = {str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest()
                for p in root.rglob('*') if p.is_file()}
    (root.parent / (root.name + '-manifest.json')).write_text(json.dumps({'commit': BASELINE, 'files': manifest}, indent=2))
    yield root
    storage.cleanup()


@pytest.fixture
def hook_resource_case(hook_resource_snapshot):
    """Always close scenario processes and remove only the owned copied tree."""
    storage = BDDTempStorage(WORKSPACE / '.tmp/hook-point-bdd')
    root = storage.create_directory('scenario-')
    neighbor = root.parent / (root.name + '-neighbor')
    neighbor.write_text('unrelated sentinel')
    context = ResourceScenario(root, hook_resource_snapshot)
    try:
        yield context
    finally:
        finish_resource_case(context, storage, neighbor)


def finish_resource_case(context, storage, neighbor):
    """Delete resources only after successful process settlement and evidence capture."""
    context.close()
    storage.cleanup()
    assert not context.root.exists()
    assert neighbor.read_text() == 'unrelated sentinel'
    neighbor.unlink()
    logging.getLogger(__name__).info('deleted owned sentinel %s', neighbor)


@given(parsers.parse('resource counts {case_id} MI={mi:d} ME={me:d} SI={si:d} SE={se:d}'))
def counts(hook_resource_case, case_id, mi, me, si, se):
    """Build exactly the requested four-source cardinalities."""
    hook_resource_case.case = case_id
    hook_resource_case.matrix((mi, me, si, se))


@given(parsers.parse('external selection {group} uses {form}'))
def shape(hook_resource_case, group, form):
    """Build one explicit configuration-shape acceptance example."""
    hook_resource_case.case = f'{group}-{form}'
    hook_resource_case.shape(group, form)


@given(parsers.parse('boundary fixture {case}'))
def boundary(hook_resource_case, case):
    """Build one named negative or lifecycle example."""
    hook_resource_case.case = case
    hook_resource_case.edge(case)


@when('the business invokes the public named Hook Point')
def invoke(hook_resource_case):
    """Run a real fresh host process with environment-only configuration."""
    hook_resource_case.execute()


@then('exact resource evidence and ordered results match the declaration')
def verify(hook_resource_case):
    """Check actual execution, ordering, input and settled process ownership."""
    hook_resource_case.verify()
