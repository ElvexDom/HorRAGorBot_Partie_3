"""
Debug Rotten Tomatoes - inspecte le HTML brut de la page The Shining
Lance : python debug_rt.py
"""
from app.utils.browser import get_driver
from selenium.webdriver.common.by import By
import time

driver = get_driver()

try:
    driver.get("https://www.rottentomatoes.com/m/shining")
    time.sleep(4)  # Laisser le JS charger

    # Dump du HTML complet dans un fichier pour inspection
    html = driver.page_source
    with open("data/output/rt_debug.html", "w", encoding="utf-8") as f:
        f.write(html)
    print("✅ HTML sauvegardé dans data/output/rt_debug.html")

    # Chercher tous les éléments qui contiennent un score (chiffre + %)
    print("\n--- Recherche éléments avec score ---")
    for selector in [
        "[data-qa='tomatometer']",
        "[data-qa='audience-score']",
        "[data-qa='critics-consensus']",
        "rt-text[slot='criticsScore']",
        "rt-text[slot='audienceScore']",
        "score-board",
        "score-board-deprecated",
        "rt-button[slot='criticsScore']",
        "media-scorecard",
        "[class*='score']",
        "[class*='tomatometer']",
        "[data-qa*='score']",
    ]:
        try:
            els = driver.find_elements(By.CSS_SELECTOR, selector)
            if els:
                print(f"  ✅ '{selector}' → {len(els)} élément(s)")
                for el in els[:2]:
                    text = el.text.strip()
                    attrs = {
                        "text": text,
                        "data-qa": el.get_attribute("data-qa"),
                        "slot": el.get_attribute("slot"),
                        "class": el.get_attribute("class"),
                    }
                    print(f"     {attrs}")
            else:
                print(f"  ❌ '{selector}' → 0 résultat")
        except Exception as e:
            print(f"  ⚠️  '{selector}' → erreur: {e}")

    # Chercher le consensus
    print("\n--- Recherche consensus ---")
    for selector in [
        "[data-qa='critics-consensus']",
        "[class*='consensus']",
        "p.what-to-know__section-body",
        "[data-qa='what-to-know-critics-consensus']",
    ]:
        try:
            els = driver.find_elements(By.CSS_SELECTOR, selector)
            if els:
                print(f"  ✅ '{selector}' → {els[0].text[:100]}")
            else:
                print(f"  ❌ '{selector}' → 0 résultat")
        except Exception as e:
            print(f"  ⚠️  '{selector}' → erreur: {e}")

finally:
    driver.quit()
    print("\nDriver fermé.")