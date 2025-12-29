'''
Author: DawsonLin
Email: lin_dongsen@126.com
Created: 2025-12-29
Purpose:
'''

import sys
from topsailai.ai_base.llm_base import ContentSender


class ContentDots(ContentSender):
    """
    A content sender implementation that outputs dots for each content sent.

    This class provides a simple visual feedback mechanism by printing dots
    to indicate content transmission progress.
    """

    def send(self, content):
        """
        Send content by printing a dot character.

        Args:
            content: The content to be sent (not used in this implementation)

        Returns:
            bool: Always returns True to indicate successful transmission
        """
        sys.stdout.write(".")
        sys.stdout.flush()
        return True
