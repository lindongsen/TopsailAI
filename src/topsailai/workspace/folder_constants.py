"""
Folder Constants Configuration for TopsailAI System

This module defines the hierarchical folder structure used by the TopsailAI system.
It provides centralized path constants that are used throughout the application
for consistent file and directory management.

Author: DawsonLin
Email: lin_dongsen@126.com
Created: 2025-12-25

Purpose:
- Define a standardized folder hierarchy for the TopsailAI system
- Provide centralized path constants for easy maintenance
- Ensure consistent file organization across different components
- Facilitate easy configuration changes if needed

Usage:
    from topsailai.workspace.folder_constants import FOLDER_ROOT, FOLDER_WORKSPACE

    # Use constants to build file paths
    file_path = FOLDER_WORKSPACE + "/my_file.txt"
"""

###################################################################################
# Layer 1: Root directory for the entire TopsailAI system
# This is the top-level directory that contains all system components
FOLDER_ROOT = "/topsailai"
###################################################################################


###################################################################################
# Layer 2: Main system directories under the root
# These directories organize the system into functional areas
###################################################################################

# Workspace directory - Contains active projects, user data, and working files
FOLDER_WORKSPACE = FOLDER_ROOT + "/workspace"

# Memory directory - Stores system memory, stories, and persistent data
FOLDER_MEMORY = FOLDER_ROOT + "/memory"

# Lock directory - Manages file locks and synchronization mechanisms
FOLDER_LOCK = FOLDER_ROOT + "/lock"

# Skill directory
FOLDER_SKILL = FOLDER_ROOT + "/skill"

# Log
FOLDER_LOG = FOLDER_ROOT + "/log"

###################################################################################
# Layer 3: Subdirectories within the main system directories
# These provide further organization within each functional area
###################################################################################

# Story subdirectory - Contains story files and narrative data within the memory system
FOLDER_MEMORY_STORY = FOLDER_MEMORY + "/story"

# Task files
FOLDER_WORKSPACE_TASK = FOLDER_WORKSPACE + "/task"
