---
name: ksa-social-lead-scraper
description: Harvests X.com SearchTimeline and UserTweets GraphQL responses across Arabic US-stock hashtags, cashtags, and Saudi broker/finfluencer reply threads, plus TikTok /api/comment/list/ comment threads on KSA finance videos.
---

# KSA Social Lead Scraper Skill

## Purpose
Governs the network-level interception and normalization of prospective retail investor leads from X.com and TikTok across Saudi Arabia and the GCC.

## Core Rules & Architecture
1. **Network-First GraphQL / XHR Interception**:
   - Primary data extraction operates by intercepting raw network payloads (`page.on("response", ...)`).
   - Never rely exclusively on brittle CSS selectors that break during minor UI updates.
   - For X.com: Intercept `SearchTimeline`, `UserTweets`, and `TweetDetail` GraphQL endpoints.
   - For TikTok: Intercept `/api/search/item/full/`, `/api/comment/list/`, and `/api/comment/list/reply/`.
2. **Search Intent Harvesting (Mode A - X.com)**:
   - Query X.com using the `Latest` tab (`f=live`) with recent time windows (last 24-48 hours).
   - Target queries configured in `config/targets_ksa.yaml` across 5 core categories:
     - Options trading (`أوبشن`, `عقود الخيارات`)
     - Halal / Sharia compliance (`الأسهم النقية`, `شرعية السهم`)
     - Day / Swing trading (`مضاربة`, `تداول الأسهم الأمريكية`)
     - US Tech cashtags (`$NVDA`, `$TSLA`, `$AAPL`, `$PLTR`, etc.)
     - Broker / recommendation seekers (`دراية جلوبل`, `سهم كابيتال`, `عوائد`, `بركة`, `توصيات`)
3. **Broker & Finfluencer Thread Infiltration (Mode B - X.com)**:
   - Target active reply and quote-tweet authors under posts from certified KSA brokerages (`@Derayah`, `@Sahm_Capital`, `@AwaedApp`, `@getbaraka`, `@SNBCapital`, `@RiyadCapital`).
   - Disregard passive follower lists; extract only engaged users asking questions or debating trades.
4. **TikTok Finance Video Comment Crawling**:
   - Search high-engagement KSA finance videos explaining US stock trading, options, and apps.
   - Paginate the comment drawer and intercept `/api/comment/list/`.
   - Match comments demonstrating buying intent, questions about trading apps, or requests for recommendations.
5. **Data Staging & Normalization**:
   - Normalize every discovered prospect into a structured schema (`NormalizedLead`).
   - Aggregate multiple interactions into a list of `TriggerEvent` records per user.
   - Append records to `data/staging/raw_leads_YYYY-MM-DD.jsonl` with `ensure_ascii=False`.
