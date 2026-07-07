'''
Author: DawsonLin
Email: lin_dongsen@126.com
Created: 2026-07-07
Purpose:
'''

import sys


class ContentSender(object):
    """
    Abstract base class for content sending mechanisms.

    This class defines the interface for sending content to various endpoints.
    Subclasses must implement the send method.
    """
    def send(self, content):
        """
        Send content to the configured endpoint.

        Args:
            content (str): The content to send

        Raises:
            NotImplementedError: Must be implemented by subclasses
        """
        raise NotImplementedError

    def finish(self):
        """
        Called when the content stream has ended.

        Subclasses may override this method to emit a final newline, release
        resources, or finalize any in-progress rendering. The default
        implementation is a no-op so existing senders remain backward
        compatible.
        """
        return True

class ContentStdout(ContentSender):
    """
    Content sender implementation that writes content to standard output.

    This is useful for debugging and command-line applications.
    """
    def send(self, content):
        """
        Write content to standard output.

        Args:
            content (str): The content to write to stdout
        """
        sys.stdout.write(content)
