"""
Data Models for Social Lead Scraping, Staging, and Scoring
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class TriggerEvent(BaseModel):
    """An individual intent event (tweet, reply, quote, TikTok comment)."""
    platform: str  # "x" or "tiktok"
    trigger_type: str  # "search_tweet", "broker_reply", "quote_tweet", "tiktok_comment"
    content: str
    url: str
    timestamp: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    cashtags: List[str] = Field(default_factory=list)
    target_broker_or_query: Optional[str] = None


class NormalizedLead(BaseModel):
    """A deduplicated prospect profile aggregating all associated trigger events."""
    platform: str  # "x" or "tiktok"
    user_id: str
    username: str
    display_name: str
    bio: str = ""
    location: str = ""
    followers_count: int = 0
    following_count: int = 0
    can_dm: Optional[bool] = None
    verified: bool = False
    profile_url: str = ""
    triggers: List[TriggerEvent] = Field(default_factory=list)
    first_discovered_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    last_activity_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def get_combined_text(self) -> str:
        """Combine bio and all trigger contents for comprehensive scoring."""
        parts = [self.bio] if self.bio else []
        for t in self.triggers:
            if t.content:
                parts.append(t.content)
        return " \n".join(parts)


class ScoredLead(BaseModel):
    """A qualified and scored prospect ready for categorization and export."""
    lead: NormalizedLead
    heuristic_score: float = 0.0
    llm_intent_score: float = 0.0
    total_score: float = 0.0
    is_genuine_retail_investor: bool = False
    is_competitor_or_seller: bool = False
    interest_category: str = "5_Broker_Platform_Seekers"
    qualification_reason_ar: str = ""
    scoring_breakdown: Dict[str, Any] = Field(default_factory=dict)
