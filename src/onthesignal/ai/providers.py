"""LLM providers behind one interface: Claude (Anthropic), ChatGPT (OpenAI), Ollama (local).

The assistant keeps a provider-neutral transcript:

* ``{"role": "user", "content": str}``
* ``{"role": "assistant", "content": str, "tool_calls": [ToolCall, ...]}``
* ``{"role": "tool", "id": str, "name": str, "content": str}``

Each provider converts it to its own message format. API keys are read from the environment
(``ANTHROPIC_API_KEY``, ``OPENAI_API_KEY``), never from project files.

``chat(..., on_delta=f)`` streams the answer: ``f(kind, text)`` receives the pieces of the
text (``kind="text"``) and of the reasoning of the model (``"thinking"``) as they are
generated; raising :class:`RequestCancelled` in ``f`` stops the generation. The returned
:class:`Reply` is complete in both cases, with the tokens used when the server tells them.
"""

from __future__ import annotations

import json
from collections.abc import Callable
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
    #: Reasoning of the model, when it gives it apart from the answer (Qwen3, Claude).
    thinking: str = ""
    #: Tokens of the request: ``{"input": n, "output": m}`` when the server tells them.
    usage: dict[str, int] = field(default_factory=dict)


Delta = Callable[[str, str], None]


class RequestCancelled(Exception):
    """Raised by an ``on_delta`` callback to stop a streamed generation."""


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


def _usage(input_tokens: Any, output_tokens: Any) -> dict[str, int]:
    if input_tokens is None and output_tokens is None:
        return {}
    return {"input": int(input_tokens or 0), "output": int(output_tokens or 0)}


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
    supports_streaming = True

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

    def chat(self, system: str, transcript: list[dict], tools: list[ToolSpec],
             on_delta: Delta | None = None) -> Reply:
        kwargs: dict[str, Any] = {}
        if tools:
            kwargs["tools"] = [{"name": t.name, "description": t.description,
                                "input_schema": t.schema} for t in tools]
        params = dict(model=self.model, max_tokens=self.max_tokens, system=system,
                      messages=self.convert(transcript), **kwargs)
        if on_delta is None:
            resp = self.client.messages.create(**params)
        else:
            with self.client.messages.stream(**params) as stream:
                for event in stream:
                    if event.type != "content_block_delta":
                        continue
                    delta = event.delta
                    if delta.type == "text_delta":
                        on_delta("text", delta.text)
                    elif delta.type == "thinking_delta":
                        on_delta("thinking", delta.thinking)
                resp = stream.get_final_message()
        text, calls, thinking = [], [], []
        for block in resp.content:
            if block.type == "text":
                text.append(block.text)
            elif block.type == "tool_use":
                calls.append(ToolCall(block.id, block.name, dict(block.input)))
            elif block.type == "thinking":
                thinking.append(block.thinking)
        usage = getattr(resp, "usage", None)
        return Reply("\n".join(text), calls, "\n".join(thinking),
                     _usage(getattr(usage, "input_tokens", None),
                            getattr(usage, "output_tokens", None)) if usage else {})


def _openai_tools(tools: list[ToolSpec]) -> list[dict]:
    return [{"type": "function", "function": {"name": t.name, "description": t.description,
                                              "parameters": t.schema}} for t in tools]


class OpenAIProvider:
    name = "openai"
    supports_tools = True
    supports_streaming = True

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

    def chat(self, system: str, transcript: list[dict], tools: list[ToolSpec],
             on_delta: Delta | None = None) -> Reply:
        kwargs: dict[str, Any] = {"tools": _openai_tools(tools)} if tools else {}
        messages = self.convert(system, transcript)
        if on_delta is None:
            resp = self.client.chat.completions.create(model=self.model, messages=messages,
                                                       **kwargs)
            msg = resp.choices[0].message
            calls = [ToolCall(tc.id, tc.function.name, json.loads(tc.function.arguments or "{}"))
                     for tc in (msg.tool_calls or [])]
            usage = getattr(resp, "usage", None)
            return Reply(msg.content or "", calls, usage=_usage(
                getattr(usage, "prompt_tokens", None),
                getattr(usage, "completion_tokens", None)) if usage else {})
        stream = self.client.chat.completions.create(
            model=self.model, messages=messages, stream=True,
            stream_options={"include_usage": True}, **kwargs)
        text: list[str] = []
        parts: dict[int, dict[str, str]] = {}
        usage_tokens: dict[str, int] = {}
        for chunk in stream:
            if getattr(chunk, "usage", None):
                usage_tokens = _usage(chunk.usage.prompt_tokens, chunk.usage.completion_tokens)
            if not chunk.choices:
                continue
            delta = chunk.choices[0].delta
            if delta.content:
                text.append(delta.content)
                on_delta("text", delta.content)
            for tc in delta.tool_calls or []:
                part = parts.setdefault(tc.index, {"id": "", "name": "", "arguments": ""})
                part["id"] = tc.id or part["id"]
                if tc.function is not None:
                    part["name"] += tc.function.name or ""
                    part["arguments"] += tc.function.arguments or ""
        calls = [ToolCall(p["id"] or f"call_{i}", p["name"], json.loads(p["arguments"] or "{}"))
                 for i, p in sorted(parts.items())]
        return Reply("".join(text), calls, usage=usage_tokens)


class OllamaProvider:
    name = "ollama"
    supports_tools = True
    supports_streaming = True

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

    def chat(self, system: str, transcript: list[dict], tools: list[ToolSpec],
             on_delta: Delta | None = None) -> Reply:
        kwargs: dict[str, Any] = {"tools": _openai_tools(tools)} if tools else {}
        if self.context:
            kwargs["options"] = {"num_ctx": self.context}
        messages = self.convert(system, transcript)
        if on_delta is None:
            resp = self.client.chat(model=self.model, messages=messages, **kwargs)
            msg = resp.message
            calls = [ToolCall(f"call_{i}", tc.function.name, dict(tc.function.arguments or {}))
                     for i, tc in enumerate(msg.tool_calls or [])]
            return Reply(msg.content or "", calls, getattr(msg, "thinking", "") or "",
                         _usage(getattr(resp, "prompt_eval_count", None),
                                getattr(resp, "eval_count", None)))
        text: list[str] = []
        thinking: list[str] = []
        calls = []
        usage_tokens: dict[str, int] = {}
        for chunk in self.client.chat(model=self.model, messages=messages, stream=True,
                                      **kwargs):
            msg = chunk.message
            if getattr(msg, "thinking", None):
                thinking.append(msg.thinking)
                on_delta("thinking", msg.thinking)
            if msg.content:
                text.append(msg.content)
                on_delta("text", msg.content)
            for tc in msg.tool_calls or []:
                calls.append(ToolCall(f"call_{len(calls)}", tc.function.name,
                                      dict(tc.function.arguments or {})))
            if getattr(chunk, "done", False):
                usage_tokens = _usage(getattr(chunk, "prompt_eval_count", None),
                                      getattr(chunk, "eval_count", None))
        return Reply("".join(text), calls, "".join(thinking), usage_tokens)


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


# ---------------------------------------------------------------------------------- profiles
AI_KEYS = ("provider", "model", "base_url", "context")
API_KEYS = {"anthropic": "ANTHROPIC_API_KEY", "openai": "OPENAI_API_KEY"}


def profiles(config: Config) -> list[dict]:
    """Named profiles ``[[ai.profiles]]`` (``name``, ``provider``, ``model``, ``base_url``,
    ``context``); entries without a name are ignored."""
    out = []
    for entry in config.get("ai.profiles", []) or []:
        if isinstance(entry, dict) and str(entry.get("name", "")).strip():
            out.append(entry)
    return out


def active_profile(config: Config) -> dict | None:
    """Profile chosen by ``[ai] profile`` (or for the session), if it exists."""
    name = str(config.get("ai.profile", "") or "")
    return next((p for p in profiles(config) if p["name"] == name), None)


def ai_settings(config: Config) -> dict:
    """``provider``, ``model``, ``base_url`` and ``context`` in force: the keys of ``[ai]``,
    overridden by those of the active profile; ``profile`` is its name ("" without one)."""
    settings = {key: config.get(f"ai.{key}") for key in AI_KEYS}
    profile = active_profile(config)
    if profile is not None:
        settings.update({k: profile[k] for k in AI_KEYS if k in profile})
    settings["provider"] = str(settings.get("provider") or "ollama").lower()
    settings["model"] = str(settings.get("model") or "")
    settings["base_url"] = str(settings.get("base_url") or "")
    settings["profile"] = profile["name"] if profile else ""
    return settings


def use_profile(config: Config, name: str) -> dict:
    """Choose a profile for the session (``""``: the keys of ``[ai]``)."""
    if name and not any(p["name"] == name for p in profiles(config)):
        known = ", ".join(p["name"] for p in profiles(config)) or "none"
        raise ParameterError(f"Unknown AI profile {name!r} (profiles: {known})")
    config.set("ai.profile", name)
    return ai_settings(config)


def consent_key(config: Config) -> str:
    """What the consent to an online provider is remembered for: the profile, else the
    provider (§11.5 of the web specification)."""
    settings = ai_settings(config)
    return settings["profile"] or settings["provider"]


def check_availability(config: Config, timeout: float = 3.0) -> tuple[bool, str]:
    """Is the provider in force usable? Ollama: server reachable and model present; online
    providers: API key in the environment (it is never shown)."""
    import os
    import urllib.request

    settings = ai_settings(config)
    name, model, base = settings["provider"], settings["model"], settings["base_url"]
    if name == "ollama":
        url = (base or "http://127.0.0.1:11434").rstrip("/") + "/api/tags"
        try:
            with urllib.request.urlopen(url, timeout=timeout) as response:
                tags = json.loads(response.read().decode("utf-8"))
        except (OSError, ValueError) as exc:
            return False, f"Ollama server not reachable at {url.rsplit('/api', 1)[0]}: {exc}"
        names = {m.get("name", "") for m in tags.get("models", [])}
        if not model:
            return False, "No model chosen (" + (", ".join(sorted(names)) or "none") + \
                " on the server)"
        if model in names or f"{model}:latest" in names:
            return True, f"{model} available on the Ollama server"
        return False, f"{model} is not on the Ollama server (ollama pull {model})"
    if name == "openai" and base and local_provider(name, base):
        try:
            with urllib.request.urlopen(base.rstrip("/") + "/models", timeout=timeout):
                return True, f"server {base} reachable"
        except OSError as exc:
            return False, f"server {base} not reachable: {exc}"
    variable = API_KEYS.get(name)
    if variable and not os.environ.get(variable):
        return False, f"{variable} is not set in the environment of the server"
    return True, f"{name}: API key present" if variable else f"{name}"


def make_provider(config: Config) -> LLMProvider:
    """Provider in force: ``[ai]`` (``provider``, ``model``, ``base_url``, ``context``), or the
    active profile."""
    settings = ai_settings(config)
    name = settings["provider"]
    if name not in PROVIDERS:
        raise ParameterError(f"Unknown AI provider {name!r} (anthropic, openai or ollama)")
    model = settings["model"] or DEFAULT_MODELS.get(name)
    if not model:
        raise ParameterError(
            f"No model configured for {name}: set [ai] model in onthesignal.toml or use "
            f"/model {name} <model>"
        )
    base_url = settings["base_url"]
    if name == "ollama":
        return OllamaProvider(model, base_url, context=context_tokens(config))
    return PROVIDERS[name](model, base_url)


def context_tokens(config: Config) -> int:
    """Context length in tokens (``[ai] context`` or that of the profile; 0 = server default)."""
    value = ai_settings(config).get("context", 0) or 0
    try:
        tokens = int(str(value).replace("_", ""))
    except ValueError:
        raise ParameterError(f"[ai] context must be a number of tokens, got {value!r}") from None
    if tokens < 0:
        raise ParameterError(f"[ai] context must be positive, got {tokens}")
    return tokens
