---
name: ksa-lead-scorer-exporter
description: Deduplicates against a 90-day SQLite history DB, filters out bots and competing signal sellers, runs a 100-point hybrid heuristic + local Ollama LLM scoring engine, buckets the top 50 leads by interest, and exports .xlsx + .csv at 12:00 PM daily.
---

# KSA Lead Scorer Exporter Skill

## Purpose
Governs the qualification, scoring, categorization, deduplication, and file generation pipeline that delivers 50 high-intent KSA US-stock leads daily by 12:00 PM.

## Core Rules & Architecture
1. **90-Day Deduplication & Competitor Exclusions**:
   - Query `data/db/leads_history.db` (`seen_leads` table).
   - Reject any prospect exported within the preceding 90 days.
   - Execute regex blacklist checks against user bios and trigger texts to eliminate competing signal sellers, VIP group advertisers, portfolio managers, and bots:
     `r"(توصيات مدفوعة|للاشتراك تواصل|إدارة محافظ|ادارة محافظ|قروب توصيات|VIP signals|DM for promo|crypto pump|airdrop)"`
2. **Hybrid 100-Point Scoring Engine**:
   - **Deterministic Heuristics (0–60 Points)**:
     - *KSA/GCC Geo Affinity (0–25 pts)*: Explicit KSA location/flag (`الرياض`, `جدة`, `السعودية`, `KSA`, `🇸🇦`) = +15 pts. Interaction with Saudi brokers (`دراية`, `سهم`, `عوائد`, `بركة`) or Gulf dialect = +10 pts.
     - *Capital & Active Trading Signals (0–20 pts)*: Options contracts (`أوبشن`, `كول`, `بوت`), US tech tickers (`$NVDA`, `$TSLA`), active execution mentions (`محفظتي`, `تداول`, `TradingView`) = up to +20 pts.
     - *Reachability (0–15 pts)*: `can_dm == True` or public contact handle in bio = +15 pts; recent reply author (<24h) = +8 pts.
   - **LLM Intent & Category Scoring (0–40 Points)**:
     - Query local Ollama (`qwen2.5:14b` / `llama3.1:8b`) or Gemini API.
     - Enforce JSON output schema:
       ```json
       {
         "is_genuine_retail_investor": true,
         "is_competitor_or_seller": false,
         "intent_score": 35,
         "interest_category": "1_Options_Traders",
         "qualification_reason_ar": "ملخص قصير لسبب التأهيل"
       }
       ```
     - Provide rule-based fallback if LLM is unreachable.
3. **Top 50 Lead Selection**:
   - Minimum qualification threshold: `total_score >= 55`.
   - Must be verified genuine retail investor and not a seller.
   - Balance top leads across the 5 categories:
     1. `Options_Traders`
     2. `Halal_Sharia_Stocks`
     3. `Day_Swing_Traders`
     4. `Tech_Tickers`
     5. `Broker_Seekers`
4. **Downloadable File Delivery**:
   - Deliver by 12:00 PM daily:
     - `exports/ksa_us_stock_leads_YYYY-MM-DD.xlsx`: Multi-tab OpenPyXL workbook with RTL Arabic layout, freeze panes, auto-fit column widths, clickable hyperlinks, a master tab (`All_Top_50`), and 5 category tabs.
     - `exports/ksa_us_stock_leads_YYYY-MM-DD.csv`: Flat CSV strictly encoded in `utf-8-sig` (UTF-8 with BOM) so Arabic text displays correctly in Excel.
   - Update SQLite database only after confirming export files exist on disk and have non-zero size.
