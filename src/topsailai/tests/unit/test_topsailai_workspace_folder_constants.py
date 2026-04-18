"""
Unit tests for topsailai.workspace.folder_constants module.

This module tests the folder constants configuration for the TopsailAI system.
It verifies that all folder paths are correctly defined and follow the expected
hierarchical structure.

Author: AI
Created: 2026-04-18
"""

import unittest
from topsailai.workspace.folder_constants import (
    FOLDER_ROOT,
    FOLDER_WORKSPACE,
    FOLDER_MEMORY,
    FOLDER_LOCK,
    FOLDER_SKILL,
    FOLDER_LOG,
    FOLDER_MEMORY_STORY,
    FOLDER_WORKSPACE_TASK,
)


class TestFolderConstantsRoot(unittest.TestCase):
    """Test cases for root folder constants."""

    def test_folder_root_is_string(self):
        """Verify FOLDER_ROOT is a string type."""
        self.assertIsInstance(FOLDER_ROOT, str)

    def test_folder_root_is_not_empty(self):
        """Verify FOLDER_ROOT is not empty."""
        self.assertTrue(len(FOLDER_ROOT) > 0)

    def test_folder_root_value(self):
        """Verify FOLDER_ROOT has the expected value."""
        self.assertEqual(FOLDER_ROOT, "/topsailai")


class TestFolderConstantsLayer2(unittest.TestCase):
    """Test cases for Layer 2 (main system directories)."""

    def test_folder_workspace_is_string(self):
        """Verify FOLDER_WORKSPACE is a string type."""
        self.assertIsInstance(FOLDER_WORKSPACE, str)

    def test_folder_workspace_starts_with_root(self):
        """Verify FOLDER_WORKSPACE is under FOLDER_ROOT."""
        self.assertTrue(FOLDER_WORKSPACE.startswith(FOLDER_ROOT))

    def test_folder_workspace_value(self):
        """Verify FOLDER_WORKSPACE has the expected value."""
        self.assertEqual(FOLDER_WORKSPACE, "/topsailai/workspace")

    def test_folder_memory_is_string(self):
        """Verify FOLDER_MEMORY is a string type."""
        self.assertIsInstance(FOLDER_MEMORY, str)

    def test_folder_memory_starts_with_root(self):
        """Verify FOLDER_MEMORY is under FOLDER_ROOT."""
        self.assertTrue(FOLDER_MEMORY.startswith(FOLDER_ROOT))

    def test_folder_memory_value(self):
        """Verify FOLDER_MEMORY has the expected value."""
        self.assertEqual(FOLDER_MEMORY, "/topsailai/memory")

    def test_folder_lock_is_string(self):
        """Verify FOLDER_LOCK is a string type."""
        self.assertIsInstance(FOLDER_LOCK, str)

    def test_folder_lock_starts_with_root(self):
        """Verify FOLDER_LOCK is under FOLDER_ROOT."""
        self.assertTrue(FOLDER_LOCK.startswith(FOLDER_ROOT))

    def test_folder_lock_value(self):
        """Verify FOLDER_LOCK has the expected value."""
        self.assertEqual(FOLDER_LOCK, "/topsailai/lock")

    def test_folder_skill_is_string(self):
        """Verify FOLDER_SKILL is a string type."""
        self.assertIsInstance(FOLDER_SKILL, str)

    def test_folder_skill_starts_with_root(self):
        """Verify FOLDER_SKILL is under FOLDER_ROOT."""
        self.assertTrue(FOLDER_SKILL.startswith(FOLDER_ROOT))

    def test_folder_skill_value(self):
        """Verify FOLDER_SKILL has the expected value."""
        self.assertEqual(FOLDER_SKILL, "/topsailai/skill")

    def test_folder_log_is_string(self):
        """Verify FOLDER_LOG is a string type."""
        self.assertIsInstance(FOLDER_LOG, str)

    def test_folder_log_starts_with_root(self):
        """Verify FOLDER_LOG is under FOLDER_ROOT."""
        self.assertTrue(FOLDER_LOG.startswith(FOLDER_ROOT))

    def test_folder_log_value(self):
        """Verify FOLDER_LOG has the expected value."""
        self.assertEqual(FOLDER_LOG, "/topsailai/log")


class TestFolderConstantsLayer3(unittest.TestCase):
    """Test cases for Layer 3 (subdirectories)."""

    def test_folder_memory_story_is_string(self):
        """Verify FOLDER_MEMORY_STORY is a string type."""
        self.assertIsInstance(FOLDER_MEMORY_STORY, str)

    def test_folder_memory_story_starts_with_memory(self):
        """Verify FOLDER_MEMORY_STORY is under FOLDER_MEMORY."""
        self.assertTrue(FOLDER_MEMORY_STORY.startswith(FOLDER_MEMORY))

    def test_folder_memory_story_value(self):
        """Verify FOLDER_MEMORY_STORY has the expected value."""
        self.assertEqual(FOLDER_MEMORY_STORY, "/topsailai/memory/story")

    def test_folder_workspace_task_is_string(self):
        """Verify FOLDER_WORKSPACE_TASK is a string type."""
        self.assertIsInstance(FOLDER_WORKSPACE_TASK, str)

    def test_folder_workspace_task_starts_with_workspace(self):
        """Verify FOLDER_WORKSPACE_TASK is under FOLDER_WORKSPACE."""
        self.assertTrue(FOLDER_WORKSPACE_TASK.startswith(FOLDER_WORKSPACE))

    def test_folder_workspace_task_value(self):
        """Verify FOLDER_WORKSPACE_TASK has the expected value."""
        self.assertEqual(FOLDER_WORKSPACE_TASK, "/topsailai/workspace/task")


class TestFolderHierarchy(unittest.TestCase):
    """Test cases for folder hierarchy relationships."""

    def test_all_folders_start_with_root(self):
        """Verify all folder constants are under FOLDER_ROOT."""
        folders = [
            FOLDER_WORKSPACE,
            FOLDER_MEMORY,
            FOLDER_LOCK,
            FOLDER_SKILL,
            FOLDER_LOG,
            FOLDER_MEMORY_STORY,
            FOLDER_WORKSPACE_TASK,
        ]
        for folder in folders:
            self.assertTrue(
                folder.startswith(FOLDER_ROOT),
                f"{folder} should start with {FOLDER_ROOT}",
            )

    def test_memory_story_under_memory(self):
        """Verify FOLDER_MEMORY_STORY is a subdirectory of FOLDER_MEMORY."""
        self.assertTrue(
            FOLDER_MEMORY_STORY.startswith(FOLDER_MEMORY + "/"),
            f"{FOLDER_MEMORY_STORY} should be under {FOLDER_MEMORY}",
        )

    def test_workspace_task_under_workspace(self):
        """Verify FOLDER_WORKSPACE_TASK is a subdirectory of FOLDER_WORKSPACE."""
        self.assertTrue(
            FOLDER_WORKSPACE_TASK.startswith(FOLDER_WORKSPACE + "/"),
            f"{FOLDER_WORKSPACE_TASK} should be under {FOLDER_WORKSPACE}",
        )

    def test_no_duplicate_slashes_in_paths(self):
        """Verify no folder constants contain duplicate slashes."""
        folders = [
            FOLDER_ROOT,
            FOLDER_WORKSPACE,
            FOLDER_MEMORY,
            FOLDER_LOCK,
            FOLDER_SKILL,
            FOLDER_LOG,
            FOLDER_MEMORY_STORY,
            FOLDER_WORKSPACE_TASK,
        ]
        for folder in folders:
            self.assertNotIn(
                "//",
                folder,
                f"{folder} should not contain double slashes",
            )

    def test_all_folders_end_properly(self):
        """Verify folder constants do not end with trailing slashes."""
        folders = [
            FOLDER_ROOT,
            FOLDER_WORKSPACE,
            FOLDER_MEMORY,
            FOLDER_LOCK,
            FOLDER_SKILL,
            FOLDER_LOG,
            FOLDER_MEMORY_STORY,
            FOLDER_WORKSPACE_TASK,
        ]
        for folder in folders:
            self.assertFalse(
                folder.endswith("/"),
                f"{folder} should not end with a trailing slash",
            )


if __name__ == "__main__":
    unittest.main()
