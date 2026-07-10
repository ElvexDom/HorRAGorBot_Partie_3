"""
Scraper Selenium — Rotten Tomatoes.

Rotten Tomatoes utilise des Web Components JavaScript (custom elements comme
<media-scorecard>, <rt-button>), ce qui rend le scraping HTML statique impossible.
Selenium pilote un vrai Chrome headless qui exécute le JavaScript.

Données extraites :
  - tomatometer_score  : % de critiques professionnels positifs (0-100)
  - audience_score     : % d'audience positive (0-100)
  - critics_consensus  : texte résumant l'opinion des critiques

Défi principal : éviter les faux positifs.
  RT renvoie parfois un film différent pour une recherche (ex: chercher "Scream"
  trouve "Primal Scream"). On valide donc le titre de la page trouvée par
  similarité Jaccard avant d'extraire les scores.

Stratégie multilingue :
  Les films stockés en français ("Hérédité", "Le Pacte des loups") ne sont pas
  sur RT en français. On essaie d'abord le titre localisé, puis l'original_title
  anglais en fallback.
"""
import re
import time
from datetime import datetime
from typing import Optional, List
from urllib.parse import quote_plus

from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, NoSuchElementException

from app.utils.browser import get_driver
from app.utils.logger import logger
from app.models.schema import RottenTomatoesData, MovieGold


def _normalize(text: str) -> str:
    """
    Normalise un texte pour la comparaison :
    minuscules, suppression des caractères non-alphanumériques,
    normalisation des espaces multiples.
    Ex : "The Shining (1980)" → "the shining 1980"
    """
    text = text.lower().strip()
    text = re.sub(r"[^\w\s]", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _title_match(searched: str, found: str, threshold: float = 0.6) -> bool:
    """
    Vérifie que le titre de la page RT correspond au film recherché.

    Utilise la similarité de Jaccard sur les ensembles de mots :
      jaccard(A, B) = |A ∩ B| / |A ∪ B|

    Exemples :
      "The Shining"  vs "The Shining"      → 1.00 (match parfait)
      "Scream"       vs "Primal Scream"     → 0.50 (rejeté si threshold=0.6)
      "Dernier train pour Busan" vs "Train to Busan" → 0.40 (rejeté)
      "Hereditary"   vs "Hereditary"        → 1.00

    threshold=0.6 : bon équilibre entre permissivité (variants de titres)
    et rigueur (éviter les faux positifs).
    """
    a = set(_normalize(searched).split())
    b = set(_normalize(found).split())
    if not a or not b:
        return False
    intersection = len(a & b)
    union = len(a | b)
    ratio = intersection / union
    logger.debug(f"Validation titre : '{searched}' vs '{found}' → ratio={ratio:.2f}")
    return ratio >= threshold


class RottenTomatoesScraper:
    """
    Scraper Selenium pour Rotten Tomatoes.

    Utilisation obligatoire comme context manager :
      with RottenTomatoesScraper() as rt:
          data = rt.scrape_movie("Hereditary", 2018)

    Le context manager gère le démarrage et l'arrêt de Chrome automatiquement.
    """

    BASE_URL   = "https://www.rottentomatoes.com"
    SEARCH_URL = f"{BASE_URL}/search?search="
    TIMEOUT    = 15   # secondes d'attente max pour les éléments Selenium

    # Sélecteurs CSS pour les différents éléments de la page
    SELECTORS = {
        # Résultat de recherche de type "movie" (exclut séries et documentaires)
        "movie_link": "a[data-qa='info-name']",
        # Web Component contenant les scores (tomatometer + audience)
        "scorecard": "media-scorecard",
        # Texte du consensus critique
        "critics_consensus": "[class*='consensus']",
        # Titre du film sur la page (plusieurs variantes selon les pages RT)
        "page_title": [
            "h1[data-qa='score-panel-title']",
            "h1[class*='title']",
            "h1",
        ],
    }

    def __init__(self):
        self.driver = None

    def __enter__(self):
        """Démarre Chrome headless à l'entrée du bloc with."""
        self.driver = get_driver()
        return self

    def __exit__(self, *args):
        """Ferme Chrome proprement à la sortie du bloc with (même en cas d'exception)."""
        if self.driver:
            self.driver.quit()
            self.driver = None

    # ------------------------------------------------------------------
    # Navigation
    # ------------------------------------------------------------------

    def _search_movie(self, title: str, year: Optional[int] = None) -> Optional[str]:
        """
        Lance une recherche sur RT et retourne l'URL du premier résultat de type "movie".

        Stratégie :
          1. Essai avec le sélecteur strict type="movie" (fiable, attend 15s)
          2. Fallback avec le sélecteur générique (attend 5s)
        La recherche inclut l'année pour réduire les ambiguïtés (ex: remakes).
        """
        query = f"{title} {year}" if year else title
        search_url = f"{self.SEARCH_URL}{quote_plus(query)}"

        logger.debug(f"RT Search : {search_url}")
        self.driver.get(search_url)
        time.sleep(2)   # pause pour laisser le JS charger les résultats

        # Essai sélecteur strict (search-page-result type="movie") puis fallback générique
        for selector in [
            'search-page-result[type="movie"] a[data-qa="info-name"]',
            self.SELECTORS["movie_link"],
        ]:
            try:
                timeout = self.TIMEOUT if selector.startswith("search-page") else 5
                WebDriverWait(self.driver, timeout).until(
                    EC.presence_of_element_located((By.CSS_SELECTOR, selector))
                )
                link = self.driver.find_element(By.CSS_SELECTOR, selector)
                return link.get_attribute("href")
            except (TimeoutException, NoSuchElementException):
                continue

        logger.debug(f"Pas de résultats RT pour : {title}")
        return None

    # ------------------------------------------------------------------
    # Validation de la page
    # ------------------------------------------------------------------

    def _extract_page_title(self) -> Optional[str]:
        """
        Extrait le titre du film affiché sur la page RT.
        Essaie plusieurs sélecteurs CSS dans l'ordre (le premier qui retourne du texte gagne).
        """
        for selector in self.SELECTORS["page_title"]:
            try:
                el   = self.driver.find_element(By.CSS_SELECTOR, selector)
                text = el.text.strip()
                if text:
                    return text
            except NoSuchElementException:
                continue
        return None

    # ------------------------------------------------------------------
    # Extraction des données
    # ------------------------------------------------------------------

    def _extract_scores_from_scorecard(self) -> tuple[Optional[int], Optional[int]]:
        """
        Extrait tomatometer et audience score depuis le Web Component <media-scorecard>.
        Le composant affiche les pourcentages sous forme "89%" et "72%".
        On cherche tous les nombres suivis de % et on prend les deux premiers.
        Premier % = tomatometer, second % = audience score.
        """
        try:
            el     = self.driver.find_element(By.CSS_SELECTOR, self.SELECTORS["scorecard"])
            scores = re.findall(r"(\d{1,3})%", el.text)
            tomatometer = int(scores[0]) if len(scores) >= 1 else None
            audience    = int(scores[1]) if len(scores) >= 2 else None
            return tomatometer, audience
        except (NoSuchElementException, IndexError):
            return None, None

    def _extract_consensus(self) -> Optional[str]:
        """
        Extrait le texte du consensus des critiques.
        Nettoie les préfixes "Certified Fresh Score." et "Critics Consensus"
        qui peuvent être inclus dans le texte.
        Filtre les textes trop courts (<30 chars) qui seraient des artefacts.
        """
        try:
            for el in self.driver.find_elements(By.CSS_SELECTOR, self.SELECTORS["critics_consensus"]):
                text = el.text.strip()
                # Supprimer les préfixes parasites
                text = re.sub(r"(?i)(certified\s+fresh\s+score\.?\s*\n?)?(critics\s+consensus\s*\n?)", "", text).strip()
                if len(text) > 30:
                    return text
        except NoSuchElementException:
            pass
        return None

    # ------------------------------------------------------------------
    # Point d'entrée principal
    # ------------------------------------------------------------------

    def scrape_movie(
        self,
        title: str,
        year: Optional[int] = None,
        original_title: Optional[str] = None,
    ) -> Optional[RottenTomatoesData]:
        """
        Scrape les scores RT pour un film donné.

        Stratégie multilingue (fallback original_title) :
          1. Recherche avec le titre localisé (ex: "Hérédité")
          2. Si validation échoue → recherche avec original_title (ex: "Hereditary")
        Cela permet de trouver les films français sur RT qui indexe les titres anglais.

        Validation par _title_match() :
          Avant d'extraire les scores, on vérifie que la page chargée correspond
          bien au film cherché (similarité Jaccard >= 0.6 sur les mots du titre).
          Cette validation élimine les faux positifs comme chercher "The Mist" et
          tomber sur "Memories in the Mist" (ratio=0.50, rejeté).

        Retourne None si :
          - Aucun résultat de recherche trouvé
          - La page trouvée ne valide pas la comparaison de titre
          - Timeout lors du chargement de la page
        """
        if not self.driver:
            raise RuntimeError("Utiliser RottenTomatoesScraper comme context manager (with ...)")

        # Construire la liste des titres à essayer dans l'ordre
        titles_to_try = [title]
        if original_title and original_title.lower() != title.lower():
            titles_to_try.append(original_title)

        for attempt_title in titles_to_try:
            if attempt_title != title:
                logger.debug(f"RT : fallback original_title → '{attempt_title}'")

            movie_url = self._search_movie(attempt_title, year)
            if not movie_url:
                continue

            logger.debug(f"RT : scraping {movie_url}")
            self.driver.get(movie_url)
            time.sleep(2)

            try:
                WebDriverWait(self.driver, self.TIMEOUT).until(
                    EC.presence_of_element_located((By.CSS_SELECTOR, "body"))
                )
            except TimeoutException:
                logger.warning(f"RT : timeout sur {movie_url}")
                continue

            # Valider contre tous les titres valides (titre localisé + original)
            valid_titles = [attempt_title]
            if original_title:
                valid_titles.append(original_title)

            page_title = self._extract_page_title()
            if page_title and not any(_title_match(t, page_title) for t in valid_titles):
                logger.info(
                    f"RT validation KO : recherché='{attempt_title}' "
                    f"| page='{page_title}' → ignoré"
                )
                continue

            # Page validée → extraire les données
            tomatometer, audience_score = self._extract_scores_from_scorecard()
            consensus = self._extract_consensus()

            logger.info(
                f"RT [{title}] → tomatometer={tomatometer}, "
                f"audience={audience_score}, consensus={'oui' if consensus else 'non'}"
            )
            return RottenTomatoesData(
                tomatometer_score=tomatometer,
                audience_score=audience_score,
                critics_consensus=consensus,
                source_url=movie_url,
                scraped_at=datetime.now(),
            )

        logger.info(f"RT : film non trouvé → {title} ({year})")
        return None

    # ------------------------------------------------------------------
    # Enrichissement batch (utilisé par main.py ancienne version)
    # ------------------------------------------------------------------

    def enrich_movies(
        self,
        movies: List[MovieGold],
        delay: float = 2.0,
        max_movies: Optional[int] = None,
    ) -> List[MovieGold]:
        """
        Enrichit une liste de MovieGold avec les scores RT.
        Méthode batch utilisée dans l'ancienne version du pipeline.
        Pour la production, préférer enrich_rt.py qui gère la reprise DB.
        """
        if not self.driver:
            raise RuntimeError("Utiliser comme context manager (with ...)")

        targets  = movies[:max_movies] if max_movies else movies
        enriched = 0

        for movie in targets:
            year = None
            if movie.release_date:
                m    = re.match(r"(\d{4})", movie.release_date)
                year = int(m.group(1)) if m else None

            rt_data = self.scrape_movie(movie.title, year)
            if rt_data:
                movie.__dict__["rt_tomatometer"]       = rt_data.tomatometer_score
                movie.__dict__["rt_audience_score"]    = rt_data.audience_score
                movie.__dict__["rt_critics_consensus"] = rt_data.critics_consensus
                movie.__dict__["rt_url"]               = rt_data.source_url
                enriched += 1

            time.sleep(delay)

        logger.info(f"RT enrichissement : {enriched}/{len(targets)} films enrichis")
        return movies
