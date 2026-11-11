"""Teste le LLM : (1) il répond, (2) il sait appeler un tool.

Usage :  python scripts/test_llm.py
Lit LLM_BASE_URL, LLM_API_KEY, LLM_MODEL dans .env
"""
import os

from dotenv import load_dotenv

load_dotenv()

missing = [k for k in ("LLM_BASE_URL", "LLM_API_KEY", "LLM_MODEL") if not os.getenv(k)]
if missing:
    raise SystemExit(f"Variables manquantes dans .env : {', '.join(missing)}")

from openai import OpenAI

client = OpenAI(base_url=os.environ["LLM_BASE_URL"], api_key=os.environ["LLM_API_KEY"])
model = os.environ["LLM_MODEL"]

# --- Test 1 : réponse simple
r = client.chat.completions.create(
    model=model, messages=[{"role": "user", "content": "Say hello in one short sentence."}]
)
print("Test 1 (réponse)  OK :", r.choices[0].message.content)

# --- Test 2 : appel de tool
tools = [{
    "type": "function",
    "function": {
        "name": "run_sql",
        "description": "Execute one SELECT query.",
        "parameters": {
            "type": "object",
            "properties": {"sql": {"type": "string"}},
            "required": ["sql"],
        },
    },
}]
r = client.chat.completions.create(
    model=model,
    messages=[{"role": "user", "content": "How many rows are in the table fact_orders? Use the tool."}],
    tools=tools,
)
calls = r.choices[0].message.tool_calls
if calls:
    print("Test 2 (tool)     OK :", calls[0].function.name, calls[0].function.arguments)
else:
    print("Test 2 (tool)     ÉCHEC : le modèle n'a pas appelé le tool. Réponse :",
          r.choices[0].message.content)
