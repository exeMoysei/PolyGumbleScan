"""Hot quote cache in Redis (rebuildable from venue snapshots) + change stream for the scanner.

Layout: hash ``pb:mq:{provider}|{market}`` with field ``{venue}|{outcome}`` -> encoded quote, TTL per
provider. A Lua script makes writes monotonic: a quote older than the cached one is dropped, so late
or duplicate updates never corrupt state. Every accepted write appends to stream ``pb:changes``.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Sequence
from typing import Any, Protocol

from redis.asyncio import Redis

from polybot.codec import dec_quote, enc_quote
from polybot.domain.models import Quote

STREAM = "pb:changes"
_CAS = """
local cur = redis.call('HGET', KEYS[1], ARGV[1])
if cur then
  local c = cjson.decode(cur)
  local ts, seq = tonumber(ARGV[3]), tonumber(ARGV[4])
  if c._ts > ts then return 0 end
  if c._ts == ts and seq >= 0 and c._seq >= 0 and c._seq >= seq then return 0 end
  if c._ts == ts and seq < 0 and c._h == ARGV[6] then return 0 end
end
redis.call('HSET', KEYS[1], ARGV[1], ARGV[2])
redis.call('PEXPIRE', KEYS[1], ARGV[5])
return 1
"""


def market_key(provider: str, market: str) -> str:
    return f"pb:mq:{provider}|{market}"


def _ts_ms(q: Quote) -> int:
    return int(q.source_at.timestamp() * 1000)


class QuoteStore(Protocol):
    async def put_many(self, quotes: Sequence[Quote], ttl_ms: dict[str, int]) -> list[Quote]: ...

    async def get_markets(self, markets: Iterable[tuple[str, str]]) -> list[Quote]: ...


class RedisQuoteStore:
    def __init__(self, redis: Redis, stream_maxlen: int = 20_000) -> None:
        self.r = redis
        self._cas = redis.register_script(_CAS)
        self.maxlen = stream_maxlen

    async def put_many(self, quotes: Sequence[Quote], ttl_ms: dict[str, int]) -> list[Quote]:
        accepted: list[Quote] = []
        changed_markets: set[tuple[str, str]] = set()
        for q in quotes:
            doc = enc_quote(q)
            doc["_ts"] = _ts_ms(q)
            doc["_seq"] = q.sequence if q.sequence is not None else -1
            doc["_h"] = q.raw_hash or ""
            ok = await self._cas(
                keys=[market_key(q.provider, q.market_external_id)],
                args=[
                    f"{q.venue_id}|{q.outcome_external_id}",
                    json.dumps(doc),
                    doc["_ts"],
                    doc["_seq"],
                    ttl_ms.get(q.provider, 120_000),
                    doc["_h"],
                ],
            )
            if ok:
                accepted.append(q)
                changed_markets.add((q.provider, q.market_external_id))
        for prov, market in changed_markets:
            await self.r.xadd(STREAM, {"p": prov, "m": market}, maxlen=self.maxlen, approximate=True)
        return accepted

    async def get_markets(self, markets: Iterable[tuple[str, str]]) -> list[Quote]:
        pipe = self.r.pipeline(transaction=False)
        keys = list(markets)
        for prov, m in keys:
            pipe.hgetall(market_key(prov, m))
        out: list[Quote] = []
        for res in await pipe.execute():
            for raw in (res or {}).values():
                out.append(dec_quote(json.loads(raw)))
        return out

    async def read_changes(self, last_id: str, block_ms: int, count: int = 500) -> tuple[str, set[tuple[str, str]]]:
        res: Any = await self.r.xread({STREAM: last_id}, block=block_ms, count=count)
        changed: set[tuple[str, str]] = set()
        for _stream, entries in res or []:
            for entry_id, fields in entries:
                last_id = entry_id.decode() if isinstance(entry_id, bytes) else entry_id
                p = fields.get(b"p") or fields.get("p")
                m = fields.get(b"m") or fields.get("m")
                if p and m:
                    changed.add((p.decode() if isinstance(p, bytes) else p, m.decode() if isinstance(m, bytes) else m))
        return last_id, changed


class MemoryQuoteStore:
    """Same semantics as Redis, for tests and offline runs."""

    def __init__(self) -> None:
        self.data: dict[tuple[str, str], dict[str, Quote]] = {}

    async def put_many(self, quotes: Sequence[Quote], ttl_ms: dict[str, int]) -> list[Quote]:
        from polybot.services.pipeline import is_newer

        accepted = []
        for q in quotes:
            bucket = self.data.setdefault((q.provider, q.market_external_id), {})
            f = f"{q.venue_id}|{q.outcome_external_id}"
            cur = bucket.get(f)
            if cur is not None and (
                not is_newer(q, cur) or (cur.raw_hash == q.raw_hash and cur.source_at == q.source_at)
            ):
                continue
            bucket[f] = q
            accepted.append(q)
        return accepted

    async def get_markets(self, markets: Iterable[tuple[str, str]]) -> list[Quote]:
        return [q for k in markets for q in self.data.get(k, {}).values()]
