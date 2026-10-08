"""Owned temporary-directory management for the root BDD suite."""

from __future__ import annotations

import logging
import shutil
import tempfile
from collections.abc import Callable
from pathlib import Path

logger = logging.getLogger("tests.bdd.temp_storage")

WORKSPACE = Path(__file__).resolve().parents[2]
BDD_TEMP_ROOT = WORKSPACE / ".tmp" / "bdd"


class BDDTempCleanupError(RuntimeError):
    """Report every owned directory that could not be removed."""

    def __init__(self, failures: list[tuple[Path, Exception]]) -> None:
        self.failures = tuple(failures)
        paths = ", ".join(str(path) for path, _error in failures)
        super().__init__(f"failed to remove owned BDD temporary directories: {paths}")


class BDDTempStorage:
    """Create and clean scenario-owned directories under one fixed workspace root."""

    def __init__(self, root: Path = BDD_TEMP_ROOT) -> None:
        self.root = root.resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self._owned: list[Path] = []

    def create_directory(self, prefix: str) -> Path:
        """Create one owned directory without falling back to another temp root."""
        directory = Path(tempfile.mkdtemp(prefix=prefix, dir=self.root))
        self._owned.append(directory)
        return directory

    def cleanup(
        self,
        remove_tree: Callable[[Path], None] = shutil.rmtree,
    ) -> None:
        """Try every owned cleanup and report all failures after successful removals."""
        failures: list[tuple[Path, Exception]] = []
        retained: list[Path] = []
        for directory in reversed(self._owned):
            try:
                remove_tree(directory)
            except FileNotFoundError as error:
                if self._owned_root_is_absent(directory):
                    logger.info(
                        "owned BDD temporary directory already absent: [%s]", directory
                    )
                    continue
                retained.append(directory)
                failures.append((directory, error))
                logger.error(
                    "failed to remove owned BDD temporary directory: [%s] (%s)",
                    directory,
                    type(error).__name__,
                )
            except Exception as error:  # noqa: BLE001 - aggregate cleanup failures
                retained.append(directory)
                failures.append((directory, error))
                logger.error(
                    "failed to remove owned BDD temporary directory: [%s] (%s)",
                    directory,
                    type(error).__name__,
                )
            else:
                logger.info("removed owned BDD temporary directory: [%s]", directory)
        self._owned = list(reversed(retained))
        if failures:
            raise BDDTempCleanupError(failures)

    @staticmethod
    def _owned_root_is_absent(directory: Path) -> bool:
        """Confirm that a missing-path error refers to the owned root itself."""
        try:
            directory.lstat()
        except FileNotFoundError:
            return True
        except OSError:
            return False
        return False
