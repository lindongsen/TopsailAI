'''
  Author: DawsonLin
  Email: lin_dongsen@126.com
  Created: 2026-04-12
  Purpose: Environment variable configuration for agent_daemon
'''

import os
from typing import Optional

from topsailai_server.agent_daemon import logger
from topsailai_server.agent_daemon.exceptions import ConfigError


class EnvConfig:
    """Environment configuration for agent_daemon"""

    # Scripts that are required for full functionality
    REQUIRED_SCRIPTS = [
        'TOPSAILAI_AGENT_DAEMON_PROCESSOR',
        'TOPSAILAI_AGENT_DAEMON_SUMMARIZER',
        'TOPSAILAI_AGENT_DAEMON_SESSION_STATE_CHECKER'
    ]

    OPTIONAL_VARS = {
        'TOPSAILAI_AGENT_DAEMON_HOST': '0.0.0.0',
        'TOPSAILAI_AGENT_DAEMON_PORT': '7373',
        'TOPSAILAI_AGENT_DAEMON_DB_URL': 'sqlite:///topsailai_agent_daemon.db',
        'TOPSAILAI_AGENT_DAEMON_LOG_LEVEL': 'INFO'
    }

    def __init__(self, validate_scripts: bool = True):
        """
        Initialize the environment configuration.
        
        Args:
            validate_scripts: If True, validate that script files exist and are executable.
                             Set to False for testing without scripts.
        """
        self._validate_scripts_flag = validate_scripts
        self._load_optional()
        self._validate_required()
        if validate_scripts:
            self._validate_scripts()
        logger.info("Environment configuration loaded successfully")

        # set log level
        logger.setLevel(self.log_level)

    def _load_optional(self):
        """Load optional environment variables with defaults"""
        for var, default in self.OPTIONAL_VARS.items():
            attr_name = var.replace('TOPSAILAI_AGENT_DAEMON_', '').lower()
            # Use private attribute to avoid conflict with properties
            private_attr = f'_{attr_name}'
            setattr(self, private_attr, os.getenv(var, default))
        logger.info("Optional configuration loaded: host=%s, port=%s, db_url=%s, log_level=%s",
                    self.host, self.port, self.db_url, self.log_level)

    def _validate_required(self):
        """Validate required environment variables"""
        # For now, we don't require any environment variables to be set
        # The service can run with default values
        logger.info("Required environment variables check passed (none required)")

    def _validate_scripts(self):
        """Validate that the configured scripts exist and are executable"""
        scripts = [
            ('TOPSAILAI_AGENT_DAEMON_PROCESSOR', self.processor_script),
            ('TOPSAILAI_AGENT_DAEMON_SUMMARIZER', self.summarizer_script),
            ('TOPSAILAI_AGENT_DAEMON_SESSION_STATE_CHECKER', self.session_state_checker_script)
        ]

        for env_name, script_path in scripts:
            if not script_path:
                logger.warning("Script not configured: %s", env_name)
                continue
                
            if not os.path.exists(script_path):
                error_msg = f"Script not found: {env_name}={script_path}"
                logger.error("Script validation failed: %s", error_msg)
                raise ConfigError(error_msg)

            if not os.access(script_path, os.X_OK):
                error_msg = f"Script is not executable: {env_name}={script_path}"
                logger.error("Script validation failed: %s", error_msg)
                raise ConfigError(error_msg)

        logger.info("All configured scripts validated successfully")

    @property
    def host(self) -> str:
        """Get the HTTP server host"""
        return getattr(self, '_host', '0.0.0.0')

    @property
    def port(self) -> int:
        """Get the HTTP server port"""
        return int(getattr(self, '_port', '7373'))

    @property
    def db_url(self) -> str:
        """Get the database URL"""
        return getattr(self, '_db_url', 'sqlite:///topsailai_agent_daemon.db')

    @property
    def log_level(self) -> str:
        """Get the log level"""
        return getattr(self, '_log_level', 'INFO')

    @property
    def processor_script(self) -> Optional[str]:
        """Get the processor script path"""
        return os.getenv('TOPSAILAI_AGENT_DAEMON_PROCESSOR')

    @property
    def summarizer_script(self) -> Optional[str]:
        """Get the summarizer script path"""
        return os.getenv('TOPSAILAI_AGENT_DAEMON_SUMMARIZER')

    @property
    def session_state_checker_script(self) -> Optional[str]:
        """Get the session state checker script path"""
        return os.getenv('TOPSAILAI_AGENT_DAEMON_SESSION_STATE_CHECKER')

    def has_processor(self) -> bool:
        """Check if processor script is configured"""
        return bool(self.processor_script)

    def has_summarizer(self) -> bool:
        """Check if summarizer script is configured"""
        return bool(self.summarizer_script)

    def has_session_state_checker(self) -> bool:
        """Check if session state checker script is configured"""
        return bool(self.session_state_checker_script)


# Global config instance
_config: Optional[EnvConfig] = None


def get_config(validate_scripts: bool = True) -> EnvConfig:
    """Get the global configuration instance"""
    global _config
    if _config is None:
        _config = EnvConfig(validate_scripts=validate_scripts)
    return _config


def reload_config(validate_scripts: bool = True) -> EnvConfig:
    """Reload the configuration"""
    global _config
    _config = EnvConfig(validate_scripts=validate_scripts)
    return _config