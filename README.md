# PolyBot (repozytorium PolyGumbleScan)

PolyBot zbiera rynki z prediction markets (Polymarket, Kalshi) oraz kursy bukmacherów (przez The Odds API),
dopasowuje **to samo wydarzenie** na różnych platformach i szuka kombinacji zakładów, w których wypłata po
odliczeniu wszystkich kosztów pokrywa wkład we wszystkich zwykłych wynikach. Odwołanie meczu, przełożenie,
remis i zwroty są liczone jako osobne scenariusze. Wynik trafia do Telegrama jako karta ze stawkami,
wynikiem (P&L) dla każdego scenariusza, wiekiem cen i linkami.

Zakłady stawia użytkownik. Bot nie przechowuje środków, nie handluje i nie używa kluczy API do handlu.

> Interfejs bota w Telegramie (komunikaty, przyciski) jest obecnie po rosyjsku. Dokumentacja jest po polsku.

## Jak to działa

```
 adaptery ──► ingest ──► dopasowanie ──► akceptacja admina ──► scan ──► okazje + outbox ──► bot
 (Polymarket,   (katalog,   (drużyny → ID,   (Telegram /pending,   (solver    (jedna transakcja,  (karty,
  Kalshi,        kursy       wydarzenia po    wersja zasad)         Decimal,   deduplikacja po      ponowne
  Odds API)      → Redis)    czasie, rynki)                         scenariusze) czacie i rewizji)  sprawdzenie)
```

* **domain/** — czyste obliczenia: scenariusze (remis, dogrywka, total z pushem, odwołanie, przełożenie),
  modele prowizji (Polymarket `C·p·r·(p(1-p))^e`, Kalshi `ceil(0.07·C·P·(1-P))`), przejście po arkuszu zleceń,
  kurs walut z rezerwą, dokładny solver z ograniczonym przeszukiwaniem, werdykty „sygnał / kandydat / odrzucone”.
  Wyłącznie `Decimal`.
* **matching/** — rejestr drużyn NBA/NFL/NHL/MLB/EPL z aliasami wszystkich platform (także w stylu Kalshi
  „Los Angeles L”), grupowanie wydarzeń po parze drużyn i czasie (dokładny czas ±3 h, wydarzenia „tylko data”
  dołączane do jedynego meczu danego dnia, doubleheadery — po numerze gry albo do ręcznej weryfikacji),
  kanoniczny klucz rynku `wydarzenie|typ|okres|linia`, kontrola zasad, cofnięcie akceptacji przy zmianach.
* **adapters/** — osobny pakiet na dostawcę + wspólny klient HTTP (limit współbieżności, backoff z jitterem,
  Retry-After, maskowanie kluczy) i stan arkusza zleceń dla WebSocketu.
* **services/** — ingest, scan, recheck, replay; **storage/** — PostgreSQL (źródło prawdy) i Redis
  (bieżące kursy z monotonicznym zapisem przez Lua); **telegram/** — bot aiogram 3 i worker powiadomień.

Więcej: [docs/architecture.md](docs/architecture.md), subskrypcja premium — [docs/premium.md](docs/premium.md), plan sprintów i stan zadań — [docs/sprinty.md](docs/sprinty.md),
etap 0 — [docs/stage0-audit.md](docs/stage0-audit.md), eksploatacja — [docs/runbook.md](docs/runbook.md),
lista techniczna — [docs/TODO.md](docs/TODO.md), dostawcy danych — [docs/providers/](docs/providers/README.md).

## Szybki start (lokalnie, bez sieci i sekretów)

```bash
uv sync
uv run polybot demo            # pełny potok na danych testowych: parsowanie → dopasowanie → obliczenia → karty
uv run pytest -q               # testy jednostkowe (integracyjne są pomijane bez bazy)
uv run ruff check src tests && uv run mypy
```

Testy integracyjne (PostgreSQL + Redis, bez sekretów):

```bash
export POLYBOT_TEST_DATABASE_URL=postgresql+asyncpg://polybot:polybot@localhost:5432/polybot_test
export POLYBOT_TEST_REDIS_URL=redis://localhost:6379/1
uv run pytest -q
```

## Polecenia CLI

| Polecenie | Przeznaczenie |
|---|---|
| `polybot migrate` | zastosowanie migracji Alembic |
| `polybot run-ingest` | pobieranie katalogu, dopasowanie, odpytywanie kursów |
| `polybot run-scan` | przeliczanie po zmianach kursów/zasad i po wygaśnięciu TTL |
| `polybot run-bot` | bot Telegram (long polling) + worker powiadomień |
| `polybot probe [--samples N --interval S --out f.json]` | etap 0: dostęp, wolumen, głębokość/limity, część wspólna wydarzeń |
| `polybot replay --at 2026-01-15T23:00:00+00:00` | przeliczenie z historycznego zrzutu z bazy, bez przyszłych kursów |
| `polybot demo` / `polybot replay --fixtures tests/fixtures` | przebieg offline na danych testowych |
| `polybot mappings list\|approve ID\|reject ID` | kolejka powiązań rynków z konsoli (admin) |
| `polybot healthcheck` | kontrola bazy i Redisa (używane przez Dockera) |

## Polecenia bota

| Polecenie | Dla kogo | Opis |
|---|---|---|
| `/start`, `/menu` | użytkownik | subskrypcja i menu z przyciskami (Sygnały, Budżet, Filtry, Pomoc) |
| `/signals` | użytkownik | aktywne sygnały dla ustawionego budżetu |
| `/budget 250` | użytkownik | budżet na jedną kombinację |
| `/filters` | użytkownik | typy alertów (sygnały/kandydaci), trasy, minimalne ROI |
| `/minprofit 2.5` | użytkownik | minimalny zysk alertu w walucie budżetu (`0` wyłącza próg) |
| `/stop`, `/help` | użytkownik | wstrzymanie wysyłki, pomoc |
| `/premium`, `/paysupport` | użytkownik | status planu, zakup Premium w Telegram Stars, pomoc w sprawie płatności (gdy `POLYBOT_PREMIUM_ENABLED=true`) |
| `/pending` | admin | kolejka powiązań rynków do zatwierdzenia/odrzucenia |
| `/pause`, `/resume` | admin | zatrzymanie i wznowienie publikacji sygnałów |
| `/stats` | admin | liczba użytkowników, wysłane alerty, powiązania, odrzucenia |
| `/alias nba "LA Lakers" nba:lal` | admin | nowy alias drużyny |
| `/grant 123456789 30`, `/revoke 123456789` | admin | przyznanie / odebranie Premium dla czatu (zapis w `admin_actions`) |

## Wdrożenie na VPS

1. Zainstalować Docker + Compose, sklonować repozytorium, `cp .env.example .env` i uzupełnić
   (`POSTGRES_PASSWORD`, `POLYBOT_TELEGRAM_BOT_TOKEN`, `POLYBOT_ADMIN_IDS`, `POLYBOT_ODDS_API_KEY`).
2. Pierwszy pomiar etapu 0 na żywych danych:
   `docker compose run --rm ingest probe --samples 6 --interval 600 --out /tmp/probe.json`.
3. `ops/deploy.sh <sha>` — pobranie obrazu `ghcr.io/exemoysei/polygumblescan:<sha>`, migracje (log w `var/log/`),
   uruchomienie `ingest`, `scan`, `bot`, `backup`, kontrola stanu. Na zewnątrz nic nie jest wystawione: metryki
   tylko na `127.0.0.1:9101-9103`, PostgreSQL i Redis w prywatnej sieci Compose.
4. W Telegramie admin otwiera `/pending` i zatwierdza powiązania. Sygnały pojawiają się tylko dla zatwierdzonych.

Test na środowisku staging bez żywych API: `POLYBOT_FIXTURES_DIR=/app/tests/fixtures` — bot przetwarza
wydarzenia testowe z bieżącym zegarem, co pozwala sprawdzić całą ścieżkę aż do wiadomości w Telegramie.

## Najważniejsze ustawienia (`POLYBOT_*`)

`LEAGUES` (domyślnie `["nba"]`), `DEFAULT_BUDGET`, `MIN_PROFIT`, `MIN_ROI`, `ROUTES`
(`prediction_prediction`, `prediction_sportsbook`; `sportsbook_sportsbook` wyłączone), `QUOTE_TTL_S`,
`MAX_QUOTE_SKEW_S`, `FX_STATIC` + `FX_RESERVE_BPS` (USDC nie jest traktowany jak USD bez rezerwy),
`SPORTSBOOK_MAX_STAKE` (znane limity u bukmacherów), `AUTO_APPROVE_STRONG_MATCHES` (wyłączone: w MVP wszystkie
powiązania zatwierdza admin). Pełna lista — `src/polybot/settings.py`.

## Ograniczenia MVP

* Tylko prematch, 2–3 nogi, rynki „zwycięzca”, 1X2 oraz total z linią połówkową/całkowitą.
* Kursy z The Odds API zawsze dają **kandydatów**: limit jest nieznany, świeżość potwierdza tylko agregator,
  zasady bukmachera są przyjęte domyślnie.
* Zasady platform są rozpoznawane po słowach kluczowych; wszystko, czego nie rozpoznano, zostaje `unknown`
  i trafia do ręcznej weryfikacji.
* Arbitraż wewnątrz jednej platformy (suma cen YES < 1 na Polymarket) nie jest jeszcze zaimplementowany.
* Obserwacja bez realnych transakcji sprawdza skaner, ale nie potwierdza rzeczywistej rentowności.
