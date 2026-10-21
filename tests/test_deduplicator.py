"""
Tests for Deduplicator & Competitor Disqualification
"""

import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
import pytest

from src.stage2_scrapers.models import NormalizedLead, ScoredLead, TriggerEvent
from src.stage3_scorer.deduplicator import Deduplicator


@pytest.fixture
def temp_db(tmp_path):
    db_file = tmp_path / "test_leads.db"
    return Deduplicator(db_path=db_file)


def create_sample_lead(
    user_id: str,
    username: str,
    bio: str = "مستثمر عادي في السوق الأمريكي",
    content: str = "وش رايكم في سهم تسلا؟",
) -> NormalizedLead:
    trigger = TriggerEvent(
        platform="x",
        trigger_type="search_tweet",
        content=content,
        url=f"https://x.com/{username}/status/123",
    )
    return NormalizedLead(
        platform="x",
        user_id=user_id,
        username=username,
        display_name=username,
        bio=bio,
        location="الرياض",
        triggers=[trigger],
    )


def test_competitor_and_seller_disqualification(temp_db):
    normal_lead = create_sample_lead("1", "trader_fahad", bio="مهتم بالأسهم الأمريكية 🇸🇦")
    promo_lead = create_sample_lead("2", "vip_group", bio="توصيات مدفوعة للاشتراك تواصل خاص")
    signals_lead = create_sample_lead("3", "signals_bot", bio="Daily VIP signals Forex pump")

    is_comp1, _ = temp_db.is_competitor_or_seller(normal_lead)
    is_comp2, pat2 = temp_db.is_competitor_or_seller(promo_lead)
    is_comp3, pat3 = temp_db.is_competitor_or_seller(signals_lead)

    assert is_comp1 is False
    assert is_comp2 is True
    assert "توصيات مدفوعة" in pat2
    assert is_comp3 is True
    assert "signals" in pat3.lower()


def test_90_day_deduplication(temp_db):
    lead = create_sample_lead("101", "saudi_investor")
    scored = ScoredLead(lead=lead, total_score=80.0, interest_category="1_Options_Traders")

    # Initially not exported
    assert not temp_db.is_lead_exported_recently("x", "101", days=90)

    # Record export
    temp_db.record_exported_leads([scored])

    # Now exported within 90 days
    assert temp_db.is_lead_exported_recently("x", "101", days=90)


def test_filter_and_disqualify_pipeline(temp_db):
    leads = [
        create_sample_lead("1", "good_lead_1", bio="مستثمر في السوق الأمريكي"),
        create_sample_lead("2", "bad_lead_seller", bio="إدارة محافظ وأرباح مضمونة"),
        create_sample_lead("3", "good_lead_2", bio="مهتم بالأوبشن في الرياض"),
    ]

    filtered = temp_db.filter_and_disqualify(leads, lookback_days=90)
    assert len(filtered) == 2
    assert [l.username for l in filtered] == ["good_lead_1", "good_lead_2"]
