# Plan sprintów i stan zadań

Sprinty trwają 2 tygodnie (czwartek–czwartek). Sprinty 1–4 pochodzą z pierwotnych issues #1–#18;
sprinty 5–8 (issues #22–#34) rozszerzają plan do 8 sprintów na podstawie specyfikacji technicznej projektu.

Stan na 12.11.2026 (koniec Sprintu 1). Kolumna „Stan” opisuje kod w gałęzi `claude/lucid-wright-faibu5`,
czyli w PR #21. **PR #21 nie jest jeszcze scalony z `main`** — po merge automatycznie zamkną się issues
#1, #2, #4, #5, #11, #13–#18.

Legenda: ✅ zrobione i pokryte testami · 🟡 częściowo · ⬜ niezrobione.

## Zespół i odpowiedzialność za sprinty

| Osoba | GitHub | Rola (karta projektu) | Odpowiada za |
|---|---|---|---|
| Ivan Puzaruk | exeMoysei | lider: wyjaśnianie zadań, plan i algorytmy | Sprint 2, Sprint 5, w Sprincie 8: #33 |
| Mikhailo Ivanyshyn | Orlixx003 | programista + dokumentacja | Sprint 4, Sprint 6, w Sprincie 8: #34 |
| Artem Vozniak | temqau | programista + testy, odpowiedzialność za błędy | Sprint 3, Sprint 7, w Sprincie 8: #32 |

Sprint 1 i Sprint 8 są wspólne (zadania rozdzielone między wszystkich). Osoba odpowiedzialna za sprint jest
przypisana (assignee) do wszystkich jego issues na GitHubie.

## Sprint 1 (29.10–12.11) — fundament

Odpowiedzialni: wspólnie — #1, #15, #16 Mikhailo; #2, #17, #18 Ivan; #13, #14 Artem.

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

Odpowiedzialny: Ivan Puzaruk (exeMoysei).

| Issue | Tytuł | Stan | Uwagi |
|---|---|---|---|
| #3 | US3: Alert arbitrażowy Polymarket (suma YES < 1) | 🟡 | Jest arbitraż **między platformami** (Polymarket ↔ Kalshi ↔ bukmacher). Brakuje arbitrażu **wewnątrz Polymarket**: suma cen YES wszystkich wyników jednego rynku < 1 — skaner wymaga dziś różnych platform |
| #4 | US4: Realny zysk w alercie (orderbook + opłaty) | ✅ | przejście po poziomach arkusza zleceń, prowizje Polymarket i Kalshi, kurs walut z rezerwą, zysk dla każdego scenariusza |
| #5 | US5: Minimalny próg zysku dla alertów | ✅ | `/minprofit 2.5` (kwota), minimalne ROI w `/filters`, progi globalne `MIN_PROFIT`, `MIN_ROI` |

Do zrobienia w sprincie: US3 dla rynków wielowynikowych Polymarket (pobieranie wszystkich aktywnych wydarzeń
`negRisk`, trasa „jedna platforma”, test na danych testowych).

## Sprint 3 (26.11–10.12) — portfele

Odpowiedzialny: Artem Vozniak (temqau).

| Issue | Tytuł | Stan | Uwagi |
|---|---|---|---|
| #6 | US6: Alert: nowy portfel z dużym zakładem | ⬜ | wymaga nowego źródła danych (transakcje Polymarket: Data API / on-chain) |
| #7 | US7: Obserwowanie wybranego portfela | ⬜ | zależy od US6 |
| #8 | US8: Włączanie/wyłączanie typów alertów | 🟡 | `/filters` włącza i wyłącza sygnały, kandydatów i trasy; do rozszerzenia o nowe typy alertów (portfele, kasyna) |

## Sprint 4 (10.12–24.12) — ranking, kasyna, admin

Odpowiedzialny: Mikhailo Ivanyshyn (Orlixx003).

| Issue | Tytuł | Stan | Uwagi |
|---|---|---|---|
| #9 | US9: Ranking najskuteczniejszych użytkowników | ⬜ | |
| #10 | US10: Alert o dużych zakładach graczy kasyn | ⬜ | wymaga wyboru źródła danych i sprawdzenia warunków korzystania |
| #11 | US11: Panel admina: statystyki | ✅ | `/stats`: liczba użytkowników, aktywne subskrypcje, wysłane alerty (łącznie i 24 h), powiązania, odrzucenia |
| #12 | US12: Subskrypcja premium | ✅ | plan Free/Premium, limit alertów na dobę, płatność w Telegram Stars, `/grant` i `/revoke`; opis w [premium.md](premium.md). Domyślnie wyłączone (`POLYBOT_PREMIUM_ENABLED`) |

## Sprint 5 (24.12–07.01) — arbitraż między platformami

Odpowiedzialny: Ivan Puzaruk (exeMoysei).

| Issue i historia | Stan | Uwagi |
|---|---|---|
| #22 US13: Jako klient chcę alert, gdy to samo wydarzenie ma różne ceny na Polymarket i Kalshi | ✅ | adapter Kalshi, dopasowanie wydarzeń, trasa prediction ↔ prediction |
| #23 US14: Jako klient chcę alert dla pary prediction market ↔ bukmacher | ✅ | The Odds API; zawsze jako „kandydat” (nieznany limit, świeżość tylko z agregatora) |
| #24 US15: Jako admin chcę zatwierdzać powiązania rynków między platformami | ✅ | `/pending`, akceptacja związana z wersją zasad, automatyczne cofnięcie przy zmianie |
| Zadanie: pomiar części wspólnej wydarzeń na żywych danych (`polybot probe`) | ⬜ | wymaga VPS i klucza The Odds API |

## Sprint 6 (07.01–21.01) — jakość sygnału

Odpowiedzialny: Mikhailo Ivanyshyn (Orlixx003).

| Issue i historia | Stan | Uwagi |
|---|---|---|
| #25 US16: Jako klient chcę ponownie sprawdzić alert przed postawieniem zakładu | ✅ | przycisk „Sprawdź ponownie”: nowa rewizja albo zamknięcie karty |
| #26 US17: Jako klient chcę ustawić budżet i dostać stawki dopasowane do budżetu | ✅ | `/budget`, kroki i minimalne rozmiary platform |
| #27 US18: Jako klient chcę widzieć wynik przy odwołaniu/przełożeniu meczu i zasady rozliczenia | ✅ | scenariusze wyjątkowe na karcie, przycisk „Zasady” |
| Zadanie: wersja językowa bota (PL) | ⬜ | komunikaty są dziś po rosyjsku |

## Sprint 7 (21.01–04.02) — wdrożenie i niezawodność

Odpowiedzialny: Artem Vozniak (temqau).

| Issue i historia | Stan | Uwagi |
|---|---|---|
| #28 US19: Jako admin chcę wdrożyć system na VPS jednym poleceniem | 🟡 | Dockerfile, Compose, `ops/deploy.sh` gotowe i sprawdzone lokalnie; brak wdrożenia na prawdziwym VPS |
| #29 US20: Jako admin chcę kopie zapasowe bazy i test odtworzenia | ✅ | `ops/backup.sh`, `ops/restore_test.sh` — wykonane lokalnie w Compose |
| #30 US21: Jako admin chcę monitoring i powiadomienia techniczne | ✅ | metryki Prometheus, przykładowe alerty, kanał techniczny |
| #31 US22: Jako admin chcę odtworzyć obliczenie z historii (replay) | ✅ | `polybot replay` bez użycia przyszłych kursów |

## Sprint 8 (04.02–18.02) — pilotaż i zamknięcie

Odpowiedzialni: wspólnie — #32 Artem (pilotaż, błędy), #33 Ivan (algorytmy), #34 Mikhailo (dokumentacja).

| Issue i historia | Stan | Uwagi |
|---|---|---|
| #32 US23: Pilotaż na żywych danych i raport z metryk (opóźnienie, duplikaty, odsetek odrzuconych) | ⬜ | wymaga działającego wdrożenia |
| #33 US24: Nowe ligi/źródła i kombinacje 3+ zakładów | 🟡 | 3 nogi i 5 lig działają; LP/MILP i bezpośrednie feedy bukmacherów — nie |
| #34 US25: Dokumentacja końcowa i prezentacja projektu | 🟡 | dokumentacja techniczna jest; brak raportu z pilotażu i prezentacji |

## Decyzje i sprawy otwarte

1. **Baza kodu.** Właściciel repozytorium zdecydował (12.11.2026), że bazą jest gałąź z PR #21 (pakiet
   `polybot`). PR #19 i #20 (pakiet `polygumblescan`) zostały zamknięte bez scalenia; ich gałęzie nie są
   usunięte.
2. **Merge PR #21 do `main`.** Dopóki PR nie jest scalony, zadania oznaczone ✅ istnieją tylko w gałęzi.
3. **Zakres US3 (#3).** Do ustalenia: czy alert „suma YES < 1” ma obejmować wszystkie rynki Polymarket
   (polityka, krypto itd.), czy tylko sport.
4. **Tablica projektu.** Issues #22–#34 trzeba dodać do tablicy „Polymarket arbitrage bot”, jeśli nie dodały
   się automatycznie.
