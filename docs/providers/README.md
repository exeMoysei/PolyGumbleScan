# Dostawcy danych

Przed podłączeniem każdego źródła wykonywany jest probe (`polybot probe`): dostęp, limity, częstotliwość
aktualizacji, prawa do używania i przekazywania danych, zasady rozliczania, stabilność identyfikatorów,
kompletność limitów oraz część wspólna z działającymi źródłami. Platformy bez pasującej linii na zewnętrzne
wydarzenie nie wchodzą do obliczeń.

| Dostawca | Plik | Stan adaptera | Probe na żywo |
|---|---|---|---|
| Polymarket | [polymarket.md](polymarket.md) | gotowy (REST + opcjonalny WebSocket) | ⏳ na VPS (ze środowiska dev zablokowane) |
| Kalshi | [kalshi.md](kalshi.md) | gotowy (REST) | ⏳ na VPS |
| The Odds API | [the-odds-api.md](the-odds-api.md) | gotowy (REST) | ⏳ na VPS, potrzebny klucz |
