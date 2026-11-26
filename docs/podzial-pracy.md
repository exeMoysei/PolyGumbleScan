# Podział pracy: warstwy, moduły i ścieżka MVP

Zadanie z zajęć 26.11 (Sprint 3): szkielet projektu, w którym kilka osób pracuje równolegle, i pierwsza pełna
ścieżka użytkownika (MVP). Issues: #37 (struktura, venv, `requirements.txt`), #38 (moduły i sygnatury — każdy
bierze swój kawałek), #39 (MVP scalone przez PR).

## Warstwy

```
  data/  ──►  logic/  ◄──  bot/
 (dane)     (logika)     (interfejs)
     ▲          ▲           ▲
     └──── services/ ───────┘   procesy łączą warstwy
```

| Warstwa | Katalog | Co robi | Zasada |
|---|---|---|---|
| 1. Dane | `src/polybot/data/` | klienci API (Polymarket, Kalshi, The Odds API), baza (SQLite/PostgreSQL), pamięć kursów | nie importuje `services/` ani `bot/` |
| 2. Logika | `src/polybot/logic/` | arbitraż, dopasowanie wydarzeń, reguły alertów, premium | bez sieci, bazy i Telegrama — same funkcje, łatwe testy |
| 3. Interfejs | `src/polybot/bot/` | komendy Telegrama, karty, przyciski, wysyłka | korzysta z logiki i danych |
| Procesy | `src/polybot/services/` | pętle: pobierz → policz → zapisz → powiadom | jedyne miejsce, które łączy wszystko |

Granice sprawdza `tests/unit/test_layers.py` — PR, który je złamie, nie przejdzie CI.

## Kto odpowiada za który moduł

Role z karty projektu: Ivan — lider, plan i algorytmy; Mikhailo — programista i dokumentacja; Artem — programista,
testy i błędy. Właściciel modułu robi review zmian w nim. `*` = szkielet: sygnatury i opis są, treść funkcji do
napisania (`NotImplementedError`).

### Ivan Puzaruk (exeMoysei) — logika arbitrażu i dopasowania

| Moduł | Zawartość |
|---|---|
| `logic/money.py`, `enums.py`, `models.py`, `codec.py` | typy domenowe, `Decimal`, kodowanie do JSON |
| `logic/scenarios.py`, `fees.py`, `legs.py`, `solver.py`, `prefilter.py`, `verdict.py` | silnik: scenariusze, prowizje, przejście po arkuszu, solver, werdykt |
| `logic/names.py`, `teams.py`, `teams_data.py`, `events.py`, `markets.py`, `catalog.py` | dopasowanie tego samego wydarzenia na różnych platformach |
| `logic/scanner.py`, `payload.py`, `yes_sum.py` | skaner arbitrażu, karta okazji, suma YES < 1 (US3) |
| `logic/crypto_arbitrage.py` * | różnice cen kryptowalut (US29, #43) |
| `services/scan.py`, `pipeline.py`, `recheck.py`, `replay.py` | procesy skanera |

### Mikhailo Ivanyshyn (Orlixx003) — bot, premium, kasyna, dokumentacja

| Moduł | Zawartość |
|---|---|
| `bot/handlers.py`, `keyboards.py`, `cards.py` | komendy, menu, filtry, karty okazji |
| `bot/alerts.py`, `bot/wallets.py` | teksty alertów portfeli i sumy YES, `/follow`, `/following`, `/top` |
| `bot/notifier.py` | wysyłka z kolejki (outbox) |
| `bot/premium.py`, `logic/premium.py`, `data/premium_repo.py`, `services/premium.py` | Premium (US12) |
| `logic/alerts.py` | typy alertów i ich przełączanie (US8) |
| `data/casino.py` *, `logic/casino_alerts.py` * | kasyna (US10 #10, US32–US34 #46–#48) |
| `docs/` | dokumentacja |

### Artem Vozniak (temqau) — dane, portfele, testy, wdrożenie

| Moduł | Zawartość |
|---|---|
| `data/http.py`, `sources.py`, `parsing.py`, `rules.py`, `orderbook.py` | wspólne narzędzia źródeł danych |
| `data/polymarket.py`, `kalshi.py`, `odds_api.py`, `fixtures.py` | klienci platform i dane testowe |
| `data/polymarket_users.py`, `logic/wallets.py`, `data/wallets_repo.py` | portfele: duże zakłady, obserwowane, ranking (US6, US7, US9) |
| `data/db.py`, `tables.py`, `repo.py`, `quote_cache.py`, `migrations/` | baza i pamięć kursów |
| `data/crypto_prices.py` * | ceny kryptowalut z giełd (US26–US28, #40–#42) |
| `services/ingest.py`, `wallets.py`, `app.py`, `runtime.py` | procesy zbierania danych i start „wszystko w jednym” |
| `tests/`, `ops/`, `.github/workflows/` | testy, wdrożenie, CI |

## Jak pracujemy równolegle

1. Jedno zadanie = jedna gałąź: `feature/<numer-issue>-krotki-opis`.
2. Zmieniasz głównie swoje moduły; zmiana w cudzym — właściciel robi review.
3. Przed PR: `pytest -q`, `ruff check src tests`, `mypy`.
4. PR do `main` z `Closes #<numer>`; CI musi być zielone.

## Ścieżka MVP od początku do końca

| Krok | Co się dzieje | Moduł |
|---|---|---|
| 1 | Użytkownik wysyła `/start`; subskrypcja zapisuje się w bazie (SQLite) | `bot/handlers.py` → `data/repo.py` |
| 2 | Bot pobiera wydarzenia i rynki z Polymarket i Kalshi | `services/ingest.py` → `data/polymarket.py`, `data/kalshi.py` |
| 3 | To samo wydarzenie z obu platform łączy się w jedno | `logic/events.py`, `logic/markets.py` |
| 4 | Admin zatwierdza powiązanie w `/pending` | `bot/handlers.py` → `data/repo.py` |
| 5 | Pobierane są arkusze zleceń, skaner liczy zysk po opłatach | `services/scan.py` → `logic/scanner.py`, `logic/solver.py` |
| 6 | Okazja i wiadomość do wysłania zapisują się w jednej transakcji | `data/repo.py` |
| 7 | Użytkownik dostaje kartę; `/signals` pokazuje listę aktywnych okazji | `bot/notifier.py`, `bot/cards.py` |

Uruchomienie: `python -m polybot run`. Test całej ścieżki bez internetu: `pytest tests/integration/test_flow.py`.
Na żywych danych (26.11.2026) bot połączył 48 wspólnych wydarzeń Polymarket ↔ Kalshi (NBA, NHL, EPL).

## Kasyna (US10) — decyzja do podjęcia

Żadne duże kasyno kryptowalutowe (Stake, Rollbit, BC.Game) nie udostępnia publicznego API zakładów innych graczy.

| Opcja | Plusy | Minusy |
|---|---|---|
| Kasyna on-chain (zakłady to transakcje w blockchainie, odczyt przez Polygon RPC) | legalne, stabilne, dane publiczne | mniejsze kasyna; trzeba wybrać kontrakty i odczytać ich zdarzenia |
| Scraping strony kasyna | duże kasyna | narusza regulamin, blokady Cloudflare, częste awarie |

Rekomendacja: on-chain. Szkielet jest gotowy w `data/casino.py` (`OnChainCasinoSource`) i `logic/casino_alerts.py`.
