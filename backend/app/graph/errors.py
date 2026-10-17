"""Typed graph errors. Pavan maps these into the HTTP error contract."""


class GraphError(Exception):
    """Base class for every error raised by the graph layer."""

    def __init__(self, message="", details=None):
        super().__init__(message)
        self.message = message
        self.details = details or {}


class GraphUnavailable(GraphError):
    """The database could not be reached or timed out."""


class NotFound(GraphError):
    """A requested ID (or the seeded graph itself) does not exist."""


class FixtureError(GraphError):
    """A fixture import was rejected, for example because of a dependency cycle."""


# Placeholders for the mutation work (confirm_decision, save_action).
class StaleEvidence(GraphError):
    """The caller's expected evidence version is no longer current."""


class IdempotencyConflict(GraphError):
    """An idempotency key was reused with a different request."""


class ReviewRequired(GraphError):
    """The proposal cannot be applied without a fresh human review."""


class InconsistentRead(GraphError):
    """The knowledge revision kept changing while a multi-query read was running."""
