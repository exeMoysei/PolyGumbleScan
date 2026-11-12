# TODO — PolyBot (lista techniczna wg etapów specyfikacji)

Plan sprintów i stan issues z GitHuba: [sprinty.md](sprinty.md).

Legenda: `[x]` zrobione i sprawdzone testami/przebiegiem, `[~]` zrobione, wymaga sprawdzenia na VPS z żywymi
danymi/kluczami, `[ ]` niezrobione. Kod znajduje się w gałęzi `claude/lucid-wright-faibu5` (jeszcze nie w `main`).

## Etap 0 — audyt
- [x] Inwentaryzacja repozytorium (był tylko README) — `docs/stage0-audit.md`
- [x] Kontrola dostępów ze środowiska dev (API platform zablokowane polityką sieciową — odnotowane)
- [x] Porównanie kontraktów Polymarket (Gamma, CLOB, prowizje `fd`), Kalshi (`orderbook_fp`, same bidy), The Odds API v4
- [x] Polecenie `polybot probe`: dostęp, opóźnienie, wydarzenia/rynki/kursy, głębokość, limity, część wspólna
- [x] Wybór rynku: NBA moneyline (z dogrywką), prematch; rezerwa EPL 1X2
- [~] Tabela z liczbą wspólnych wydarzeń w okresie obserwacji — uruchomić `probe --samples 12` na VPS

## Etap 1 — szkielet i silnik
- [x] Python 3.12, uv, `pyproject.toml`, `uv.lock`, struktura `src/polybot/{domain,adapters,matching,services,storage,telegram}`
- [x] Modele domenowe: Provider/Venue, Event, Market, Outcome, RuleSet, Quote, FX, Capabilities (unknown = unknown)
- [x] Scenariusze: zwycięzca z dogrywką, czas regulaminowy (remis), 1X2, total .5 i całkowity (push), odwołanie, przełożenie
- [x] Prowizje: Polymarket `C·p·r·(p(1−p))^e`, Kalshi `ceil(0.07·C·P·(1−P))`, % od stawki, prowizja od wygranej
- [x] Przejście po arkuszu zleceń, cena średnia, brak głębokości; stawka minimalna, krok, maksimum; wypłaty zaokrąglane w dół
- [x] Kurs walut z ostrożną rezerwą w obie strony, przeterminowany kurs blokuje sygnał
- [x] Wstępna selekcja `S = Σ1/dᵢ` (tylko dla podziału liniowego) i wzór na stawki idealne (48.59 / 51.41)
- [x] Dokładny solver: kotwica + sąsiednie rozmiary + granice, limit przeszukiwania → `solver_limit`
- [x] Werdykty: sygnał / kandydat (limity, agregator, strata lub unknown w wyjątkach, zasady domyślne) / odrzucone
- [x] Dane testowe oznaczone TEST DATA: remis, zwrot, prowizja, głębokość, obie trasy
- [x] CI: ruff, ruff format, mypy strict, pytest z PostgreSQL/Redis, alembic check, demo-smoke, obraz wg SHA

## Etap 2 — zbieranie danych
- [x] Adaptery Polymarket, Kalshi, The Odds API (+ capabilities, włączanie konfiguracją i wg lig)
- [x] HTTP: limit współbieżności, backoff z jitterem, Retry-After, maskowanie kluczy
- [x] Przechowywanie: SQLAlchemy 2 async, Alembic, unikalne zewnętrzne ID w obrębie dostawcy, NUMERIC, UTC
- [x] Źródło danych ≠ marka bukmachera (`oddsapi:<bookmaker>:<region>`)
- [x] Redis: zapis monotoniczny (Lua), spóźniona/zduplikowana aktualizacja odrzucana, TTL per źródło
- [x] Historia kursów z ograniczonym czasem przechowywania, wersja zasad przy każdym rynku
- [x] Awaria jednego źródła nie zatrzymuje pozostałych (sprawdzone w Compose bez sieci)
- [x] Tryb smoke `POLYBOT_FIXTURES_DIR`: wydarzenia testowe z bieżącym zegarem dla środowiska staging
- [x] Arkusz z WebSocketu: zrzut + delty, luka w sekwencji → nieważny do następnego zrzutu
- [~] Normalizacja na prawdziwych odpowiedziach — sprawdzić przez `probe` na VPS

## Etap 3 — zasady i skaner
- [x] Rejestr drużyn NBA/NFL/NHL/MLB/EPL z aliasami platform, aliasy z bazy (`/alias`)
- [x] Dopasowanie wydarzeń: para drużyn + okno czasu, „tylko data”, doubleheadery, role, pewność
- [x] Kanoniczny klucz rynku, wyniki → scenariusze, „Nie” na kontrakcie binarnym, „A / nie A” w piłce nożnej
- [x] Rozpoznawanie zasad (dogrywka, odwołanie 50-50 / „Nie” / void, przełożenie carry / void, remis), unknown → needs_review
- [x] Kolejka ręcznej weryfikacji, akceptacja związana z wersją zasad i parametrami; zmiana → invalidated
- [x] Skaner po zmianach (debounce), po TTL, kontrola wersji wejścia przed publikacją
- [x] Okazja + outbox w jednej transakcji, rewizje tylko przy istotnej zmianie
- [x] Testy: remis, dogrywka, niezgodny total, przełożenie, jednostronny zwrot

## Etap 4 — Telegram
- [x] `/start` z menu inline, `/menu`, `/signals`, `/filters`, `/budget`, `/minprofit`, `/help`, `/stop`
- [x] Karta: wydarzenie i okres, wyniki, platformy, stawki, wolumeny/unknown, wypłaty, min. P&L, wyjątki, czas zrzutu, linki
- [x] Przyciski „Sprawdź ponownie”, „Zasady”, „Ukryj”; kontrola właściciela i bieżącej rewizji
- [x] Ponowne sprawdzenie: nowe kursy → nowa rewizja albo zamknięcie karty
- [x] Admin: `/pending` z akceptacją/odrzuceniem (wg wersji zasad), `/pause`, `/resume`, `/stats` (użytkownicy, wysłane alerty), `/alias`
- [x] Worker outbox: dzierżawa, backoff, wygasanie, deduplikacja, blokada bota przez użytkownika → subskrypcja wyłączona
- [x] Maskowanie tokenów, kluczy i haseł w logach
- [~] Ręczny przebieg z prawdziwym tokenem bota (staging: `POLYBOT_FIXTURES_DIR`)
- [ ] Wersja językowa bota po polsku (komunikaty są po rosyjsku)

## Etap 5 — VPS i pilotaż
- [x] Dockerfile, docker-compose (sieć prywatna, metryki tylko na localhost), healthcheck, usługa migrate
- [x] Kopie `pg_dump` + test odtworzenia (`ops/restore_test.sh`) — wykonane lokalnie w Compose
- [x] Restart: stan się odtwarza, bez ponownej wysyłki (znalezione i naprawione w przebiegu Compose)
- [x] Zerwanie połączenia z Redisem/bazą nie zatrzymuje pętli ingest i scan (znalezione w Compose, naprawione, jest test)
- [x] Unieważnione powiązanie nie zasypuje admina przy każdym discovery; kolejna zmiana parametrów przywraca je do kolejki
- [x] Metryki Prometheus dla pilotażu, przykład scrape i alertów, runbook
- [x] Replay z historycznego zrzutu bez przyszłych kursów (`polybot replay`)
- [x] Wdrożenie wg SHA (`ops/deploy.sh`, workflow `deploy`)
- [~] Pilotaż na żywych danych: opóźnienie, duplikaty, odsetek odrzuconych — po wdrożeniu

## Etap 6 — skalowanie (kolejne zadania)
- [ ] Arbitraż wewnątrz Polymarket: suma cen YES wszystkich wyników < 1 (US3)
- [ ] Alerty portfeli, ranking użytkowników, gracze kasyn, subskrypcja premium (US6, US7, US9, US10, US12)
- [ ] Bezpośrednie feedy bukmacherów i giełd zakładów (osobny model odpowiedzialności dla lay)
- [ ] 3+ wyniki przez LP/MILP (`max t: pnl[s] ≥ t`) z końcową weryfikacją w Decimal
- [ ] Middles: różne linie totalu jako podział scenariuszy
- [ ] WebSocket Kalshi z podpisanymi kluczami, WS Polymarket domyślnie po pilotażu
- [ ] Wersjonowanie akceptacji w czasie dla dokładnego replay powiązań
