"""
SQLite 90-Day Deduplication & Competitor/Bot Disqualification Engine
"""

from __future__ import annotations

import logging
import re
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

from src.stage2_scrapers.models import NormalizedLead, ScoredLead

logger = logging.getLogger(__name__)


DEFAULT_BLACKLIST_REGEXES = [
    r"توصيات مدفوعة",
    r"للاشتراك تواصل",
    r"إدارة محافظ",
    r"ادارة محافظ",
    r"قروب توصيات",
    r"اشترك الآن",
    r"اشترك الان",
    r"VIP signals",
    r"VIP Signals",
    r"DM for promo",
    r"Account manager",
    r"Forex signals",
    r"crypto pump",
    r"airdrop",
    r"بوت تداول",
    r"ارباح مضمونة",
]


class Deduplicator:
    def __init__(self, db_path: Path | str, blacklist_patterns: Optional[List[str]] = None):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.blacklist_patterns = blacklist_patterns or DEFAULT_BLACKLIST_REGEXES
        self._compiled_regexes = [
            re.compile(p, re.IGNORECASE) for p in self.blacklist_patterns
        ]
        self._init_db()

    def _get_connection(self) -> sqlite3.Connection:
        return sqlite3.connect(str(self.db_path))

    def _init_db(self) -> None:
        """Create seen_leads table and indices if they do not exist."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS seen_leads (
                    platform TEXT NOT NULL,
                    user_id TEXT NOT NULL,
                    username TEXT,
                    first_seen_at TEXT NOT NULL,
                    last_exported_at TEXT,
                    interest_category TEXT,
                    total_score REAL,
                    PRIMARY KEY (platform, user_id)
                )
                """
            )
            cursor.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_seen_leads_exported 
                ON seen_leads (last_exported_at)
                """
            )
            conn.commit()
        logger.info(f"Initialized SQLite leads history database at {self.db_path}")

    def is_competitor_or_seller(self, lead: NormalizedLead) -> Tuple[bool, str]:
        """
        Check if the profile bio or trigger text matches promotional, signal seller, or spam keywords.
        Returns (is_competitor, matched_pattern).
        """
        combined_text = lead.get_combined_text()
        for rx in self._compiled_regexes:
            match = rx.search(combined_text)
            if match:
                return True, match.group(0)
        return False, ""

    def is_lead_exported_recently(self, platform: str, user_id: str, days: int = 90) -> bool:
        """
        Check if the lead has been exported in the last N days.
        """
        cutoff_date = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT last_exported_at FROM seen_leads 
                WHERE platform = ? AND user_id = ? AND last_exported_at IS NOT NULL
                """,
                (platform, user_id),
            )
            row = cursor.fetchone()
            if row and row[0]:
                exported_at = row[0]
                if exported_at >= cutoff_date:
                    return True
        return False

    def filter_and_disqualify(
        self, leads: List[NormalizedLead], lookback_days: int = 90
    ) -> List[NormalizedLead]:
        """
        Deduplicates against the 90-day SQLite history and removes competitors/bots.
        """
        qualified: List[NormalizedLead] = []
        for lead in leads:
            # 1. Deduplication check
            if self.is_lead_exported_recently(lead.platform, lead.user_id, days=lookback_days):
                logger.debug(
                    f"Skipping {lead.platform}:@{lead.username} (exported within {lookback_days} days)"
                )
                continue

            # 2. Competitor / Seller / Bot check
            is_comp, pattern = self.is_competitor_or_seller(lead)
            if is_comp:
                logger.info(
                    f"Disqualified {lead.platform}:@{lead.username} — matched blacklist: '{pattern}'"
                )
                continue

            qualified.append(lead)

        logger.info(
            f"Deduplication & Disqualification complete: {len(qualified)}/{len(leads)} leads retained"
        )
        return qualified

    def record_exported_leads(self, scored_leads: List[ScoredLead]) -> None:
        """
        Persist exported leads into SQLite with last_exported_at timestamp.
        """
        now_str = datetime.now(timezone.utc).isoformat()
        with self._get_connection() as conn:
            cursor = conn.cursor()
            for sl in scored_leads:
                lead = sl.lead
                cursor.execute(
                    """
                    INSERT INTO seen_leads (
                        platform, user_id, username, first_seen_at, 
                        last_exported_at, interest_category, total_score
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(platform, user_id) DO UPDATE SET
                        username = excluded.username,
                        last_exported_at = excluded.last_exported_at,
                        interest_category = excluded.interest_category,
                        total_score = excluded.total_score
                    """,
                    (
                        lead.platform,
                        lead.user_id,
                        lead.username,
                        lead.first_discovered_at,
                        now_str,
                        sl.interest_category,
                        sl.total_score,
                    ),
                )
            conn.commit()
        logger.info(f"Recorded {len(scored_leads)} leads into {self.db_path}")
