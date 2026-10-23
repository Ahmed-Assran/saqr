"""
Deterministic 60-Point Heuristic Scoring Engine
Evaluates KSA/GCC Geo Affinity (25 pts), Capital & Trading Signals (20 pts), and Reachability (15 pts).
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Tuple

from src.stage2_scrapers.models import NormalizedLead

logger = logging.getLogger(__name__)

# KSA Cities and Identifiers
KSA_GEO_PATTERNS = [
    r"الرياض", r"جدة", r"الدمام", r"الخبر", r"مكة", r"المدينة", r"القصيم",
    r"بريدة", r"تبوك", r"حائل", r"أبها", r"خميس مشيط", r"الهفوف", r"الجبيل",
    r"السعودية", r"المملكة", r"ksa\b", r"riyadh", r"jeddah", r"dammam", r"khobar",
    r"🇸🇦", r"عاصمة القرار",
]

# KSA Brokers and Gulf Dialect Keywords
KSA_BROKER_AND_DIALECT_PATTERNS = [
    r"دراية", r"سهم", r"عوائد", r"بركة", r"الأهلي كابيتال", r"الرياض المالية",
    r"الجزيرة كابيتال", r"الراجحي المالية", r"الإنماء للاستثمار", r"derayah", r"sahm",
    r"awaed", r"baraka",
    # Gulf dialect phrases
    r"وش رايكم", r"وش رايك", r"شريت", r"ودّي", r"ودي", r"ابي ادخل", r"ابي اعرف",
    r"عطونا", r"تكفون", r"يا اخوان", r"يا شباب", r"يالربع", r"بالله",
]

# Options Trading Keywords
OPTIONS_PATTERNS = [
    r"أوبشن", r"اوبشن", r"عقود الخيارات", r"عقود الاوبشن", r"كول", r"بوت",
    r"عقود", r"\bcall\b", r"\bput\b", r"\boptions?\b", r"سترايك", r"انفلايت",
]

# US Tickers Cashtag Patterns
US_TICKER_PATTERNS = [
    r"\$NVDA\b", r"\$TSLA\b", r"\$AAPL\b", r"\$MSFT\b", r"\$AMZN\b",
    r"\$GOOGL?\b", r"\$META\b", r"\$AMD\b", r"\$PLTR\b", r"\$COIN\b",
    r"\$MSTR\b", r"\$SPY\b", r"\$QQQ\b", r"\$SMCI\b", r"\$ARM\b",
]

# Active Trading / Execution Keywords
EXECUTION_PATTERNS = [
    r"محفظتي", r"تداول", r"شريت", r"بعت", r"شارت", r"تحليل فني", r"وقف الخسارة",
    r"دخول", r"هدف", r"مضاربة", r"tradingview", r"interactive brokers", r"ibkr",
    r"سوق المال", r"راس المال", r"سيولة",
]

# Contact info in bio regex
CONTACT_INFO_PATTERNS = [
    r"snap(chat)?:", r"t\.me/", r"wa\.me/", r"واتساب", r"سناب",
    r"تليجرام", r"للتواصل", r"dm", r"@[A-Za-z0-9_]{3,}", r"\b\+?966[0-9]{8,9}\b",
]


class HeuristicScorer:
    def __init__(self) -> None:
        self.geo_regexes = [re.compile(p, re.IGNORECASE) for p in KSA_GEO_PATTERNS]
        self.broker_dialect_regexes = [
            re.compile(p, re.IGNORECASE) for p in KSA_BROKER_AND_DIALECT_PATTERNS
        ]
        self.options_regexes = [re.compile(p, re.IGNORECASE) for p in OPTIONS_PATTERNS]
        self.ticker_regexes = [re.compile(p, re.IGNORECASE) for p in US_TICKER_PATTERNS]
        self.execution_regexes = [re.compile(p, re.IGNORECASE) for p in EXECUTION_PATTERNS]
        self.contact_regexes = [re.compile(p, re.IGNORECASE) for p in CONTACT_INFO_PATTERNS]

    def score_lead(self, lead: NormalizedLead) -> Tuple[float, Dict[str, Any]]:
        """
        Calculates deterministic heuristic score (0–60 pts) and returns breakdown.
        """
        breakdown: Dict[str, Any] = {
            "geo_score": 0.0,
            "capital_score": 0.0,
            "reachability_score": 0.0,
            "details": [],
        }

        combined_text = lead.get_combined_text()
        location_text = lead.location or ""

        # 1. KSA/GCC Geo & Dialect Affinity (0–25 pts)
        geo_pts = 0.0
        has_geo = any(rx.search(location_text) or rx.search(lead.bio) for rx in self.geo_regexes)
        if has_geo:
            geo_pts += 15.0
            breakdown["details"].append("KSA explicit location/flag detected (+15)")

        has_broker_dialect = any(rx.search(combined_text) for rx in self.broker_dialect_regexes)
        if has_broker_dialect:
            geo_pts += 10.0
            breakdown["details"].append("Saudi broker mention or Gulf dialect detected (+10)")

        geo_score = min(25.0, geo_pts)
        breakdown["geo_score"] = geo_score

        # 2. Capital & Active Trading Signals (0–20 pts)
        capital_pts = 0.0
        has_options = any(rx.search(combined_text) for rx in self.options_regexes)
        if has_options:
            capital_pts += 10.0
            breakdown["details"].append("Options trading interest (+10)")

        has_tickers = any(rx.search(combined_text) for rx in self.ticker_regexes)
        if has_tickers:
            capital_pts += 5.0
            breakdown["details"].append("US Tech tickers mentioned (+5)")

        has_execution = any(rx.search(combined_text) for rx in self.execution_regexes)
        if has_execution:
            capital_pts += 5.0
            breakdown["details"].append("Active portfolio execution signals (+5)")

        capital_score = min(20.0, capital_pts)
        breakdown["capital_score"] = capital_score

        # 3. Reachability & Direct Contact (0–15 pts)
        reach_pts = 0.0
        if lead.phone_number or lead.whatsapp_url:
            reach_pts += 15.0
            breakdown["details"].append(f"Verified mobile / WhatsApp link ({lead.phone_number or lead.whatsapp_url}) (+15)")
        elif lead.can_dm is True:
            reach_pts += 15.0
            breakdown["details"].append("Direct Messages enabled on X.com (+15)")
        elif lead.telegram_handle:
            reach_pts += 12.0
            breakdown["details"].append(f"Direct Telegram handle ({lead.telegram_handle}) (+12)")
        else:
            has_contact = any(rx.search(lead.bio) for rx in self.contact_regexes)
            if has_contact:
                reach_pts += 10.0
                breakdown["details"].append("Public contact details in profile bio (+10)")
            else:
                # Check recent activity within 24h
                try:
                    last_act = datetime.fromisoformat(lead.last_activity_at)
                    if datetime.now(timezone.utc) - last_act <= timedelta(hours=24):
                        reach_pts += 8.0
                        breakdown["details"].append("Active interaction within last 24h (+8)")
                except Exception:
                    pass

        reachability_score = min(15.0, reach_pts)
        breakdown["reachability_score"] = reachability_score

        total_heuristic = min(60.0, geo_score + capital_score + reachability_score)
        breakdown["total_heuristic_score"] = total_heuristic

        return total_heuristic, breakdown
