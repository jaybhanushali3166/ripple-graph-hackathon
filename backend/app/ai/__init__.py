"""Ripple AI layer: Decision extraction, tool-calling bounded agent, and grounded drafting.

All public functions and classes for the AI layer are exposed here.
Provider initialization is lazy: importing this package does not require
a secret or make a network connection.
"""

from backend.app.ai.agent import (
    StaleEvidenceError,
    run_agent,
)
from backend.app.ai.extraction import (
    extract_decision,
)
from backend.app.ai.grounding import (
    GroundingValidationError,
    build_grounded_answer,
    validate_citations_list,
    validate_draft,
    verify_citation_exact_quote,
)
from backend.app.ai.provider import (
    AIProviderError,
    AgentStepResult,
    DeterministicTestDouble,
    ExtractionValidationError,
    GeminiProvider,
    LLMProvider,
    OllamaProvider,
    ProviderAuthenticationError,
    ProviderSchemaError,
    ProviderTimeoutError,
    ReviewRequiredError,
    ToolCall,
    get_provider,
)
from backend.app.ai.tools import (
    MAX_TOOL_CALLS,
    TOOL_DECLARATIONS,
    AgentTools,
    ToolBudgetExceededError,
)

__all__ = [
    "run_agent",
    "extract_decision",
    "AgentTools",
    "MAX_TOOL_CALLS",
    "TOOL_DECLARATIONS",
    "ToolBudgetExceededError",
    "StaleEvidenceError",
    "LLMProvider",
    "OllamaProvider",
    "GeminiProvider",
    "DeterministicTestDouble",
    "ToolCall",
    "AgentStepResult",
    "get_provider",
    "AIProviderError",
    "ProviderTimeoutError",
    "ProviderSchemaError",
    "ProviderAuthenticationError",
    "ReviewRequiredError",
    "ExtractionValidationError",
    "GroundingValidationError",
    "validate_draft",
    "validate_citations_list",
    "verify_citation_exact_quote",
    "build_grounded_answer",
]
