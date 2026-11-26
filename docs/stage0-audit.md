# Etap 0 — audyt, dostępy, probe źródeł, wybór rynku

Data: 04.11.2026. Wykonano w środowisku deweloperskim (kontener w chmurze).

## Inwentaryzacja repozytorium

Na starcie gałąź `main` w `exeMoysei/PolyGumbleScan` zawierała tylko `README.md` („Rachunki — Arbitrage tracker”),
bez kodu, `AGENTS.md`, CI i historii zmian. Później (10.11.2026) pojawiły się PR #19 i #20 z własną strukturą
pakietu `polygumblescan` — nie są scalone z `main`; patrz [sprinty.md](sprinty.md).

## Kontrola dostępów

04.11.2026 API platform były zablokowane przez ograniczoną sieć środowiska deweloperskiego (403 z proxy — nie
zależy od kraju). Kontrakty adapterów porównano wtedy z dokumentacją, a potok sprawdzono na danych testowych.

26.11.2026 sieć środowiska otwarto dla publicznych API i wykonano pomiar na żywych danych:

| Host | Wynik |
|---|---|
| gamma-api.polymarket.com, clob.polymarket.com | ✅ bez klucza |
| data-api.polymarket.com (`/v2/…`) | ✅ bez klucza; v1 i `lb-api.polymarket.com` wyłączone (410) |
| api.elections.kalshi.com | ✅ bez klucza |
| api.the-odds-api.com | ⏳ wymaga klucza |
| polygon-rpc.com | ❌ wymaga klucza API (do wyboru inny publiczny węzeł RPC) |

Wynik pomiaru (ligi NBA, NHL, EPL): 66 wydarzeń, **48 wspólnych dla Polymarket i Kalshi**, 0 nierozpoznanych nazw,
473 powiązania rynków do zatwierdzenia, 946 kursów. Okazji arbitrażowych Polymarket ↔ Kalshi w chwili pomiaru nie
było (112 kombinacji bez przewagi po najlepszych cenach). Suma YES < 1: 93 wydarzenia, 1 okazja.

Pomiar ujawnił i naprawiono: prowizje Polymarket w `feeSchedule`, czas `timestamp` arkusza (ostatnia zmiana, nie
czas odpowiedzi), wolne pobieranie arkuszy Kalshi (teraz paczkami), nowe sformułowania zasad, drużyny EPL 2026/27.

## Tabela źródeł

| Źródło | Typ | Cena do obliczeń | Głębokość | Limity | Świeżość | Linki | Status |
|---|---|---|---|---|---|---|---|
| Polymarket | prediction | drabinka ask z CLOB | tak | tak (wolumen poziomów) | z platformy | tak | ✅ działa na żywo |
| Kalshi | prediction | ask = 1 − bid strony przeciwnej | tak | tak | z platformy (czas odbioru) | tak | ✅ działa na żywo |
| The Odds API | agregator bukmacherów | kurs dziesiętny | nie | unknown | tylko agregator | częściowo (`includeLinks`) | adapter gotowy, potrzebny klucz |

## Wybór pierwszego rynku

**NBA, „zwycięzca meczu” z dogrywką (moneyline), prematch.**

* Dwa zwykłe wyniki bez remisu → czysty model dwuwynikowy MVP.
* Rynek jest we wszystkich trzech źródłach: Polymarket (`nba-<gość>-<gospodarz>-<data>`), Kalshi (`KXNBAGAME`),
  bukmacherzy przez The Odds API (`basketball_nba`, `h2h`) → obie trasy (prediction ↔ prediction oraz
  prediction ↔ bukmacher) na jednym wydarzeniu.
* Duża częstotliwość meczów (ok. 7–15 dziennie w sezonie) daje statystykę pilotażu w dni, nie miesiące.
* Rezerwa: EPL 1X2 (90 minut) — sprawdzenie remisu i pary „A / nie A” (liga `epl` jest już obsługiwana).

Ostateczną decyzję potwierdzą liczby z `polybot probe` na VPS: jeśli część wspólna NBA między Polymarket
a Kalshi okaże się pusta, pilotaż idzie trasą prediction ↔ bukmacher, a druga trasa jest pokazywana na
przykładzie testowym (`polybot demo`, karta „SIGNAL · prediction ↔ prediction”).

## Jak uzyskać liczby

```bash
docker compose run --rm ingest probe --samples 12 --interval 900 --out /app/var/probe-nba.json
```

W wyniku: `sources.<dostawca>.{events,markets,quotes,with_depth,with_limits,max_age_s}`,
`overlap["kalshi+oddsapi+polymarket"]` — liczba wspólnych wydarzeń, `unresolved` — nazwy, których nie udało się
przypisać (kandydaci na aliasy: `/alias nba "<nazwa>" nba:<kod>`), `quota` — pozostały limit The Odds API.
