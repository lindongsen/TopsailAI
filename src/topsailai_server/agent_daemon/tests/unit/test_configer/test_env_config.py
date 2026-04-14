'''
  Author: mm-m25
  Email: mm-m25@topsail.ai
  Created: 2026-04-14
  Purpose: Unit tests for EnvConfig
'''

import os
import stat
import tempfile
import unittest
from unittest.mock import patch, MagicMock

from topsailai_server.agent_daemon import logger
from topsailai_server.agent_daemon.configer.env_config import EnvConfig, get_config, reload_config
from topsailai_server.agent_daemon.exceptions import ConfigError


class TestEnvConfig(unittest.TestCase):
    """Unit tests for EnvConfig"""

    def setUp(self):
        """Set up test environment"""
        self.original_environ = os.environ.copy()
        self._clear_test_vars()
        # Clear global config
        import topsailai_server.agent_daemon.configer.env_config as env_config_module
        env_config_module._config = None

    def tearDown(self):
        """Clean up test environment"""
        os.environ.clear()
        os.environ.update(self.original_environ)
        # Clear global config
        import topsailai_server.agent_daemon.configer.env_config as env_config_module
        env_config_module._config = None

    def _clear_test_vars(self):
        """Clear environment variables used in tests"""
        test_vars = [
            'TOPSAILAI_AGENT_DAEMON_PROCESSOR',
            'TOPSAILAI_AGENT_DAEMON_SUMMARIZER',
            'TOPSAILAI_AGENT_DAEMON_SESSION_STATE_CHECKER',
            'TOPSAILAI_AGENT_DAEMON_HOST',
            'TOPSAILAI_AGENT_DAEMON_PORT',
            'TOPSAILAI_AGENT_DAEMON_DB_URL',
            'TOPSAILAI_AGENT_DAEMON_LOG_LEVEL'
        ]
        for var in test_vars:
            os.environ.pop(var, None)

    def _create_executable_script(self, content="#!/bin/bash\nexit 0"):
        """Create a temporary executable script"""
        fd, path = tempfile.mkstemp(suffix='.sh')
        with os.fdopen(fd, 'w') as f:
            f.write(content)
        os.chmod(path, os.stat(path).st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
        return path

    def _create_non_executable_script(self, content="#!/bin/bash\nexit 0"):
        """Create a temporary non-executable script"""
        fd, path = tempfile.mkstemp(suffix='.sh')
        with os.fdopen(fd, 'w') as f:
            f.write(content)
        return path

    # ==================== Environment Variable Loading Tests ====================

    def test_all_required_variables_loaded_correctly(self):
        """Test that all required variables are loaded correctly"""
        processor = self._create_executable_script()
        summarizer = self._create_executable_script()
        checker = self._create_executable_script()

        os.environ['TOPSAILAI_AGENT_DAEMON_PROCESSOR'] = processor
        os.environ['TOPSAILAI_AGENT_DAEMON_SUMMARIZER'] = summarizer
        os.environ['TOPSAILAI_AGENT_DAEMON_SESSION_STATE_CHECKER'] = checker

        config = EnvConfig(validate_scripts=False)

        self.assertEqual(config.processor_script, processor)
        self.assertEqual(config.summarizer_script, summarizer)
        self.assertEqual(config.session_state_checker_script, checker)
        logger.info("test_all_required_variables_loaded_correctly: passed")

    def test_default_values_applied_when_not_set(self):
        """Test that default values are applied when environment variables are not set"""
        config = EnvConfig(validate_scripts=False)

        self.assertEqual(config.host, '0.0.0.0')
        self.assertEqual(config.port, 7373)
        self.assertEqual(config.db_url, 'sqlite:///topsailai_agent_daemon.db')
        self.assertEqual(config.log_level, 'INFO')
        logger.info("test_default_values_applied_when_not_set: passed")

    def test_custom_values_override_defaults(self):
        """Test that custom values override defaults"""
        os.environ['TOPSAILAI_AGENT_DAEMON_HOST'] = '127.0.0.1'
        os.environ['TOPSAILAI_AGENT_DAEMON_PORT'] = '8080'
        os.environ['TOPSAILAI_AGENT_DAEMON_DB_URL'] = 'sqlite:///custom.db'
        os.environ['TOPSAILAI_AGENT_DAEMON_LOG_LEVEL'] = 'DEBUG'

        config = EnvConfig(validate_scripts=False)

        self.assertEqual(config.host, '127.0.0.1')
        self.assertEqual(config.port, 8080)
        self.assertEqual(config.db_url, 'sqlite:///custom.db')
        self.assertEqual(config.log_level, 'DEBUG')
        logger.info("test_custom_values_override_defaults: passed")

    # ==================== Script Validation Tests ====================

    def test_valid_script_paths_accepted(self):
        """Test that valid script paths are accepted"""
        processor = self._create_executable_script()
        summarizer = self._create_executable_script()
        checker = self._create_executable_script()

        os.environ['TOPSAILAI_AGENT_DAEMON_PROCESSOR'] = processor
        os.environ['TOPSAILAI_AGENT_DAEMON_SUMMARIZER'] = summarizer
        os.environ['TOPSAILAI_AGENT_DAEMON_SESSION_STATE_CHECKER'] = checker

        # Should not raise any exception
        config = EnvConfig(validate_scripts=True)
        self.assertIsNotNone(config)
        logger.info("test_valid_script_paths_accepted: passed")

    def test_invalid_script_paths_rejected(self):
        """Test that invalid script paths are rejected when validation enabled"""
        os.environ['TOPSAILAI_AGENT_DAEMON_PROCESSOR'] = '/nonexistent/path/script.sh'
        os.environ['TOPSAILAI_AGENT_DAEMON_SUMMARIZER'] = self._create_executable_script()
        os.environ['TOPSAILAI_AGENT_DAEMON_SESSION_STATE_CHECKER'] = self._create_executable_script()

        with self.assertRaises(ConfigError) as context:
            EnvConfig(validate_scripts=True)

        self.assertIn('Script not found', str(context.exception))
        logger.info("test_invalid_script_paths_rejected: passed")

    def test_nonexistent_files_handled(self):
        """Test that non-existent script files are handled gracefully"""
        os.environ['TOPSAILAI_AGENT_DAEMON_PROCESSOR'] = '/path/that/does/not/exist/processor.sh'
        os.environ['TOPSAILAI_AGENT_DAEMON_SUMMARIZER'] = self._create_executable_script()
        os.environ['TOPSAILAI_AGENT_DAEMON_SESSION_STATE_CHECKER'] = self._create_executable_script()

        with self.assertRaises(ConfigError):
            EnvConfig(validate_scripts=True)
        logger.info("test_nonexistent_files_handled: passed")

    def test_non_executable_script_rejected(self):
        """Test that non-executable scripts are rejected"""
        script = self._create_non_executable_script()

        os.environ['TOPSAILAI_AGENT_DAEMON_PROCESSOR'] = script
        os.environ['TOPSAILAI_AGENT_DAEMON_SUMMARIZER'] = self._create_executable_script()
        os.environ['TOPSAILAI_AGENT_DAEMON_SESSION_STATE_CHECKER'] = self._create_executable_script()

        with self.assertRaises(ConfigError) as context:
            EnvConfig(validate_scripts=True)

        self.assertIn('not executable', str(context.exception))
        logger.info("test_non_executable_script_rejected: passed")

    def test_validation_disabled_allows_missing_scripts(self):
        """Test that validation can be disabled to allow missing scripts"""
        os.environ['TOPSAILAI_AGENT_DAEMON_PROCESSOR'] = '/nonexistent/path/script.sh'
        os.environ['TOPSAILAI_AGENT_DAEMON_SUMMARIZER'] = '/nonexistent/path/summarizer.sh'
        os.environ['TOPSAILAI_AGENT_DAEMON_SESSION_STATE_CHECKER'] = '/nonexistent/path/checker.sh'

        # Should not raise exception when validation is disabled
        config = EnvConfig(validate_scripts=False)
        self.assertIsNotNone(config)
        self.assertEqual(config.processor_script, '/nonexistent/path/script.sh')
        logger.info("test_validation_disabled_allows_missing_scripts: passed")

    # ==================== Configuration Properties Tests ====================

    def test_all_properties_return_correct_values(self):
        """Test that all properties return correct values"""
        processor = self._create_executable_script()
        summarizer = self._create_executable_script()
        checker = self._create_executable_script()

        os.environ['TOPSAILAI_AGENT_DAEMON_PROCESSOR'] = processor
        os.environ['TOPSAILAI_AGENT_DAEMON_SUMMARIZER'] = summarizer
        os.environ['TOPSAILAI_AGENT_DAEMON_SESSION_STATE_CHECKER'] = checker
        os.environ['TOPSAILAI_AGENT_DAEMON_HOST'] = '192.168.1.1'
        os.environ['TOPSAILAI_AGENT_DAEMON_PORT'] = '9000'
        os.environ['TOPSAILAI_AGENT_DAEMON_DB_URL'] = 'sqlite:///test.db'
        os.environ['TOPSAILAI_AGENT_DAEMON_LOG_LEVEL'] = 'WARNING'

        config = EnvConfig(validate_scripts=False)

        self.assertEqual(config.host, '192.168.1.1')
        self.assertEqual(config.port, 9000)
        self.assertEqual(config.db_url, 'sqlite:///test.db')
        self.assertEqual(config.log_level, 'WARNING')
        self.assertEqual(config.processor_script, processor)
        self.assertEqual(config.summarizer_script, summarizer)
        self.assertEqual(config.session_state_checker_script, checker)
        logger.info("test_all_properties_return_correct_values: passed")

    def test_property_access_works_after_loading(self):
        """Test that property access works after loading"""
        config = EnvConfig(validate_scripts=False)

        # Access properties multiple times
        host1 = config.host
        host2 = config.host
        self.assertEqual(host1, host2)

        port1 = config.port
        port2 = config.port
        self.assertEqual(port1, port2)
        logger.info("test_property_access_works_after_loading: passed")

    def test_has_processor_returns_true_when_configured(self):
        """Test has_processor returns True when processor is configured"""
        processor = self._create_executable_script()
        os.environ['TOPSAILAI_AGENT_DAEMON_PROCESSOR'] = processor

        config = EnvConfig(validate_scripts=False)
        self.assertTrue(config.has_processor())
        logger.info("test_has_processor_returns_true_when_configured: passed")

    def test_has_processor_returns_false_when_not_configured(self):
        """Test has_processor returns False when processor is not configured"""
        config = EnvConfig(validate_scripts=False)
        self.assertFalse(config.has_processor())
        logger.info("test_has_processor_returns_false_when_not_configured: passed")

    def test_has_summarizer_returns_true_when_configured(self):
        """Test has_summarizer returns True when summarizer is configured"""
        summarizer = self._create_executable_script()
        os.environ['TOPSAILAI_AGENT_DAEMON_SUMMARIZER'] = summarizer

        config = EnvConfig(validate_scripts=False)
        self.assertTrue(config.has_summarizer())
        logger.info("test_has_summarizer_returns_true_when_configured: passed")

    def test_has_session_state_checker_returns_true_when_configured(self):
        """Test has_session_state_checker returns True when checker is configured"""
        checker = self._create_executable_script()
        os.environ['TOPSAILAI_AGENT_DAEMON_SESSION_STATE_CHECKER'] = checker

        config = EnvConfig(validate_scripts=False)
        self.assertTrue(config.has_session_state_checker())
        logger.info("test_has_session_state_checker_returns_true_when_configured: passed")

    # ==================== Error Handling Tests ====================

    def test_missing_required_variables_handled(self):
        """Test that missing required variables are handled gracefully"""
        # No required variables are enforced, so this should not raise
        config = EnvConfig(validate_scripts=False)
        self.assertIsNotNone(config)
        logger.info("test_missing_required_variables_handled: passed")

    def test_invalid_values_handled_gracefully(self):
        """Test that invalid values are handled gracefully"""
        os.environ['TOPSAILAI_AGENT_DAEMON_PORT'] = 'not_a_number'

        # EnvConfig raises ValueError for invalid port values
        with self.assertRaises(ValueError):
            EnvConfig(validate_scripts=False)
        logger.info("test_invalid_values_handled_gracefully: passed")

    def test_port_conversion_to_integer(self):
        """Test that port is converted to integer"""
        os.environ['TOPSAILAI_AGENT_DAEMON_PORT'] = '8888'

        config = EnvConfig(validate_scripts=False)
        self.assertIsInstance(config.port, int)
        self.assertEqual(config.port, 8888)
        logger.info("test_port_conversion_to_integer: passed")

    # ==================== Global Config Tests ====================

    def test_get_config_returns_singleton(self):
        """Test that get_config returns the same instance"""
        os.environ['TOPSAILAI_AGENT_DAEMON_PROCESSOR'] = self._create_executable_script()
        os.environ['TOPSAILAI_AGENT_DAEMON_SUMMARIZER'] = self._create_executable_script()
        os.environ['TOPSAILAI_AGENT_DAEMON_SESSION_STATE_CHECKER'] = self._create_executable_script()

        config1 = get_config(validate_scripts=False)
        config2 = get_config(validate_scripts=False)

        self.assertIs(config1, config2)
        logger.info("test_get_config_returns_singleton: passed")

    def test_reload_config_creates_new_instance(self):
        """Test that reload_config creates a new instance"""
        os.environ['TOPSAILAI_AGENT_DAEMON_PROCESSOR'] = self._create_executable_script()
        os.environ['TOPSAILAI_AGENT_DAEMON_SUMMARIZER'] = self._create_executable_script()
        os.environ['TOPSAILAI_AGENT_DAEMON_SESSION_STATE_CHECKER'] = self._create_executable_script()

        config1 = get_config(validate_scripts=False)
        config2 = reload_config(validate_scripts=False)

        self.assertIsNot(config1, config2)
        logger.info("test_reload_config_creates_new_instance: passed")


if __name__ == '__main__':
    unittest.main()
