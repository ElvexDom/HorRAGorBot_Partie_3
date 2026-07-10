# 🩸 HorRAGor BOT — Deck de soutenance (9 slides)

> Chaque slide est suivie de ses **🎤 Notes orateur** : ce que tu racontes à l'oral
> (contexte, anecdotes, pourquoi) — pas une paraphrase de la slide.
> Les extraits de code sont tirés du vrai repo.

---
---

## SLIDE 1 — Titre & équipe

# 🩸 HorRAGor BOT
### L'agent conversationnel qui connaît vraiment l'horreur

**Un chatbot RAG + ReAct anti-hallucination**
1179 films · 6 outils · 1 Juge

*Tim (Front-End) · Nicolas (FAISS) · Julie (API + Tools)*

### 🎤 Notes orateur — Slide 1
- Accroche : « Demandez à ChatGPT la note Rotten Tomatoes d'un film d'horreur
  obscur de 2012 : il vous répondra avec assurance… et souvent faux. Notre bot,
  lui, refuse d'inventer. »
- Poser le contexte en 2 phrases : Partie 1 = on a construit la base de données
  (pipeline d'ingestion TMDB/IMDB/RT + PySpark). Partie 2 = on construit le
  « cerveau » qui l'exploite.
- Annoncer le plan : architecture → données → agent → outils → Le Juge → démo.
- Ne pas s'attarder : 30 secondes max sur cette slide.

---
---

## SLIDE 2 — Le problème & notre réponse

### Le problème : les LLM hallucinent
- Un LLM seul **invente** des dates, des notes, des synopsis
- Inacceptable pour un assistant « expert »

### Notre réponse : 3 garde-fous
| Garde-fou | Rôle |
|---|---|
| 🗄️ **RAG** (SQL + vectoriel) | L'agent répond depuis **nos données réelles** |
| 🧰 **Tools** (ReAct) | Le LLM **agit** au lieu de deviner |
| ⚖️ **Le Juge** | Un 2ᵉ LLM **relit et rejette** les réponses douteuses |

### 🎤 Notes orateur — Slide 2
- Raconter l'anecdote vécue : pendant les tests, quand la base était
  inaccessible, le bot se rabattait sur sa mémoire interne et recommandait
  toujours les mêmes classiques (« L'Exorciste, Halloween… ») — exactement le
  comportement qu'on voulait éliminer. C'est ce qui nous a poussés à durcir le
  system prompt et à afficher les outils utilisés dans l'UI.
- Expliquer le terme RAG si la classe n'est pas à l'aise : Retrieval-Augmented
  Generation = on va chercher les faits AVANT de générer la réponse.
- Teaser : « Le Juge, on y revient en détail slide 8 — c'est notre pièce
  maîtresse. »

---
---

## SLIDE 3 — Architecture : découplage strict

```
┌─────────────────┐  HTTP POST /chat   ┌─────────────────┐
│    STREAMLIT    │ ─────────────────► │     FASTAPI     │
│  frontend/app.py│ ◄───────────────── │   main_api.py   │
│  (UI seulement) │    JSON typé       │ (Pydantic strict)│
└─────────────────┘                    └────────┬────────┘
                                                │
                                       ┌────────▼────────┐
                                       │  AGENT ReAct    │
                                       │   llm_groq.py   │
                                       │ Groq llama-3.3  │
                                       │  + ⚖️ Le Juge   │
                                       └──┬─────┬─────┬──┘
                                          │     │     │
                                   ┌──────▼─┐ ┌─▼───┐ ┌▼─────────┐
                                   │ FAISS  │ │ DB  │ │Wikipédia │
                                   │ (RAM)  │ │Supa-│ │ API REST │
                                   │1179 vec│ │base │ │  (live)  │
                                   └────────┘ └─────┘ └──────────┘
```

**Règle d'or** : le front ne contient **aucune** logique métier, aucune clé API.

### 🎤 Notes orateur — Slide 3
- Insister sur le POURQUOI du découplage : on peut remplacer Streamlit par une
  app mobile demain sans toucher au back ; les clés Groq/Supabase ne quittent
  jamais le serveur ; et chacun de nous a pu travailler sur sa brique (front /
  FAISS / API) sans se marcher dessus — 3 branches Git, 3 développeurs.
- Mentionner le typage Pydantic : chaque requête/réponse est validée — si le
  front envoie n'importe quoi, l'API refuse proprement (HTTP 422), pas de crash.
- Transition : « Voyons maintenant ce qu'il y a dans cette base. »

---
---

## SLIDE 4 — Les données : Hub & Spoke (héritage Partie 1)

```
                    ┌──────────┐
     ┌──────────────│   FILM   │──────────────┐
     │              │  (hub)   │              │
     │              └────┬─────┘              │
┌────▼─────┐      ┌──────▼──────┐      ┌──────▼───────┐
│  GENRE   │      │ EVALUATION  │      │ ANALYSE_SPARK│
│ (spoke)  │      │   (spoke)   │      │   (spoke)    │
│Horror,...│      │TMDB/IMDB/RT │      │horror_keywords│
└──────────┘      └─────────────┘      └──────────────┘
```

⚠️ **Piège vécu** : `genres` et `vote_average` ne sont **pas** des colonnes de `film` !

```sql
SELECT f.title,
       ARRAY_AGG(DISTINCT g.name)                          AS genres,
       MAX(CASE WHEN e.source_name = 'TMDB'
           THEN e.score_value END)                         AS vote_average
FROM film f
LEFT JOIN film_genre fg ON f.id = fg.film_id
LEFT JOIN genre g       ON fg.genre_id = g.id
LEFT JOIN evaluation e  ON f.id = e.film_id
WHERE f.id = ANY(%s)
GROUP BY f.id, f.title
```

### 🎤 Notes orateur — Slide 4
- Raconter le bug en mode « war story » : un de nos outils interrogeait
  `SELECT genres FROM film` → PostgreSQL renvoyait *column does not exist* →
  notre gestion d'erreur trop générique traduisait ça en « base inaccessible » →
  on a passé du temps à suspecter Supabase (qui était en pause Free Tier par
  ailleurs, vraie fausse piste !). Leçon double : 1) respecter le modèle Hub &
  Spoke partout, 2) ne jamais masquer les vraies erreurs derrière un message
  générique.
- Rappeler d'où viennent les `horror_keywords` : c'est le résultat du job
  PySpark de la Partie 1 — et on va les réutiliser dans le simulateur de survie
  (slide 7). Boucle bouclée entre les deux parties du projet.

---
---

## SLIDE 5 — FAISS : la recherche par le sens

**Objectif** : « recommande un film de possession » → trouver les bons films
**sans** que le mot “possession” soit forcément dans le synopsis.

```python
# llm_groq.py — au démarrage (une seule fois, en RAM)
_model = SentenceTransformer("all-MiniLM-L6-v2")   # texte → vecteur 384 dims
_index = faiss.read_index("data/faiss.index")      # 1179 synopsis vectorisés
_id_map = np.load("data/id_map.npy")               # position FAISS → id film

# À chaque recherche : ~2 ms
def _search_horror_movies(query: str, k: int = 5) -> str:
    vec = _model.encode([query], normalize_embeddings=True)
    _, indices = _index.search(vec, k)          # similarité cosinus
    film_ids = [int(_id_map[i]) for i in indices[0]]
    films = _fetch_films_from_db(film_ids)      # jointures Supabase
    ...
```

**Pipeline** : requête → vecteur → top-k voisins FAISS → IDs → SQL → contexte réel pour le LLM

### 🎤 Notes orateur — Slide 5
- Vulgariser l'embedding : « chaque synopsis devient un point dans un espace à
  384 dimensions ; deux films qui parlent de la même chose sont des points
  proches. La recherche = trouver les plus proches voisins du point-question. »
- `normalize_embeddings=True` : détail technique à placer si question — vecteurs
  normalisés ⇒ le produit scalaire EST la similarité cosinus, c'est ce que fait
  l'index en interne.
- Justifier le choix vs pgvector (le brief le suggérait) : index en RAM = zéro
  latence réseau, zéro charge sur Supabase (qui est un Free Tier partagé !), et
  le calcul vectoriel est découplé de la base. Trade-off assumé : si les données
  changent, on relance `utils/build_faiss_index.py`. Sur un dataset figé de
  1179 films, c'est le bon compromis.
- Anticiper la question « pourquoi MiniLM ? » : 91 Mo, rapide sur CPU, largement
  suffisant pour de la similarité de synopsis — pas besoin d'un modèle 7B.

---
---

## SLIDE 6 — L'agent ReAct : le LLM qui agit au lieu de deviner

**Pas de framework (LangChain) : une boucle tool-use maison, transparente.**

```python
# llm_groq.py — le cœur du ReAct : Reason → Act → Observe → Respond
response = await self.client.chat.completions.create(
    model="llama-3.3-70b-versatile",
    messages=messages,
    tools=TOOLS,              # les 6 outils décrits en JSON Schema
    tool_choice="auto",       # 🧠 REASON : le LLM choisit lui-même
)

if choice.finish_reason == "tool_calls":
    tool_name = tool_call.function.name
    args = json.loads(tool_call.function.arguments)

    if tool_name == "query_movie_metadata":            # 🎬 ACT
        metadata = await asyncio.to_thread(query_movie_metadata,
                                           args["movie_name"])
        # 👁️ OBSERVE : le résultat réel repart au LLM
        tool_result_msg = {"role": "tool", "content": metadata, ...}
        response2 = await self.client.chat.completions.create(
            messages=[*messages, assistant_msg, tool_result_msg], ...)
        answer = response2.choices[0].message.content   # ✍️ RESPOND
```

🔒 Le LLM **ne génère jamais de SQL** — il fournit un titre, nos fonctions Python font des requêtes paramétrées.

### 🎤 Notes orateur — Slide 6
- Assumer le choix devant le jury : le brief mentionnait LangChain/LangGraph.
  On a préféré implémenter le cycle ReAct nous-mêmes avec le tool-use natif du
  SDK OpenAI (compatible Groq). Arguments : (1) on comprend et on peut déboguer
  chaque étape — pas de « magie » de framework, (2) moins de dépendances,
  (3) c'était trivial d'y insérer notre nœud d'évaluation custom, Le Juge.
  Pédagogiquement, on a appris ce que LangChain fait sous le capot.
- Expliquer `tool_choice="auto"` : c'est LE moment « Reason » — le modèle lit
  les descriptions des 6 outils et décide seul lequel appeler (ou aucun).
  La qualité des descriptions d'outils est donc cruciale : on les a réécrites
  plusieurs fois pendant les tests.
- Anecdote technique si le temps le permet : trop de « OBLIGATOIRE » /
  « INTERDIT » en majuscules dans le system prompt faisait bugger la génération
  des tool calls de llama-3.3 (erreur `tool_use_failed` chez Groq). Un prompt
  plus sobre a résolu le problème — le prompt engineering, c'est de l'artisanat.
- Mentionner la mémoire conversationnelle : le front envoie les 8 derniers
  messages, donc « quel âge a LE film ? » après avoir parlé de *Dans le noir*
  fonctionne (résolution de référence implicite).

---
---

## SLIDE 7 — La boîte à outils : 6 tools, zoom sur 2

| # | Tool | Source |
|---|---|---|
| 1 | `query_movie_metadata` | SQL Supabase |
| 2 | `similar_movies` | FAISS |
| 3 | `search_horror_movies` | FAISS |
| 4 | `movie_age` | Python pur |
| 5 | `detailed_synopsis` | Wikipédia live |
| 6 | `survival_sim` 🎲 | SQL + PySpark keywords |

**Zoom `movie_age`** — parfois le bon outil n'est PAS un LLM :
```python
release = row["release_date"]; today = date.today()
age = today.year - release.year - (
    (today.month, today.day) < (release.month, release.day))
date_fr = f"{release.day} {_MOIS_FR[release.month]} {release.year}"
```

**Zoom `survival_sim`** — les données PySpark de la Partie 1 réutilisées :
```python
SELECT f.overview, s.horror_keywords, s.richness_score
FROM film f LEFT JOIN analyse_spark s ON f.id = s.film_id
WHERE f.title ILIKE %s
```
→ injectées dans un prompt « maître du jeu sadique » : *probabilité de survie,
cause de mort probable, 3 menaces, verdict cinglant* 💀

### 🎤 Notes orateur — Slide 7
- `movie_age` : le point pédagogique, c'est qu'un LLM est MAUVAIS en
  arithmétique de dates — donc on ne lui demande pas. Fonction Python pure,
  zéro appel réseau, résultat exact garanti. Bonus : le dictionnaire `_MOIS_FR`
  existe parce que Windows renvoyait les mois en anglais via la locale système —
  petit bug réel, fix simple.
- `survival_sim` : c'est le pont avec la Partie 1 — les `horror_keywords`
  extraits par le job PySpark nourrissent la créativité du LLM. Montrer que
  RAG ≠ réponses ennuyeuses : ici les données réelles CADRENT la créativité
  (les menaces citées viennent vraiment du film).
- Dire un mot de `detailed_synopsis` : API REST Wikipédia (pas de scraping HTML
  fragile), tronqué à la dernière phrase complète — c'est l'outil « aller
  chercher en direct sur le web » demandé par le brief.
- Rappeler la règle transverse : chaque tool attrape ses erreurs et renvoie un
  message exploitable par le LLM plutôt qu'une stack trace.

---
---

## SLIDE 8 — ⚖️ Le Juge : l'anti-hallucination

**Après CHAQUE réponse, un 2ᵉ appel LLM évalue — et peut faire recommencer.**

```python
_JUDGE_SYSTEM_PROMPT = (
    "Tu es Le Juge, un évaluateur strict de HorRAGor BOT. "
    "Ta mission : détecter les hallucinations et vérifier la cohérence. "
    'Format obligatoire : {"is_valid": true, "confidence": 0.95, '
    '"reasoning": "..."} ...')

# Jugement déterministe : température 0.1 (vs 0.7 pour l'agent)
verdict = await self._judge_response(question, answer, tools_used)

for attempt in range(_MAX_RETRIES):        # max 2 retries
    if verdict["is_valid"] or verdict["confidence"] >= 0.65:
        break
    retry_messages.append({"role": "user", "content":
        f"[Critique du Juge] {verdict['reasoning']}. Corrige-la..."})
    answer  = ...  # l'agent réécrit sa réponse
    verdict = await self._judge_response(question, answer, tools_used)
```

**Verdict affiché en direct dans l'UI :**
🩸 APPROUVÉ (≥ 80 %) · ⚠️ MITIGÉ (< 80 %) · 💀 CONDAMNÉ (invalide → retry)

### 🎤 Notes orateur — Slide 8
- C'est LA slide à défendre le plus : pattern « LLM-as-a-judge », utilisé en
  production dans l'industrie (évaluation automatique de réponses).
- Détailler les 2 températures : l'agent crée à 0.7 (réponses vivantes), le
  Juge évalue à 0.1 (jugement froid, quasi déterministe). Deux rôles, deux
  réglages.
- Expliquer la boucle de correction : le Juge ne se contente pas de noter — sa
  critique (`reasoning`) est réinjectée à l'agent comme un message utilisateur,
  et l'agent corrige. Max 2 tentatives pour borner la latence et le coût.
- Transparence côté utilisateur : le verdict, le % de confiance ET les outils
  utilisés s'affichent dans le bandeau bas de l'UI. L'utilisateur sait toujours
  D'OÙ vient la réponse et à quel point le système lui fait confiance.
  Choix UX : les noms d'outils sont bannis du corps de la réponse (naturel)
  et réservés au bandeau (traçabilité).
- Limite à admettre si on vous pousse : le Juge est le même modèle que l'agent
  — il peut partager ses angles morts. Piste : un modèle différent pour juger.

---
---

## SLIDE 9 — Démo & bilan

### 🎬 Démo live (le bandeau du Juge sous chaque réponse)
```
« Parle-moi de The Shining »        → query_movie_metadata  (SQL)
« Films similaires à Hereditary »   → similar_movies        (FAISS)
« Quel âge a LE film ? »            → mémoire multi-tours ✨
« Je survivrais dans Scream ? »     → survival_sim 💀
```

### ✅ Ce qu'on retient
- **Découplage** front / API / agent — 3 devs en parallèle
- **Zéro SQL généré par le LLM** — requêtes paramétrées uniquement
- **Le Juge** : confiance mesurée et affichée, retry automatique

### 🔮 Perspectives
- Juge sur un modèle différent (croiser les angles morts)
- pgvector si les données deviennent évolutives
- Historique persistant (base) au-delà de la session

*(+ l'UI cache des zombies interactifs — drag & throw, à lancer sur la lune 🧟🌕)*

### 🎤 Notes orateur — Slide 9
- Dérouler la démo dans CET ordre : chaque question déclenche un outil
  différent, et la 3ᵉ montre la mémoire conversationnelle (poser d'abord une
  question sur un film, PUIS demander « quel âge a le film ? » sans le nommer —
  avant ce fix, le bot répondait sur Shining par défaut, vécu en test !).
- Pointer physiquement le bandeau du Juge à l'écran après la première réponse :
  verdict + % + outils. C'est la matérialisation de tout le discours
  anti-hallucination.
- Garder les zombies pour la FIN — moment détente : attraper un zombie à la
  souris, le lancer sur la lune, il marche en orbite tête en bas. Message
  sérieux derrière : soigner l'UX d'un projet data, ça marque les esprits
  (et c'est du JS/SVG injecté, pas un gadget de librairie).
- Phrase de clôture proposée : « HorRAGor ne sait pas tout — mais il ne vous
  mentira pas : il vérifie, il cite ses sources, et quand il doute, il vous le
  dit. C'est ça, pour nous, une IA de confiance. »
- Si question sur la répartition du travail : Tim front + intégration, Nicolas
  FAISS + similarité, Julie API + tools — mais revue de code croisée sur main.
