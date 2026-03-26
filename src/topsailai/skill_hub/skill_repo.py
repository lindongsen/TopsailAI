'''
  Author: DawsonLin
  Email: lin_dongsen@126.com
  Created: 2026-03-26
  Purpose:
'''

import os
import shutil
import urllib.request
import urllib.error
import zipfile
import tempfile
import subprocess
import re

from topsailai.logger import logger
from topsailai.utils.env_tool import EnvReaderInstance
from topsailai.workspace.folder_constants import (
    FOLDER_SKILL,
)
from topsailai.skill_hub.skill_tool import (
    get_file_skill_md,
)

# Module-level constants
MAX_DEPTH = EnvReaderInstance.get("TOPSAILAI_SEARCH_SKILLS_MAX_DEPTH", default=3, formatter=int) or 3  # Maximum recursion depth for skill discovery
GIT_CLONE_TIMEOUT = 300  # 5 minutes timeout for git clone
URL_DOWNLOAD_TIMEOUT = 300  # 5 minutes timeout for URL download


def list_skills() -> list[str]:
    """
    List all of skills from FOLDER_SKILL
    If the folder exists skill.md or SKILL.md, it is skill folder.
    search subfolders with recursion (default depth 3)

    Returns:
        list[str]: [relative_folder1, relative_folder2], example: ["local/x", "skillhub.cn/x", "team/Software-engineering-development-and-testing"]
    """
    skills = []
    skipped_dirs = []  # Track skipped directories for reporting

    if not os.path.exists(FOLDER_SKILL):
        return skills

    # Recursively find all folders containing SKILL.md or skill.md
    # Maximum recursion depth is 3 levels from FOLDER_SKILL

    def _is_skill_folder(folder_path: str) -> bool:
        """Check if folder contains SKILL.md or skill.md"""
        if get_file_skill_md(folder_path):
            return True
        return False

    def _scan_folder(base_path: str, current_depth: int):
        """Recursively scan folder for skill folders"""
        if current_depth > MAX_DEPTH:
            return

        # Check if current folder is a skill folder (but not the root FOLDER_SKILL)
        if current_depth > 0 and _is_skill_folder(base_path):
            # Get relative path from FOLDER_SKILL
            rel_path = os.path.relpath(base_path, FOLDER_SKILL)
            skills.append(rel_path)
            return  # Don't recurse into skill folders

        # Scan subdirectories
        try:
            for item in os.listdir(base_path):
                item_path = os.path.join(base_path, item)
                if os.path.isdir(item_path):
                    _scan_folder(item_path, current_depth + 1)
        except PermissionError as e:
            # Log permission errors instead of silently ignoring
            skipped_dirs.append((base_path, str(e)))
            logger.warning(f"Permission denied accessing folder: {base_path}")

    _scan_folder(FOLDER_SKILL, 0)

    # Log skipped directories if any
    if skipped_dirs:
        logger.info(f"Skipped {len(skipped_dirs)} directories due to permission errors")

    return sorted(skills)


def install_skill(address: str) -> str:
    """
    Install a skill to FOLDER_SKILL

    Args:
        address (str): local path, url address, git URL, or zip file path,
                       example: /path/to/x, https://skillhub.cn/x, https://github.com/user/repo.git, /path/to/skill.zip

    Returns:
        str: local skill folder, download to here, example: FOLDER_SKILL/local/x,  FOLDER_SKILL/skillhub.cn/x

    Raises:
        ValueError: If the address is invalid or installation fails
    """
    if not address:
        raise ValueError("Address cannot be empty")

    # Ensure FOLDER_SKILL exists
    os.makedirs(FOLDER_SKILL, exist_ok=True)

    # Determine if it's a git URL, URL, zip file, or local path
    if _is_git_url(address):
        return install_from_git(address)
    elif address.startswith("http://") or address.startswith("https://"):
        return install_from_url(address)
    elif address.endswith(".zip"):
        return install_from_zip(address)
    elif os.path.exists(address):
        return install_from_local(address)

    raise ValueError("Illegal address: [%s]", address)

def _is_git_url(address: str) -> bool:
    """
    Check if the address is a git URL.

    Args:
        address (str): The address to check

    Returns:
        bool: True if it appears to be a git URL
    """
    # Check for .git suffix
    if address.endswith(".git"):
        return True

    # Check for common git hosting patterns - more specific to avoid false positives
    git_patterns = [
        r"^https?://github\.com/[^/]+/[^/]+",  # github.com/user/repo
        r"^https?://gitlab\.com/[^/]+/[^/]+",  # gitlab.com/user/repo
        r"^https?://bitbucket\.org/[^/]+/[^/]+",  # bitbucket.org/user/repo
        r"^git@github\.com:",  # SSH git@github.com:user/repo
        r"^git@gitlab\.com:",  # SSH git@gitlab.com:user/repo
    ]

    for pattern in git_patterns:
        if re.search(pattern, address, re.IGNORECASE):
            return True

    return False


def _validate_skill_installation(skill_path: str) -> bool:
    """
    Validate that the installed skill contains a valid SKILL.md file.

    Args:
        skill_path (str): Path to the installed skill folder

    Returns:
        bool: True if SKILL.md exists, False otherwise
    """
    if get_file_skill_md(skill_path):
        return True
    logger.warning(f"Installed skill at {skill_path} does not contain SKILL.md or skill.md")
    return False


def _safe_extract(zip_ref, member, path):
    """
    Safely extract a zip member to prevent path traversal attacks.

    Args:
        zip_ref: ZipFile object
        member: Member name to extract
        path: Destination path

    Raises:
        ValueError: If the member would extract outside the target directory
    """
    # Get the absolute path of the target directory
    target_dir = os.path.abspath(path)

    # Get the absolute path where the member would be extracted
    member_path = os.path.abspath(os.path.join(target_dir, member))

    # Ensure the member path is within the target directory
    if not member_path.startswith(target_dir + os.sep) and member_path != target_dir:
        raise ValueError(f"Path traversal attempt detected: {member}")

    # Extract the member
    zip_ref.extract(member, path)


def install_from_git(git_url: str, branch: str = "main") -> str:
    """
    Install a skill from a git repository.

    Args:
        git_url (str): Git repository URL, example: https://github.com/user/repo.git
        branch (str): Branch to checkout, default: "main"

    Returns:
        str: Local skill folder path

    Raises:
        ValueError: If git is not installed, URL is invalid, or installation fails
    """
    if not git_url:
        raise ValueError("Git URL cannot be empty")

    # Check if git is installed
    try:
        subprocess.run(
            ["git", "--version"],
            capture_output=True,
            check=True,
            timeout=10
        )
    except (subprocess.CalledProcessError, FileNotFoundError, subprocess.TimeoutExpired):
        raise ValueError("git is not installed or not accessible")

    # Extract repo name from URL for folder naming
    # Remove .git suffix if present
    repo_name = git_url.rstrip('/')
    if repo_name.endswith(".git"):
        repo_name = repo_name[:-4]

    # Get the last path component as skill name
    skill_name = os.path.basename(repo_name)

    if not skill_name:
        raise ValueError(f"Invalid git URL: {git_url}")

    # Determine domain for folder organization
    git_domain = "git"
    if "github.com" in git_url.lower():
        git_domain = "github.com"
    elif "gitlab.com" in git_url.lower():
        git_domain = "gitlab.com"
    elif "bitbucket.org" in git_url.lower():
        git_domain = "bitbucket.org"

    dest_folder = os.path.join(FOLDER_SKILL, git_domain, skill_name)

    # Check if already exists
    if os.path.exists(dest_folder):
        return dest_folder

    # Create temp directory for cloning
    temp_dir = tempfile.mkdtemp(prefix="skill_git_")

    try:
        # Clone the repository - try main first, then fallback to master
        print(f"Cloning git repository: {git_url}")

        branches_to_try = [branch, "main", "master"] if branch == "main" else [branch]
        clone_success = False
        last_error = None

        for try_branch in branches_to_try:
            clone_result = subprocess.run(
                ["git", "clone", "--branch", try_branch, "--single-branch", "--depth", "1", git_url, temp_dir],
                capture_output=True,
                text=True,
                timeout=GIT_CLONE_TIMEOUT
            )

            if clone_result.returncode == 0:
                clone_success = True
                if try_branch != branch:
                    logger.info(f"Branch '{branch}' not found, using '{try_branch}' instead")
                break
            else:
                last_error = clone_result.stderr.strip()
                # Clear temp directory for next attempt
                shutil.rmtree(temp_dir, ignore_errors=True)
                temp_dir = tempfile.mkdtemp(prefix="skill_git_")

        if not clone_success:
            error_msg = last_error or "Unknown error"
            if "could not find" in error_msg.lower() or "branch" in error_msg.lower():
                raise ValueError(f"Branch not found in repository. Tried: {', '.join(branches_to_try)}")
            elif "not found" in error_msg.lower() or "repository" in error_msg.lower():
                raise ValueError(f"Repository not found: {git_url}")
            else:
                raise ValueError(f"Failed to clone repository: {error_msg}")

        # Create destination folder
        os.makedirs(os.path.dirname(dest_folder), exist_ok=True)

        # Move cloned content to destination
        # The temp_dir contains the cloned repo, we need to move its contents
        temp_contents = os.listdir(temp_dir)
        if len(temp_contents) == 1 and os.path.isdir(os.path.join(temp_dir, temp_contents[0])):
            # If there's a single subdirectory, use it
            source_folder = os.path.join(temp_dir, temp_contents[0])
        else:
            source_folder = temp_dir

        # Atomic installation: copy to temp destination first, then move
        temp_dest = dest_folder + ".tmp"
        try:
            if os.path.exists(temp_dest):
                shutil.rmtree(temp_dest)
            shutil.copytree(source_folder, temp_dest)
            # Atomic rename
            shutil.move(temp_dest, dest_folder)
        except Exception as e:
            # Clean up temp destination if it exists
            if os.path.exists(temp_dest):
                shutil.rmtree(temp_dest, ignore_errors=True)
            raise ValueError(f"Failed to install skill: {e}")

        # Validate installation
        if not _validate_skill_installation(dest_folder):
            raise ValueError(f"Installed skill at {dest_folder} does not contain valid SKILL.md")

        return dest_folder

    except subprocess.TimeoutExpired:
        raise ValueError("Git clone timed out")
    except ValueError:
        raise
    except (OSError, shutil.Error) as e:
        raise ValueError(f"Failed to install skill from git (OS error): {e}")
    except Exception as e:
        raise ValueError(f"Failed to install skill from git: {e}")
    finally:
        # Clean up temp directory with consistent behavior
        if os.path.exists(temp_dir):
            shutil.rmtree(temp_dir, ignore_errors=True)


def install_from_zip(zip_path: str, extract_subfolder: str = None) -> str:
    """
    Install a skill from a local zip file.

    Args:
        zip_path (str): Local path to the zip file, example: /path/to/skill.zip
        extract_subfolder (str): Optional subfolder name to extract from the zip.
                                 If provided, only this subfolder will be extracted.

    Returns:
        str: Local skill folder path

    Raises:
        ValueError: If the zip file doesn't exist, is invalid, or extraction fails
    """
    # Resolve the absolute path
    abs_path = os.path.abspath(zip_path)

    if not os.path.exists(abs_path):
        raise ValueError(f"Zip file does not exist: {zip_path}")

    if not abs_path.endswith(".zip"):
        raise ValueError(f"File is not a zip file: {zip_path}")

    # Get the skill name from the zip file name (without .zip extension)
    skill_name = os.path.splitext(os.path.basename(abs_path))[0]
    dest_folder = os.path.join(FOLDER_SKILL, "local", skill_name)

    # Check if already exists
    if os.path.exists(dest_folder):
        return dest_folder

    # Create temp directory for extraction
    temp_dir = tempfile.mkdtemp(prefix="skill_zip_")

    try:
        print(f"Extracting skill from: {zip_path}")

        # Validate zip file
        if not zipfile.is_zipfile(abs_path):
            raise ValueError(f"Invalid zip file: {zip_path}")

        # Extract the zip file with path traversal protection
        with zipfile.ZipFile(abs_path, 'r') as zip_ref:
            if extract_subfolder:
                # Extract only the specified subfolder with validation
                for member in zip_ref.namelist():
                    if member.startswith(extract_subfolder + '/') or member == extract_subfolder + '/':
                        # Validate path before extraction
                        _safe_extract(zip_ref, member, temp_dir)
                # Find the extracted subfolder
                extracted_base = os.path.join(temp_dir, extract_subfolder)
            else:
                # Extract all with validation
                for member in zip_ref.namelist():
                    _safe_extract(zip_ref, member, temp_dir)

                # Find the base folder (first level directory in the zip)
                temp_contents = os.listdir(temp_dir)
                if len(temp_contents) == 1 and os.path.isdir(os.path.join(temp_dir, temp_contents[0])):
                    extracted_base = os.path.join(temp_dir, temp_contents[0])
                else:
                    extracted_base = temp_dir

        # Create destination folder
        os.makedirs(os.path.dirname(dest_folder), exist_ok=True)

        # Atomic installation: copy to temp destination first, then move
        temp_dest = dest_folder + ".tmp"
        try:
            if os.path.exists(temp_dest):
                shutil.rmtree(temp_dest)
            shutil.copytree(extracted_base, temp_dest)
            # Atomic rename
            shutil.move(temp_dest, dest_folder)
        except Exception as e:
            # Clean up temp destination if it exists
            if os.path.exists(temp_dest):
                shutil.rmtree(temp_dest, ignore_errors=True)
            raise ValueError(f"Failed to install skill: {e}")

        # Validate installation
        if not _validate_skill_installation(dest_folder):
            raise ValueError(f"Installed skill at {dest_folder} does not contain valid SKILL.md")

        return dest_folder

    except zipfile.BadZipFile:
        raise ValueError(f"Invalid or corrupted zip file: {zip_path}")
    except ValueError:
        raise
    except (OSError, shutil.Error) as e:
        raise ValueError(f"Failed to install skill from zip (OS error): {e}")
    except Exception as e:
        raise ValueError(f"Failed to install skill from zip: {e}")
    finally:
        # Clean up temp directory with consistent behavior
        if os.path.exists(temp_dir):
            shutil.rmtree(temp_dir, ignore_errors=True)


def install_from_url(url: str) -> str:
    """
    Download and install a skill from a URL.

    Args:
        url (str): URL to download from (zip file or direct folder)

    Returns:
        str: Local skill folder path

    Raises:
        ValueError: If download or extraction fails
    """
    # Extract skill name from URL for folder naming
    # Try to get the last path component as skill name
    url_path = url.rstrip('/')
    url_domain = url.split("//", 1)[-1].split('/')[0]
    skill_name = os.path.basename(url_path)

    if not skill_name:
        raise ValueError(f"Invalid URL: {url}")

    dest_folder = os.path.join(FOLDER_SKILL, url_domain, skill_name)

    # Check if already exists
    if os.path.exists(dest_folder):
        return dest_folder

    # Create temp directory for download
    temp_dir = tempfile.mkdtemp(prefix="skill_url_")

    try:
        # Download the content
        print(f"Downloading skill from: {url}")

        # Create a temporary file to store the download
        tmp_path = os.path.join(temp_dir, "download.zip")

        try:
            # Download with timeout using urlopen instead of urlretrieve
            with urllib.request.urlopen(url, timeout=URL_DOWNLOAD_TIMEOUT) as response:
                with open(tmp_path, 'wb') as out_file:
                    shutil.copyfileobj(response, out_file)

            # Try to extract as zip file
            if zipfile.is_zipfile(tmp_path):
                # Atomic installation: extract to temp location first
                temp_extract_dir = os.path.join(temp_dir, "extracted")
                os.makedirs(temp_extract_dir, exist_ok=True)

                with zipfile.ZipFile(tmp_path, 'r') as zip_ref:
                    # Extract with path traversal protection
                    for member in zip_ref.namelist():
                        _safe_extract(zip_ref, member, temp_extract_dir)

                # Find the base folder
                temp_contents = os.listdir(temp_extract_dir)
                if len(temp_contents) == 1 and os.path.isdir(os.path.join(temp_extract_dir, temp_contents[0])):
                    extracted_base = os.path.join(temp_extract_dir, temp_contents[0])
                else:
                    extracted_base = temp_extract_dir

                # Create destination folder
                os.makedirs(os.path.dirname(dest_folder), exist_ok=True)

                # Atomic move to final destination
                temp_dest = dest_folder + ".tmp"
                try:
                    if os.path.exists(temp_dest):
                        shutil.rmtree(temp_dest)
                    shutil.copytree(extracted_base, temp_dest)
                    shutil.move(temp_dest, dest_folder)
                except Exception as e:
                    if os.path.exists(temp_dest):
                        shutil.rmtree(temp_dest, ignore_errors=True)
                    raise ValueError(f"Failed to install skill: {e}")
            else:
                # Not a zip file, assume it's a direct download
                # Create folder and save the file
                os.makedirs(dest_folder, exist_ok=True)
                shutil.move(tmp_path, os.path.join(dest_folder, skill_name))

            # Validate installation
            if not _validate_skill_installation(dest_folder):
                raise ValueError(f"Installed skill at {dest_folder} does not contain valid SKILL.md")

            return dest_folder

        finally:
            # Clean up temp file if it still exists
            if os.path.exists(tmp_path):
                os.remove(tmp_path)

    except urllib.error.URLError as e:
        raise ValueError(f"Failed to download from URL: {e}")
    except ValueError:
        raise
    except (OSError, shutil.Error) as e:
        raise ValueError(f"Failed to install skill from URL (OS error): {e}")
    except Exception as e:
        raise ValueError(f"Failed to install skill from URL: {e}")
    finally:
        # Clean up temp directory with consistent behavior
        if os.path.exists(temp_dir):
            shutil.rmtree(temp_dir, ignore_errors=True)


def install_from_local(local_path: str) -> str:
    """
    Install a skill from a local path by copying to FOLDER_SKILL.

    Args:
        local_path (str): Local path to the skill folder

    Returns:
        str: Local skill folder path

    Raises:
        ValueError: If the local path doesn't exist or is invalid
    """
    # Resolve the absolute path
    abs_path = os.path.abspath(local_path)

    if not os.path.exists(abs_path):
        raise ValueError(f"Local path does not exist: {local_path}")

    if not os.path.isdir(abs_path):
        raise ValueError(f"Local path is not a directory: {local_path}")

    # Get the folder name
    skill_name = os.path.basename(abs_path)
    dest_folder = os.path.join(FOLDER_SKILL, "local", skill_name)

    # Check if already exists
    if os.path.exists(dest_folder):
        return dest_folder

    try:
        # Atomic installation: copy to temp destination first, then move
        temp_dest = dest_folder + ".tmp"
        try:
            if os.path.exists(temp_dest):
                shutil.rmtree(temp_dest)
            shutil.copytree(abs_path, temp_dest)
            # Atomic rename
            shutil.move(temp_dest, dest_folder)
        except Exception as e:
            # Clean up temp destination if it exists
            if os.path.exists(temp_dest):
                shutil.rmtree(temp_dest, ignore_errors=True)
            raise ValueError(f"Failed to install skill: {e}")

        # Validate installation
        if not _validate_skill_installation(dest_folder):
            raise ValueError(f"Installed skill at {dest_folder} does not contain valid SKILL.md")

        return dest_folder

    except (OSError, shutil.Error) as e:
        raise ValueError(f"Failed to copy skill from {local_path} (OS error): {e}")
    except ValueError:
        raise
    except Exception as e:
        raise ValueError(f"Failed to copy skill from {local_path}: {e}")


def uninstall_skill(skill_folder: str) -> bool:
    """
    Uninstall a skill by removing its folder from FOLDER_SKILL.

    Args:
        skill_folder (str): The name of the skill folder to remove,
                          example: "local/x", "skillhub.cn/x", "team/Software-engineering-development-and-testing"

    Returns:
        bool: True if the skill was successfully removed, False if it didn't exist

    Raises:
        ValueError: If the skill_folder is empty or removal fails due to permission errors
    """
    if not skill_folder:
        raise ValueError("Skill name cannot be empty")

    # Construct the full path to the skill folder
    skill_path = os.path.join(FOLDER_SKILL, skill_folder)

    # Check if the skill folder exists
    if not os.path.exists(skill_path):
        return False

    try:
        # Remove the skill folder
        shutil.rmtree(skill_path)
        return True
    except PermissionError as e:
        raise ValueError(f"Permission denied while removing skill: {e}")
    except OSError as e:
        raise ValueError(f"Failed to remove skill folder: {e}")
