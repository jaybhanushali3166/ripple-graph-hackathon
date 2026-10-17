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


def _normalize_schema_types(val: Any) -> Any:
    """Recursively normalize uppercase schema type names to lowercase JSON Schema types."""
    if isinstance(val, dict):
        new_dict = {}
        for k, v in val.items():
            if k == "type" and isinstance(v, str):
                new_dict[k] = v.lower()
            else:
                new_dict[k] = _normalize_schema_types(v)
        return new_dict
    elif isinstance(val, list):
        return [_normalize_schema_types(item) for item in val]
    return val


def _format_tools_for_ollama(tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Format tool declarations into standard OpenAI/Ollama function calling schema."""
    formatted = []
    for t in tools:
        if t.get("type") == "function" and "function" in t:
            fn = dict(t["function"])
            if "parameters" in fn:
                fn["parameters"] = _normalize_schema_types(fn["parameters"])
            formatted.append({"type": "function", "function": fn})
        elif "name" in t:
            params = _normalize_schema_types(t.get("parameters", {}))
            formatted.append({
                "type": "function",
                "function": {
                    "name": t["name"],
                    "description": t.get("description", ""),
                    "parameters": params,
                },
            })
        else:
            formatted.append(t)
    return formatted


def _format_messages_for_ollama(
    messages: list[dict[str, Any]],
    system_prompt: str | None = None,
) -> list[dict[str, Any]]:
    """Format internal message list into Ollama /api/chat messages."""
    formatted: list[dict[str, Any]] = []
    if system_prompt:
        formatted.append({"role": "system", "content": system_prompt})

    for msg in messages:
        msg_role = msg.get("role", "user")

        if msg_role == "system":
            formatted.append({
                "role": "system",
                "content": msg.get("content") or msg.get("text", ""),
            })
        elif msg_role == "user":
            formatted.append({
                "role": "user",
                "content": msg.get("content") or msg.get("text", ""),
            })
        elif msg_role in ("model", "assistant"):
            tc_list: list[dict[str, Any]] = []
            if "tool_calls" in msg:
                for item in msg["tool_calls"]:
                    if "function" in item:
                        tc_list.append(item)
                    else:
                        tc_list.append({
                            "type": "function",
                            "function": {
                                "name": item.get("name", ""),
                                "arguments": item.get("args") or item.get("arguments", {}),
                            },
                        })
            elif "function_calls" in msg:
                for item in msg["function_calls"]:
                    tc_list.append({
                        "type": "function",
                        "function": {
                            "name": item.get("name", ""),
                            "arguments": item.get("args") or item.get("arguments", {}),
                        },
                    })

            assistant_msg: dict[str, Any] = {
                "role": "assistant",
                "content": msg.get("content") or msg.get("text", "") or "",
            }
            if tc_list:
                assistant_msg["tool_calls"] = tc_list
            formatted.append(assistant_msg)
        elif msg_role in ("function", "tool"):
            if "function_responses" in msg:
                for fr in msg["function_responses"]:
                    res = fr.get("response", {})
                    content_str = json.dumps(res) if isinstance(res, (dict, list)) else str(res)
                    formatted.append({
                        "role": "tool",
                        "content": content_str,
                        "name": fr.get("name", ""),
                    })
            elif "function_response" in msg:
                fr = msg["function_response"]
                res = fr.get("response", {})
                content_str = json.dumps(res) if isinstance(res, (dict, list)) else str(res)
                formatted.append({
                    "role": "tool",
                    "content": content_str,
                    "name": fr.get("name", ""),
                })
            else:
                content = msg.get("content", "")
                content_str = json.dumps(content) if isinstance(content, (dict, list)) else str(content)
                formatted.append({
                    "role": "tool",
                    "content": content_str,
                    "name": msg.get("name", ""),
                })

    return formatted


class OllamaProvider(LLMProvider):
    """Ollama API provider (supporting Ollama Cloud and local Ollama) using httpx.

    Connects to Ollama Cloud (https://ollama.com) or local Ollama instance (http://localhost:11434).
    Initialization is lazy: neither secret validation nor network connection
    happens during __init__.
    API keys are sent via the 'Authorization: Bearer <api_key>' header.
    """

    def __init__(
        self,
        api_key: str | None = None,
        model: str = "llama3.3",
        base_url: str = "https://ollama.com",
    ) -> None:
        self.api_key = api_key
        self.model = model
        self.base_url = base_url.rstrip("/")

    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        elif "ollama.com" in self.base_url.lower():
            raise ProviderAuthenticationError(
                "Ollama API key is not configured. Set LLM_API_KEY environment variable."
            )
        return headers

    async def generate_text(
        self,
        prompt: str,
        system_prompt: str | None = None,
        timeout: float = 30.0,
    ) -> str:
        headers = self._headers()
        endpoint = f"{self.base_url}/api/chat"

        messages: list[dict[str, Any]] = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        payload: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "stream": False,
            "options": {
                "temperature": 0.1,
            },
        }

        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                response = await client.post(endpoint, json=payload, headers=headers)
        except httpx.TimeoutException as exc:
            raise ProviderTimeoutError(f"Ollama API request timed out after {timeout}s") from exc
        except httpx.HTTPError as exc:
            raise AIProviderError(f"Ollama HTTP connection error: {exc}") from exc

        if response.status_code in (401, 403):
            raise ProviderAuthenticationError(f"Ollama authentication failed (status {response.status_code})")
        if response.status_code != 200:
            raise AIProviderError(f"Ollama API error (status {response.status_code}): {response.text}")

        data = response.json()
        message = data.get("message")
        if not message or "content" not in message:
            raise ProviderSchemaError("Ollama returned no message in response", details=data)

        return message.get("content", "")

    async def generate_structured(
        self,
        prompt: str,
        schema: type[T],
        system_prompt: str | None = None,
        timeout: float = 30.0,
    ) -> T:
        headers = self._headers()
        endpoint = f"{self.base_url}/api/chat"

        messages: list[dict[str, Any]] = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})

        json_schema_prompt = (
            f"{prompt}\n\nRespond ONLY with a valid JSON object matching this schema:\n"
            f"{json.dumps(schema.model_json_schema())}"
        )
        messages.append({"role": "user", "content": json_schema_prompt})

        payload: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "format": schema.model_json_schema(),
            "stream": False,
            "options": {
                "temperature": 0.0,
            },
        }

        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                response = await client.post(endpoint, json=payload, headers=headers)
        except httpx.TimeoutException as exc:
            raise ProviderTimeoutError(f"Ollama API structured request timed out after {timeout}s") from exc
        except httpx.HTTPError as exc:
            raise AIProviderError(f"Ollama HTTP connection error: {exc}") from exc

        if response.status_code in (401, 403):
            raise ProviderAuthenticationError(f"Ollama authentication failed (status {response.status_code})")
        if response.status_code != 200:
            raise AIProviderError(f"Ollama API error (status {response.status_code}): {response.text}")

        data = response.json()
        message = data.get("message")
        if not message or "content" not in message:
            raise ProviderSchemaError("Ollama returned no message in response", details=data)

        raw_text = message.get("content", "")
        if not raw_text:
            raise ProviderSchemaError("Ollama returned empty content for structured response", details=data)

        raw_text = raw_text.strip()
        if raw_text.startswith("```"):
            lines = raw_text.splitlines()
            if lines and lines[0].startswith("```"):
                lines = lines[1:]
            if lines and lines[-1].startswith("```"):
                lines = lines[:-1]
            raw_text = "\n".join(lines).strip()

        try:
            parsed_json = json.loads(raw_text)
            return schema.model_validate(parsed_json)
        except json.JSONDecodeError as exc:
            raise ProviderSchemaError(f"Failed to parse JSON from Ollama response: {exc}") from exc
        except ValidationError as exc:
            raise ProviderSchemaError(f"Ollama response did not conform to schema {schema.__name__}: {exc}") from exc

    async def generate_tool_step(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        system_prompt: str | None = None,
        timeout: float = 30.0,
    ) -> AgentStepResult:
        headers = self._headers()
        endpoint = f"{self.base_url}/api/chat"

        ollama_messages = _format_messages_for_ollama(messages, system_prompt=system_prompt)

        payload: dict[str, Any] = {
            "model": self.model,
            "messages": ollama_messages,
            "stream": False,
            "options": {
                "temperature": 0.0,
            },
        }
        if tools:
            payload["tools"] = _format_tools_for_ollama(tools)

        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                response = await client.post(endpoint, json=payload, headers=headers)
        except httpx.TimeoutException as exc:
            raise ProviderTimeoutError(f"Ollama API tool step timed out after {timeout}s") from exc
        except httpx.HTTPError as exc:
            raise AIProviderError(f"Ollama HTTP connection error: {exc}") from exc

        if response.status_code in (401, 403):
            raise ProviderAuthenticationError(f"Ollama authentication failed (status {response.status_code})")
        if response.status_code != 200:
            raise AIProviderError(f"Ollama API error (status {response.status_code}): {response.text}")

        data = response.json()
        message = data.get("message")
        if not message and not data.get("done"):
            raise ProviderSchemaError("Ollama returned no message in tool step", details=data)

        raw_tool_calls = message.get("tool_calls") or [] if message else []
        tool_calls: list[ToolCall] = []

        for tc in raw_tool_calls:
            fn = tc.get("function", {})
            name = fn.get("name", "")
            args = fn.get("arguments", {})
            if isinstance(args, str):
                try:
                    args = json.loads(args)
                except Exception:
                    args = {}
            if name:
                tool_calls.append(ToolCall(name=name, arguments=args))

        text_out = message.get("content") if message else None
        if text_out and not text_out.strip():
            text_out = None

        return AgentStepResult(
            tool_calls=tool_calls,
            text=text_out,
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
    model: str = "llama3.3",
    base_url: str = "https://ollama.com",
    test_double: LLMProvider | None = None,
) -> LLMProvider:
    """Factory for LLM providers.

    If test_double is explicitly passed, it is used.
    Otherwise returns OllamaProvider.
    """
    if test_double is not None:
        return test_double
    return OllamaProvider(api_key=api_key, model=model, base_url=base_url)


# Backward compatibility alias
GeminiProvider = OllamaProvider

