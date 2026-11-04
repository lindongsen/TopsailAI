"""Build owned representative Cython discovery artifacts. Author: DawsonLin."""

from __future__ import annotations

import logging
import os
from pathlib import Path
import shutil
import subprocess
import stat
from collections.abc import Sequence

from topsailai.utils.env_tool import resolve_python_interpreter


logger = logging.getLogger(__name__)
EXCLUDED = {
    "tests", "scripts", "docs", "features", "issues", "bin", "__pycache__",
    "build", "dist", "node_modules",
}
BUILD_SCRIPT = '''
from pathlib import Path
import sys
from Cython.Build import cythonize
from setuptools import Extension, setup

root = Path.cwd()
sources = []
for package in sys.argv[1:]:
    sources.extend(sorted((root / package.replace(".", "/")).glob("*.py")))
extensions = [Extension(".".join(path.relative_to(root).with_suffix("").parts),
                        [str(path)]) for path in sources if path.name != "__init__.py"]
sys.argv = [sys.argv[0], "build_ext", "--inplace"]
setup(name="compiled-discovery-fixture", ext_modules=cythonize(
    extensions, compiler_directives={"language_level": 3, "annotation_typing": False},
    build_dir=str(root / "generated")))
'''


def _ignored(directory: str, names: list[str]) -> set[str]:
    """Keep hidden state, caches, test trees and prior extensions out of copies."""
    ignored = set()
    for name in names:
        mode = (Path(directory) / name).lstat().st_mode
        excluded = name.startswith(".") or name in EXCLUDED
        artifact = name.endswith((".pyc", ".so", ".pyd"))
        if excluded or artifact or not (stat.S_ISREG(mode) or stat.S_ISDIR(mode)):
            ignored.add(name)
    return ignored


def build_compiled_package(
    workspace: Path, build_root: Path, packages: Sequence[str], log_path: Path,
) -> Path:
    """Compile representative real modules and remove only copied source siblings."""
    uv = shutil.which("uv")
    if uv is None:
        raise RuntimeError("uv is required to prepare isolated Cython build dependencies")
    package_root = build_root / "topsailai"
    shutil.copytree(workspace, package_root, ignore=_ignored)
    script = build_root / "build_fixture.py"
    script.write_text(BUILD_SCRIPT, encoding="utf-8")
    env = os.environ.copy()
    env.pop("PYTHONPATH", None)
    env.setdefault("UV_HTTP_TIMEOUT", "120")
    env.update({
        "UV_CACHE_DIR": str(build_root / "uv-cache"),
        "TMPDIR": str(build_root / "tmp"),
        "TEMP": str(build_root / "tmp"),
        "TMP": str(build_root / "tmp"),
        "PYTHONDONTWRITEBYTECODE": "1",
    })
    (build_root / "tmp").mkdir()
    command = [uv, "run", "--no-project", "--python", resolve_python_interpreter(),
               "--with", "Cython>=3,<4", "--with", "setuptools>=75",
               "python", "-B", str(script), *packages]
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("w", encoding="utf-8") as log:
        log.write(f"Command: {command!r}\n")
        log.flush()
        result = subprocess.run(command, cwd=build_root, env=env, stdout=log,
                                stderr=subprocess.STDOUT, check=False)
    if result.returncode:
        raise RuntimeError(f"compiled fixture build failed ({result.returncode}); see {log_path}")
    # Publish extension-only inventories only after the complete build succeeds.
    import importlib.machinery
    for package in packages:
        directory = build_root.joinpath(*package.split("."))
        for source in directory.glob("*.py"):
            if source.name == "__init__.py":
                continue
            if not any(source.with_name(source.stem + suffix).is_file()
                       for suffix in importlib.machinery.EXTENSION_SUFFIXES):
                raise RuntimeError(f"build did not produce an extension for {source}")
            source.unlink()
            logger.info("deleted compiled fixture source sibling: %s", source)
    return build_root
