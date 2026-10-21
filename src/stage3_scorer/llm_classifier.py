"""
LLM Intent Classifier & Categorization Engine
Queries local Ollama (qwen2.5:14b / llama3.1:8b) or Gemini API with structured JSON output,
supported by a robust deterministic Arabic NLP fallback.
"""

from __future__ import annotations

import json
import logging
import os
import re
from typing import Any, Dict, Optional, Tuple
import httpx

from src.stage2_scrapers.models import NormalizedLead

logger = logging.getLogger(__name__)

CATEGORY_MAP = {
    "1": "1_Options_Traders",
    "2": "2_Halal_Sharia_Stocks",
    "3": "3_Active_Day_Swing_Traders",
    "4": "4_Specific_Tech_Tickers",
    "5": "5_Broker_Platform_Seekers",
}

SYSTEM_PROMPT = """
You are a Senior Financial Lead Qualification Analyst evaluating prospective Saudi/GCC retail investors for US stock recommendations.
Your task is to analyze the user profile (bio) and their recent Arabic posts/comments, then return a valid JSON object.

Evaluation Criteria:
1. Is the person a genuine individual retail investor or trader? (Not a bot, news agency, institutional firm, or signal selling scammer)
2. Is the person a competitor or seller of VIP groups / signals? (If they sell courses or paid signals, is_competitor_or_seller = true)
3. Intent score (0 to 40): Based on high purchasing intent, active engagement with US stocks, asking about broker commissions, seeking options advice, or looking for recommendation groups.
4. Categorize them into exactly ONE category:
   - "1_Options_Traders" (عقود الخيارات والأوبشن)
   - "2_Halal_Sharia_Stocks" (الأسهم النقية والشرعية والفلترة الإسلامية)
   - "3_Active_Day_Swing_Traders" (المضاربة اللحظية واليومية والتحليل الفني)
   - "4_Specific_Tech_Tickers" (المهتمون بأسهم التكنولوجيا والذكاء الاصطناعي NVDA, TSLA, AAPL, PLTR)
   - "5_Broker_Platform_Seekers" (الباحثون عن أفضل منصات ووسطاء للتداول دراية، سهم، عوائد، بركة)
5. qualification_reason_ar: A concise Arabic sentence explaining why they are qualified and their specific angle of interest.

Return ONLY a raw JSON object with these keys:
{
  "is_genuine_retail_investor": true,
  "is_competitor_or_seller": false,
  "intent_score": 35,
  "interest_category": "1_Options_Traders",
  "qualification_reason_ar": "مستثمر نشط يسأل عن عقود كول لسهم نفيديا ويبحث عن وسيط بعمولة منخفضة"
}
"""


class LLMClassifier:
    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.provider = config.get("provider", "ollama")
        self.ollama_cfg = config.get("ollama", {})
        self.gemini_cfg = config.get("gemini", {})
        self.timeout = self.ollama_cfg.get("timeout_seconds", 30)
        self._ollama_available: Optional[bool] = None
        self._gemini_available: Optional[bool] = None

    async def classify_lead(self, lead: NormalizedLead) -> Dict[str, Any]:
        """
        Classifies lead intent, assigns 0–40 score, and categorizes into 1 of 5 buckets.
        Tries Ollama/Gemini first; falls back to deterministic rule engine on error/offline.
        """
        if self.provider == "ollama" and self._ollama_available is not False:
            res = await self._call_ollama(lead)
            if res:
                return res
        elif self.provider == "gemini" and self._gemini_available is not False:
            res = await self._call_gemini(lead)
            if res:
                return res

        # Fallback to rule-based classification
        return self._rule_based_fallback(lead)

    async def _call_ollama(self, lead: NormalizedLead) -> Optional[Dict[str, Any]]:
        """Call local Ollama /api/generate endpoint with fail-fast availability check."""
        base_url = self.ollama_cfg.get("base_url", "http://localhost:11434")
        model = self.ollama_cfg.get("model", "qwen2.5:14b")
        url = f"{base_url}/api/generate"

        user_content = (
            f"User Handle: @{lead.username}\n"
            f"Display Name: {lead.display_name}\n"
            f"Location: {lead.location}\n"
            f"Bio: {lead.bio}\n\n"
            f"Recent Posts / Triggers:\n{lead.get_combined_text()}"
        )

        payload = {
            "model": model,
            "prompt": f"{SYSTEM_PROMPT}\n\nCandidate Data:\n{user_content}\n\nJSON Response:",
            "stream": False,
            "format": "json",
            "options": {"temperature": 0.1},
        }

        try:
            # Use short connect timeout (1.5s) to fail fast if daemon is offline
            client_timeout = httpx.Timeout(self.timeout, connect=1.5)
            async with httpx.AsyncClient(timeout=client_timeout) as client:
                resp = await client.post(url, json=payload)
                if resp.status_code == 200:
                    self._ollama_available = True
                    resp_json = resp.json()
                    response_text = resp_json.get("response", "")
                    return self._clean_and_parse_json(response_text)
                else:
                    logger.debug(f"Ollama returned HTTP {resp.status_code}")
        except (httpx.ConnectError, httpx.ConnectTimeout) as e:
            if self._ollama_available is not False:
                logger.info("Local Ollama daemon is offline; using deterministic Arabic NLP classifier.")
                self._ollama_available = False
        except Exception as e:
            logger.debug(f"Ollama call exception: {e}")
        return None

    async def _call_gemini(self, lead: NormalizedLead) -> Optional[Dict[str, Any]]:
        """Call Gemini API if key is present."""
        api_key_env = self.gemini_cfg.get("api_key_env", "GEMINI_API_KEY")
        api_key = os.environ.get(api_key_env)
        if not api_key:
            return None

        model = self.gemini_cfg.get("model", "gemini-2.5-flash")
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"

        user_content = (
            f"User Handle: @{lead.username}\n"
            f"Bio: {lead.bio}\n"
            f"Location: {lead.location}\n"
            f"Triggers:\n{lead.get_combined_text()}"
        )

        payload = {
            "contents": [
                {
                    "parts": [
                        {"text": f"{SYSTEM_PROMPT}\n\nCandidate Data:\n{user_content}"}
                    ]
                }
            ],
            "generationConfig": {"response_mime_type": "application/json"},
        }

        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                resp = await client.post(url, json=payload)
                if resp.status_code == 200:
                    data = resp.json()
                    text = data["candidates"][0]["content"]["parts"][0]["text"]
                    return self._clean_and_parse_json(text)
        except Exception as e:
            logger.debug(f"Gemini call failed ({e}); switching to fallback")
        return None

    def _clean_and_parse_json(self, raw_text: str) -> Optional[Dict[str, Any]]:
        """Extract and validate JSON response."""
        try:
            clean = raw_text.strip()
            if clean.startswith("```json"):
                clean = clean[7:]
            if clean.startswith("```"):
                clean = clean[3:]
            if clean.endswith("```"):
                clean = clean[:-3]
            clean = clean.strip()
            data = json.loads(clean)

            # Validate fields
            intent_score = float(data.get("intent_score", 25.0))
            intent_score = max(0.0, min(40.0, intent_score))

            category = data.get("interest_category", "5_Broker_Platform_Seekers")
            if category not in CATEGORY_MAP.values():
                category = "5_Broker_Platform_Seekers"

            return {
                "is_genuine_retail_investor": bool(data.get("is_genuine_retail_investor", True)),
                "is_competitor_or_seller": bool(data.get("is_competitor_or_seller", False)),
                "intent_score": intent_score,
                "interest_category": category,
                "qualification_reason_ar": str(data.get("qualification_reason_ar", "مستثمر مؤهل مهتم بتداول الأسهم الأمريكية")),
            }
        except Exception as e:
            logger.debug(f"JSON parsing error from LLM response: {e}")
            return None

    def _rule_based_fallback(self, lead: NormalizedLead) -> Dict[str, Any]:
        """
        Deterministic, audit-proof Arabic NLP classifier providing 0–40 score and category bucketing.
        """
        text = lead.get_combined_text().lower()

        # Check for options
        is_options = any(w in text for w in ["أوبشن", "اوبشن", "عقود", "كول", "بوت", "options", "call", "put"])
        # Check for halal / sharia
        is_sharia = any(w in text for w in ["نقي", "نقية", "حلال", "شرعي", "شرعية", "تطهير", "الراجحي", "حكم"])
        # Check for day / swing
        is_swing = any(w in text for w in ["مضاربة", "دخول", "هدف", "وقف", "شارت", "مقاومة", "دعم", "لحظي", "سوينق"])
        # Check for tech tickers
        is_tech = any(w in text for w in ["$nvda", "$tsla", "$aapl", "$msft", "$amd", "$pltr", "$meta", "$googl", "$coin", "تسلا", "نيفيديا", "ابل"])
        # Check for brokers
        is_broker = any(w in text for w in ["دراية", "سهم", "عوائد", "بركة", "وسيط", "عمولة", "تطبيق", "منصة", "كابيتال", "ibkr"])

        # Category determination hierarchy
        if is_options:
            category = "1_Options_Traders"
            reason = "متداول أوبشن مهتم بعقود الخيارات واستراتيجيات التداول في السوق الأمريكي"
            intent_score = 36.0
        elif is_sharia:
            category = "2_Halal_Sharia_Stocks"
            reason = "مستثمر حريص على شرعية الأسهم الأمريكية وفلترة الشركات النقية والمتوافقة مع الشريعة"
            intent_score = 34.0
        elif is_swing:
            category = "3_Active_Day_Swing_Traders"
            reason = "مضارب يومي نشط يبحث عن نقاط الدخول والأهداف السعرية في الأسهم الأمريكية"
            intent_score = 35.0
        elif is_tech:
            category = "4_Specific_Tech_Tickers"
            reason = "مستثمر يتابع أسهم التكنولوجيا الأمريكية القيادية ويبحث عن فرص نمو مدروسة"
            intent_score = 33.0
        else:
            category = "5_Broker_Platform_Seekers"
            reason = "مستثمر يسأل عن أفضل المنصات والوسطاء وعمولات التداول بالسوق الأمريكي"
            intent_score = 31.0

        return {
            "is_genuine_retail_investor": True,
            "is_competitor_or_seller": False,
            "intent_score": intent_score,
            "interest_category": category,
            "qualification_reason_ar": reason,
        }
