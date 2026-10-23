"""
Tests for Heuristic Scorer and LLM Classifier
"""

import pytest
from src.stage2_scrapers.models import NormalizedLead, TriggerEvent
from src.stage3_scorer.heuristic_scorer import HeuristicScorer
from src.stage3_scorer.llm_classifier import LLMClassifier


@pytest.fixture
def scorer():
    return HeuristicScorer()


@pytest.fixture
def classifier():
    return LLMClassifier({"provider": "heuristic_fallback"})


def test_heuristic_high_intent_lead(scorer):
    trigger = TriggerEvent(
        platform="x",
        trigger_type="search_tweet",
        content="وش رايكم في عقود كول سهم $NVDA سترايك 140 في دراية جلوبل؟ شريت اليوم وابي اعرف الأهداف.",
        url="https://x.com/trader_1/status/123",
        cashtags=["$NVDA"],
    )
    lead = NormalizedLead(
        platform="x",
        user_id="u1",
        username="trader_1",
        display_name="أبو سلطان",
        bio="مستثمر في أسواق الأسهم العالمية 🇸🇦 الرياض",
        location="الرياض، المملكة العربية السعودية",
        can_dm=True,
        triggers=[trigger],
    )

    score, breakdown = scorer.score_lead(lead)

    # Geo: 15 (Riyadh/🇸🇦) + 10 (دراية / وش رايكم) = 25
    assert breakdown["geo_score"] == 25.0
    # Capital: 10 (عقود كول) + 5 ($NVDA) + 5 (شريت) = 20
    assert breakdown["capital_score"] == 20.0
    # Reachability: 15 (can_dm = True)
    assert breakdown["reachability_score"] == 15.0
    # Total heuristic = 60
    assert score == 60.0


def test_heuristic_low_intent_lead(scorer):
    trigger = TriggerEvent(
        platform="x",
        trigger_type="search_tweet",
        content="صباح الخير للجميع وجمعة مباركة",
        url="https://x.com/user_random/status/456",
    )
    lead = NormalizedLead(
        platform="x",
        user_id="u2",
        username="user_random",
        display_name="User",
        bio="حساب شخصي",
        location="Unknown",
        can_dm=False,
        triggers=[trigger],
    )

    score, breakdown = scorer.score_lead(lead)
    assert score < 20.0


@pytest.mark.asyncio
async def test_llm_classifier_options_fallback(classifier):
    lead = NormalizedLead(
        platform="x",
        user_id="u_opt",
        username="options_hunter",
        display_name="Options Hunter",
        bio="عقود الأوبشن الأمريكية",
        triggers=[
            TriggerEvent(
                platform="x",
                trigger_type="search_tweet",
                content="كيف اشتري كول على سهم $TSLA في تطبيق سهم؟",
                url="https://x.com/test/1",
            )
        ],
    )

    res = await classifier.classify_lead(lead)
    assert res["is_genuine_retail_investor"] is True
    assert res["is_competitor_or_seller"] is False
    assert res["interest_category"] == "1_Options_Traders"
    assert res["intent_score"] >= 30.0
    assert "أوبشن" in res["qualification_reason_ar"]


@pytest.mark.asyncio
async def test_llm_classifier_sharia_fallback(classifier):
    lead = NormalizedLead(
        platform="x",
        user_id="u_sharia",
        username="halal_seeker",
        display_name="Halal Seeker",
        bio="الأسهم النقية الأمريكية",
        triggers=[
            TriggerEvent(
                platform="x",
                trigger_type="search_tweet",
                content="هل سهم بالانتير نقي ومتوافق مع الضوابط الشرعية؟",
                url="https://x.com/test/2",
            )
        ],
    )

    res = await classifier.classify_lead(lead)
    assert res["interest_category"] == "2_Halal_Sharia_Stocks"
    assert res["intent_score"] >= 30.0


def test_heuristic_lead_with_phone_contact(scorer):
    lead = NormalizedLead(
        platform="x",
        user_id="u_phone",
        username="phone_trader",
        display_name="فهد تداول",
        bio="متداول أوبشن بالرياض",
        location="الرياض",
        phone_number="+966501234567",
        whatsapp_url="https://wa.me/966501234567",
        can_dm=False,
    )
    score, breakdown = scorer.score_lead(lead)
    assert breakdown["reachability_score"] == 15.0
    assert any("Verified mobile" in d for d in breakdown["details"])

