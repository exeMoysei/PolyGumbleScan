"""Punkt wejścia aplikacji."""

import logging

from polygumblescan.config import get_settings

logger = logging.getLogger(__name__)


def run() -> None:
    settings = get_settings()
    logging.basicConfig(level=settings.log_level)
    if not settings.bot_token:
        raise SystemExit("Brak BOT_TOKEN. Skopiuj .env.example do .env i uzupełnij token.")
    # Uruchomienie bota (aiogram) zostanie dodane w zadaniu #15.
    logger.info("PolyGumbleScan: konfiguracja wczytana poprawnie.")


if __name__ == "__main__":
    run()
