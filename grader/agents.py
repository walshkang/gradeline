from __future__ import annotations

import json
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from .gemini_client import parse_json_maybe_fenced
from .types import JsonDict


def _parse_gemini_output(output: str) -> JsonDict:
    agent_response = parse_json_maybe_fenced(output)
    content = agent_response.get("response")
    if not content:
        turns = agent_response.get("turns", [])
        if turns:
            content = turns[-1].get("content")
    if not content:
        raise ValueError("Agent response has no extractable content.")
    return parse_json_maybe_fenced(content)


def _parse_claude_output(output: str) -> JsonDict:
    try:
        envelope = parse_json_maybe_fenced(output)
    except (json.JSONDecodeError, ValueError):
        return parse_json_maybe_fenced(output)
    result = envelope.get("result")
    if isinstance(result, str) and result.strip():
        try:
            return parse_json_maybe_fenced(result)
        except (json.JSONDecodeError, ValueError):
            pass
    content = envelope.get("content")
    if isinstance(content, list):
        for block in content:
            if isinstance(block, dict):
                text = block.get("text", "")
                if isinstance(text, str) and text.strip():
                    try:
                        return parse_json_maybe_fenced(text)
                    except (json.JSONDecodeError, ValueError):
                        continue
    if "questions" in envelope:
        return envelope
    raise ValueError("Claude agent response has no extractable grading content.")


@dataclass(frozen=True)
class AgentDefinition:
    name: str
    binary: str
    cmd_template: list[str]
    model_flags: list[str]
    prompt_flavor: str
    parse_output: Callable[[str], JsonDict]


_REGISTRY: dict[str, AgentDefinition] = {}


def _register(agent: AgentDefinition) -> None:
    _REGISTRY[agent.name] = agent


_register(AgentDefinition(
    name="gemini",
    binary="gemini",
    cmd_template=["gemini", "-p", "{prompt}", "-o", "json"],
    model_flags=["-m", "{model}"],
    prompt_flavor="Use your ability to read and analyze PDF files directly.",
    parse_output=_parse_gemini_output,
))

_register(AgentDefinition(
    name="copilot",
    binary="copilot",
    cmd_template=["copilot", "-p", "{prompt}", "--allow-all-paths", "--allow-all-tools", "-s"],
    model_flags=["-m", "{model}"],
    prompt_flavor="Use your file reading and analysis tools to examine the PDF contents.",
    parse_output=parse_json_maybe_fenced,
))

_register(AgentDefinition(
    name="claude",
    binary="claude",
    cmd_template=["claude", "-p", "{prompt}", "--output-format", "json"],
    model_flags=[],
    prompt_flavor="Analyze the PDF files provided in the context.",
    parse_output=_parse_claude_output,
))

_register(AgentDefinition(
    name="codex",
    binary="codex",
    cmd_template=["codex", "exec", "{prompt}"],
    model_flags=["-m", "{model}"],
    prompt_flavor="Use your code execution and file reading tools to analyze the PDF contents.",
    parse_output=parse_json_maybe_fenced,
))


def get_agent(name: str) -> AgentDefinition:
    """Look up an agent by name; raises ValueError for unknown names."""
    try:
        return _REGISTRY[name]
    except KeyError:
        raise ValueError(f"Unknown agent type: {name!r}. Available: {sorted(_REGISTRY)}")


def available_agents() -> list[str]:
    """Return sorted list of registered agent names."""
    return sorted(_REGISTRY)


def detect_installed_agents() -> dict[str, str]:
    """Return {name: path} for agents whose binary is on PATH."""
    found: dict[str, str] = {}
    for name, agent in _REGISTRY.items():
        path = shutil.which(agent.binary)
        if path is not None:
            found[name] = path
    return found


def build_agent_cmd(agent: AgentDefinition, prompt: str, model: str) -> list[str]:
    """Expand the agent's cmd_template into a concrete argv list."""
    cmd = [token.replace("{prompt}", prompt) for token in agent.cmd_template]
    if model and agent.model_flags:
        model_args = [token.replace("{model}", model) for token in agent.model_flags]
        cmd.extend(model_args)
    return cmd
