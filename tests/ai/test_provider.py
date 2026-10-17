"""Unit tests for AI provider boundary, test doubles, and error mapping."""

import pytest
from pydantic import BaseModel

from backend.app.ai.provider import (
    AIProviderError,
    DeterministicTestDouble,
    GeminiProvider,
    ProviderAuthenticationError,
    ProviderSchemaError,
    ProviderTimeoutError,
    get_provider,
)


class DummySchema(BaseModel):
    name: str
    count: int


@pytest.mark.asyncio
async def test_provider_lazy_initialization():
    """Importing and instantiating GeminiProvider does not require key or make network calls."""
    provider = GeminiProvider()
    assert provider.model == "gemini-2.0-flash"
    assert provider.api_key is None


@pytest.mark.asyncio
async def test_provider_raises_auth_error_when_called_without_key():
    """Invoking GeminiProvider without an API key raises ProviderAuthenticationError."""
    provider = GeminiProvider(api_key=None)
    with pytest.raises(ProviderAuthenticationError, match="API key is not configured"):
        await provider.generate_text("Hello")

    with pytest.raises(ProviderAuthenticationError, match="API key is not configured"):
        await provider.generate_structured("Hello", DummySchema)


@pytest.mark.asyncio
async def test_deterministic_test_double_text():
    """DeterministicTestDouble returns configured text responses."""
    double = DeterministicTestDouble(text_responses={"impact": "Impact is high"})
    res = await double.generate_text("Tell me about the impact")
    assert res == "Impact is high"
    assert len(double.call_history) == 1


@pytest.mark.asyncio
async def test_deterministic_test_double_structured():
    """DeterministicTestDouble returns configured structured responses."""
    expected = DummySchema(name="Acme", count=42)
    double = DeterministicTestDouble(structured_responses={"test": expected})
    res = await double.generate_structured("Run test", DummySchema)
    assert res == expected
    assert res.name == "Acme"
    assert res.count == 42


@pytest.mark.asyncio
async def test_deterministic_test_double_forced_timeout():
    """DeterministicTestDouble cleanly simulates timeout errors."""
    double = DeterministicTestDouble(force_timeout=True)
    with pytest.raises(ProviderTimeoutError, match="simulated timeout"):
        await double.generate_text("Prompt")


@pytest.mark.asyncio
async def test_deterministic_test_double_forced_schema_error():
    """DeterministicTestDouble cleanly simulates schema errors."""
    double = DeterministicTestDouble(force_schema_error=True)
    with pytest.raises(ProviderSchemaError, match="simulated schema error"):
        await double.generate_structured("Prompt", DummySchema)


@pytest.mark.asyncio
async def test_get_provider_factory():
    """Factory returns test double if supplied, otherwise GeminiProvider."""
    double = DeterministicTestDouble()
    p1 = get_provider(test_double=double)
    assert p1 is double

    p2 = get_provider(api_key="secret", model="gemini-custom")
    assert isinstance(p2, GeminiProvider)
    assert p2.model == "gemini-custom"

