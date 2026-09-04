"""
nodes.py — Les Ouvriers (La Logique Métier)

Chaque fonction prend l'état actuel (state: AgentState) en paramètre unique et
retourne un dictionnaire de modifications à fusionner dans le State. Les nœuds
ne savent jamais qui a travaillé avant eux ni qui prendra la suite.
"""
import logging

from groq import BadRequestError
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage

from graph.llm import get_groq_llm
from graph.metrics import NODE_DURATION_SECONDS, record_token_usage, record_tool_call
from graph.state import AgentState
from tools.rag_tool import INSUFFICIENT_MARKERS, RAG_TOOL_DISPATCH, RAG_TOOLS
from tools.scraper_tool import SCRAPER_TOOL_DISPATCH, SCRAPER_TOOLS

logger = logging.getLogger(__name__)

_MAX_TOOL_ROUNDS = 3

# ---------------------------------------------------------------------------
# Agent RAG — Le Chercheur Local
# ---------------------------------------------------------------------------

_RAG_SYSTEM_PROMPT = (
    "Tu es l'Agent RAG de HorRAGor, le Chercheur Local. Premier point de contact "
    "de l'utilisateur, ta seule mission est d'interroger le savoir structuré et "
    "vectoriel (base de 1179 films d'horreur, recherche sémantique FAISS) pour "
    "extraire le lore brut des œuvres d'horreur et corriger les approximations "
    "de l'utilisateur (titre mal orthographié, date approximative...).\n\n"
    "Utilise les outils à ta disposition pour rassembler un maximum de faits "
    "précis et sourcés depuis la base de données. N'invente jamais une "
    "information absente des résultats d'outils. Ne rédige surtout pas de "
    "réponse finale stylisée ou narrative — un autre agent s'en chargera : "
    "contente-toi de rassembler la matière brute."
)


def rag_node(state: AgentState) -> dict:
    with NODE_DURATION_SECONDS.labels(node="rag").time():
        question = state["user_question"]
        llm = get_groq_llm(temperature=0.2).bind_tools(RAG_TOOLS)

        messages: list = [
            SystemMessage(content=_RAG_SYSTEM_PROMPT),
            HumanMessage(content=question),
        ]

        tools_used: list[str] = []
        collected: list[str] = []
        ai_msg: AIMessage = None

        for _ in range(_MAX_TOOL_ROUNDS):
            try:
                ai_msg = llm.invoke(messages)
            except BadRequestError as e:
                # Groq valide strictement les arguments générés par le modèle
                # (ex: un "k" sérialisé en string). Plutôt que de planter le
                # nœud, on s'arrête là avec ce qui a déjà été collecté.
                logger.warning(f"[RAG] Appel LLM rejeté par Groq, arrêt de la collecte : {e}")
                break
            messages.append(ai_msg)
            record_token_usage("rag", getattr(ai_msg, "usage_metadata", None))

            if not ai_msg.tool_calls:
                break

            for tool_call in ai_msg.tool_calls:
                name = tool_call["name"]
                args = tool_call["args"]
                fn = RAG_TOOL_DISPATCH.get(name)
                result = fn(args) if fn else f"Outil inconnu : {name}"
                logger.info(f"[RAG] Outil appelé : {name}({args})")
                tools_used.append(name)
                collected.append(result)
                record_tool_call(name, "rag")
                messages.append(ToolMessage(content=result, tool_call_id=tool_call["id"]))

        rag_context = "\n\n".join(collected) if collected else (ai_msg.content if ai_msg else "")
        rag_sufficient = _is_sufficient(rag_context)

        logger.info(f"[RAG] sufficient={rag_sufficient} tools_used={tools_used}")

        return {
            "rag_context": rag_context,
            "rag_sufficient": rag_sufficient,
            "tools_used": tools_used,
        }


def _is_sufficient(context: str) -> bool:
    """Heuristique déterministe : le RAG est suffisant s'il a produit du texte
    sans marqueur d'échec (« Aucun film trouvé », « introuvable », etc.)."""
    if not context or not context.strip():
        return False
    lower = context.lower()
    return not any(marker in lower for marker in INSUFFICIENT_MARKERS)


# ---------------------------------------------------------------------------
# Agent Scraper — L'Enquêteur du Web
# ---------------------------------------------------------------------------

_SCRAPER_SYSTEM_PROMPT = (
    "Tu es l'Agent Scraper de HorRAGor, l'Enquêteur du Web. Tu n'es déclenché "
    "que lorsque la base locale est incomplète. Ta mission : identifier le "
    "titre du film d'horreur mentionné par l'utilisateur et aller creuser le "
    "web (Wikipedia) pour en extraire les anecdotes et détails manquants."
)


def scraper_node(state: AgentState) -> dict:
    with NODE_DURATION_SECONDS.labels(node="scraper").time():
        question = state["user_question"]
        llm = get_groq_llm(temperature=0.0).bind_tools(
            SCRAPER_TOOLS, tool_choice="detailed_synopsis"
        )

        messages = [
            SystemMessage(content=_SCRAPER_SYSTEM_PROMPT),
            HumanMessage(content=question),
        ]

        tools_used: list[str] = []
        scraper_context = ""

        try:
            ai_msg = llm.invoke(messages)
        except BadRequestError as e:
            logger.warning(f"[Scraper] Appel LLM rejeté par Groq : {e}")
            return {"scraper_context": scraper_context, "tools_used": tools_used}

        record_token_usage("scraper", getattr(ai_msg, "usage_metadata", None))

        if ai_msg.tool_calls:
            tool_call = ai_msg.tool_calls[0]
            name = tool_call["name"]
            args = tool_call["args"]
            fn = SCRAPER_TOOL_DISPATCH.get(name)
            if fn:
                scraper_context = fn(args)
                tools_used.append(name)
                record_tool_call(name, "scraper")
                logger.info(f"[Scraper] Outil appelé : {name}({args})")

        return {
            "scraper_context": scraper_context,
            "tools_used": tools_used,
        }


# ---------------------------------------------------------------------------
# Agent de Narration — L'Écrivain Gothique
# ---------------------------------------------------------------------------

_NARRATION_SYSTEM_PROMPT = (
    "Tu es l'Agent de Narration de HorRAGor, l'Écrivain Gothique. Tu es isolé "
    "de toute la plomberie technique du système : tu ne connais ni les outils, "
    "ni la base de données, ni la façon dont les informations ont été "
    "récoltées. Tu reçois uniquement une synthèse de données brutes sur un "
    "sujet d'horreur, et ta seule mission est de l'emballer dans une "
    "atmosphère textuelle terrifiante, immersive et hautement romancée.\n\n"
    "Ne mentionne JAMAIS d'outil, de base de données, de recherche ou de "
    "processus technique dans ta réponse. Reste fidèle aux faits fournis, "
    "sans en inventer de nouveaux — seule l'atmosphère est romancée."
)


def narration_node(state: AgentState) -> dict:
    with NODE_DURATION_SECONDS.labels(node="narration").time():
        question = state["user_question"]

        synthesis_parts = [state.get("rag_context", "")]
        if state.get("scraper_context"):
            synthesis_parts.append(state["scraper_context"])
        synthesis = "\n\n".join(part for part in synthesis_parts if part)

        if not synthesis.strip():
            synthesis = (
                "Aucune donnée n'a pu être récoltée localement ni sur le web. "
                "Réponds avec ta connaissance générale de l'univers de l'horreur, "
                "dans le même ton gothique, en restant honnête sur l'incertitude."
            )

        llm = get_groq_llm(temperature=0.85)
        messages = [
            SystemMessage(content=_NARRATION_SYSTEM_PROMPT),
            HumanMessage(
                content=(
                    f"Question originale de l'utilisateur : {question}\n\n"
                    f"Synthèse de données à romancer :\n{synthesis}"
                )
            ),
        ]

        ai_msg = llm.invoke(messages)
        answer = ai_msg.content
        record_token_usage("narration", getattr(ai_msg, "usage_metadata", None))

        logger.info(f"[Narration] Réponse générée ({len(answer)} caractères)")

        return {
            "messages": [AIMessage(content=answer)],
            "tools_used": ["narration-llm"],
        }
