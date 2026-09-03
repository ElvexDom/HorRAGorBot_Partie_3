"""
API FastAPI de la Couche Données (HorRAGor 1).

Encapsule tous les accès à la base de films : la Couche Intelligence
(main_api.py / graph/ / tools/) ne parle plus jamais SQL directement, elle
appelle ce service via tools/data_api_client.py.
"""
import logging

from fastapi import Depends, FastAPI, HTTPException, Query
from sqlalchemy.orm import Session

from data_api.db import find_film_by_title, get_films_by_ids, get_session, to_film_detail
from data_api.schemas import FilmDetail

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

app = FastAPI(
    title="HorRAGor Data API",
    description="Couche Données — encapsule l'accès à la base de films (HorRAGor 1)",
    version="1.0.0",
)


@app.get("/health", tags=["Health"])
async def health_check():
    return {"status": "ok"}


@app.get("/films/search", response_model=FilmDetail, tags=["Films"])
async def search_film(
    title: str = Query(..., min_length=1, description="Titre (français ou original) à rechercher"),
    session: Session = Depends(get_session),
):
    film = find_film_by_title(session, title)
    if film is None:
        raise HTTPException(status_code=404, detail=f"Aucun film trouvé pour « {title} ».")
    return to_film_detail(film)


@app.get("/films/batch", response_model=list[FilmDetail], tags=["Films"])
async def batch_films(
    ids: str = Query(..., description="Liste d'ids séparés par des virgules, ex: 1,2,3"),
    session: Session = Depends(get_session),
):
    try:
        id_list = [int(i) for i in ids.split(",") if i.strip()]
    except ValueError:
        raise HTTPException(status_code=422, detail="`ids` doit être une liste d'entiers séparés par des virgules.")

    films_by_id = get_films_by_ids(session, id_list)
    # Préserve l'ordre des ids en entrée (classement de similarité FAISS en amont).
    return [to_film_detail(films_by_id[i]) for i in id_list if i in films_by_id]


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("data_api.main:app", host="0.0.0.0", port=8100, reload=True, log_level="info")
