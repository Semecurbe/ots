"""LLM providers behind one interface: Claude (Anthropic), ChatGPT (OpenAI), Ollama (local).

The assistant keeps a provider-neutral transcript:

* ``{"role": "user", "content": str}``
* ``{"role": "assistant", "content": str, "tool_calls": [ToolCall, ...]}``
* ``{"role": "tool", "id": str, "name": str, "content": str}``

Each provider converts it to its own message format. API keys are read from the environment
(``ANTHROPIC_API_KEY``, ``OPENAI_API_KEY``), never from project files.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Protocol

from ..core.config import Config
from ..core.errors import ParameterError

DEFAULT_MODELS = {"anthropic": "claude-fable-5-2"}


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: dict


@dataclass
class Reply:
    text: str
    tool_calls: list[ToolCall] = field(default_factory=list)


@dataclass
class ToolSpec:
    name: str
    description: str
    schema: dict


class LLMProvider(Protocol):
    name: str
    model: str
    supports_tools: bool

    def chat(self, system: str, transcript: list[dict], tools: list[ToolSpec]) -> Reply: ...


def _require(module: str) -> Any:
    try:
        return __import__(module)
    except ImportError as exc:
        raise ParameterError(
            f"The '{module}' package is not installed: pip install 'onthesignal[ai]'"
        ) from exc


class AnthropicProvider:
    name = "anthropic"
    supports_tools = True

    def __init__(self, model: str, base_url: str = "", max_tokens: int = 4096) -> None:
        anthropic = _require("anthropic")
        self.model, self.max_tokens = model, max_tokens
        self.client = anthropic.Anthropic(base_url=base_url or None)

    @staticmethod
    def convert(transcript: list[dict]) -> list[dict]:
        messages: list[dict] = []
        for entry in transcript:
            if entry["role"] == "user":
                messages.append({"role": "user", "content": entry["content"]})
            elif entry["role"] == "assistant":
                blocks: list[dict] = []
                if entry.get("content"):
                    blocks.append({"type": "text", "text": entry["content"]})
                for call in entry.get("tool_calls", []):
                    blocks.append({"type": "tool_use", "id": call.id, "name": call.name,
                                   "input": call.arguments})
                content = blocks or entry.get("content", "")
                messages.append({"role": "assistant", "content": content})
            else:
                result = {"type": "tool_result", "tool_use_id": entry["id"],
                          "content": entry["content"]}
                last = messages[-1] if messages else None
                if last and last["role"] == "user" and isinstance(last["content"], list):
                    last["content"].append(result)
                else:
                    messages.append({"role": "user", "content": [result]})
        return messages

    def chat(self, system: str, transcript: list[dict], tools: list[ToolSpec]) -> Reply:
        kwargs: dict[str, Any] = {}
        if tools:
            kwargs["tools"] = [{"name": t.name, "description": t.description,
                                "input_schema": t.schema} for t in tools]
        resp = self.client.messages.create(model=self.model, max_tokens=self.max_tokens,
                                           system=system, messages=self.convert(transcript),
                                           **kwargs)
        text, calls = [], []
        for block in resp.content:
            if block.type == "text":
                text.append(block.text)
            elif block.type == "tool_use":
                calls.append(ToolCall(block.id, block.name, dict(block.input)))
        return Reply("\n".join(text), calls)


def _openai_tools(tools: list[ToolSpec]) -> list[dict]:
    return [{"type": "function", "function": {"name": t.name, "description": t.description,
                                              "parameters": t.schema}} for t in tools]


class OpenAIProvider:
    name = "openai"
    supports_tools = True

    def __init__(self, model: str, base_url: str = "") -> None:
        openai = _require("openai")
        self.model = model
        self.client = openai.OpenAI(base_url=base_url or None)

    @staticmethod
    def convert(system: str, transcript: list[dict]) -> list[dict]:
        messages: list[dict] = [{"role": "system", "content": system}]
        for entry in transcript:
            if entry["role"] == "user":
                messages.append({"role": "user", "content": entry["content"]})
            elif entry["role"] == "assistant":
                msg: dict[str, Any] = {"role": "assistant", "content": entry.get("content") or None}
                if entry.get("tool_calls"):
                    msg["tool_calls"] = [
                        {"id": c.id, "type": "function",
                         "function": {"name": c.name, "arguments": json.dumps(c.arguments)}}
                        for c in entry["tool_calls"]
                    ]
                messages.append(msg)
            else:
                messages.append({"role": "tool", "tool_call_id": entry["id"],
                                 "content": entry["content"]})
        return messages

    def chat(self, system: str, transcript: list[dict], tools: list[ToolSpec]) -> Reply:
        kwargs = {"tools": _openai_tools(tools)} if tools else {}
        resp = self.client.chat.completions.create(
            model=self.model, messages=self.convert(system, transcript), **kwargs)
        msg = resp.choices[0].message
        calls = [ToolCall(tc.id, tc.function.name, json.loads(tc.function.arguments or "{}"))
                 for tc in (msg.tool_calls or [])]
        return Reply(msg.content or "", calls)


class OllamaProvider:
    name = "ollama"
    supports_tools = True

    def __init__(self, model: str, base_url: str = "", context: int = 0) -> None:
        """``context`` is sent as ``num_ctx`` (tokens); 0 keeps the server default.

        Ollama caps it at the context length the model was trained for, with only a warning in
        the server log.
        """
        ollama = _require("ollama")
        self.model, self.context = model, context
        self.client = ollama.Client(host=base_url or None)

    @staticmethod
    def convert(system: str, transcript: list[dict]) -> list[dict]:
        messages: list[dict] = [{"role": "system", "content": system}]
        for entry in transcript:
            if entry["role"] == "assistant":
                msg: dict[str, Any] = {"role": "assistant", "content": entry.get("content", "")}
                if entry.get("tool_calls"):
                    msg["tool_calls"] = [{"function": {"name": c.name, "arguments": c.arguments}}
                                         for c in entry["tool_calls"]]
                messages.append(msg)
            elif entry["role"] == "tool":
                messages.append({"role": "tool", "content": entry["content"],
                                 "tool_name": entry["name"]})
            else:
                messages.append({"role": "user", "content": entry["content"]})
        return messages

    def chat(self, system: str, transcript: list[dict], tools: list[ToolSpec]) -> Reply:
        kwargs: dict[str, Any] = {"tools": _openai_tools(tools)} if tools else {}
        if self.context:
            kwargs["options"] = {"num_ctx": self.context}
        resp = self.client.chat(model=self.model, messages=self.convert(system, transcript),
                                **kwargs)
        msg = resp.message
        calls = [ToolCall(f"call_{i}", tc.function.name, dict(tc.function.arguments or {}))
                 for i, tc in enumerate(msg.tool_calls or [])]
        return Reply(msg.content or "", calls)


PROVIDERS = {"anthropic": AnthropicProvider, "openai": OpenAIProvider, "ollama": OllamaProvider}


def local_provider(name: str, base_url: str = "") -> bool:
    """True when the provider keeps the data on the machine or the local network (Ollama).

    Claude and ChatGPT are online services; an ``openai`` provider pointed at a server of the
    local network (vLLM on a GB10) is local too.
    """
    from urllib.parse import urlsplit

    if name.lower() == "ollama":
        return True
    host = (urlsplit(base_url).hostname or "") if base_url else ""
    if not host:
        return False
    import ipaddress

    if host in ("localhost",) or host.endswith(".local") or host.endswith(".lan"):
        return True
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        return False
    return address.is_private or address.is_loopback


def make_provider(config: Config) -> LLMProvider:
    """Provider configured in ``[ai]`` (``provider``, ``model``, ``base_url``, ``context``)."""
    name = str(config.get("ai.provider", "ollama")).lower()
    if name not in PROVIDERS:
        raise ParameterError(f"Unknown AI provider {name!r} (anthropic, openai or ollama)")
    model = config.get("ai.model") or DEFAULT_MODELS.get(name)
    if not model:
        raise ParameterError(
            f"No model configured for {name}: set [ai] model in onthesignal.toml or use "
            f"/model {name} <model>"
        )
    base_url = config.get("ai.base_url", "")
    if name == "ollama":
        return OllamaProvider(model, base_url, context=context_tokens(config))
    return PROVIDERS[name](model, base_url)


def context_tokens(config: Config) -> int:
    """``[ai] context`` as a number of tokens (0 = server default)."""
    value = config.get("ai.context", 0) or 0
    try:
        tokens = int(str(value).replace("_", ""))
    except ValueError:
        raise ParameterError(f"[ai] context must be a number of tokens, got {value!r}") from None
    if tokens < 0:
        raise ParameterError(f"[ai] context must be positive, got {tokens}")
    return tokens
