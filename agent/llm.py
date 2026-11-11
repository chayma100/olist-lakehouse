"""llm.py : seule porte vers le LLM. Changer de provider = changer .env.

Utilise l'API « chat completions » compatible OpenAI, que la plupart des
providers gratuits proposent (base_url + clé + nom de modèle).
"""
import json
from typing import Any

from .config import Config
from .tracing import trace


class LLM:
    def __init__(self, cfg: Config):
        from openai import OpenAI
        self.cfg = cfg
        self.client = OpenAI(base_url=cfg.llm_base_url or None, api_key=cfg.llm_api_key)

    @trace("llm_chat", "llm")
    def chat(self, messages: list[dict], tools: list[dict]) -> dict[str, Any]:
        """Un appel au modèle. Renvoie un dict normalisé :
        {content, tool_calls: [{id, name, arguments}], usage: (prompt, completion)}"""
        resp = self.client.chat.completions.create(
            model=self.cfg.llm_model,
            messages=messages,
            tools=tools,
            temperature=self.cfg.temperature,
        )
        msg = resp.choices[0].message
        calls = []
        for tc in msg.tool_calls or []:
            try:
                args = json.loads(tc.function.arguments or "{}")
            except json.JSONDecodeError:
                args = {"_invalid_json": tc.function.arguments}
            calls.append({"id": tc.id, "name": tc.function.name, "arguments": args})
        usage = (
            getattr(resp.usage, "prompt_tokens", 0) or 0,
            getattr(resp.usage, "completion_tokens", 0) or 0,
        )
        return {"content": msg.content or "", "tool_calls": calls, "usage": usage}
