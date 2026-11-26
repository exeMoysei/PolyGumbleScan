# PolyBot (repozytorium PolyGumbleScan)

Bot na Telegramie, który śledzi prediction markets (Polymarket, Kalshi) i kursy bukmacherów (The Odds API) i wysyła:

* **arbitraż między platformami** — kombinacje zakładów na **to samo wydarzenie**, w których wypłata po wszystkich
  kosztach pokrywa wkład w każdym zwykłym wyniku (odwołanie, przełożenie i remis liczone osobno);
* **suma YES < 1 na Polymarket** — wydarzenie z wieloma wynikami, w którym zakup YES na każdy wynik kosztuje mniej
  niż wypłata 1 USDC;
* **nowe portfele z dużym zakładem** i **transakcje obserwowanych portfeli** (Polymarket);
* **ranking najlepszych graczy** (`/top`).

Zakłady stawia użytkownik. Bot nie przechowuje środków i nie handluje. Komunikaty bota i kod są po angielsku,
dokumentacja — po polsku.

## Szybki start (lokalnie, bez Dockera)

Wymagany Python 3.12 lub 3.13.

```bash
python -m venv venv
source venv/bin/activate            # Windows: venv\Scripts\activate
pip install -r requirements.txt     # programiści: pip install -r requirements-dev.txt
cp .env.example .env                # uzupełnij POLYBOT_TELEGRAM_BOT_TOKEN i POLYBOT_ADMIN_IDS
python -m polybot run
```

`python -m polybot run` uruchamia wszystko w jednym procesie: pobieranie rynków, skaner, alerty portfeli, bota
i wysyłkę powiadomień. Dane trafiają do jednego pliku SQLite (`polybot.db`) — PostgreSQL, Redis ani Docker nie są
potrzebne. Bez tokenu bot zbiera i liczy dane, ale nic nie wysyła.

W Telegramie: `/start` → admin zatwierdza powiązania rynków w `/pending` → alerty przychodzą same, `/signals`
pokazuje aktywne okazje. To jest ścieżka MVP, opisana krok po kroku w [docs/podzial-pracy.md](docs/podzial-pracy.md).

Bez internetu i bez tokenu: `python -m polybot demo` — cały potok na danych testowych.

## Struktura projektu

```
src/polybot/
├── data/       1. DANE      — skąd dane przychodzą i gdzie leżą: API platform, baza, pamięć podręczna kursów
├── logic/      2. LOGIKA    — reguły biznesowe bez sieci i bazy: arbitraż, dopasowanie wydarzeń, alerty
├── bot/        3. INTERFEJS — Telegram: komendy, karty, przyciski, wysyłka
├── services/   procesy łączące warstwy: pobieranie → logika → zapis → powiadomienie
├── cli.py      polecenia (python -m polybot …)
└── settings.py ustawienia z .env
tests/
├── unit/         szybkie testy bez bazy
├── integration/  cała ścieżka na bazie (domyślnie SQLite)
└── fixtures/     dane testowe w formacie odpowiedzi API (oznaczone TEST DATA)
docs/             dokumentacja (po polsku)
migrations/       migracje Alembic (PostgreSQL)
ops/              skrypty serwera: wdrożenie, kopie zapasowe, monitoring
```

Granice warstw sprawdza test `tests/unit/test_layers.py`: `logic/` nie importuje bazy, HTTP ani Telegrama,
a `data/` nie importuje `services/` ani `bot/`. Kto odpowiada za który moduł — [docs/podzial-pracy.md](docs/podzial-pracy.md).

## Polecenia bota

| Polecenie | Opis |
|---|---|
| `/start`, `/menu` | subskrypcja i menu z przyciskami |
| `/signals` | aktywne okazje arbitrażowe dla Twojego budżetu |
| `/budget 250` | budżet na jedną kombinację |
| `/filters` | typy alertów (arbitraż, suma YES, nowe portfele, obserwowane portfele), sygnały/kandydaci, trasy, ROI |
| `/minprofit 2.5` | minimalny zysk alertu arbitrażowego |
| `/top [day\|week\|month\|all] [volume]` | ranking graczy Polymarket |
| `/follow 0x… [min_usdc] [nazwa]`, `/following`, `/unfollow 0x…` | obserwowane portfele |
| `/premium` | plan Premium (alerty bez dziennego limitu) |
| `/pending`, `/pause`, `/resume`, `/stats`, `/alias`, `/grant`, `/revoke` | tylko admin |

## Polecenia CLI

| Polecenie | Przeznaczenie |
|---|---|
| `python -m polybot run` | wszystko w jednym procesie (najprostszy start) |
| `python -m polybot migrate` | tabele w SQLite albo migracje Alembic w PostgreSQL |
| `python -m polybot run-ingest` / `run-scan` / `run-bot` | osobne procesy (serwer, Docker Compose) |
| `python -m polybot demo` | potok offline na danych testowych |
| `python -m polybot probe` | pomiar źródeł na żywych danych (dostęp, wolumen, wspólne wydarzenia) |
| `python -m polybot replay --at …` | przeliczenie z historii bez przyszłych kursów |
| `python -m polybot mappings list\|approve ID\|reject ID` | powiązania rynków z konsoli |

## Testy i jakość

```bash
pip install -r requirements-dev.txt
pytest -q                           # testy jednostkowe + integracyjne na SQLite
ruff check src tests && mypy        # styl i typy (mypy strict)
```

Na PostgreSQL + Redis (jak w CI): ustaw `POLYBOT_TEST_DATABASE_URL` i `POLYBOT_TEST_REDIS_URL`. Zespół może też
używać `uv` (`uv sync`, `uv run pytest`) — `requirements*.txt` są generowane z `uv.lock`.

## Serwer (produkcja)

Docker Compose z PostgreSQL i Redis: `cp .env.example .env`, `ops/deploy.sh <sha>`. Szczegóły, kopie zapasowe
i monitoring: [docs/runbook.md](docs/runbook.md).

## Dokumentacja

| Plik | Zawartość |
|---|---|
| [docs/podzial-pracy.md](docs/podzial-pracy.md) | warstwy, kto odpowiada za który moduł, ścieżka MVP |
| [docs/sprinty.md](docs/sprinty.md) | 16 sprintów, zadania i ich stan |
| [docs/architecture.md](docs/architecture.md) | jak działa dopasowanie wydarzeń i solver |
| [docs/zrodla-danych.md](docs/zrodla-danych.md) | API: Polymarket, Kalshi, The Odds API, kasyna |
| [docs/premium.md](docs/premium.md) | subskrypcja Premium |
| [docs/runbook.md](docs/runbook.md) | serwer, kopie zapasowe, monitoring |
| [docs/stage0-audit.md](docs/stage0-audit.md) | audyt startowy i wybór rynku |
| [docs/TODO.md](docs/TODO.md) | lista techniczna wg etapów specyfikacji |
