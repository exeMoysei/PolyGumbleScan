# Etap 0 — audyt, dostępy, probe źródeł, wybór rynku

Data: 04.11.2026. Wykonano w środowisku deweloperskim (kontener w chmurze).

## Inwentaryzacja repozytorium

Na starcie gałąź `main` w `exeMoysei/PolyGumbleScan` zawierała tylko `README.md` („Rachunki — Arbitrage tracker”),
bez kodu, `AGENTS.md`, CI i historii zmian. Później (10.11.2026) pojawiły się PR #19 i #20 z własną strukturą
pakietu `polygumblescan` — nie są scalone z `main`; patrz [sprinty.md](sprinty.md).

## Kontrola dostępów ze środowiska deweloperskiego

| Host | Wynik |
|---|---|
| gamma-api.polymarket.com, clob.polymarket.com | ❌ 403 z proxy środowiska (zablokowane polityką sieciową) |
| api.elections.kalshi.com | ❌ 403 z proxy środowiska |
| api.the-odds-api.com | ❌ 403 z proxy środowiska |
| pypi.org | ✅ |

Pomiar na żywych danych z tego środowiska nie jest możliwy. Dlatego:

* kontrakty adapterów zostały porównane z oficjalną dokumentacją (zob. `docs/providers/*.md`), w tym aktualny
  format Kalshi `orderbook_fp` (same bidy, ceny jako napisy w dolarach) oraz model prowizji Polymarket
  `fd = {r, e, to}`;
* dodano polecenie `polybot probe`, które na VPS mierzy dostęp, opóźnienie, liczbę wydarzeń/rynków/kursów,
  odsetek kursów z głębokością i z potwierdzonymi limitami, limity API oraz **liczbę wspólnych wydarzeń**
  dla zestawów platform w okresie obserwacji (`--samples N --interval S`) i zapisuje JSON do tego raportu;
* cały potok sprawdzono na danych testowych w formacie odpowiedzi platform (oznaczone `TEST DATA`).

## Tabela źródeł

| Źródło | Typ | Cena do obliczeń | Głębokość | Limity | Świeżość | Linki | Status |
|---|---|---|---|---|---|---|---|
| Polymarket | prediction | drabinka ask z CLOB | tak | tak (wolumen poziomów) | z platformy | tak | adapter gotowy, probe na VPS |
| Kalshi | prediction | ask = 1 − bid strony przeciwnej | tak | tak | z platformy (czas odbioru) | tak | adapter gotowy, probe na VPS |
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
