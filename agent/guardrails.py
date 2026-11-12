"""guardrails.py : contrôles faits par le code, jamais par le LLM.

validate_sql refuse tout ce qui n'est pas un SELECT unique sur les tables
autorisées, et impose un LIMIT.
"""
from dataclasses import dataclass

import sqlglot
from sqlglot import exp

FORBIDDEN = (
    exp.Insert, exp.Update, exp.Delete, exp.Drop, exp.Create, exp.Alter,
    exp.Merge, exp.Command, exp.TruncateTable, exp.Grant,
)


@dataclass
class GuardResult:
    ok: bool
    reason: str = ""
    sql: str = ""   # SQL final (avec LIMIT) si ok


def validate_sql(sql: str, allowed_tables: list[str], max_rows: int = 100,
                 dialect: str = "databricks") -> GuardResult:
    if not sql or not sql.strip():
        return GuardResult(False, "Empty SQL.")
    try:
        statements = [s for s in sqlglot.parse(sql, read=dialect) if s is not None]
    except sqlglot.errors.SqlglotError as e:
        return GuardResult(False, f"SQL could not be parsed: {e}")

    if len(statements) != 1:
        return GuardResult(False, "Exactly one SQL statement is allowed.")
    stmt = statements[0]

    if not isinstance(stmt, exp.Query):
        return GuardResult(False, "Only SELECT queries are allowed.")
    for node in stmt.walk():
        if isinstance(node, FORBIDDEN):
            return GuardResult(False, "Only read-only SELECT queries are allowed.")

    allowed = {t.lower() for t in allowed_tables}
    cte_names = {cte.alias_or_name.lower() for cte in stmt.find_all(exp.CTE)}
    for table in stmt.find_all(exp.Table):
        name = table.name.lower()
        if name in cte_names:
            continue
        if name not in allowed:
            return GuardResult(
                False,
                f"Table '{table.name}' is not allowed. Allowed tables: "
                f"{', '.join(sorted(allowed))}.",
            )

    limit = stmt.args.get("limit")
    if limit is None:
        stmt = stmt.limit(max_rows)
    else:
        value = limit.args.get("expression")
        if isinstance(value, exp.Literal) and value.is_int and int(value.name) > max_rows:
            stmt = stmt.limit(max_rows)

    return GuardResult(True, "", stmt.sql(dialect=dialect))


# ---------------------------------------------------------------- garde d'entrée

import re

# Demandes de modification de données : l'agent est en lecture seule, on refuse tôt
_WRITE_INTENT = re.compile(
    r"^\s*(please\s+|can you\s+|could you\s+)?(delete|drop|truncate|update|insert|alter|remove|erase|"
    r"wipe|modify|grant|revoke"
    r"|create\s+(or\s+replace\s+)?(table|view|schema|database)"
    r"|(create|make|build)\s+(a\s+|an\s+)?(new\s+|temporary\s+)?(table|view|schema)\b[^.?!]{0,40}\b(called|named)"
    r"|(create|make|build)\s+(a\s+|an\s+)?new\s+(table|view|schema))\b", re.I)
_INJECTION = re.compile(
    r"(ignore|forget|disregard)\b.{0,30}\b(previous|above|prior|all|your)\b.{0,30}\b(instruction|rule|prompt)s?"
    r"|(reveal|show|print|repeat|output)\b.{0,30}\b(system prompt|your prompt|your instructions)"
    r"|you are now\b|developer mode|jailbreak|act as (an? )?(unrestricted|dan)\b", re.I)
_SECRETS = re.compile(r"\b(api[ _-]?key|access[ _-]?token|password|secret|credentials?|\.env)\b", re.I)


def input_guard(question: str, max_chars: int = 1000) -> GuardResult:
    """Contrôles faits AVANT d'appeler le LLM : longueur, écriture, injection, secrets."""
    if not question or not question.strip():
        return GuardResult(False, "Empty question.")
    if len(question) > max_chars:
        return GuardResult(False, f"Question too long (max {max_chars} characters).")
    if _WRITE_INTENT.search(question):
        return GuardResult(False, "This assistant is read-only: it can analyse the data but "
                                  "cannot modify, delete or create anything.")
    if _INJECTION.search(question):
        return GuardResult(False, "I can't follow instructions that try to change my rules "
                                  "or reveal my configuration. Ask a question about the data.")
    if _SECRETS.search(question):
        return GuardResult(False, "I don't have access to credentials or secrets, and can't "
                                  "share them. Ask a question about the data.")
    return GuardResult(True)


# ---------------------------------------------------------------- garde de sortie


_THOUSANDS = re.compile(r"(?<=\d),(?=\d{3}\b)")
_NUMBER = re.compile(r"\d+(?:\.\d+)?")


def _numbers(text: str) -> list[float]:
    return [float(x) for x in _NUMBER.findall(_THOUSANDS.sub("", text))]


def ungrounded_numbers(answer: str, sources: list[str]) -> list[str]:
    """Chiffres de la réponse qui n'apparaissent dans aucun résultat de tool ni dans la question.

    Vérification simple (alerte, pas blocage) : un pourcentage ou une somme calculés par
    le modèle seront signalés, c'est voulu : à relire."""
    if not sources:
        return []
    known = [n for src in sources for n in _numbers(src)]
    bad: list[str] = []
    for token in _NUMBER.findall(_THOUSANDS.sub("", answer)):
        value = float(token)
        has_decimal = "." in token
        if not has_decimal and (value < 100 or 1990 <= value <= 2030):
            continue   # petits entiers et années : trop de faux positifs
        if any(abs(value - k) <= max(0.011, abs(k) * 0.0006) for k in known):
            continue
        bad.append(token)
    return sorted(set(bad))
