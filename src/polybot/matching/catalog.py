"""Matching orchestration over full catalogs: events -> clusters, markets -> mapping proposals."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import timedelta

from polybot.domain.models import ProviderEvent, ProviderMarket
from polybot.matching.events import DEFAULT_WINDOW, EventCluster, Unresolved, match
from polybot.matching.markets import MarketProposal, map_market
from polybot.matching.teams import TeamRegistry


@dataclass(slots=True)
class MatchReport:
    clusters: list[EventCluster] = field(default_factory=list)
    unresolved: list[Unresolved] = field(default_factory=list)
    proposals: list[MarketProposal] = field(default_factory=list)
    unmatched_markets: list[ProviderMarket] = field(default_factory=list)

    @property
    def cross_venue_clusters(self) -> list[EventCluster]:
        return [c for c in self.clusters if len(c.providers) > 1]

    def overlap(self) -> dict[frozenset[str], int]:
        """Number of shared events per provider set (stage-0 metric)."""
        counts: dict[frozenset[str], int] = defaultdict(int)
        for c in self.clusters:
            counts[frozenset(c.providers)] += 1
        return dict(counts)

    def by_key(self) -> dict[str, list[MarketProposal]]:
        out: dict[str, list[MarketProposal]] = defaultdict(list)
        for p in self.proposals:
            out[p.canonical_market_key].append(p)
        return dict(out)


def match_catalog(
    events: list[ProviderEvent],
    markets: list[ProviderMarket],
    registry: TeamRegistry,
    window: timedelta = DEFAULT_WINDOW,
) -> MatchReport:
    clusters, unresolved = match(events, registry, window)
    member_of: dict[tuple[str, str], EventCluster] = {}
    for c in clusters:
        for m in c.members:
            member_of[(m.provider, m.event.external_id)] = c
    report = MatchReport(clusters=clusters, unresolved=unresolved)
    for mk in markets:
        cluster = member_of.get((mk.provider, mk.external_event_id))
        if cluster is None:
            report.unmatched_markets.append(mk)
            continue
        report.proposals.append(map_market(mk, cluster, registry))
    return report
