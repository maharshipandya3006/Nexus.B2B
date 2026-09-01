import time
import threading
from typing import Optional, Dict, Tuple
from slowapi import Limiter
from slowapi.util import get_remote_address
from .config import settings

# Global SlowAPI Limiter instance
limiter = Limiter(key_func=get_remote_address, default_limits=[])


class AccountLockoutManager:
    """
    Thread-safe in-memory manager to track failed authentication attempts
    and temporarily lock accounts targeted by brute-force attacks.
    """

    def __init__(self, max_attempts: int = 5, lockout_duration_seconds: int = 900):
        self.max_attempts = max_attempts
        self.lockout_duration_seconds = lockout_duration_seconds
        # username -> (failed_count, lockout_timestamp, last_attempt_timestamp)
        self._records: Dict[str, Tuple[int, Optional[float], float]] = {}
        self._lock = threading.Lock()

    def _normalize(self, username: str) -> str:
        return username.strip().lower()

    def check_lockout(self, username: str) -> Optional[int]:
        """
        Returns remaining locked seconds if account is currently locked, otherwise None.
        Automatically lifts lockout if expiration has elapsed.
        """
        norm = self._normalize(username)
        now = time.time()

        with self._lock:
            if norm not in self._records:
                return None

            count, locked_at, last_seen = self._records[norm]
            if locked_at is not None:
                elapsed = now - locked_at
                if elapsed < self.lockout_duration_seconds:
                    return int(self.lockout_duration_seconds - elapsed)
                else:
                    # Lockout expired: reset failed attempts
                    del self._records[norm]
                    return None

            return None

    def record_failure(self, username: str) -> Tuple[int, bool, Optional[int]]:
        """
        Records a failed attempt.
        Returns: (current_failed_count, is_now_locked, remaining_lockout_seconds)
        """
        norm = self._normalize(username)
        now = time.time()

        with self._lock:
            # First clean up stale entries (idle for over 1 hour)
            self._prune_stale(now)

            if norm not in self._records:
                if self.max_attempts <= 1:
                    self._records[norm] = (1, now, now)
                    return (1, True, self.lockout_duration_seconds)
                else:
                    self._records[norm] = (1, None, now)
                    return (1, False, None)

            count, locked_at, _ = self._records[norm]

            # If already locked, calculate remaining
            if locked_at is not None:
                remaining = int(self.lockout_duration_seconds - (now - locked_at))
                if remaining > 0:
                    return (count, True, remaining)
                else:
                    # Reset after expiry
                    count = 0

            new_count = count + 1
            if new_count >= self.max_attempts:
                self._records[norm] = (new_count, now, now)
                return (new_count, True, self.lockout_duration_seconds)
            else:
                self._records[norm] = (new_count, None, now)
                return (new_count, False, None)

    def reset_attempts(self, username: str):
        """Resets failed attempt count upon successful authentication."""
        norm = self._normalize(username)
        with self._lock:
            self._records.pop(norm, None)

    def clear_all(self):
        """Clears all tracked lockout records (useful for test resets)."""
        with self._lock:
            self._records.clear()

    def _prune_stale(self, now: float):
        """Helper to evict old tracked items to prevent unbounded memory growth."""
        stale_keys = []
        for k, (_, locked_at, last_seen) in self._records.items():
            if last_seen is None:
                continue
            is_idle = (now - last_seen) > 3600
            is_unlocked_or_expired = (locked_at is None) or ((now - locked_at) > self.lockout_duration_seconds)
            if is_idle and is_unlocked_or_expired:
                stale_keys.append(k)

        for k in stale_keys:
            del self._records[k]


# Singleton instance configured from settings
lockout_manager = AccountLockoutManager(
    max_attempts=settings.ACCOUNT_LOCKOUT_MAX_ATTEMPTS,
    lockout_duration_seconds=settings.ACCOUNT_LOCKOUT_DURATION_MINUTES * 60,
)
