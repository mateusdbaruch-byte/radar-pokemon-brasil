"""Recência e freshness de oportunidades."""

from __future__ import annotations

import re
from datetime import datetime, timezone

from src.opportunity_models import Opportunity

DATE_PATTERNS = (
    re.compile(r"(\d{1,2})[/.-](\d{1,2})[/.-](20\d{2})"),
    re.compile(r"(20\d{2})[/.-](\d{1,2})[/.-](\d{1,2})"),
)


def _parse_date_from_text(text: str) -> datetime | None:
    text = text or ""
    for pattern in DATE_PATTERNS:
        match = pattern.search(text)
        if not match:
            continue
        groups = match.groups()
        try:
            if len(groups[0]) == 4:
                year, month, day = int(groups[0]), int(groups[1]), int(groups[2])
            else:
                day, month, year = int(groups[0]), int(groups[1]), int(groups[2])
            return datetime(year, month, day, tzinfo=timezone.utc)
        except ValueError:
            continue
    return None


def serpapi_recency_param(recency_days: int | None) -> str | None:
    if not recency_days or recency_days <= 0:
        return None
    if recency_days <= 7:
        return "qdr:w"
    if recency_days <= 31:
        return "qdr:m"
    if recency_days <= 365:
        return "qdr:y"
    return None


def google_recency_param(recency_days: int | None) -> str | None:
    if not recency_days or recency_days <= 0:
        return None
    if recency_days <= 7:
        return "d7"
    if recency_days <= 31:
        return "m1"
    if recency_days <= 365:
        return "y1"
    return None


def apply_freshness_to_opportunity(
    opp: Opportunity,
    *,
    title: str = "",
    snippet: str = "",
    recency_days: int | None = None,
) -> Opportunity:
    text = f"{title} {snippet}".strip()
    detected = _parse_date_from_text(text)
    now = datetime.now(timezone.utc)

    if detected:
        age = max(0, (now - detected).days)
        opp.detected_date = detected
        opp.age_days = age
        if recency_days and age <= recency_days:
            opp.freshness_status = "recent"
        elif recency_days and age > recency_days:
            opp.freshness_status = "old"
            opp.confidence_score = max(0, opp.confidence_score - 15)
        else:
            opp.freshness_status = "recent" if age <= 30 else "old"
    else:
        opp.freshness_status = "unknown"
        opp.detected_date = None
        opp.age_days = None
        if recency_days:
            opp.confidence_score = max(0, opp.confidence_score - 10)

    return opp
