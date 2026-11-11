"""state.py : les objets qui circulent dans l'agent."""
import uuid
from dataclasses import dataclass, field
from typing import Any


@dataclass
class ToolResult:
    """Ce que renvoie chaque tool. result_for_llm est le seul texte vu par le LLM."""
    success: bool
    result_for_llm: str
    error: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


class NeedsUserInput(Exception):
    """Levée quand l'agent a besoin d'une précision (interface sans terminal, ex. API)."""

    def __init__(self, question: str):
        super().__init__(question)
        self.question = question


@dataclass
class AgentRun:
    """Trace complète d'une exécution (sert au benchmark et au dashboard)."""
    question: str
    run_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    backend: str = ""
    model: str = ""
    answer: str = ""
    steps: int = 0
    trace: list[dict[str, Any]] = field(default_factory=list)
    prompt_tokens: int = 0
    completion_tokens: int = 0
    latency_s: float = 0.0
    llm_time_s: float = 0.0     # temps passé à attendre le LLM
    tools_time_s: float = 0.0   # temps passé dans les tools (SQL, graphiques)
    warnings: list[str] = field(default_factory=list)   # alertes non bloquantes (ex. chiffre non sourcé)
    tool_calls: int = 0
    stopped_reason: str = "answered"   # answered | max_steps | blocked | budget | needs_input | error
