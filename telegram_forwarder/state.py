"""State management for tracking job progress and enabling resume."""

import json
import uuid
from dataclasses import dataclass, asdict, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Optional, List, Dict, Any


class JobStatus(Enum):
    """Status of a forwarding job."""
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    INTERRUPTED = "interrupted"
    FAILED = "failed"


class JobType(Enum):
    """Type of forwarding job."""
    FORWARD_LAST = "forward-last"
    FORWARD_ALL = "forward-all"
    FORWARD_LIVE = "forward-live"


@dataclass
class Job:
    """Represents a forwarding job with progress tracking."""
    job_id: str
    job_type: str
    source: int
    destinations: List[int]
    status: str = JobStatus.PENDING.value
    
    # Progress tracking
    last_message_id: int = 0
    total_processed: int = 0
    total_messages: int = 0
    total_skipped: int = 0
    total_failed: int = 0
    
    # Options
    drop_author: bool = False
    delete_after: bool = False
    batch_size: int = 100
    count: Optional[int] = None  # For forward-last
    
    # Timestamps
    started_at: Optional[str] = None
    updated_at: Optional[str] = None
    completed_at: Optional[str] = None
    
    # Error info
    last_error: Optional[str] = None
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert job to dictionary for JSON serialization."""
        return asdict(self)
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Job":
        """Create job from dictionary."""
        return cls(**data)
    
    def is_resumable(self) -> bool:
        """Check if job can be resumed."""
        return (
            self.status == JobStatus.INTERRUPTED.value and
            self.job_type in (JobType.FORWARD_ALL.value, JobType.FORWARD_LAST.value) and
            self.last_message_id > 0
        )


class StateManager:
    """Manages job state persistence and resume functionality."""
    
    def __init__(self, jobs_file: Path):
        """Initialize state manager.
        
        Args:
            jobs_file: Path to jobs JSON file
        """
        self.jobs_file = jobs_file
        self._jobs: Dict[str, Job] = {}
        self._current_job_id: Optional[str] = None
        self._load()
    
    def _load(self):
        """Load jobs from file."""
        if not self.jobs_file.exists():
            self._jobs = {}
            return
        
        try:
            with open(self.jobs_file, 'r') as f:
                data = json.load(f)
                self._jobs = {
                    job_id: Job.from_dict(job_data)
                    for job_id, job_data in data.get('jobs', {}).items()
                }
        except (json.JSONDecodeError, IOError, KeyError):
            self._jobs = {}
    
    def _save(self):
        """Save jobs to file."""
        data = {
            'jobs': {
                job_id: job.to_dict()
                for job_id, job in self._jobs.items()
            }
        }
        
        with open(self.jobs_file, 'w') as f:
            json.dump(data, f, indent=2)
    
    @property
    def current_job_id(self) -> Optional[str]:
        """Get current job ID."""
        return self._current_job_id
    
    def create_job(
        self,
        job_type: JobType,
        source: int,
        destinations: List[int],
        drop_author: bool = False,
        delete_after: bool = False,
        batch_size: int = 100,
        count: Optional[int] = None,
        total_messages: int = 0
    ) -> Job:
        """Create a new job.
        
        Args:
            job_type: Type of job
            source: Source chat ID
            destinations: List of destination chat IDs
            drop_author: Whether to drop author
            delete_after: Whether to delete after forwarding
            batch_size: Batch size
            count: Message count for forward-last
            total_messages: Estimated total messages
            
        Returns:
            New Job instance
        """
        job_id = str(uuid.uuid4())[:8]
        
        job = Job(
            job_id=job_id,
            job_type=job_type.value,
            source=source,
            destinations=destinations,
            status=JobStatus.RUNNING.value,
            drop_author=drop_author,
            delete_after=delete_after,
            batch_size=batch_size,
            count=count,
            total_messages=total_messages,
            started_at=datetime.now().isoformat(),
            updated_at=datetime.now().isoformat(),
        )
        
        self._jobs[job_id] = job
        self._current_job_id = job_id
        self._save()
        
        return job
    
    def get_job(self, job_id: str) -> Optional[Job]:
        """Get a job by ID.
        
        Args:
            job_id: Job ID
            
        Returns:
            Job instance or None
        """
        return self._jobs.get(job_id)
    
    def get_current_job(self) -> Optional[Job]:
        """Get the current running job.
        
        Returns:
            Current Job instance or None
        """
        if self._current_job_id:
            return self._jobs.get(self._current_job_id)
        return None
    
    def list_jobs(self, status: Optional[JobStatus] = None) -> List[Job]:
        """List all jobs, optionally filtered by status.
        
        Args:
            status: Optional status filter
            
        Returns:
            List of jobs
        """
        jobs = list(self._jobs.values())
        
        if status:
            jobs = [j for j in jobs if j.status == status.value]
        
        # Sort by updated_at descending
        jobs.sort(key=lambda j: j.updated_at or '', reverse=True)
        
        return jobs
    
    def get_resumable_jobs(self) -> List[Job]:
        """Get all jobs that can be resumed.
        
        Returns:
            List of resumable jobs
        """
        return [j for j in self._jobs.values() if j.is_resumable()]
    
    def save_checkpoint(self, message_id: int, processed: int = 0, skipped: int = 0, failed: int = 0):
        """Save progress checkpoint for current job.
        
        Args:
            message_id: Last processed message ID
            processed: Number of messages processed in this batch
            skipped: Number of messages skipped in this batch
            failed: Number of messages failed in this batch
        """
        if not self._current_job_id:
            return
        
        job = self._jobs.get(self._current_job_id)
        if not job:
            return
        
        job.last_message_id = message_id
        job.total_processed += processed
        job.total_skipped += skipped
        job.total_failed += failed
        job.updated_at = datetime.now().isoformat()
        
        self._save()
    
    def update_progress(
        self,
        message_id: int,
        processed: int,
        skipped: int = 0,
        failed: int = 0
    ):
        """Update progress for current job (absolute values).
        
        Args:
            message_id: Last processed message ID
            processed: Total messages processed so far
            skipped: Total messages skipped so far
            failed: Total messages failed so far
        """
        if not self._current_job_id:
            return
        
        job = self._jobs.get(self._current_job_id)
        if not job:
            return
        
        job.last_message_id = message_id
        job.total_processed = processed
        job.total_skipped = skipped
        job.total_failed = failed
        job.updated_at = datetime.now().isoformat()
        
        self._save()
    
    def mark_interrupted(self, error: Optional[str] = None):
        """Mark current job as interrupted.
        
        Args:
            error: Optional error message
        """
        if not self._current_job_id:
            return
        
        job = self._jobs.get(self._current_job_id)
        if not job:
            return
        
        job.status = JobStatus.INTERRUPTED.value
        job.updated_at = datetime.now().isoformat()
        if error:
            job.last_error = error
        
        self._save()
        self._current_job_id = None
    
    def mark_completed(self):
        """Mark current job as completed."""
        if not self._current_job_id:
            return
        
        job = self._jobs.get(self._current_job_id)
        if not job:
            return
        
        job.status = JobStatus.COMPLETED.value
        job.completed_at = datetime.now().isoformat()
        job.updated_at = datetime.now().isoformat()
        
        self._save()
        self._current_job_id = None
    
    def mark_failed(self, error: str):
        """Mark current job as failed.
        
        Args:
            error: Error message
        """
        if not self._current_job_id:
            return
        
        job = self._jobs.get(self._current_job_id)
        if not job:
            return
        
        job.status = JobStatus.FAILED.value
        job.last_error = error
        job.updated_at = datetime.now().isoformat()
        
        self._save()
        self._current_job_id = None
    
    def resume_job(self, job_id: str) -> Optional[Job]:
        """Resume an interrupted job.
        
        Args:
            job_id: Job ID to resume
            
        Returns:
            Job instance if resumable, None otherwise
        """
        job = self._jobs.get(job_id)
        if not job or not job.is_resumable():
            return None
        
        job.status = JobStatus.RUNNING.value
        job.updated_at = datetime.now().isoformat()
        self._current_job_id = job_id
        
        self._save()
        
        return job
    
    def delete_job(self, job_id: str) -> bool:
        """Delete a job from history.
        
        Args:
            job_id: Job ID to delete
            
        Returns:
            True if deleted, False if not found
        """
        if job_id in self._jobs:
            del self._jobs[job_id]
            self._save()
            return True
        return False
    
    def cleanup_old_jobs(self, max_age_days: int = 30):
        """Remove old completed jobs.
        
        Args:
            max_age_days: Maximum age in days for completed jobs
        """
        now = datetime.now()
        to_delete = []
        
        for job_id, job in self._jobs.items():
            if job.status != JobStatus.COMPLETED.value:
                continue
            
            if job.completed_at:
                completed = datetime.fromisoformat(job.completed_at)
                age = (now - completed).days
                if age > max_age_days:
                    to_delete.append(job_id)
        
        for job_id in to_delete:
            del self._jobs[job_id]
        
        if to_delete:
            self._save()


def get_state_manager(jobs_file: Path) -> StateManager:
    """Get a StateManager instance.
    
    Args:
        jobs_file: Path to jobs file
        
    Returns:
        StateManager instance
    """
    return StateManager(jobs_file)
