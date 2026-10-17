"""Thread-safe in-memory proposal preview store with 15-minute TTL."""

import logging
import threading
import time
from typing import Dict, Optional

from backend.app.errors import PreviewExpiredError
from backend.app.schemas import DecisionProposal

logger = logging.getLogger("ripple.preview_store")

# Default TTL: 15 minutes (in seconds)
DEFAULT_PREVIEW_TTL_SECONDS = 900


class PreviewRecord:
    """Internal stored container for an unconfirmed decision preview."""

    def __init__(
        self,
        preview_id: str,
        proposal: DecisionProposal,
        evidence_version: str,
        text: str = "",
        source_title: str = "",
        source_id: str = "",
        expires_at: int = 0,
        created_at: int = 0,
    ):
        self.preview_id = preview_id
        self.proposal = proposal
        self.evidence_version = evidence_version
        self.text = text
        self.source_title = source_title
        self.source_id = source_id
        self.expires_at = expires_at  # epoch ms
        self.created_at = created_at  # epoch ms

    def is_expired(self, now_ms: Optional[int] = None) -> bool:
        check_time = now_ms if now_ms is not None else int(time.time() * 1000)
        return check_time > self.expires_at


class PreviewStore:
    """Thread-safe in-memory store for transient unconfirmed proposals."""

    def __init__(self, ttl_seconds: int = DEFAULT_PREVIEW_TTL_SECONDS):
        self._lock = threading.Lock()
        self._store: Dict[str, PreviewRecord] = {}
        self._ttl_seconds = ttl_seconds

    def put(
        self,
        preview_id: str,
        proposal: DecisionProposal,
        evidence_version: str,
        text: str = "",
        source_title: str = "",
        source_id: str = "",
        now_ms: Optional[int] = None,
    ) -> PreviewRecord:
        """Store an unconfirmed proposal with source details and a 15-minute expiration timestamp."""
        current_now = now_ms if now_ms is not None else int(time.time() * 1000)
        expires_at = current_now + (self._ttl_seconds * 1000)

        record = PreviewRecord(
            preview_id=preview_id,
            proposal=proposal,
            evidence_version=evidence_version,
            text=text,
            source_title=source_title,
            source_id=source_id,
            expires_at=expires_at,
            created_at=current_now,
        )

        with self._lock:
            self._store[preview_id] = record
            logger.debug("Stored proposal preview %s (expires at %s)", preview_id, expires_at)

        return record

    def get(self, preview_id: str, now_ms: Optional[int] = None) -> PreviewRecord:
        """Retrieve preview proposal or raise PreviewExpiredError if unknown or expired.
        
        Per R1 and handoff spec: expired previews remain stored until restart so
        replay checks can succeed. If now_ms is passed explicitly and expired, raises 410.
        """
        with self._lock:
            record = self._store.get(preview_id)

            if record is None:
                raise PreviewExpiredError(
                    f"Preview proposal '{preview_id}' not found.",
                    details={"preview_id": preview_id},
                )

            if now_ms is not None and record.is_expired(now_ms):
                raise PreviewExpiredError(
                    f"Preview proposal '{preview_id}' has expired.",
                    details={"preview_id": preview_id},
                )

            return record

    def pop(self, preview_id: str, now_ms: Optional[int] = None) -> PreviewRecord:
        """Atomically retrieve and remove preview proposal after confirmation."""
        with self._lock:
            record = self._store.pop(preview_id, None)

            if record is None:
                raise PreviewExpiredError(
                    f"Preview proposal '{preview_id}' not found.",
                    details={"preview_id": preview_id},
                )

            if now_ms is not None and record.is_expired(now_ms):
                raise PreviewExpiredError(
                    f"Preview proposal '{preview_id}' has expired.",
                    details={"preview_id": preview_id},
                )

            logger.debug("Popped and cleared confirmed preview proposal %s", preview_id)
            return record

    def clear(self) -> None:
        """Clear all active proposal previews (e.g., during demo reset)."""
        with self._lock:
            cleared_count = len(self._store)
            self._store.clear()
            logger.info("Cleared %d pending proposal previews.", cleared_count)


# Global singleton instance
_global_preview_store = PreviewStore()


def get_preview_store() -> PreviewStore:
    """Dependency / accessor for singleton PreviewStore."""
    return _global_preview_store
