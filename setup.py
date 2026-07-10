#!/usr/bin/env python
"""
Guide d'installation et de configuration de HorRAGor BOT avec Grok
"""

import os
import sys
from pathlib import Path

def print_header(text):
    print(f"\n{'='*60}")
    print(f"  {text}")
    print(f"{'='*60}\n")

def check_python_version():
    """Vérifie que Python 3.8+ est utilisé"""
    print_header("Vérification de la version Python")
    
    version = sys.version_info
    if version.major >= 3 and version.minor >= 8:
        print(f"✅ Python {version.major}.{version.minor}.{version.micro} OK")
        return True
    else:
        print(f"❌ Python 3.8+ requis (actuellement: {version.major}.{version.minor})")
        return False

def check_files():
    """Vérifie que les fichiers nécessaires existent"""
    print_header("Vérification des fichiers")
    
    required_files = [
        "main.py",
        "llm_grok.py",
        "streamlit_app.py",
        "requirements.txt",
        ".env"
    ]
    
    all_exist = True
    for file in required_files:
        if os.path.exists(file):
            print(f"✅ {file}")
        else:
            print(f"❌ {file} (manquant)")
            all_exist = False
    
    return all_exist

def check_env_file():
    """Vérifie la configuration du fichier .env"""
    print_header("Vérification du fichier .env")
    
    if not os.path.exists(".env"):
        print("❌ .env n'existe pas")
        return False
    
    with open(".env", "r") as f:
        content = f.read()
    
    if "your_xai_api_key_here" in content:
        print("⚠️  XAI_API_KEY n'est pas configurée")
        print("\n📋 Pour obtenir une clé API Grok:")
        print("   1. Allez sur: https://console.x.ai/")
        print("   2. Créez un compte si vous n'en avez pas")
        print("   3. Allez dans API Keys")
        print("   4. Créez une nouvelle clé API")
        print("   5. Copiez la clé dans le fichier .env:")
        print("      XAI_API_KEY=votre_clé_api_ici")
        return False
    else:
        print("✅ XAI_API_KEY configurée")
        return True

def install_requirements():
    """Installe les dépendances"""
    print_header("Installation des dépendances")
    
    try:
        import subprocess
        print("Installation en cours... (cela peut prendre quelques minutes)")
        result = subprocess.run(
            [sys.executable, "-m", "pip", "install", "-q", "-r", "requirements.txt"],
            capture_output=True,
            text=True
        )
        
        if result.returncode == 0:
            print("✅ Dépendances installées")
            return True
        else:
            print(f"❌ Erreur lors de l'installation: {result.stderr}")
            return False
    except Exception as e:
        print(f"❌ Erreur: {str(e)}")
        return False

def print_next_steps(grok_configured):
    """Affiche les prochaines étapes"""
    print_header("Prochaines étapes")
    
    if grok_configured:
        print("1️⃣  Pour tester la configuration Grok:")
        print("   python test_grok_config.py\n")
        
        print("2️⃣  Pour lancer l'API FastAPI:")
        print("   python main.py")
        print("   ou")
        print("   uvicorn main:app --reload\n")
        
        print("3️⃣  Pour lancer Streamlit (dans un autre terminal):")
        print("   streamlit run streamlit_app.py\n")
        
        print("4️⃣  Documentation de l'API:")
        print("   http://localhost:8000/docs (Swagger)")
        print("   http://localhost:8000/redoc (ReDoc)\n")
        
        print("5️⃣  Interface utilisateur:")
        print("   http://localhost:8501 (Streamlit)\n")
    else:
        print("❌ Veuillez configurer XAI_API_KEY avant de continuer")
        print("\nÉtapes:")
        print("   1. Obtenir une clé API sur: https://console.x.ai/")
        print("   2. Éditer le fichier .env")
        print("   3. Définir XAI_API_KEY=votre_clé_api")
        print("   4. Relancer ce script")

def main():
    print("\n")
    print("     ██╗  ██╗ ██████╗ ██████╗ ██████╗  █████╗  ██████╗ ██████╗ ██████╗")
    print("     ██║  ██║██╔═══██╗██╔══██╗██╔══██╗██╔══██╗██╔════╝██╔════╝██╔════╝")
    print("     ███████║██║   ██║██████╔╝██████╔╝███████║██║     ██║     ██║")
    print("     ██╔══██║██║   ██║██╔══██╗██╔══██╗██╔══██║██║     ██║     ██║")
    print("     ██║  ██║╚██████╔╝██║  ██║██║  ██║██║  ██║╚██████╗╚██████╗╚██████╗")
    print("     ╚═╝  ╚═╝ ╚═════╝ ╚═╝  ╚═╝╚═╝  ╚═╝╚═╝  ╚═╝ ╚═════╝ ╚═════╝ ╚═════╝")
    print("                         Agent Conversationnel de l'Horreur")
    print("                              Powered by Grok (xAI)")
    
    print_header("Guide d'Installation et Configuration")
    
    # Vérifications
    checks = [
        ("Python 3.8+", check_python_version()),
        ("Fichiers nécessaires", check_files()),
    ]
    
    all_ok = all(result for _, result in checks)
    
    if not all_ok:
        print("\n❌ Vérifications échouées. Veuillez corriger les erreurs ci-dessus.")
        return False
    
    # Installer les dépendances
    if not install_requirements():
        return False
    
    # Vérifier la configuration Grok
    grok_configured = check_env_file()
    
    # Afficher les prochaines étapes
    print_next_steps(grok_configured)
    
    return grok_configured

if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
