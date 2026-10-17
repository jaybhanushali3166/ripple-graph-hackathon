"""Domain exceptions and error mapping for Ripple."""

from typing import Any


class RippleError(Exception):
    """Base exception for all Ripple domain errors."""

    code: str = "internal_error"
    status_code: int = 500

    def __init__(self, message: str, details: Any = None):
        super().__init__(message)
        self.message = message
        self.details = details


class GraphError(RippleError):
    """Base exception for graph-related failures."""

    code: str = "graph_error"
    status_code: int = 500


class GraphUnavailableError(GraphError):
    """Raised when FalkorDB is unreachable or fails to respond."""

    code: str = "graph_unavailable"
    status_code: int = 503


class EntityNotFoundError(RippleError):
    """Raised when a requested entity or source does not exist."""

    code: str = "not_found"
    status_code: int = 404


class StaleVersionError(RippleError):
    """Raised when expected_version does not match the active knowledge revision."""

    code: str = "stale_evidence"
    status_code: int = 409


class IdempotencyConflictError(RippleError):
    """Raised when an idempotency key is reused with a different payload."""

    code: str = "idempotency_conflict"
    status_code: int = 409


class PreviewExpiredError(RippleError):
    """Raised when a proposal preview has passed its TTL."""

    code: str = "preview_expired"
    status_code: int = 410


class ReviewRequiredError(RippleError):
    """Raised when extraction or input contains ambiguity requiring human review."""

    code: str = "review_required"
    status_code: int = 422


class AIUnavailableError(RippleError):
    """Raised when the AI provider fails and no useful partial response is possible."""

    code: str = "ai_unavailable"
    status_code: int = 502
