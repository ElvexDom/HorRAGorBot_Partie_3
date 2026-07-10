"""
API FastAPI pour HorRAGor BOT
Composant Back-End : réception des messages Streamlit et traitement via l'agent LLM

Intégration avec Groq API
"""

import asyncio
import logging
from contextlib import asynccontextmanager
from typing import Optional

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from llm_groq import GroqLLM, get_groq_client, initialize_retriever
from pydantic import BaseModel, ConfigDict, Field

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
# CLIENT GROQ (SINGLETON)
# ============================================================================

groq_client: Optional[GroqLLM] = None


def get_groq() -> GroqLLM:
    """
    Retourne une instance singleton du client Groq.
    """

    global groq_client

    if groq_client is None:
        try:
            groq_client = get_groq_client()
            logger.info("Client Groq initialisé avec succès")

        except ValueError as e:
            logger.error(f"Impossible d'initialiser Groq : {e}")
            raise

    return groq_client


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
    description="Agent conversationnel spécialisé dans l'univers de l'horreur",
    version="1.0.0",
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
        "version": "1.0.0",
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
    Reçoit une question et génère une réponse via Groq.
    """

    try:
        logger.info(
            f"Question reçue : {request.question[:100]}"
        )

        try:
            groq = get_groq()

        except ValueError:
            raise HTTPException(
                status_code=500,
                detail=(
                    "Configuration Groq manquante. "
                    "Vérifiez la variable GROQ_API_KEY."
                )
            )

        result = await groq.generate_response(
            user_question=request.question,
            conversation_history=request.history
        )

        logger.info(
            f"Réponse générée ({len(result.answer)} caractères) "
            f"— outils : {result.tools_used}"
        )

        conversation_id = (
            request.conversation_id
            or f"conv_{request.user_id or 'anonymous'}"
        )

        verdict = None
        if result.judge_verdict:
            verdict = JudgeVerdict(
                is_valid=result.judge_verdict.get("is_valid", True),
                confidence=result.judge_verdict.get("confidence", 0.75),
                reasoning=result.judge_verdict.get("reasoning", "")
            )

        return ChatResponse(
            answer=result.answer,
            tools_used=result.tools_used,
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

    groq_status = "connected"

    try:
        get_groq()

    except ValueError:
        groq_status = "not_configured"

    return {
        "agent": "HorRAGor BOT",
        "version": "1.0.0",
        "llm": {
            "provider": "Groq",
            "model": "llama-3.3-70b-versatile",
            "status": groq_status
        },
        "available_tools": [
            "groq-llm",
            "query_movie_metadata",
            "find_similar_horror_movies",
            "scrape_detailed_synopsis",
            "calculate_movie_age",
            "horror_survival_simulator"
        ],
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