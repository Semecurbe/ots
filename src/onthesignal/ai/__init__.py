"""AI assistant (specification §17): Claude, ChatGPT or Ollama driving onthesignal tools."""

from .assistant import Assistant, extract_code, get_assistant
from .context import agent_doc, init_context, system_prompt, write_agent_doc
from .providers import PROVIDERS, Reply, ToolCall, ToolSpec, make_provider
from .tools import build_tools, summarize

__all__ = [
    "PROVIDERS",
    "Assistant",
    "Reply",
    "ToolCall",
    "ToolSpec",
    "agent_doc",
    "build_tools",
    "extract_code",
    "get_assistant",
    "init_context",
    "make_provider",
    "summarize",
    "system_prompt",
    "write_agent_doc",
]
