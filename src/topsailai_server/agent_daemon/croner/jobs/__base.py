'''
  Author: DawsonLin
  Email: lin_dongsen@126.com
  Created: 2026-04-12
  Purpose: Cron job base class for agent daemon
'''

from abc import ABC, abstractmethod
from datetime import datetime, timedelta
from typing import Optional

from topsailai_server.agent_daemon.storage import Storage
from topsailai_server.agent_daemon.worker import WorkerManager


class CronJobBase(ABC):
    """
    Abstract base class for cron jobs.
    
    All cron jobs should inherit from this class and implement the run() method.
    The base class provides:
    - Interval-based execution control
    - Storage and WorkerManager access
    - Last run time tracking
    """
    
    def __init__(
        self, 
        interval_seconds: int, 
        storage: Optional[Storage] = None,
        worker_manager: Optional[WorkerManager] = None
    ):
        """
        Initialize the cron job.
        
        Args:
            interval_seconds: How often the job should run (in seconds)
            storage: Storage instance for database operations
            worker_manager: WorkerManager instance for managing workers
        """
        self.interval_seconds = interval_seconds
        self.storage = storage
        self.worker_manager = worker_manager
        self.last_run: Optional[datetime] = None
    
    @abstractmethod
    def run(self) -> None:
        """
        Execute the cron job.
        
        Subclasses must implement this method with their specific logic.
        """
        pass
    
    def should_run(self) -> bool:
        """
        Check if the job should run based on the interval.
        
        Returns:
            True if the job should run, False otherwise
        """
        if self.last_run is None:
            return True
        return datetime.now() - self.last_run >= timedelta(seconds=self.interval_seconds)
    
    def mark_run(self) -> None:
        """
        Mark the job as having run.
        
        Should be called at the end of successful execution.
        """
        self.last_run = datetime.now()
    
    def get_name(self) -> str:
        """
        Get the name of the job.
        
        Returns:
            The class name of the job
        """
        return self.__class__.__name__
