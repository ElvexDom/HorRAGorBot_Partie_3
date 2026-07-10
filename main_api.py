"""
API FastAPI pour HorRAGor BOT
Composant Back-End : réception des messages Streamlit et traitement via le
graphe multi-agent LangGraph (Agent RAG -> Router -> Agent Scraper -> Agent
de Narration), avec monitoring Langfuse et évaluation qualité par Le Juge.
"""

import asyncio
import logging
import os
from contextlib import asynccontextmanager
from typing import Optional

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from langchain_core.messages import AIMessage, HumanMessage
from pydantic import BaseModel, ConfigDict, Field

from graph.judge import judge_and_retry
from graph.pipeline import app as agent_graph
from tools.rag_tool import initialize_retriever

# ============================================================================
# CONFIGURATION
# ============================================================================

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)

logger = logging.getLogger(__name__)

# ============================================================================
# LANGFUSE (MONITORING, OPTIONNEL EN LOCAL)
# ============================================================================


def _get_langfuse_callbacks() -> list:
    """Retourne le callback Langfuse si les clés sont configurées, sinon une
    liste vide — le graphe tourne sans monitoring plutôt que de planter."""
    if not (os.getenv("LANGFUSE_PUBLIC_KEY") and os.getenv("LANGFUSE_SECRET_KEY")):
        return []
    try:
        from langfuse.langchain import CallbackHandler
        return [CallbackHandler()]
    except Exception as e:
        logger.warning(f"Langfuse indisponible, monitoring désactivé : {e}")
        return []


# ============================================================================
# APPLICATION FASTAPI
# ============================================================================

@asynccontextmanager
async def lifespan(app: FastAPI):
    await asyncio.to_thread(initialize_retriever)
    logger.info("Retriever FAISS pré-chargé au démarrage")
    yield


app = FastAPI(
    title="HorRAGor BOT API",
    description="Agent conversationnel multi-agent spécialisé dans l'univers de l'horreur",
    version="3.0.0",
    lifespan=lifespan
)

# ============================================================================
# MODÈLES PYDANTIC
# ============================================================================


class ChatRequest(BaseModel):
    """
    Requête utilisateur.
    """

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "question": "Quel film d'horreur me recommandes-tu si j'aime The Shining ?",
                "user_id": "user_123",
                "conversation_id": "conv_456"
            }
        }
    )

    question: str = Field(
        ...,
        min_length=1,
        max_length=5000,
        description="Question utilisateur"
    )

    user_id: Optional[str] = Field(
        default=None,
        description="Identifiant utilisateur"
    )

    conversation_id: Optional[str] = Field(
        default=None,
        description="Identifiant conversation"
    )

    history: list[dict] = Field(
        default_factory=list,
        description="Historique de la conversation (messages {role, content})"
    )


class ToolResult(BaseModel):
    """
    Résultat d'un outil.
    """

    tool_name: str
    status: str
    data: Optional[dict] = None
    error_message: Optional[str] = None


class JudgeVerdict(BaseModel):
    """
    Verdict qualité.
    """

    is_valid: bool

    confidence: float = Field(
        ...,
        ge=0.0,
        le=1.0
    )

    reasoning: str


class ChatResponse(BaseModel):
    """
    Réponse du chatbot.
    """

    answer: str

    tools_used: list[str] = Field(
        default_factory=list
    )

    judge_verdict: Optional[JudgeVerdict] = None

    conversation_id: str

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "answer": "Je te recommande The Haunting (1963).",
                "tools_used": ["groq-llm"],
                "judge_verdict": {
                    "is_valid": True,
                    "confidence": 0.95,
                    "reasoning": "Réponse cohérente et pertinente."
                },
                "conversation_id": "conv_456"
            }
        }
    )


class ErrorResponse(BaseModel):
    """
    Réponse d'erreur.
    """

    error: str
    detail: str
    request_id: Optional[str] = None


# ============================================================================
# ENDPOINTS
# ============================================================================


@app.get(
    "/",
    tags=["Root"]
)
async def root():
    """
    Endpoint racine.
    """

    return {
        "name": "HorRAGor BOT API",
        "version": "3.0.0",
        "status": "running"
    }


@app.get(
    "/health",
    tags=["Health"]
)
async def health_check():
    """
    Vérification de santé.
    """

    return {
        "status": "ok",
        "message": "HorRAGor BOT API is running"
    }


@app.post(
    "/chat",
    response_model=ChatResponse,
    responses={
        400: {
            "model": ErrorResponse,
            "description": "Requête invalide"
        },
        500: {
            "model": ErrorResponse,
            "description": "Erreur serveur"
        }
    },
    tags=["Chat"],
    summary="Génération de réponse"
)
async def chat(request: ChatRequest) -> ChatResponse:
    """
    Reçoit une question et la fait traverser le graphe multi-agent
    (Agent RAG -> Router -> Agent Scraper -> Agent de Narration).
    """

    try:
        logger.info(
            f"Question reçue : {request.question[:100]}"
        )

        history_messages = [
            AIMessage(content=m["content"]) if m.get("role") == "assistant"
            else HumanMessage(content=m["content"])
            for m in request.history
        ]

        initial_state = {
            "messages": [*history_messages, HumanMessage(content=request.question)],
            "user_question": request.question,
            "tools_used": [],
        }

        try:
            result = await agent_graph.ainvoke(
                initial_state,
                config={"callbacks": _get_langfuse_callbacks()}
            )
        except ValueError as e:
            raise HTTPException(
                status_code=500,
                detail=(
                    "Configuration Groq manquante. "
                    f"Vérifiez la variable GROQ_API_KEY. ({e})"
                )
            )

        answer     = result["messages"][-1].content
        tools_used = result.get("tools_used", [])

        answer, judge_result = await asyncio.to_thread(
            judge_and_retry, request.question, answer, tools_used
        )

        logger.info(
            f"Réponse générée ({len(answer)} caractères) — outils : {tools_used}"
        )

        conversation_id = (
            request.conversation_id
            or f"conv_{request.user_id or 'anonymous'}"
        )

        verdict = JudgeVerdict(
            is_valid=judge_result.get("is_valid", True),
            confidence=judge_result.get("confidence", 0.75),
            reasoning=judge_result.get("reasoning", "")
        )

        return ChatResponse(
            answer=answer,
            tools_used=tools_used,
            judge_verdict=verdict,
            conversation_id=conversation_id
        )

    except HTTPException:
        raise

    except Exception as e:
        logger.exception("Erreur inattendue")

        raise HTTPException(
            status_code=500,
            detail=f"Erreur lors de la génération : {str(e)}"
        )


@app.get(
    "/info",
    tags=["Info"],
    summary="Informations système"
)
async def get_info():
    """
    Informations sur le service.
    """

    groq_status = "connected" if os.getenv("GROQ_API_KEY") else "not_configured"
    langfuse_status = "enabled" if _get_langfuse_callbacks() else "disabled"

    return {
        "agent": "HorRAGor BOT",
        "version": "3.0.0",
        "architecture": "multi-agent (LangGraph) : rag -> router -> [scraper] -> narration",
        "llm": {
            "provider": "Groq",
            "model": "llama-3.3-70b-versatile",
            "status": groq_status
        },
        "monitoring": {
            "langfuse": langfuse_status
        },
        "agents": {
            "rag_node": [
                "search_horror_movies",
                "query_movie_metadata",
                "similar_movies",
                "movie_age",
                "survival_sim"
            ],
            "scraper_node": ["detailed_synopsis"],
            "narration_node": []
        },
        "models": {
            "request": "ChatRequest",
            "response": "ChatResponse",
            "judge_verdict": "JudgeVerdict"
        }
    }


# ============================================================================
# LANCEMENT LOCAL
# ============================================================================

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "main_api:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
        log_level="info"
    )