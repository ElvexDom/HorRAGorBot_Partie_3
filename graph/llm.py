"""
Client LLM partagé par les nœuds du graphe (config.py "config des LLM" du brief,
adapté à Groq plutôt qu'Ollama — cf. écart assumé dans le plan de la Partie 3).
"""
import os

from langchain_groq import ChatGroq

# llama-3.3-70b-versatile a ete retire du catalogue Groq (verifie via
# GET /openai/v1/models) -- openai/gpt-oss-120b le remplace : tool-calling
# supporte, disponible sur le compte utilise pour ce projet.
DEFAULT_MODEL = os.getenv("GROQ_MODEL", "openai/gpt-oss-120b")


def get_groq_llm(temperature: float = 0.7) -> ChatGroq:
    api_key = os.getenv("GROQ_API_KEY")
    if not api_key:
        raise ValueError(
            "GROQ_API_KEY non configurée. Définis la variable d'environnement."
        )
    return ChatGroq(model=DEFAULT_MODEL, temperature=temperature, api_key=api_key)
