from selenium import webdriver
from selenium.webdriver.chrome.service import Service as ChromeService
from selenium.webdriver.chrome.options import Options as ChromeOptions
from webdriver_manager.chrome import ChromeDriverManager
from app.config.config import settings
from app.utils.logger import logger
import os

def get_driver():
    """Initialise et retourne un driver Selenium (Chrome)."""
    chrome_options = ChromeOptions()
    
    if settings.SELENIUM_HEADLESS:
        chrome_options.add_argument("--headless")
    
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.add_argument("--window-size=1920,1080")
    chrome_options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36")

    try:
        logger.info("Tentative d'initialisation de Chrome Driver...")
        driver_path = ChromeDriverManager().install()
        
        # Correction pour webdriver-manager qui peut retourner un fichier texte au lieu de l'exe
        if not driver_path.endswith(".exe"):
            parent_dir = os.path.dirname(driver_path)
            potential_exe = os.path.join(parent_dir, "chromedriver.exe")
            if os.path.exists(potential_exe):
                driver_path = potential_exe
            else:
                # Si on est dans le dossier chromedriver-win32
                potential_exe = os.path.join(driver_path, "chromedriver.exe")
                if os.path.exists(potential_exe):
                    driver_path = potential_exe

        logger.info(f"Utilisation du driver : {driver_path}")
        
        service = ChromeService(executable_path=driver_path)
        driver = webdriver.Chrome(service=service, options=chrome_options)
        return driver
    except Exception as e:
        logger.error(f"Erreur lors de l'initialisation du Chrome driver : {str(e)}")
        raise e
