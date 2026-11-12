"""Command line entry point: ``polybot <command>``."""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import json
import re
import signal
import sys
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

from polybot.settings import Settings, get_settings

FIXTURES = Path(__file__).resolve().parents[2] / "tests" / "fixtures"


def _strip_html(text: str) -> str:
    text = re.sub(r"<a href=\"([^\"]+)\">([^<]+)</a>", r"\2 (\1)", text)
    return re.sub(r"<[^>]+>", "", text).replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">")


async def _with_signals(main: Awaitable[Any], stoppers: list[Callable[[], None]]) -> None:
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        with contextlib.suppress(NotImplementedError):  # pragma: no cover - windows
            loop.add_signal_handler(sig, lambda: [s() for s in stoppers])
    await main


def _resources(settings: Settings) -> tuple[Any, Any, Any]:
    from redis.asyncio import Redis

    from polybot.storage.db import make_engine, make_sessionmaker
    from polybot.storage.quotes import RedisQuoteStore

    engine = make_engine(settings.database_url)
    sessions = make_sessionmaker(engine)
    redis = Redis.from_url(settings.redis_url)
    return engine, sessions, RedisQuoteStore(redis)


# ----------------------------------------------------------------------------- commands
def cmd_migrate(_: argparse.Namespace) -> int:
    import os

    from alembic import command
    from alembic.config import Config

    root = Path(__file__).resolve().parents[2]
    cfg = Config(str(root / "alembic.ini")) if (root / "alembic.ini").exists() else Config()
    cfg.set_main_option("script_location", str(root / "migrations"))
    os.environ.setdefault("POLYBOT_DATABASE_URL", get_settings().database_url)
    print("applying migrations…", flush=True)
    command.upgrade(cfg, "head")
    print("migrations: at head", flush=True)
    return 0


def cmd_run_ingest(_: argparse.Namespace) -> int:
    from polybot import metrics
    from polybot.logging import setup_logging
    from polybot.services.ingest import IngestService
    from polybot.services.runtime import build_adapters

    s = get_settings()
    setup_logging(s.log_level, s.log_json)
    metrics.serve(s.metrics_port)
    engine, sessions, store = _resources(s)
    svc = IngestService(s, build_adapters(s), sessions, store)

    async def main() -> None:
        try:
            await _with_signals(svc.run(), [svc.stop])
        finally:
            for a in svc.adapters:
                await a.aclose()
            await engine.dispose()

    asyncio.run(main())
    return 0


def cmd_run_scan(_: argparse.Namespace) -> int:
    from polybot import metrics
    from polybot.logging import setup_logging
    from polybot.services.scan import ScanService

    s = get_settings()
    setup_logging(s.log_level, s.log_json)
    metrics.serve(s.metrics_port)
    engine, sessions, store = _resources(s)
    svc = ScanService(s, sessions, store)

    async def main() -> None:
        try:
            await _with_signals(svc.run(), [svc.stop])
        finally:
            await engine.dispose()

    asyncio.run(main())
    return 0


def cmd_run_bot(_: argparse.Namespace) -> int:
    from polybot import metrics
    from polybot.logging import setup_logging
    from polybot.services.runtime import build_adapters
    from polybot.telegram.bot import COMMANDS, BotContext, build_bot, build_dispatcher
    from polybot.telegram.notifier import AiogramSender, Notifier

    s = get_settings()
    setup_logging(s.log_level, s.log_json)
    if s.telegram_bot_token is None:
        print("POLYBOT_TELEGRAM_BOT_TOKEN is not set", file=sys.stderr)
        return 2
    metrics.serve(s.metrics_port)
    engine, sessions, _store = _resources(s)
    adapters = build_adapters(s)
    bot = build_bot(s.telegram_bot_token.get_secret_value())
    dp = build_dispatcher(BotContext(s, sessions, adapters))
    notifier = Notifier(sessions, AiogramSender(bot), lease_s=s.outbox_lease_s, max_attempts=s.outbox_max_attempts)

    async def main() -> None:
        await bot.set_my_commands(COMMANDS)
        worker = asyncio.create_task(notifier.run())
        try:
            await dp.start_polling(bot, handle_signals=True)
        finally:
            notifier.stop()
            worker.cancel()
            for a in adapters:
                await a.aclose()
            await bot.session.close()
            await engine.dispose()

    asyncio.run(main())
    return 0


def _print_report(report: Any, scan: Any, show_cards: bool) -> None:
    from polybot.services.payload import draft_payload
    from polybot.telegram.cards import render_card

    print(
        f"\n=== Matching: {len(report.clusters)} events, {len(report.cross_venue_clusters)} shared, "
        f"{len(report.unresolved)} unresolved"
    )
    for c in sorted(report.clusters, key=lambda c: c.id):
        print(
            f"  {c.id:<36} {','.join(sorted(c.providers)):<30} conf={c.confidence:.2f} "
            f"{' '.join(c.reasons) if c.reasons else ''}"
        )
    for u in report.unresolved:
        print(f"  ! unresolved {u.event.provider}:{u.event.external_id} {u.reason}")
    print(f"\n=== Scan: keys={scan.keys_scanned} evaluated={scan.combos_evaluated} drafts={len(scan.drafts)}")
    print("  rejections:", dict(scan.rejections))
    if show_cards:
        for d in scan.drafts:
            print("\n" + "-" * 72)
            print(_strip_html(render_card(draft_payload(d))))


def cmd_demo(args: argparse.Namespace) -> int:
    """Full offline pipeline on the TEST DATA fixtures (no network, no database)."""
    from polybot.adapters.fixture import fixture_adapters
    from polybot.matching.teams import TeamRegistry
    from polybot.services.pipeline import collect, fx_table_from, run_offline, scan_config_from

    s = get_settings()
    now = datetime.fromisoformat(args.at) if args.at else datetime(2026, 1, 15, 23, 0, tzinfo=UTC)
    root = Path(args.fixtures) if args.fixtures else FIXTURES
    leagues = args.leagues.split(",")
    world = asyncio.run(collect(fixture_adapters(root, leagues, now=now)))
    cfg = scan_config_from(s, Decimal(args.budget))
    report, scan = run_offline(world, TeamRegistry.default(), cfg, fx_table_from(s, now), now, lambda p: True)
    print("TEST DATA ONLY — fixtures are synthetic; all mappings auto-approved for the demo.")
    _print_report(report, scan, True)
    return 0


def cmd_probe(args: argparse.Namespace) -> int:
    """Stage-0 probe: access, volume, depth/limit coverage and cross-venue overlap of live sources."""
    from polybot.matching.catalog import match_catalog
    from polybot.services.pipeline import collect
    from polybot.services.runtime import build_adapters, registry_with_aliases

    s = get_settings()
    adapters = build_adapters(s)
    samples: list[dict[str, Any]] = []

    async def one() -> dict[str, Any]:
        started = datetime.now(UTC)
        world = await collect(adapters)
        report = match_catalog(world.events, world.markets, registry_with_aliases([]))
        per: dict[str, dict[str, Any]] = {}
        for q in world.quotes:
            d = per.setdefault(q.provider, {"quotes": 0, "with_depth": 0, "with_limits": 0, "max_age_s": 0.0})
            d["quotes"] += 1
            d["with_depth"] += q.total_size is not None
            d["with_limits"] += q.total_size is not None or q.max_size is not None
            d["max_age_s"] = max(d["max_age_s"], (started - q.source_at).total_seconds())
        for e in world.events:
            per.setdefault(e.provider, {"quotes": 0, "with_depth": 0, "with_limits": 0, "max_age_s": 0.0})
            per[e.provider]["events"] = per[e.provider].get("events", 0) + 1
        for m in world.markets:
            per[m.provider]["markets"] = per[m.provider].get("markets", 0) + 1
        overlap = {"+".join(sorted(k)): v for k, v in report.overlap().items()}
        return {
            "at": started.isoformat(),
            "errors": world.errors,
            "sources": per,
            "overlap": overlap,
            "unresolved": [f"{u.event.provider}:{u.event.title}:{u.reason}" for u in report.unresolved][:50],
            "quota": {a.id: getattr(a, "quota", {}) for a in adapters},
        }

    async def main() -> None:
        for i in range(args.samples):
            samples.append(await one())
            print(json.dumps(samples[-1], indent=1, ensure_ascii=False), flush=True)
            if i + 1 < args.samples:
                await asyncio.sleep(args.interval)
        for a in adapters:
            await a.aclose()

    asyncio.run(main())
    if args.out:
        Path(args.out).write_text(json.dumps(samples, indent=1, ensure_ascii=False))
        print(f"saved {args.out}")
    return 0


def cmd_replay(args: argparse.Namespace) -> int:
    from polybot.services.payload import draft_payload
    from polybot.services.pipeline import fx_table_from, scan_config_from
    from polybot.services.replay import replay_db
    from polybot.telegram.cards import render_card

    if args.fixtures:
        ns = argparse.Namespace(fixtures=args.fixtures, at=args.at, budget=args.budget, leagues=args.leagues)
        return cmd_demo(ns)
    s = get_settings()
    at = datetime.fromisoformat(args.at) if args.at else datetime.now(UTC)
    engine, sessions, _ = _resources(s)

    async def main() -> None:
        async with sessions() as sess:
            drafts, rej = await replay_db(
                sess,
                at,
                scan_config_from(s, Decimal(args.budget)),
                fx_table_from(s, at),
                timedelta(minutes=args.lookback),
            )
        print(f"replay at {at.isoformat()}: {len(drafts)} drafts, rejections={rej}")
        for d in drafts:
            print("-" * 72)
            print(_strip_html(render_card(draft_payload(d))))
        await engine.dispose()

    asyncio.run(main())
    return 0


def cmd_mappings(args: argparse.Namespace) -> int:
    from polybot.storage import repo

    s = get_settings()
    engine, sessions, _ = _resources(s)

    async def main() -> None:
        async with sessions() as sess, sess.begin():
            if args.action == "list":
                for m, mrow in await repo.pending_mappings(sess, limit=200):
                    print(f"#{m.id} {m.status:<13} {mrow.provider:<10} {m.canonical_market_key} reasons={m.reasons}")
            else:
                row = await repo.decide_mapping(sess, args.id, args.action == "approve", 0, "cli", datetime.now(UTC))
                print("not found" if row is None else f"#{row.id} -> {row.status}")
        await engine.dispose()

    asyncio.run(main())
    return 0


def cmd_healthcheck(_: argparse.Namespace) -> int:
    from redis.asyncio import Redis
    from sqlalchemy import text

    from polybot.storage.db import make_engine

    s = get_settings()

    async def main() -> None:
        engine = make_engine(s.database_url)
        async with engine.connect() as c:
            await c.execute(text("select 1"))
        await engine.dispose()
        r = Redis.from_url(s.redis_url)
        await r.ping()
        await r.aclose()

    try:
        asyncio.run(asyncio.wait_for(main(), 10))
    except Exception as exc:
        print(f"unhealthy: {type(exc).__name__}", file=sys.stderr)
        return 1
    print("ok")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="polybot", description="PolyBot arbitrage scanner")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("migrate", help="apply database migrations").set_defaults(fn=cmd_migrate)
    sub.add_parser("run-ingest", help="catalog discovery, matching and quote polling").set_defaults(fn=cmd_run_ingest)
    sub.add_parser("run-scan", help="opportunity scanner").set_defaults(fn=cmd_run_scan)
    sub.add_parser("run-bot", help="Telegram bot + notification worker").set_defaults(fn=cmd_run_bot)
    sub.add_parser("healthcheck", help="check database and redis").set_defaults(fn=cmd_healthcheck)
    for name, fn in (("demo", cmd_demo), ("replay", cmd_replay)):
        sp = sub.add_parser(name, help="offline fixtures run" if name == "demo" else "recompute from history")
        sp.add_argument("--at", help="ISO timestamp (UTC) of the snapshot")
        sp.add_argument("--budget", default="200")
        sp.add_argument("--fixtures", help="fixture directory (offline)")
        sp.add_argument("--leagues", default="nba,epl")
        if name == "replay":
            sp.add_argument("--lookback", type=int, default=60, help="minutes of history to consider")
        sp.set_defaults(fn=fn)
    pr = sub.add_parser("probe", help="stage-0 probe of live sources")
    pr.add_argument("--samples", type=int, default=1)
    pr.add_argument("--interval", type=int, default=600)
    pr.add_argument("--out")
    pr.set_defaults(fn=cmd_probe)
    mp = sub.add_parser("mappings", help="admin: list/approve/reject mappings")
    mp.add_argument("action", choices=["list", "approve", "reject"])
    mp.add_argument("id", type=int, nargs="?", default=0)
    mp.set_defaults(fn=cmd_mappings)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return int(args.fn(args))


if __name__ == "__main__":
    raise SystemExit(main())
