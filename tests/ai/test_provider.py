"""Unit tests for AI provider boundary, test doubles, and error mapping."""

import pytest
from pydantic import BaseModel

from backend.app.ai.provider import (
    AIProviderError,
    DeterministicTestDouble,
    OllamaProvider,
    ProviderAuthenticationError,
    ProviderSchemaError,
    ProviderTimeoutError,
    _format_messages_for_ollama,
    _format_tools_for_ollama,
    get_provider,
)


class DummySchema(BaseModel):
    name: str
    count: int


@pytest.mark.asyncio
async def test_provider_lazy_initialization():
    """Importing and instantiating OllamaProvider does not require key or make network calls."""
    provider = OllamaProvider()
    assert provider.model == "llama3.3"
    assert provider.base_url == "https://ollama.com"
    assert provider.api_key is None


@pytest.mark.asyncio
async def test_provider_raises_auth_error_when_called_without_key():
    """Invoking OllamaProvider targeting Ollama Cloud without an API key raises ProviderAuthenticationError."""
    provider = OllamaProvider(api_key=None, base_url="https://ollama.com")
    with pytest.raises(ProviderAuthenticationError, match="API key is not configured"):
        await provider.generate_text("Hello")

    with pytest.raises(ProviderAuthenticationError, match="API key is not configured"):
        await provider.generate_structured("Hello", DummySchema)


@pytest.mark.asyncio
async def test_provider_bearer_auth_headers():
    """OllamaProvider attaches Bearer token header when API key is provided."""
    provider = OllamaProvider(api_key="ollama_sec_123", base_url="https://ollama.com")
    headers = provider._headers()
    assert headers["Authorization"] == "Bearer ollama_sec_123"
    assert headers["Content-Type"] == "application/json"


@pytest.mark.asyncio
async def test_provider_local_endpoint_allows_no_key():
    """Local Ollama instance does not require an API key in headers."""
    provider = OllamaProvider(api_key=None, base_url="http://localhost:11434")
    headers = provider._headers()
    assert "Authorization" not in headers
    assert headers["Content-Type"] == "application/json"


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
    """Factory returns test double if supplied, otherwise OllamaProvider."""
    double = DeterministicTestDouble()
    p1 = get_provider(test_double=double)
    assert p1 is double

    p2 = get_provider(api_key="secret", model="llama-custom", base_url="https://ollama.com")
    assert isinstance(p2, OllamaProvider)
    assert p2.model == "llama-custom"
    assert p2.base_url == "https://ollama.com"


def test_ollama_tools_formatting():
    """_format_tools_for_ollama wraps tool declarations in standard OpenAI/Ollama schema."""
    raw_tools = [
        {
            "name": "lookup",
            "description": "Lookup entity",
            "parameters": {
                "type": "OBJECT",
                "properties": {"id": {"type": "STRING"}},
            },
        }
    ]
    formatted = _format_tools_for_ollama(raw_tools)
    assert len(formatted) == 1
    assert formatted[0]["type"] == "function"
    assert formatted[0]["function"]["name"] == "lookup"
    # Type was normalized to lowercase
    assert formatted[0]["function"]["parameters"]["type"] == "object"
    assert formatted[0]["function"]["parameters"]["properties"]["id"]["type"] == "string"


def test_ollama_messages_formatting():
    """_format_messages_for_ollama formats assistant tool calls and tool responses."""
    internal_msgs = [
        {"role": "user", "text": "What happened?"},
        {
            "role": "model",
            "function_calls": [{"name": "get_source", "args": {"source_id": "src_1"}}],
        },
        {
            "role": "function",
            "function_responses": [{"name": "get_source", "response": {"title": "Doc 1"}}],
        },
    ]
    formatted = _format_messages_for_ollama(internal_msgs, system_prompt="You are helpful.")
    assert len(formatted) == 4
    assert formatted[0]["role"] == "system"
    assert formatted[0]["content"] == "You are helpful."
    assert formatted[1]["role"] == "user"
    assert formatted[1]["content"] == "What happened?"
    assert formatted[2]["role"] == "assistant"
    assert formatted[2]["tool_calls"][0]["function"]["name"] == "get_source"
    assert formatted[3]["role"] == "tool"
    assert formatted[3]["name"] == "get_source"
    assert "Doc 1" in formatted[3]["content"]

