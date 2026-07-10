"""
Le Juge — évaluation qualité post-graphe.

Non prévu par le cahier des charges Partie 3 (qui termine le flux à la
Narration), mais déjà en production côté API/UI (bandeau verdict Streamlit) :
on le conserve comme étape de post-traitement après app.ainvoke(), plutôt que
comme un nœud du graphe multi-agent.
"""
import json
import logging
import re

from langchain_core.messages import HumanMessage, SystemMessage

from graph.llm import get_groq_llm

logger = logging.getLogger(__name__)

_MAX_RETRIES = 2
_CONFIDENCE_THRESHOLD = 0.65

_JUDGE_SYSTEM_PROMPT = (
    "Tu es Le Juge, un évaluateur strict de HorRAGor BOT. "
    "Ta mission : détecter les hallucinations et vérifier la cohérence des réponses. "
    "Réponds UNIQUEMENT avec un objet JSON valide, sans texte avant ni après. "
    'Format obligatoire : {"is_valid": true, "confidence": 0.95, "reasoning": "..."} '
    "is_valid = false si : hallucinations détectées, réponse hors sujet, données contredites, "
    "réponse vide ou incompréhensible. confidence entre 0.0 et 1.0."
)


def _evaluate(question: str, answer: str, tools_used: list[str]) -> dict:
    context_info = (
        f"Outils/agents utilisés : {', '.join(tools_used)}"
        if tools_used else "Réponse directe sans outil"
    )
    user_msg = (
        f"Question posée : {question}\n\n"
        f"Contexte : {context_info}\n\n"
        f"Réponse de l'agent :\n{answer}\n\n"
        "La réponse est-elle fidèle, complète et sans hallucination ?\n"
        'Réponds en JSON : {"is_valid": true/false, "confidence": 0.0-1.0, "reasoning": "..."}'
    )
    try:
        llm = get_groq_llm(temperature=0.1)
        resp = llm.invoke([
            SystemMessage(content=_JUDGE_SYSTEM_PROMPT),
            HumanMessage(content=user_msg),
        ])
        content = resp.content or ""
        match = re.search(r"\{[^{}]+\}", content, re.DOTALL)
        if match:
            return json.loads(match.group())
    except Exception as e:
        logger.warning(f"[Juge] Évaluation indisponible : {e}")
    return {"is_valid": True, "confidence": 0.75, "reasoning": "Évaluation automatique non disponible."}


def judge_and_retry(question: str, answer: str, tools_used: list[str]) -> tuple[str, dict]:
    """Évalue la réponse et la régénère (jusqu'à _MAX_RETRIES fois) si le Juge
    la juge insuffisante. Retourne (réponse finale, verdict final)."""
    verdict = _evaluate(question, answer, tools_used)
    logger.info(
        f"[Juge] valid={verdict.get('is_valid')} "
        f"conf={verdict.get('confidence'):.2f} — {verdict.get('reasoning', '')[:80]}"
    )

    for attempt in range(_MAX_RETRIES):
        if verdict.get("is_valid", True) or verdict.get("confidence", 1.0) >= _CONFIDENCE_THRESHOLD:
            break
        logger.info(f"[Juge] Retry {attempt + 1}/{_MAX_RETRIES}")
        llm = get_groq_llm(temperature=0.7)
        retry_resp = llm.invoke([
            SystemMessage(content=(
                "Tu es l'Écrivain Gothique de HorRAGor. Corrige ta réponse précédente "
                "en restant fidèle aux données et sans hallucination."
            )),
            HumanMessage(content=(
                f"Question : {question}\n\n"
                f"Réponse précédente : {answer}\n\n"
                f"[Critique du Juge] {verdict.get('reasoning', '')}"
            )),
        ])
        answer = retry_resp.content
        verdict = _evaluate(question, answer, tools_used)
        logger.info(
            f"[Juge] Après retry {attempt + 1} : valid={verdict.get('is_valid')} "
            f"conf={verdict.get('confidence'):.2f}"
        )

    return answer, verdict
