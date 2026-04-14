#!/usr/bin/env python3
'''
  Author: Dawsonlin
  Email: lin_dongsen@126.com
  Created: 2026-04-14
  Purpose: Interactive terminal for agent_daemon - unified interface for sending messages and auto-refreshing
'''

import argparse
import os
import sys
import socket
import threading
import time
import requests
from datetime import datetime

# Add the parent directory to the path for imports
CWD = __file__
CWD = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(CWD))

from topsailai_server.agent_daemon import logger

# Default values - support environment variable overrides
DEFAULT_HOST = os.environ.get("TOPSAILAI_AGENT_DAEMON_HOST", "localhost")
DEFAULT_PORT = int(os.environ.get("TOPSAILAI_AGENT_DAEMON_PORT", "7373"))
DEFAULT_SESSION_ID = socket.gethostname()

# Terminal display constants
TERM_WIDTH = 80
SPLIT_LINE = "=" * TERM_WIDTH
DOUBLE_LINE = "=" * TERM_WIDTH
MSG_SEPARATOR = "-" * TERM_WIDTH


def format_time(time_str):
    """Format time string to HH:MM:SS"""
    if not time_str:
        return 'N/A'
    # Handle ISO format: 2026-04-13T23:27:53.123456
    if 'T' in time_str:
        date_part, time_part = time_str.split('T')
        time_part = time_part.split('.')[0]
        # Return only time part for chat display
        return time_part.split(':')[0] + ':' + time_part.split(':')[1]
    return time_str


def get_terminal_size():
    """Get terminal width"""
    try:
        import shutil
        size = shutil.get_terminal_size(fallback=(TERM_WIDTH, 24))
        return size.columns
    except:
        return TERM_WIDTH


def clear_screen():
    """Clear the terminal screen"""
    os.system('cls' if os.name == 'nt' else 'clear')


def truncate_text(text, max_width):
    """Truncate text to fit within max width"""
    if not text:
        return ""
    if len(text) <= max_width:
        return text
    return text[:max_width - 3] + "..."


class AgentTerminal:
    """Interactive terminal for agent_daemon"""

    def __init__(self, host, port, session_id, refresh_interval=2):
        self.host = host
        self.port = port
        self.session_id = session_id
        self.refresh_interval = refresh_interval
        self.base_url = f"http://{host}:{port}"
        self.running = True
        self.last_msg_count = 0
        self.last_processed_msg_id = None
        self.term_width = get_terminal_size()

        # Colors for terminal (simple ANSI codes)
        self.COLOR_USER = "\033[94m"      # Blue
        self.COLOR_ASSISTANT = "\033[92m"  # Green
        self.COLOR_SYSTEM = "\033[93m"     # Yellow
        self.COLOR_RESET = "\033[0m"
        self.COLOR_BOLD = "\033[1m"
        self.COLOR_DIM = "\033[2m"

    def get_messages(self, order_by='asc'):
        """Retrieve messages from the session"""
        url = f"{self.base_url}/api/v1/message"
        params = {
            "session_id": self.session_id,
            "order_by": order_by,
            "limit": 1000,
        }

        try:
            response = requests.get(url, params=params, timeout=10)
            if response.status_code == 200:
                result = response.json()
                if result.get("code") == 0:
                    return result.get("data", [])
            logger.warning("Failed to get messages: %s", result.get('message', 'Unknown error'))
        except requests.exceptions.ConnectionError:
            logger.warning("Cannot connect to server at %s", self.base_url)
        except Exception as e:
            logger.exception("Error getting messages: %s", e)
        return []

    def send_message(self, message, role='user'):
        """Send a message to the session"""
        url = f"{self.base_url}/api/v1/message"
        data = {
            "message": message,
            "session_id": self.session_id,
            "role": role,
        }

        try:
            response = requests.post(url, json=data, timeout=10)
            if response.status_code == 200:
                result = response.json()
                if result.get("code") == 0:
                    return True, "Message sent"
                return False, result.get('message', 'Unknown error')
            return False, f"HTTP {response.status_code}"
        except requests.exceptions.ConnectionError:
            return False, "Cannot connect to server"
        except Exception as e:
            logger.exception("Error sending message: %s", e)
            return False, str(e)

    def get_session_info(self):
        """Get session information"""
        url = f"{self.base_url}/api/v1/session"
        params = {
            "session_ids": [self.session_id],
            "limit": 1,
        }

        try:
            response = requests.get(url, params=params, timeout=10)
            if response.status_code == 200:
                result = response.json()
                if result.get("code") == 0:
                    sessions = result.get("data", [])
                    if sessions:
                        return sessions[0]
        except Exception as e:
            logger.exception("Error getting session info: %s", e)
        return None

    def display_header(self):
        """Display terminal header"""
        print(self.COLOR_BOLD)
        print(SPLIT_LINE)
        print(f"  topsailai_agent_terminal".center(self.term_width))
        print(f"  Session: {self.session_id}".center(self.term_width))
        print(f"  Server: {self.host}:{self.port}".center(self.term_width))
        print(f"  Auto-refresh: {self.refresh_interval}s".center(self.term_width))
        print(SPLIT_LINE)
        print(self.COLOR_RESET)
        print()

    def display_messages(self, messages):
        """Display messages in chat format"""
        if not messages:
            print(self.COLOR_DIM + "  No messages yet..." + self.COLOR_RESET)
            return

        for msg in messages:
            role = msg.get('role', 'unknown')
            content = msg.get('message', '')
            create_time = format_time(msg.get('create_time'))
            msg_id = msg.get('msg_id', '')[:8]
            task_id = msg.get('task_id')
            task_result = msg.get('task_result')

            # Role label and color
            if role == 'user':
                role_label = "USER"
                color = self.COLOR_USER
            elif role == 'assistant':
                role_label = "BOT"
                color = self.COLOR_ASSISTANT
            else:
                role_label = role.upper()
                color = self.COLOR_SYSTEM

            # Display message
            print(MSG_SEPARATOR)
            print(f"{color}{self.COLOR_BOLD}[{create_time}] {role_label}{self.COLOR_RESET}")

            # Word wrap the message content
            max_content_width = self.term_width - 2
            lines = content.split('\n')
            for line in lines:
                # Simple word wrap
                words = line.split()
                current_line = ""
                for word in words:
                    if len(current_line) + len(word) + 1 <= max_content_width:
                        current_line += (" " if current_line else "") + word
                    else:
                        if current_line:
                            print(f"  {current_line}")
                        current_line = word
                if current_line:
                    print(f"  {current_line}")

            # Display task info if exists
            if task_id:
                print()
                print(f"{self.COLOR_DIM}  >> task_id: {task_id[:16]}...{self.COLOR_RESET}")
            if task_result:
                # Truncate task result for display
                result_preview = task_result[:200] + "..." if len(task_result) > 200 else task_result
                print(f"{self.COLOR_DIM}  >> result: {result_preview}{self.COLOR_RESET}")

        print(MSG_SEPARATOR)

    def display_status_bar(self, msg_count, processed_msg_id):
        """Display status bar at the bottom"""
        print()
        print(SPLIT_LINE)
        status = f"Messages: {msg_count}"
        if processed_msg_id:
            status += f" | Processed: {processed_msg_id[:8]}..."
        print(f"  {status}".ljust(self.term_width))
        print(f"  Type your message and press Enter to send | Ctrl+C to exit".ljust(self.term_width))
        print(SPLIT_LINE)

    def refresh_display(self):
        """Refresh the display with current messages"""
        clear_screen()
        self.display_header()

        messages = self.get_messages()
        self.display_messages(messages)

        # Get session info for processed_msg_id
        session_info = self.get_session_info()
        processed_msg_id = session_info.get('processed_msg_id') if session_info else None

        self.display_status_bar(len(messages), processed_msg_id)

        # Check if there are new messages
        current_msg_count = len(messages)
        has_new_messages = current_msg_count > self.last_msg_count
        self.last_msg_count = current_msg_count
        self.last_processed_msg_id = processed_msg_id

        return has_new_messages

    def run(self):
        """Run the interactive terminal"""
        # Initial display
        self.refresh_display()

        # Auto-refresh loop
        print()
        print(f"{self.COLOR_DIM}  Connecting to session...{self.COLOR_RESET}")

        while self.running:
            try:
                # Wait for input or timeout
                print()
                print(f"{self.COLOR_BOLD}You:{self.COLOR_RESET} ", end="", flush=True)

                # Use input with timeout for auto-refresh
                try:
                    user_input = input()
                except EOFError:
                    break

                if user_input.strip():
                    # Send the message
                    success, msg = self.send_message(user_input.strip())
                    if success:
                        logger.info("Message sent successfully")
                    else:
                        print(f"{self.COLOR_SYSTEM}  Error: {msg}{self.COLOR_RESET}")
                        logger.warning("Failed to send message: %s", msg)

                    # Refresh display after sending
                    time.sleep(0.5)  # Brief delay to allow server to process
                    self.refresh_display()
                else:
                    # Empty input - just refresh
                    self.refresh_display()

            except KeyboardInterrupt:
                print()
                print(f"\n{self.COLOR_DIM}  Exiting...{self.COLOR_RESET}")
                self.running = False
            except Exception as e:
                logger.exception("Terminal error: %s", e)
                print(f"{self.COLOR_SYSTEM}  Error: {e}{self.COLOR_RESET}")
                time.sleep(1)

        print(f"\n{self.COLOR_BOLD}Goodbye!{self.COLOR_RESET}")


def main():
    """Main entry point"""
    parser = argparse.ArgumentParser(
        description='Interactive terminal for agent_daemon',
        prog='topsailai_agent_terminal'
    )
    parser.add_argument(
        '--host',
        type=str,
        default=DEFAULT_HOST,
        help=f'Server host (default: {DEFAULT_HOST}, env: TOPSAILAI_AGENT_DAEMON_HOST)'
    )
    parser.add_argument(
        '--port',
        type=int,
        default=DEFAULT_PORT,
        help=f'Server port (default: {DEFAULT_PORT}, env: TOPSAILAI_AGENT_DAEMON_PORT)'
    )
    parser.add_argument(
        '--session-id',
        type=str,
        default=DEFAULT_SESSION_ID,
        help=f'Session ID to connect to (default: {DEFAULT_SESSION_ID})'
    )
    parser.add_argument(
        '--refresh-interval',
        type=int,
        default=2,
        help='Auto-refresh interval in seconds (default: 2)'
    )

    args = parser.parse_args()

    # Create and run terminal
    terminal = AgentTerminal(
        host=args.host,
        port=args.port,
        session_id=args.session_id,
        refresh_interval=args.refresh_interval
    )

    try:
        terminal.run()
    except KeyboardInterrupt:
        print("\nExited.")
        sys.exit(0)


if __name__ == '__main__':
    main()
