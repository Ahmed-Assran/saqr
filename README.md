<p align="center">
  <h1 align="center">🦅 Saqr (صقر)</h1>
  <p align="center">
    <strong>Autonomous KSA & GCC US-Stock Lead Scouting & Qualification Engine</strong>
  </p>
  <p align="center">
    <em>Scout, qualify, score, and export ~50 high-intent retail investor leads daily from Saudi Arabia & the GCC for US stock & options recommendations.</em>
  </p>
  <p align="center">
    <a href="#features"><img src="https://img.shields.io/badge/Python-3.10%2B-blue?logo=python" alt="Python 3.10+"></a>
    <a href="#architecture"><img src="https://img.shields.io/badge/Playwright-Stealth%20Async-green?logo=playwright" alt="Playwright"></a>
    <a href="#scoring-engine"><img src="https://img.shields.io/badge/Scoring-100pt%20Hybrid-orange" alt="100pt Scoring"></a>
    <a href="LICENSE"><img src="https://img.shields.io/badge/License-MIT-purple.svg" alt="MIT License"></a>
    <a href="#output-formats"><img src="https://img.shields.io/badge/Export-RTL%20Excel%20%2B%20CSV-teal" alt="RTL Excel + CSV"></a>
  </p>
</p>

---

## 📌 Overview

**Saqr (صقر)** is a high-precision, production-ready local Python pipeline engineered to discover and qualify prospective retail investors across **Saudi Arabia (KSA) and the GCC** who are actively interested in trading US stocks, options contracts, and algorithmic strategies.

The system is built for financial advisory teams, broker sales desks, and fintech apps. It automatically intercepts social buying intent, filters competitors, scores leads using a **100-point hybrid heuristic + AI intent model**, buckets prospects into **5 interest categories**, and generates downloadable **multi-tab Right-to-Left (RTL) Arabic Excel workbooks** and **UTF-8 with BOM CSVs** daily at **12:00 PM**.

> [!NOTE]
> **Strict Scope Boundary**: Saqr operates exclusively as a read-only discovery, scoring, and deduplication engine. It contains **zero** automated DM sending or spamming mechanisms, ensuring all outreach remains ethical and handled manually by human sales professionals.

---

## ⚡ Key Capabilities

- **Stealth Network Interception**: Captures raw GraphQL and XHR JSON payloads directly from X.com (`SearchTimeline`, `TweetDetail`, `UserTweets`) and TikTok (`/api/comment/list/`), avoiding brittle CSS scraping.
- **KSA & GCC Browser Emulation**: Injects `ar-SA` locale, `Asia/Riyadh` timezone, Riyadh geolocation coordinates, and WebGL anti-bot evasions.
- **Proactive Account Rotation**: State machine (`active`, `cooldown`, `challenged`, `banned`) enforcing a 20-request threshold and 45-minute cooldown per account with HTTP 429/403 circuit breakers.
- **Resilient `--resume` Recovery**: Atomic JSON checkpointing guarantees interrupted runs pick up immediately without re-scraping completed queries.
- **90-Day SQLite Deduplication**: Tracks previously exported prospects in `leads_history.db` to prevent pitching recently contacted leads.
- **Competitor & Bot Disqualification**: Instant regex rejection of signal sellers, VIP group advertisers, portfolio managers, and spam bots (`توصيات مدفوعة`, `إدارة محافظ`, etc.).
- **100-Point Hybrid Scoring Engine**:
  - **Deterministic Heuristics (0–60 pts)**: KSA cities/flags, Saudi broker mentions (`دراية`, `سهم`, `عوائد`, `بركة`), Gulf dialect, US cashtags (`$NVDA`, `$TSLA`), and Direct Message reachability.
  - **AI Intent Scoring (0–40 pts)**: Local Ollama (`qwen2.5:14b` / `llama3.1:8b`) or Gemini API with structured JSON output and deterministic Arabic NLP fallback.
- **Multi-Tab RTL Excel & UTF-8 BOM CSV**: OpenPyXL workbook featuring freeze panes, styled navy headers, zebra striping, clickable hyperlinks, a master tab (`All_Top_50`), and 5 interest category tabs.

---

## 🏛️ System Architecture

```mermaid
flowchart TD
    subgraph Config ["1. Targets & Configuration"]
        T["targets_ksa.yaml<br/>(Hashtags, Cashtags, Brokers, TikTok queries)"]
        A["accounts_pool.json<br/>(X.com & TikTok accounts + KSA proxies)"]
        S["settings.yaml<br/>(Thresholds, LLM endpoints, schedules)"]
    end

    subgraph Stage1 ["Stage 1: Browser Stealth & Rotation"]
        AV["AccountVault<br/>(Active, Cooldown, Challenged state machine)"]
        SC["StealthContext<br/>(ar-SA locale, Asia/Riyadh, media blocker, jitter)"]
        CK["CheckpointManager<br/>(Atomic progress.json for --resume)"]
    end

    subgraph Stage2 ["Stage 2: Social Lead Harvesting"]
        XS["XScraper<br/>(SearchTimeline live & Broker reply threads)"]
        TS["TikTokScraper<br/>(Search & /api/comment/list/ interception)"]
        M["NormalizedLead & TriggerEvent<br/>(data/staging/raw_leads_YYYY-MM-DD.jsonl)"]
    end

    subgraph Stage3 ["Stage 3: Scoring & File Delivery"]
        DD["Deduplicator<br/>(90-day SQLite history + Bot/Promo blacklist)"]
        HS["HeuristicScorer (0–60 pts)<br/>(KSA geo, Broker affinity, Capital signals, DM status)"]
        LLM["LLMClassifier (0–40 pts)<br/>(Local Ollama or Gemini with Arabic NLP fallback)"]
        EX["Exporter Engine<br/>(Top-50 balanced selector, OpenPyXL .xlsx + UTF-8-SIG .csv)"]
    end

    subgraph Output ["Daily Deliverables (12:00 PM)"]
        XL["exports/ksa_us_stock_leads_YYYY-MM-DD.xlsx<br/>(All_Top_50 + 5 Category Tabs)"]
        CSV["exports/ksa_us_stock_leads_YYYY-MM-DD.csv<br/>(UTF-8 BOM Arabic Excel compatible)"]
    end

    T --> XS
    T --> TS
    A --> AV
    AV --> SC
    SC --> XS
    SC --> TS
    XS --> M
    TS --> M
    M --> DD
    DD --> HS
    HS --> LLM
    LLM --> EX
    EX --> XL
    EX --> CSV
```

---

## 🎯 5 Target Interest Categories

The Top 50 leads exported daily are balanced across 5 dedicated categories:

| Category Tab | Focus Area & Arabic Keywords | Ideal Pitch Offer |
| :--- | :--- | :--- |
| **`1_Options_Traders`** | `أوبشن`, `عقود الخيارات`, `كول`, `بوت`, `سترايك` | US Options alert packages & contract flow signals |
| **`2_Halal_Sharia_Stocks`** | `الأسهم النقية`, `الأسهم الحلال`, `شرعية السهم`, `تطهير` | Sharia-compliant US stock lists & Islamic filters |
| **`3_Active_Day_Swing_Traders`** | `مضاربة لحظية`, `دخول`, `هدف`, `وقف الخسارة`, `شارت` | High-velocity day trading setups & TradingView charts |
| **`4_Specific_Tech_Tickers`** | `$NVDA`, `$TSLA`, `$AAPL`, `$MSFT`, `$PLTR`, `$AMD` | Tech & AI sector equity research & swing targets |
| **`5_Broker_Platform_Seekers`** | `دراية جلوبل`, `سهم كابيتال`, `عوائد`, `بركة`, `عمولة` | Broker onboarding assistance & platform advisory |

---

## 🚀 Quickstart

### 1. Installation
Clone the repository and install dependencies:
```bash
git clone https://github.com/Ahmed-Assran/saqr.git
cd saqr
pip install -r requirements.txt
playwright install chromium
```

### 2. Verify with an Offline Dry Run
Execute an end-to-end synthetic run to verify scoring, deduplication, and export generation without hitting live platforms:
```bash
python -m src.cli dry-run --sample-size 50
```
Inspect the generated files in `exports/`:
- `exports/ksa_us_stock_leads_dry_run_YYYY-MM-DD.xlsx`
- `exports/ksa_us_stock_leads_dry_run_YYYY-MM-DD.csv`

---

## 🛠️ Configuration & Account Setup

### 1. Configure Accounts (`config/accounts_pool.json`)
Copy the template and configure your scouting accounts with residential proxies:
```bash
cp config/accounts_pool.example.json config/accounts_pool.json
```
```json
{
  "accounts": [
    {
      "account_id": "x_ksa_01",
      "platform": "x",
      "username": "your_burner_handle",
      "proxy_url": "http://user:pass@ksa-res-proxy-1.provider.com:8080",
      "storage_state_path": "data/sessions/x_ksa_01.json",
      "status": "active"
    }
  ]
}
```

### 2. Save Session Cookies Interactively
Run the headed login command for each account:
```bash
python -m src.cli login --account-id x_ksa_01
```
A browser window will launch with the account's assigned proxy. Complete the manual login once, return to your terminal, and press **ENTER**. The session state is saved to `data/sessions/` for future headless scraping.

---

## 💻 CLI Commands

| Command | Description |
| :--- | :--- |
| `python -m src.cli dry-run --sample-size 50` | Runs an offline synthetic pipeline test generating verified `.xlsx` and `.csv` files |
| `python -m src.cli login --account-id <id>` | Launches headed browser to log in and save session cookies |
| `python -m src.cli run-all --limit 50 --resume` | Executes the complete live daily harvesting, scoring, and delivery pipeline |

---

## ⏰ Daily Automation

To guarantee your daily lead export is ready in `exports/` by **12:00 PM**, schedule the pipeline to start at **10:30 AM**:

### Linux / macOS (Cron)
```bash
bash scripts/setup_cron.sh
```
*Installs a crontab entry: `30 10 * * *` executing `scripts/run_daily_pipeline.sh` inside a detached `tmux` session.*

### Windows (PowerShell / Task Scheduler)
Schedule [`scripts/run_daily_pipeline.ps1`](scripts/run_daily_pipeline.ps1) to run daily at 10:30 AM via Windows Task Scheduler.

---

## 🧪 Testing

Run the full automated test suite:
```bash
python -m pytest tests -v
```
All 10 unit and integration tests validate:
- SQLite 90-day deduplication & blacklist regex disqualification
- 60-point heuristic scoring engine
- LLM classifier structured JSON parsing and Arabic NLP fallback
- OpenPyXL multi-tab Excel generation with RTL layout and freeze panes
- UTF-8 with BOM CSV encoding for clean rendering in Microsoft Excel

---

## 📄 License

Distributed under the **MIT License**. See [`LICENSE`](LICENSE) for details.

Developed with precision by **Ahmed Assran**.
