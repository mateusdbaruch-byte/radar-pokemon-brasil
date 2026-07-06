"""Performance e priorização de templates de query."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml

from src.paths import TEMPLATE_PERFORMANCE

ALL_PROFILES = ("demand_leads", "supply_deals", "market_reference")


@dataclass
class QueryTemplateSpec:
    template: str
    enabled: bool = True
    priority_weight: int = 50
    last_success_rate: float = 0.0
    last_saved_count: int = 0
    last_rejected_count: int = 0

    @property
    def sort_score(self) -> float:
        base = float(self.priority_weight)
        if self.last_saved_count + self.last_rejected_count > 0:
            base += self.last_success_rate * 40.0
        if not self.enabled:
            return -1.0
        return base

    def to_stats_dict(self) -> dict:
        return {
            "last_success_rate": round(self.last_success_rate, 3),
            "last_saved_count": self.last_saved_count,
            "last_rejected_count": self.last_rejected_count,
        }


def _stats_key(profile: str, template: str) -> str:
    return f"{profile}::{template}"


def load_template_performance(path: Path = TEMPLATE_PERFORMANCE) -> dict[str, dict]:
    if not path.exists():
        return {}
    with open(path, encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    return {k: v for k, v in data.items() if isinstance(v, dict)}


def save_template_performance(
    stats: dict[str, dict],
    path: Path = TEMPLATE_PERFORMANCE,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        yaml.safe_dump(stats, f, allow_unicode=True, default_flow_style=False, sort_keys=True)


def parse_template_entry(raw: str | dict) -> QueryTemplateSpec:
    if isinstance(raw, str):
        return QueryTemplateSpec(template=raw)
    return QueryTemplateSpec(
        template=str(raw.get("template", "")),
        enabled=bool(raw.get("enabled", True)),
        priority_weight=int(raw.get("priority_weight", 50)),
        last_success_rate=float(raw.get("last_success_rate", 0.0)),
        last_saved_count=int(raw.get("last_saved_count", 0)),
        last_rejected_count=int(raw.get("last_rejected_count", 0)),
    )


def merge_template_stats(
    specs: list[QueryTemplateSpec],
    profile: str,
    perf: dict[str, dict] | None = None,
) -> list[QueryTemplateSpec]:
    perf = perf if perf is not None else load_template_performance()
    merged: list[QueryTemplateSpec] = []
    for spec in specs:
        if not spec.template:
            continue
        key = _stats_key(profile, spec.template)
        stored = perf.get(key, {})
        merged.append(
            QueryTemplateSpec(
                template=spec.template,
                enabled=spec.enabled,
                priority_weight=spec.priority_weight,
                last_success_rate=float(stored.get("last_success_rate", spec.last_success_rate)),
                last_saved_count=int(stored.get("last_saved_count", spec.last_saved_count)),
                last_rejected_count=int(stored.get("last_rejected_count", spec.last_rejected_count)),
            )
        )
    return merged


def prioritized_templates(
    profile: str,
    raw_templates: list[str | dict],
    *,
    perf: dict[str, dict] | None = None,
) -> list[QueryTemplateSpec]:
    specs = merge_template_stats(
        [parse_template_entry(t) for t in raw_templates],
        profile,
        perf=perf,
    )
    enabled = [s for s in specs if s.enabled]
    enabled.sort(key=lambda s: s.sort_score, reverse=True)
    return enabled


def match_template_pattern(query: str, card: str, template: str) -> bool:
    expected = template.format(card=card)
    return query.strip() == expected.strip()


def find_template_for_query(
    profile: str,
    card: str,
    query: str,
    raw_templates: list[str | dict],
) -> str | None:
    for spec in prioritized_templates(profile, raw_templates):
        if match_template_pattern(query, card, spec.template):
            return spec.template
    return None


def update_stats_from_query_runs(
    runs: list,
    profiles_cfg: dict[str, list[str | dict]],
) -> dict[str, dict]:
    """Agrega query_runs em template_performance (por template pattern)."""
    agg: dict[str, dict[str, int]] = {}
    for run in runs:
        profile = run.profile
        if profile not in profiles_cfg:
            continue
        template = find_template_for_query(
            profile, run.card, run.query, profiles_cfg[profile],
        )
        if not template:
            continue
        key = _stats_key(profile, template)
        bucket = agg.setdefault(key, {"saved": 0, "rejected": 0})
        bucket["saved"] += run.saved_count
        bucket["rejected"] += run.rejected_count

    perf = load_template_performance()
    for key, counts in agg.items():
        saved = counts["saved"]
        rejected = counts["rejected"]
        total = saved + rejected
        rate = (saved / total) if total else perf.get(key, {}).get("last_success_rate", 0.0)
        perf[key] = {
            "last_success_rate": round(rate, 3),
            "last_saved_count": saved,
            "last_rejected_count": rejected,
        }
    save_template_performance(perf)
    return perf


@dataclass
class TemplateReportRow:
    profile: str
    template: str
    enabled: bool
    priority_weight: int
    success_rate: float
    saved: int
    rejected: int
    suggestion: str = ""


def build_template_report(
    profiles_cfg: dict[str, list[str | dict]],
) -> list[TemplateReportRow]:
    perf = load_template_performance()
    rows: list[TemplateReportRow] = []
    for profile, templates in profiles_cfg.items():
        for spec in merge_template_stats(
            [parse_template_entry(t) for t in templates],
            profile,
            perf=perf,
        ):
            total = spec.last_saved_count + spec.last_rejected_count
            rate = spec.last_success_rate
            suggestion = ""
            if total >= 2 and rate >= 0.5:
                suggestion = "manter alta prioridade"
            elif total >= 2 and rate == 0:
                suggestion = "reduzir prioridade ou desativar"
            elif total >= 3 and rate < 0.2:
                suggestion = "desativar ou restringir contexto"
            rows.append(
                TemplateReportRow(
                    profile=profile,
                    template=spec.template,
                    enabled=spec.enabled,
                    priority_weight=spec.priority_weight,
                    success_rate=rate,
                    saved=spec.last_saved_count,
                    rejected=spec.last_rejected_count,
                    suggestion=suggestion,
                )
            )
    rows.sort(key=lambda r: (-r.success_rate, -r.saved, r.rejected))
    return rows
