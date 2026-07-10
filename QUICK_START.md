🚀 HorRAGor BOT - Quick Start avec Groq
⚡ Démarrage rapide en 5 minutes
Step 1: Obtenir une clé API Groq
Allez sur : https://console.groq.com/
Connectez-vous / créez un compte
Accédez à API Keys
Cliquez sur Create New API Key
Copiez la clé (commence généralement par gsk_...)
Step 2: Configurer .env

Ouvrez le fichier .env et remplacez :

GROQ_API_KEY=your_groq_api_key_here

Par votre vraie clé :

GROQ_API_KEY=gsk_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
Step 3: Installer les dépendances
pip install -r requirements.txt
Step 4: Tester la configuration Groq
python test_groq_config.py
Vous devriez voir :
✅ Configuration Groq
✅ Import du module
✅ Client Groq
✅ Génération de réponse
Step 5: Lancer l’API
🖥️ Terminal 1 - FastAPI
python main.py

👉 Documentation Swagger :
http://localhost:8000/docs

🎨 Terminal 2 - Streamlit
streamlit run streamlit_app.py

👉 Interface :
http://localhost:8501

🧪 Tester l’API avec curl
curl -X POST "http://localhost:8000/chat" \
  -H "Content-Type: application/json" \
  -d '{
    "question": "Recommande-moi un film d'\''horreur comme The Shining"
  }'
Réponse attendue :
{
  "answer": "[Réponse générée par Groq...]",
  "tools_used": ["groq-llm"],
  "judge_verdict": {
    "is_valid": true,
    "confidence": 0.95,
    "reasoning": "Réponse générée par Groq et validée..."
  },
  "conversation_id": "conv_default"
}
📝 Architecture
┌─────────────────┐
│   Streamlit     │
│  (Front-End)    │
└────────┬────────┘
         │ HTTP POST
         │ /chat
         ↓
┌─────────────────┐
│   FastAPI       │
│  (Back-End)     │
└────────┬────────┘
         │ async call
         │ generate_response()
         ↓
┌─────────────────┐
│   Groq LLM      │
│ (Llama / Mixtral│
└─────────────────┘
🔑 Fichiers clés
Fichier	Rôle
main.py	API FastAPI avec endpoint /chat
llm_groq.py	Client Groq asynchrone
streamlit_app.py	Interface utilisateur
.env	Configuration (GROQ_API_KEY)
requirements.txt	Dépendances
📚 Endpoints disponibles
1. /health (GET)
curl http://localhost:8000/health
2. /chat (POST)
curl -X POST "http://localhost:8000/chat" \
  -H "Content-Type: application/json" \
  -d '{"question": "Ta question ici"}'
3. /info (GET)
curl http://localhost:8000/info
4. /docs (Swagger UI)

👉 http://localhost:8000/docs

⚙️ Configuration avancée

Éditer .env :

# Modèle Groq
LLM_MODEL=llama-3.3-70b-versatile

# Température (0 = précis, 1 = créatif)
LLM_TEMPERATURE=0.7

# Max tokens
LLM_MAX_TOKENS=2048

# API server
API_HOST=0.0.0.0
API_PORT=8000
🐛 Dépannage
❌ "GROQ_API_KEY not configured"

→ Vérifie ton fichier .env

❌ "Connection refused"

→ Lance l’API :

python main.py
❌ "Module not found"
pip install -r requirements.txt
❌ Streamlit ne répond pas

Vérifie dans streamlit_app.py :

API_URL = "http://localhost:8000"
📖 Documentation
https://console.groq.com/
https://docs.groq.com/
https://fastapi.tiangolo.com/
https://docs.streamlit.io/
💡 Prochaines étapes
Ajouter RAG (FAISS / embeddings)
Ajouter mémoire conversationnelle
Intégrer LangGraph
Connecter Supabase
Ajouter cache des réponses Groq
👻 HorRAGor BOT est prêt

✔ Backend FastAPI
✔ LLM Groq connecté
✔ Frontend Streamlit
✔ Architecture scalable