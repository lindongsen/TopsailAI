'''
  Author: DawsonLin
  Email: lin_dongsen@126.com
  Created: 2025-12-11
  Purpose: Environment prompt generation module for TopsailAI context management
  
  This module provides classes and functions to generate environment-related prompts
  including system information, current date, and custom environment prompts.
'''
import os

from topsailai.utils import (
    time_tool,
    cmd_tool,
)


def get_system_info() -> dict:
    """
    Retrieve key system information including OS details.
    
    This function collects system information by executing system commands
    and reading system files to gather details about the operating system.
    
    Returns:
        dict: A dictionary containing system information with keys:
            - 'uname': Output from 'uname -a' command (system architecture and version)
            - 'issue': Content from /etc/issue file (OS distribution info)
    """
    result = {}

    # Execute 'uname -a' to get system architecture and version information
    ret = cmd_tool.exec_cmd("uname -a")
    if ret and ret[1]:
        result["uname"] = ret[1].strip()

    # Read /etc/issue file to get OS distribution information
    if os.path.exists("/etc/issue"):
        with open("/etc/issue", encoding="utf-8") as fd:
            result["issue"] = fd.read().strip()

    return result


class _Base(object):
    """
    Base class for prompt generators.
    
    This abstract class defines the interface for all prompt generator classes.
    Subclasses must implement the 'prompt' property to provide specific
    prompt content.
    """
    
    def __init__(self):
        """Initialize the base prompt generator."""
        pass

    def __str__(self):
        """
        String representation of the prompt generator.
        
        Returns:
            str: The prompt content when object is converted to string
        """
        return self.prompt

    @property
    def prompt(self) -> str:
        """
        Abstract property for prompt content.
        
        Returns:
            str: The generated prompt content
            
        Raises:
            NotImplementedError: Must be implemented by subclasses
        """
        raise NotImplementedError


class CurrentDate(_Base):
    """
    Prompt generator for current date information.
    
    This class generates a prompt containing the current date in ISO 8601 format.
    """
    
    @property
    def prompt(self) -> str:
        """
        Generate prompt with current date.
        
        Returns:
            str: Formatted string containing current date
        """
        return f"""CurrentDate: {time_tool.get_current_date(True)}"""


class CurrentSystem(_Base):
    """
    Prompt generator for system information.
    
    This class generates a prompt containing system information
    collected from the operating system.
    """
    
    # Class-level system info to avoid repeated system calls
    system_info = get_system_info()

    @property
    def prompt(self) -> str:
        """
        Generate prompt with system information.
        
        Returns:
            str: Formatted string containing system information
                 with each item on a separate line
        """
        result = "System Info:\n"
        # Format each system info item with bullet points
        for k, v in self.system_info.items():
            if v:
                result += f"- {k}:{v}\n"
        return result


def generate_prompt_for_env() -> str:
    """
    Generate a comprehensive environment prompt for AI context.
    
    This function combines date, system information, and optional
    custom environment prompts into a single formatted string.
    
    The custom environment prompt can be provided via the ENV_PROMPT
    environment variable, which can be either:
    - A file path (if starts with '.' or '/') - content will be read
    - Direct text content
    
    Returns:
        str: Complete environment prompt with header and all components
    """
    
    # Get custom environment prompt from environment variable
    env_prompt = os.getenv("ENV_PROMPT") or ""
    
    # If ENV_PROMPT is a file path, read its content
    if env_prompt:
        # Check if it's a file path (starts with . or /)
        if env_prompt[0] in ['.', '/']:
            with open(env_prompt, encoding="utf-8") as fd:
                env_prompt = fd.read()

    # Combine all prompt components with proper formatting
    return "# Environment\n" + "\n".join(
        [
            CurrentDate().prompt,
            CurrentSystem().prompt,
            env_prompt,
        ]
    )