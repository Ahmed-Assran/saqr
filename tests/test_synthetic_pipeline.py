"""
End-to-End Synthetic Pipeline Integration Test
"""

import asyncio
from pathlib import Path
import pytest

from src.cli import generate_synthetic_leads
from src.stage2_scrapers.models import ScoredLead
from src.stage3_scorer.deduplicator import Deduplicator
from src.stage3_scorer.exporter import LeadExporter
from src.stage3_scorer.heuristic_scorer import HeuristicScorer
from src.stage3_scorer.llm_classifier import LLMClassifier


@pytest.mark.asyncio
async def test_full_synthetic_pipeline_end_to_end(tmp_path):
    db_file = tmp_path / "test_leads_history.db"
    exports_dir = tmp_path / "exports"

    # 1. Generate 60 diverse synthetic leads
    raw_leads = generate_synthetic_leads(count=60)
    assert len(raw_leads) == 60

    # 2. Stage 3: Deduplication & Disqualification
    dedup = Deduplicator(db_path=db_file)
    clean_leads = dedup.filter_and_disqualify(raw_leads, lookback_days=90)
    # The disqualified promo accounts (vip_signals_promo) should be excluded
    disqualified_handles = [l.username for l in raw_leads if "vip_signals" in l.username]
    for h in disqualified_handles:
        assert not any(l.username == h for l in clean_leads)

    # 3. Stage 3: Heuristic & LLM Scoring
    scorer = HeuristicScorer()
    classifier = LLMClassifier({"provider": "heuristic_fallback"})

    scored_leads = []
    for l in clean_leads:
        h_score, breakdown = scorer.score_lead(l)
        llm_res = await classifier.classify_lead(l)
        tot = h_score + llm_res.get("intent_score", 0.0)

        sl = ScoredLead(
            lead=l,
            heuristic_score=h_score,
            llm_intent_score=llm_res.get("intent_score", 0.0),
            total_score=tot,
            is_genuine_retail_investor=llm_res.get("is_genuine_retail_investor", True),
            is_competitor_or_seller=llm_res.get("is_competitor_or_seller", False),
            interest_category=llm_res.get("interest_category", "5_Broker_Platform_Seekers"),
            qualification_reason_ar=llm_res.get("qualification_reason_ar", ""),
            scoring_breakdown=breakdown,
        )
        scored_leads.append(sl)

    # 4. Stage 3: Exporter
    exporter = LeadExporter(exports_dir=exports_dir, target_count=50, min_score=55.0)
    result = exporter.export_all(scored_leads, date_tag="integration_test")

    excel_path = result["excel"]
    csv_path = result["csv"]
    exported_leads = result["leads_exported"]

    assert excel_path.exists() and excel_path.stat().st_size > 0
    assert csv_path.exists() and csv_path.stat().st_size > 0
    assert len(exported_leads) <= 50

    # 5. Record to SQLite database and verify 90-day persistence
    dedup.record_exported_leads(exported_leads)
    for el in exported_leads[:5]:
        assert dedup.is_lead_exported_recently(el.lead.platform, el.lead.user_id, days=90)
