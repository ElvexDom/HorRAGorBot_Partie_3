import sys
import os
# Ajouter le chemin racine au PYTHONPATH
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app.scrapers.rotten_tomatoes import RottenTomatoesScraper
from app.utils.logger import logger

def test_rt():
    scraper = RottenTomatoesScraper()
    
    print("\n--- TEST ROTTEN TOMATOES SCRAPER ---")
    
    # Test avec un film d'horreur qui a des scores
    title = "Smile"
    year = "2022"
    print(f"Scraping de : {title} ({year})")
    
    data = scraper.scrape_movie(title, year)
    
    if data:
        print(f"Succès !")
        print(f"Tomatometer : {data.tomatometer_score}%")
        print(f"Audience Score : {data.audience_score}%")
        print(f"Consensus : {data.critics_consensus}")
    else:
        print("Échec du scraping (film peut-être pas encore sur RT ou URL incorrecte).")
    
    scraper.close()

if __name__ == "__main__":
    test_rt()
