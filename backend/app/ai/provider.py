"""LLM Provider boundary for Ripple AI layer.

Provides lazy-initialized model clients, deterministic test doubles,
and clean error mapping for timeouts and schema failures.
Importing this module never makes a network request or requires an API key.
"""

from __future__ import annotations

import json
from abc import ABC, abstractmethod
from typing import Any, Callable, TypeVar

import httpx
from pydantic import BaseModel, Field, ValidationError

T = TypeVar("T", bound=BaseModel)


class AIProviderError(Exception):
    """Base exception for all AI provider failures."""

    def __init__(self, message: str, details: Any = None) -> None:
        super().__init__(message)
        self.message = message
        self.details = details


class ProviderTimeoutError(AIProviderError):
    """Raised when an LLM provider request times out."""


class ProviderSchemaError(AIProviderError):
    """Raised when an LLM provider returns unparseable or schema-violating output."""


class ProviderAuthenticationError(AIProviderError):
    """Raised when the LLM provider is invoked without a required API key."""


class ReviewRequiredError(AIProviderError):
    """Raised when an extracted note or proposal requires human review."""

    def __init__(self, reason: str, field: str | None = None, details: Any = None) -> None:
        super().__init__(f"Review required: {reason}", details=details)
        self.reason = reason
        self.field = field


class ExtractionValidationError(AIProviderError):
    """Raised when extraction outputs fail server-side candidate or quotation verification."""


class ToolCall(BaseModel):
    """Represents a tool call chosen by the model."""

    name: str
    arguments: dict[str, Any] = Field(default_factory=dict)


class AgentStepResult(BaseModel):
    """Result of an agent tool execution step from the LLM."""

    tool_calls: list[ToolCall] = Field(default_factory=list)
    text: str | None = None


class LLMProvider(ABC):
    """Abstract interface for LLM operations."""

    @abstractmethod
    async def generate_text(
        self,
        prompt: str,
        system_prompt: str | None = None,
        timeout: float = 30.0,
    ) -> str:
        """Generate raw text response."""
        ...

    @abstractmethod
    async def generate_structured(
        self,
        prompt: str,
        schema: type[T],
        system_prompt: str | None = None,
        timeout: float = 30.0,
    ) -> T:
        """Generate structured response validated against a Pydantic schema."""
        ...

    @abstractmethod
    async def generate_tool_step(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        system_prompt: str | None = None,
        timeout: float = 30.0,
    ) -> AgentStepResult:
        """Execute a tool-calling step returning either tool invocations or final text."""
        ...


class GeminiProvider(LLMProvider):
    """Google Gemini API provider using httpx.

    Initialization is lazy: neither secret validation nor network connection
    happens during __init__.
    API keys are sent via the 'x-goog-api-key' header to avoid URL log leakage.
    """

    def __init__(
        self,
        api_key: str | None = None,
        model: str = "gemini-2.0-flash",
        base_url: str = "https://generativelanguage.googleapis.com/v1beta",
    ) -> None:
        self.api_key = api_key
        self.model = model
        self.base_url = base_url.rstrip("/")

    def _headers(self) -> dict[str, str]:
        if not self.api_key:
            raise ProviderAuthenticationError(
                "Gemini API key is not configured. Set LLM_API_KEY environment variable."
            )
        return {
            "x-goog-api-key": self.api_key,
            "Content-Type": "application/json",
        }

    async def generate_text(
        self,
        prompt: str,
        system_prompt: str | None = None,
        timeout: float = 30.0,
    ) -> str:
        headers = self._headers()
        endpoint = f"{self.base_url}/models/{self.model}:generateContent"

        contents = []
        if system_prompt:
            contents.append({"role": "user", "parts": [{"text": f"System context:\n{system_prompt}"}]})
            contents.append({"role": "model", "parts": [{"text": "Understood. I will follow all instructions and grounding constraints."}]})
        contents.append({"role": "user", "parts": [{"text": prompt}]})

        payload = {
            "contents": contents,
            "generationConfig": {
                "temperature": 0.1,
            },
        }

        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                response = await client.post(endpoint, json=payload, headers=headers)
        except httpx.TimeoutException as exc:
            raise ProviderTimeoutError(f"Gemini API request timed out after {timeout}s") from exc
        except httpx.HTTPError as exc:
            raise AIProviderError(f"Gemini HTTP connection error: {exc}") from exc

        if response.status_code in (401, 403):
            raise ProviderAuthenticationError(f"Gemini authentication failed (status {response.status_code})")
        if response.status_code != 200:
            raise AIProviderError(f"Gemini API error (status {response.status_code})")

        data = response.json()
        try:
            candidates = data.get("candidates", [])
            if not candidates:
                raise ProviderSchemaError("Gemini returned no candidates in response", details=data)
            parts = candidates[0].get("content", {}).get("parts", [])
            if not parts:
                raise ProviderSchemaError("Gemini returned empty parts list in response", details=data)
            return parts[0].get("text", "")
        except (KeyError, IndexError) as exc:
            raise ProviderSchemaError(f"Unexpected response structure from Gemini: {exc}", details=data) from exc

    async def generate_structured(
        self,
        prompt: str,
        schema: type[T],
        system_prompt: str | None = None,
        timeout: float = 30.0,
    ) -> T:
        headers = self._headers()
        endpoint = f"{self.base_url}/models/{self.model}:generateContent"

        contents = []
        if system_prompt:
            contents.append({"role": "user", "parts": [{"text": f"System context:\n{system_prompt}"}]})
            contents.append({"role": "model", "parts": [{"text": "Understood. I will strictly output JSON matching the requested schema."}]})

        json_schema_prompt = (
            f"{prompt}\n\nRespond ONLY with a valid JSON object matching this schema:\n"
            f"{json.dumps(schema.model_json_schema())}"
        )
        contents.append({"role": "user", "parts": [{"text": json_schema_prompt}]})

        payload = {
            "contents": contents,
            "generationConfig": {
                "temperature": 0.0,
                "responseMimeType": "application/json",
            },
        }

        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                response = await client.post(endpoint, json=payload, headers=headers)
        except httpx.TimeoutException as exc:
            raise ProviderTimeoutError(f"Gemini API structured request timed out after {timeout}s") from exc
        except httpx.HTTPError as exc:
            raise AIProviderError(f"Gemini HTTP connection error: {exc}") from exc

        if response.status_code in (401, 403):
            raise ProviderAuthenticationError(f"Gemini authentication failed (status {response.status_code})")
        if response.status_code != 200:
            raise AIProviderError(f"Gemini API error (status {response.status_code})")

        data = response.json()
        try:
            candidates = data.get("candidates", [])
            if not candidates:
                raise ProviderSchemaError("Gemini returned no candidates in response", details=data)
            parts = candidates[0].get("content", {}).get("parts", [])
            raw_text = parts[0].get("text", "")
            parsed_json = json.loads(raw_text)
            return schema.model_validate(parsed_json)
        except json.JSONDecodeError as exc:
            raise ProviderSchemaError(f"Failed to parse JSON from Gemini response: {exc}") from exc
        except ValidationError as exc:
            raise ProviderSchemaError(f"Gemini response did not conform to schema {schema.__name__}: {exc}") from exc
        except (KeyError, IndexError) as exc:
            raise ProviderSchemaError(f"Unexpected response structure from Gemini: {exc}", details=data) from exc

    async def generate_tool_step(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        system_prompt: str | None = None,
        timeout: float = 30.0,
    ) -> AgentStepResult:
        headers = self._headers()
        endpoint = f"{self.base_url}/models/{self.model}:generateContent"

        contents = []
        if system_prompt:
            contents.append({"role": "user", "parts": [{"text": f"System context:\n{system_prompt}"}]})
            contents.append({"role": "model", "parts": [{"text": "Understood. I will call available tools to look up graph facts before answering."}]})

        for msg in messages:
            role = "user" if msg["role"] == "user" else "model"
            parts = []
            if "text" in msg and msg["text"]:
                parts.append({"text": msg["text"]})
            if "function_call" in msg:
                parts.append({"functionCall": msg["function_call"]})
            if "function_response" in msg:
                # Gemini function responses are sent with role 'function' or 'user'
                role = "function"
                parts.append({"functionResponse": msg["function_response"]})
            if parts:
                contents.append({"role": role, "parts": parts})

        payload: dict[str, Any] = {
            "contents": contents,
            "generationConfig": {
                "temperature": 0.0,
            },
        }

        if tools:
            payload["tools"] = [{"functionDeclarations": tools}]

        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                response = await client.post(endpoint, json=payload, headers=headers)
        except httpx.TimeoutException as exc:
            raise ProviderTimeoutError(f"Gemini API tool step timed out after {timeout}s") from exc
        except httpx.HTTPError as exc:
            raise AIProviderError(f"Gemini HTTP connection error: {exc}") from exc

        if response.status_code in (401, 403):
            raise ProviderAuthenticationError(f"Gemini authentication failed (status {response.status_code})")
        if response.status_code != 200:
            raise AIProviderError(f"Gemini API error (status {response.status_code})")

        data = response.json()
        candidates = data.get("candidates", [])
        if not candidates:
            raise ProviderSchemaError("Gemini returned no candidates in tool step", details=data)

        parts = candidates[0].get("content", {}).get("parts", [])
        tool_calls: list[ToolCall] = []
        text_out: list[str] = []

        for p in parts:
            if "functionCall" in p:
                fc = p["functionCall"]
                tool_calls.append(ToolCall(name=fc.get("name", ""), arguments=fc.get("args", {})))
            if "text" in p and p["text"]:
                text_out.append(p["text"])

        return AgentStepResult(
            tool_calls=tool_calls,
            text="\n".join(text_out) if text_out else None,
        )


class DeterministicTestDouble(LLMProvider):
    """Deterministic test double for development, offline testing, and CI.

    Supports canned responses, tool step callbacks, and forced error conditions.
    IMPORTANT: Must never be silently used in place of a failing live provider
    in production.
    """

    def __init__(
        self,
        text_responses: dict[str, str] | None = None,
        structured_responses: dict[str, BaseModel] | None = None,
        tool_step_handler: Callable[[list[dict[str, Any]], list[dict[str, Any]]], AgentStepResult] | None = None,
        force_timeout: bool = False,
        force_schema_error: bool = False,
        force_auth_error: bool = False,
    ) -> None:
        self.text_responses = text_responses or {}
        self.structured_responses = structured_responses or {}
        self.tool_step_handler = tool_step_handler
        self.force_timeout = force_timeout
        self.force_schema_error = force_schema_error
        self.force_auth_error = force_auth_error
        self.call_history: list[dict[str, Any]] = []

    async def generate_text(
        self,
        prompt: str,
        system_prompt: str | None = None,
        timeout: float = 30.0,
    ) -> str:
        self.call_history.append({"type": "text", "prompt": prompt, "system_prompt": system_prompt})
        if self.force_timeout:
            raise ProviderTimeoutError("Test double: simulated timeout")
        if self.force_auth_error:
            raise ProviderAuthenticationError("Test double: simulated auth error")
        if self.force_schema_error:
            raise ProviderSchemaError("Test double: simulated schema error")

        for key, resp in self.text_responses.items():
            if key in prompt:
                return resp
        return "Deterministic test response"

    async def generate_structured(
        self,
        prompt: str,
        schema: type[T],
        system_prompt: str | None = None,
        timeout: float = 30.0,
    ) -> T:
        self.call_history.append({"type": "structured", "prompt": prompt, "schema": schema.__name__})
        if self.force_timeout:
            raise ProviderTimeoutError("Test double: simulated timeout")
        if self.force_auth_error:
            raise ProviderAuthenticationError("Test double: simulated auth error")
        if self.force_schema_error:
            raise ProviderSchemaError("Test double: simulated schema error")

        for key, resp in self.structured_responses.items():
            if key in prompt:
                if isinstance(resp, schema):
                    return resp
                if isinstance(resp, dict):
                    return schema.model_validate(resp)

        try:
            return schema.model_validate({})
        except ValidationError as exc:
            raise ProviderSchemaError(
                f"No deterministic response registered for prompt key, and schema {schema.__name__} has required fields."
            ) from exc

    async def generate_tool_step(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        system_prompt: str | None = None,
        timeout: float = 30.0,
    ) -> AgentStepResult:
        self.call_history.append({"type": "tool_step", "messages": messages, "tools_count": len(tools)})
        if self.force_timeout:
            raise ProviderTimeoutError("Test double: simulated timeout")
        if self.force_auth_error:
            raise ProviderAuthenticationError("Test double: simulated auth error")
        if self.force_schema_error:
            raise ProviderSchemaError("Test double: simulated schema error")

        if self.tool_step_handler:
            return self.tool_step_handler(messages, tools)

        # Default fallback: check if last user message matches any text response
        last_user = ""
        for m in reversed(messages):
            if m.get("role") == "user":
                last_user = m.get("text", "")
                break

        for key, resp in self.text_responses.items():
            if key in last_user:
                return AgentStepResult(text=resp)

        return AgentStepResult(text="Deterministic test step complete")


def get_provider(
    api_key: str | None = None,
    model: str = "gemini-2.0-flash",
    test_double: LLMProvider | None = None,
) -> LLMProvider:
    """Factory for LLM providers.

    If test_double is explicitly passed, it is used.
    Otherwise returns GeminiProvider.
    """
    if test_double is not None:
        return test_double
    return GeminiProvider(api_key=api_key, model=model)
