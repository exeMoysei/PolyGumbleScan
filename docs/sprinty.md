# Plan sprintów i stan zadań

16 sprintów po 2 tygodnie (czwartek–czwartek), od 29.10.2026 do 10.06.2027. Sprinty 1–4: pierwotne issues #1–#18;
sprinty 5–8: #22–#34; sprinty 9–16: #40–#63; zadania z zajęć 26.11: #37–#39.

Stan na 26.11.2026 (koniec Sprintu 2, początek Sprintu 3), wg kodu w PR z gałęzi `claude/lucid-wright-faibu5`.
Po scaleniu tego PR zamkną się #3, #6, #7, #8, #37, #38, #39.

Legenda: ✅ zrobione i pokryte testami · 🟡 częściowo · ⬜ niezrobione.

## Zespół

| Osoba | GitHub | Rola (karta projektu) | Sprinty |
|---|---|---|---|
| Ivan Puzaruk | exeMoysei | lider: plan i algorytmy | 2, 5, 10, 13 + części 1, 8, 15, 16 |
| Mikhailo Ivanyshyn | Orlixx003 | programista + dokumentacja | 4, 6, 11, 14 + części 1, 8, 15, 16 |
| Artem Vozniak | temqau | programista + testy, odpowiedzialność za błędy | 3, 7, 9, 12 + części 1, 8, 15, 16 |

Osoba odpowiedzialna za sprint jest przypisana do jego issues. Moduły i ich właściciele: [podzial-pracy.md](podzial-pracy.md).

## Sprint 1 (29.10–12.11) — fundament

Odpowiedzialni: wspólnie — #1, #15, #16 Mikhailo; #2, #17, #18 Ivan; #13, #14 Artem.

| Issue | Tytuł | Stan | Uwagi |
|---|---|---|---|
| #1 | US1: Bot: komenda /start i menu | ✅ | `/start` zapisuje subskrypcję i pokazuje menu z przyciskami (Signals, Budget, Filters, Help) |
| #2 | US2: Zapis rynków i alertów w bazie danych | ✅ | `markets`, `outcomes`, `opportunities`, `outbox`, `quote_snapshots`; SQLite lokalnie, PostgreSQL na serwerze |
| #13 | Struktura projektu, .env, Ruff i pytest | ✅ | `src/polybot`, `pyproject.toml`, `requirements.txt`, `.env.example` |
| #14 | GitHub Actions: Ruff i testy | ✅ | `.github/workflows/ci.yml` |
| #15 | Bot aiogram 3: /start i menu inline | ✅ | `src/polybot/bot/handlers.py`, `keyboards.py` |
| #16 | README | ✅ | `README.md` po polsku |
| #17 | Schemat bazy danych + SQLAlchemy | ✅ | `src/polybot/data/tables.py`, migracje Alembic |
| #18 | Klient Polymarket Gamma API | ✅ | `src/polybot/data/polymarket.py`, działa na żywych danych |

## Sprint 2 (12.11–26.11) — alert arbitrażowy

Odpowiedzialny: Ivan Puzaruk (exeMoysei).

| Issue | Tytuł | Stan | Uwagi |
|---|---|---|---|
| #3 | US3: Alert arbitrażowy Polymarket (suma YES < 1) | ✅ | wszystkie kategorie, wydarzenia `negRisk`; zysk po prowizjach na dostępnym wolumenie. Na żywo 26.11: 93 wydarzenia, 1 okazja (+0.57 USDC) |
| #4 | US4: Realny zysk w alercie (orderbook + opłaty) | ✅ | prowizje Polymarket z `feeSchedule` rynku (poprawione 26.11) |
| #5 | US5: Minimalny próg zysku dla alertów | ✅ | `/minprofit`, ROI w `/filters` |

## Sprint 3 (26.11–10.12) — portfele i szkielet projektu

Odpowiedzialny: Artem Vozniak (temqau).

| Issue | Tytuł | Kto | Stan | Uwagi |
|---|---|---|---|---|
| #6 | US6: Alert: nowy portfel z dużym zakładem | Artem | ✅ | Data API v2 `/v2/trades` (≥ 5000 USDC), „nowy” = ≤ 10 transakcji w ostatnich 7 dniach |
| #7 | US7: Obserwowanie wybranego portfela | Artem | ✅ | `/follow 0x… [min_usdc] [nazwa]`, `/following`, `/unfollow` |
| #8 | US8: Włączanie/wyłączanie typów alertów | Artem | ✅ | w `/filters`: arbitraż, suma YES, nowe portfele, obserwowane portfele |
| #37 | Szkielet: katalogi, venv, `requirements.txt` | Artem | ✅ | warstwy `data/` → `logic/` → `bot/`, SQLite, `python -m venv venv` |
| #38 | Moduły i puste funkcje z sygnaturami | wszyscy | ✅ | szkielety: `data/casino.py`, `logic/casino_alerts.py`, `data/crypto_prices.py`, `logic/crypto_arbitrage.py` |
| #39 | MVP: pełna ścieżka użytkownika przez PR | Ivan | ✅ | `python -m polybot run`; test `tests/integration/test_flow.py` |

## Sprint 4 (10.12–24.12) — ranking, kasyna, admin

Odpowiedzialny: Mikhailo Ivanyshyn (Orlixx003).

| Issue | Tytuł | Stan | Uwagi |
|---|---|---|---|
| #9 | US9: Ranking najskuteczniejszych użytkowników | 🟡 | `/top`: zysk i wolumen (dzień/tydzień/miesiąc/wszystko). Odsetek trafień nie jest w API — US36 (#50) |
| #10 | US10: Alert o dużych zakładach graczy kasyn | 🟡 | szkielet z sygnaturami; brak decyzji o źródle danych (zob. podzial-pracy.md) |
| #11 | US11: Panel admina: statystyki | ✅ | `/stats` |
| #12 | US12: Subskrypcja premium | ✅ | [premium.md](premium.md) |

## Sprint 5 (24.12–07.01) — arbitraż między platformami

Odpowiedzialny: Ivan Puzaruk (exeMoysei).

| Issue i historia | Stan | Uwagi |
|---|---|---|
| #22 US13: Polymarket ↔ Kalshi | ✅ | na żywo 26.11: 48 wspólnych wydarzeń (NBA, NHL, EPL), skaner liczy wszystkie pary; okazji akurat brak |
| #23 US14: prediction market ↔ bukmacher | 🟡 | adapter gotowy, potrzebny klucz The Odds API |
| #24 US15: Admin zatwierdza powiązania rynków | ✅ | `/pending`, akceptacja związana z wersją zasad |

## Sprint 6 (07.01–21.01) — jakość sygnału

Odpowiedzialny: Mikhailo Ivanyshyn (Orlixx003).

| Issue i historia | Stan | Uwagi |
|---|---|---|
| #25 US16: Ponowne sprawdzenie alertu | ✅ | przycisk „Recheck” |
| #26 US17: Budżet i stawki | ✅ | `/budget` |
| #27 US18: Wynik przy odwołaniu/przełożeniu i zasady | ✅ | przycisk „Rules” |
| Zadanie: język bota | ✅ | wszystko po angielsku |

## Sprint 7 (21.01–04.02) — wdrożenie i niezawodność

Odpowiedzialny: Artem Vozniak (temqau).

| Issue i historia | Stan | Uwagi |
|---|---|---|
| #28 US19: Wdrożenie na VPS | 🟡 | lokalnie jednym poleceniem (`python -m polybot run`) i Docker Compose; brak prawdziwego VPS |
| #29 US20: Kopie zapasowe i test odtworzenia | ✅ | wykonane lokalnie w Compose |
| #30 US21: Monitoring | ✅ | metryki Prometheus |
| #31 US22: Replay | ✅ | `polybot replay` |

## Sprint 8 (04.02–18.02) — pilotaż

Odpowiedzialni: wspólnie — #32 Artem, #33 Ivan, #34 Mikhailo.

| Issue i historia | Stan | Uwagi |
|---|---|---|
| #32 US23: Pilotaż na żywych danych i raport | ⬜ | wymaga wdrożenia z tokenem bota |
| #33 US24: Nowe ligi/źródła, 3+ zakłady | 🟡 | 5 lig, do 3 nóg |
| #34 US25: Dokumentacja końcowa i prezentacja | 🟡 | dokumentacja techniczna gotowa |

## Sprint 9 (18.02–04.03) — kryptowaluty: dane

Odpowiedzialny: Artem Vozniak (temqau).

| Issue i historia | Kto | Stan | Uwagi |
|---|---|---|---|
| #40 US26: Ceny kryptowalut z kilku giełd w jednym miejscu | Artem | ⬜ | Moduł `data/crypto_prices.py` (szkielet gotowy): ccxt, kilka giełd, wybrane pary. |
| #41 US27: Opłaty za wypłatę i sieci transferu kryptowalut | Artem | ⬜ | Funkcja `withdrawal_fee` w `data/crypto_prices.py`; nieznana opłata zostaje „unknown”. |
| #42 US28: Cena referencyjna z CoinGecko i odrzucanie błędnych kursów | Artem | ⬜ |  |

## Sprint 10 (04.03–18.03) — kryptowaluty: arbitraż

Odpowiedzialny: Ivan Puzaruk (exeMoysei).

| Issue i historia | Kto | Stan | Uwagi |
|---|---|---|---|
| #43 US29: Alert o różnicy cen tej samej kryptowaluty między giełdami | Ivan | ⬜ | Moduł `logic/crypto_arbitrage.py` (szkielet gotowy): `find_gaps`, zysk na dostępnym wolumenie. |
| #44 US30: Ceny DEX (Jupiter, 0x) i arbitraż CEX ↔ DEX | Ivan | ⬜ |  |
| #45 US31: Wybór giełd, par i minimalnego zysku dla alertów krypto | Ivan | ⬜ | Nowy typ alertu w `/filters`. |

## Sprint 11 (18.03–01.04) — kasyna on-chain

Odpowiedzialny: Mikhailo Ivanyshyn (Orlixx003).

| Issue i historia | Kto | Stan | Uwagi |
|---|---|---|---|
| #46 US32: Źródło danych kasyna on-chain | Mikhailo | ⬜ | Szkielet `data/casino.py` (`OnChainCasinoSource`); najpierw wybór kasyn i ich kontraktów. |
| #47 US33: Alert o dużej stawce lub wygranej gracza kasyna | Mikhailo | ⬜ | Dokończenie US10 (#10): `logic/casino_alerts.py` (szkielet gotowy), przełącznik „Casino players” w `/filters`. |
| #48 US34: Lista obserwowanych graczy kasyn w bocie | Mikhailo | ⬜ | Komendy na wzór `/follow` dla portfeli Polymarket. |

## Sprint 12 (01.04–15.04) — analityka portfeli

Odpowiedzialny: Artem Vozniak (temqau).

| Issue i historia | Kto | Stan | Uwagi |
|---|---|---|---|
| #49 US35: Profil portfela: zysk, liczba zakładów, odsetek wygranych | Artem | ⬜ | Dane: Polymarket Data API v2 (`/v2/positions`, `/v2/activity`). |
| #50 US36: Ranking z odsetkiem trafionych zakładów i filtrem kategorii | Artem | ⬜ | Rozszerzenie `/top` (US9, #9): dziś ranking pokazuje zysk i wolumen. |
| #51 US37: Alert, gdy kilku najlepszych graczy obstawia ten sam wynik | Artem | ⬜ |  |

## Sprint 13 (15.04–29.04) — nowe źródła zakładów

Odpowiedzialny: Ivan Puzaruk (exeMoysei).

| Issue i historia | Kto | Stan | Uwagi |
|---|---|---|---|
| #52 US38: Bukmacherzy na żywych danych (The Odds API) | Ivan | ⬜ | Adapter jest gotowy; potrzebny klucz The Odds API i kontrola limitu zapytań. |
| #53 US39: Giełda zakładów (back/lay) z prowizją | Ivan | ⬜ | Osobny model odpowiedzialności dla lay. |
| #54 US40: Kolejne ligi i rynki: totale i handicapy | Ivan | ⬜ |  |

## Sprint 14 (29.04–13.05) — wygoda użytkownika

Odpowiedzialny: Mikhailo Ivanyshyn (Orlixx003).

| Issue i historia | Kto | Stan | Uwagi |
|---|---|---|---|
| #55 US41: Wybór języka bota (EN/PL) | Mikhailo | ⬜ |  |
| #56 US42: Podsumowanie dnia w bocie | Mikhailo | ⬜ |  |
| #57 US43: Historia moich alertów i eksport do CSV | Mikhailo | ⬜ |  |

## Sprint 15 (13.05–27.05) — niezawodność i bezpieczeństwo

Odpowiedzialni: wspólnie — #58 Artem, #59 Ivan, #60 Mikhailo.

| Issue i historia | Kto | Stan | Uwagi |
|---|---|---|---|
| #58 US44: Testy obciążeniowe i limity zapytań do API | Artem | ⬜ |  |
| #59 US45: Przegląd bezpieczeństwa | Ivan | ⬜ |  |
| #60 US46: Monitoring produkcyjny z alertami dla admina | Mikhailo | ⬜ |  |

## Sprint 16 (27.05–10.06) — zamknięcie projektu

Odpowiedzialni: wspólnie — #61 Artem, #62 Mikhailo, #63 Ivan.

| Issue i historia | Kto | Stan | Uwagi |
|---|---|---|---|
| #61 US47: Raport z pilotażu | Artem | ⬜ |  |
| #62 US48: Dokumentacja końcowa i instrukcja użytkownika | Mikhailo | ⬜ |  |
| #63 US49: Prezentacja końcowa i demo na żywo | Ivan | ⬜ |  |

## Decyzje i sprawy otwarte

1. **Kasyna (#10, #46–#48):** wybór źródła danych — rekomendacja: kasyna on-chain ([podzial-pracy.md](podzial-pracy.md#kasyna-us10--decyzja-do-podjęcia)).
2. **The Odds API (#23, #52):** potrzebny klucz (płatny plan, limit zapytań).
3. **Kalshi „fair price”:** przy odwołaniu/przełożeniu > 48 h Kalshi rozlicza po cenie ustalanej później — admin ocenia
   ryzyko przy zatwierdzaniu powiązań.
4. **Tablica projektu:** issues #37–#63 trzeba dodać do tablicy „Polymarket arbitrage bot”, jeśli nie dodały się same.
