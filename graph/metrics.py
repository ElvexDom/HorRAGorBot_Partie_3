"""
Métriques Prometheus métier du graphe multi-agent — au-delà des métriques
HTTP génériques (latence/statut par route, déjà fournies par
prometheus-fastapi-instrumentator sur main_api.py), le brief demande
explicitement de tracer les appels d'outils et la consommation de tokens.

Enregistrées dans le REGISTRY par défaut de prometheus_client : visibles
automatiquement sur le /metrics exposé par main_api.py (même processus).
"""
from prometheus_client import Counter, Histogram

TOOL_CALLS_TOTAL = Counter(
    "horragor_tool_calls_total",
    "Nombre d'appels à un outil, par outil et par nœud du graphe",
    ["tool_name", "node"],
)

NODE_DURATION_SECONDS = Histogram(
    "horragor_node_duration_seconds",
    "Durée d'exécution d'un nœud du graphe (rag/scraper/narration)",
    ["node"],
)

LLM_TOKENS_TOTAL = Counter(
    "horragor_llm_tokens_total",
    "Tokens consommés par les appels LLM, par nœud et par type (prompt/completion)",
    ["node", "token_type"],
)


def record_tool_call(tool_name: str, node: str) -> None:
    TOOL_CALLS_TOTAL.labels(tool_name=tool_name, node=node).inc()


def record_token_usage(node: str, usage_metadata: dict | None) -> None:
    """`usage_metadata` est l'attribut standard LangChain d'un AIMessage
    ({"input_tokens", "output_tokens", "total_tokens"}) — None si absent
    (ex: réponse mockée en test, ou provider qui ne le renseigne pas)."""
    if not usage_metadata:
        return
    input_tokens = usage_metadata.get("input_tokens")
    output_tokens = usage_metadata.get("output_tokens")
    if input_tokens:
        LLM_TOKENS_TOTAL.labels(node=node, token_type="prompt").inc(input_tokens)
    if output_tokens:
        LLM_TOKENS_TOTAL.labels(node=node, token_type="completion").inc(output_tokens)
