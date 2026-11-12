# Plan sprintów i stan zadań

Sprinty trwają 2 tygodnie (czwartek–czwartek). Sprinty 1–4 pochodzą z istniejących issues na GitHubie;
sprinty 5–8 to **propozycja** rozszerzenia planu do 8 sprintów, oparta na specyfikacji technicznej projektu.

Stan na 12.11.2026 (koniec Sprintu 1). Kolumna „Stan” opisuje kod w gałęzi `claude/lucid-wright-faibu5`.
**Ta gałąź nie jest jeszcze scalona z `main`** — zadanie można uznać za zamknięte dopiero po merge.

Legenda: ✅ zrobione i pokryte testami · 🟡 częściowo · ⬜ niezrobione.

## Sprint 1 (29.10–12.11) — fundament

| Issue | Tytuł | Stan | Uwagi |
|---|---|---|---|
| #1 | US1: Bot: komenda /start i menu | ✅ | `/start` zakłada subskrypcję i pokazuje menu z przyciskami inline (Sygnały, Budżet, Filtry, Pomoc); `/menu` |
| #2 | US2: Zapis rynków i alertów w bazie danych | ✅ | PostgreSQL: `markets`, `outcomes`, `opportunities` (alerty z rewizjami), `outbox` (wysyłki), `quote_snapshots` |
| #13 | Struktura projektu, .env, konfiguracja Ruff i pytest | ✅ | pakiet `src/polybot`, `pyproject.toml`, `.env.example`. **Równolegle istnieje PR #19** (pakiet `polygumblescan`) — do rozstrzygnięcia, patrz niżej |
| #14 | GitHub Actions: Ruff i testy | ✅ | `.github/workflows/ci.yml` (ruff, mypy, pytest z PostgreSQL/Redis, obraz Dockera). **Równolegle istnieje PR #20** |
| #15 | Bot aiogram 3: /start i menu z przyciskami inline | ✅ | `src/polybot/telegram/bot.py`, `keyboards.py` |
| #16 | README: opis projektu i instrukcja uruchomienia | ✅ | `README.md` po polsku |
| #17 | Schemat bazy danych + SQLAlchemy | ✅ | 16 tabel, SQLAlchemy 2 async, migracja startowa Alembic |
| #18 | Klient Polymarket Gamma API | ✅ | `adapters/polymarket`: aktywne wydarzenia sportowe wybranych lig, także rynki wielowynikowe (3 kontrakty binarne w EPL). Pobieranie *wszystkich* kategorii rynków nie jest zrobione — potrzebne dla US3 |

## Sprint 2 (12.11–26.11) — alert arbitrażowy

| Issue | Tytuł | Stan | Uwagi |
|---|---|---|---|
| #3 | US3: Alert arbitrażowy Polymarket (suma YES < 1) | 🟡 | Jest arbitraż **między platformami** (Polymarket ↔ Kalshi ↔ bukmacher). Brakuje arbitrażu **wewnątrz Polymarket**: suma cen YES wszystkich wyników jednego rynku < 1 — skaner wymaga dziś różnych platform |
| #4 | US4: Realny zysk w alercie (orderbook + opłaty) | ✅ | przejście po poziomach arkusza zleceń, prowizje Polymarket i Kalshi, kurs walut z rezerwą, zysk dla każdego scenariusza |
| #5 | US5: Minimalny próg zysku dla alertów | ✅ | `/minprofit 2.5` (kwota), minimalne ROI w `/filters`, progi globalne `MIN_PROFIT`, `MIN_ROI` |

Do zrobienia w sprincie: US3 dla rynków wielowynikowych Polymarket (pobieranie wszystkich aktywnych wydarzeń
`negRisk`, trasa „jedna platforma”, test na danych testowych).

## Sprint 3 (26.11–10.12) — portfele

| Issue | Tytuł | Stan | Uwagi |
|---|---|---|---|
| #6 | US6: Alert: nowy portfel z dużym zakładem | ⬜ | wymaga nowego źródła danych (transakcje Polymarket: Data API / on-chain) |
| #7 | US7: Obserwowanie wybranego portfela | ⬜ | zależy od US6 |
| #8 | US8: Włączanie/wyłączanie typów alertów | 🟡 | `/filters` włącza i wyłącza sygnały, kandydatów i trasy; do rozszerzenia o nowe typy alertów (portfele, kasyna) |

## Sprint 4 (10.12–24.12) — ranking, kasyna, admin

| Issue | Tytuł | Stan | Uwagi |
|---|---|---|---|
| #9 | US9: Ranking najskuteczniejszych użytkowników | ⬜ | |
| #10 | US10: Alert o dużych zakładach graczy kasyn | ⬜ | wymaga wyboru źródła danych i sprawdzenia warunków korzystania |
| #11 | US11: Panel admina: statystyki | ✅ | `/stats`: liczba użytkowników, aktywne subskrypcje, wysłane alerty (łącznie i 24 h), powiązania, odrzucenia |
| #12 | US12: Subskrypcja premium | ⬜ | |

## Sprint 5 (24.12–07.01) — arbitraż między platformami *(propozycja)*

| Historia | Stan | Uwagi |
|---|---|---|
| US13: Jako klient chcę alert, gdy to samo wydarzenie ma różne ceny na Polymarket i Kalshi | ✅ | adapter Kalshi, dopasowanie wydarzeń, trasa prediction ↔ prediction |
| US14: Jako klient chcę alert dla pary prediction market ↔ bukmacher | ✅ | The Odds API; zawsze jako „kandydat” (nieznany limit, świeżość tylko z agregatora) |
| US15: Jako admin chcę zatwierdzać powiązania rynków między platformami | ✅ | `/pending`, akceptacja związana z wersją zasad, automatyczne cofnięcie przy zmianie |
| Zadanie: pomiar części wspólnej wydarzeń na żywych danych (`polybot probe`) | ⬜ | wymaga VPS i klucza The Odds API |

## Sprint 6 (07.01–21.01) — jakość sygnału *(propozycja)*

| Historia | Stan | Uwagi |
|---|---|---|
| US16: Jako klient chcę ponownie sprawdzić alert przed postawieniem zakładu | ✅ | przycisk „Sprawdź ponownie”: nowa rewizja albo zamknięcie karty |
| US17: Jako klient chcę ustawić budżet i dostać stawki dopasowane do budżetu | ✅ | `/budget`, kroki i minimalne rozmiary platform |
| US18: Jako klient chcę widzieć wynik przy odwołaniu/przełożeniu meczu i zasady rozliczenia | ✅ | scenariusze wyjątkowe na karcie, przycisk „Zasady” |
| Zadanie: wersja językowa bota (PL) | ⬜ | komunikaty są dziś po rosyjsku |

## Sprint 7 (21.01–04.02) — wdrożenie i niezawodność *(propozycja)*

| Historia | Stan | Uwagi |
|---|---|---|
| US19: Jako admin chcę wdrożyć system na VPS jednym poleceniem | 🟡 | Dockerfile, Compose, `ops/deploy.sh` gotowe i sprawdzone lokalnie; brak wdrożenia na prawdziwym VPS |
| US20: Jako admin chcę kopie zapasowe bazy i test odtworzenia | ✅ | `ops/backup.sh`, `ops/restore_test.sh` — wykonane lokalnie w Compose |
| US21: Jako admin chcę monitoring i powiadomienia techniczne | ✅ | metryki Prometheus, przykładowe alerty, kanał techniczny |
| US22: Jako admin chcę odtworzyć obliczenie z historii (replay) | ✅ | `polybot replay` bez użycia przyszłych kursów |

## Sprint 8 (04.02–18.02) — pilotaż i zamknięcie *(propozycja)*

| Historia | Stan | Uwagi |
|---|---|---|
| US23: Pilotaż na żywych danych i raport z metryk (opóźnienie, duplikaty, odsetek odrzuconych) | ⬜ | wymaga działającego wdrożenia |
| US24: Nowe ligi/źródła i kombinacje 3+ zakładów | 🟡 | 3 nogi i 5 lig działają; LP/MILP i bezpośrednie feedy bukmacherów — nie |
| US25: Dokumentacja końcowa i prezentacja projektu | 🟡 | dokumentacja techniczna jest; brak raportu z pilotażu i prezentacji |

## Sprawy do rozstrzygnięcia przez zespół

1. **Dwie struktury projektu.** PR #19 i #20 (autor: temqau) tworzą pakiet `polygumblescan` z konfiguracją
   i CI. Gałąź `claude/lucid-wright-faibu5` zawiera pełną implementację w pakiecie `polybot` (inny
   `pyproject.toml`, inny `ci.yml`). Obu wersji nie da się scalić bez konfliktów — trzeba wybrać jedną
   jako bazę i przenieść do niej brakujące elementy drugiej.
2. **Merge do `main`.** Dopóki gałąź nie jest scalona, zadania oznaczone ✅ istnieją tylko w niej.
3. **Zakres US3.** Czy alert ma obejmować wszystkie rynki Polymarket (polityka, krypto itd.), czy tylko sport.
4. **Sprinty 5–8.** Propozycję trzeba zatwierdzić i założyć dla niej issues na tablicy projektu.
