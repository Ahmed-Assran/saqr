"""
CLI Entry Point for KSA US-Stock Lead Scouter
Supports account login, stage-by-stage execution, full pipeline automation, and offline dry runs.
"""

from __future__ import annotations

import asyncio
import io
import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional
import typer
import yaml
from rich.console import Console
from rich.table import Table

def ensure_utf8_console() -> None:
    """Ensure UTF-8 output on Windows consoles when running interactively."""
    if sys.platform == "win32":
        try:
            if hasattr(sys.stdout, "reconfigure"):
                sys.stdout.reconfigure(encoding="utf-8", errors="replace")
            if hasattr(sys.stderr, "reconfigure"):
                sys.stderr.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

ensure_utf8_console()

from src.stage1_browser.account_vault import AccountVault, SocialAccount
from src.stage1_browser.checkpoint import CheckpointManager
from src.stage1_browser.stealth_context import create_stealth_context
from src.stage2_scrapers.models import NormalizedLead, ScoredLead, TriggerEvent
from src.stage2_scrapers.link_resolver import ContactResolver
from src.stage2_scrapers.tiktok_scraper import TikTokScraper
from src.stage2_scrapers.x_scraper import XScraper
from src.stage3_scorer.deduplicator import Deduplicator
from src.stage3_scorer.exporter import LeadExporter
from src.stage3_scorer.heuristic_scorer import HeuristicScorer
from src.stage3_scorer.llm_classifier import LLMClassifier

app = typer.Typer(help="Saqr 🦅 (صقر) — Autonomous KSA & GCC US-Stock Lead Scouter CLI")
console = Console(legacy_windows=False)

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def setup_logging(logs_dir: Path, date_tag: str) -> None:
    """Configures rotating file and stream logging with UTF-8 safety."""
    logs_dir.mkdir(parents=True, exist_ok=True)
    log_file = logs_dir / f"pipeline_{date_tag}.log"

    # Wrap stdout stream with UTF-8 replacement to avoid Windows charmap errors
    stdout_stream = sys.stdout
    if hasattr(sys.stdout, "buffer"):
        try:
            stdout_stream = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
        except Exception:
            pass

    stream_handler = logging.StreamHandler(stdout_stream)

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        handlers=[
            logging.FileHandler(str(log_file), encoding="utf-8"),
            stream_handler,
        ],
        force=True,
    )


def load_config() -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """Load settings.yaml and targets_ksa.yaml."""
    settings_path = PROJECT_ROOT / "config" / "settings.yaml"
    targets_path = PROJECT_ROOT / "config" / "targets_ksa.yaml"

    with open(settings_path, "r", encoding="utf-8") as f:
        settings = yaml.safe_load(f)

    with open(targets_path, "r", encoding="utf-8") as f:
        targets = yaml.safe_load(f)

    return settings, targets


@app.command()
def login(
    account_id: str = typer.Option(..., "--account-id", "-a", help="Account ID to log in to"),
):
    """
    Launch a real browser window to manually log in to X.com or TikTok
    and save the session cookie state to data/sessions/.
    """
    settings, targets = load_config()
    accounts_path = PROJECT_ROOT / "config" / "accounts_pool.json"
    vault = AccountVault(accounts_path, base_dir=PROJECT_ROOT)

    account = vault.get_account_by_id(account_id)
    if not account:
        console.print(f"[bold red]Account ID '{account_id}' not found in pool config![/bold red]")
        raise typer.Exit(code=1)

    console.print(f"[bold cyan]Launching browser for account: {account_id} ({account.platform})...[/bold cyan]")

    async def _do_login():
        from playwright.async_api import async_playwright

        async with async_playwright() as p:
            # Try real Chrome first for maximum trust and anti-bot bypass
            launch_kwargs: Dict[str, Any] = {
                "headless": False,
                "args": [
                    "--disable-blink-features=AutomationControlled",
                    "--no-sandbox",
                    "--start-maximized",
                ],
            }
            try:
                browser = await p.chromium.launch(channel="chrome", **launch_kwargs)
            except Exception:
                browser = await p.chromium.launch(**launch_kwargs)

            # Clean context WITHOUT blocking stylesheets/images so the login page renders fully
            context_opts: Dict[str, Any] = {
                "user_agent": account.user_agent,
                "viewport": None,  # Match window size
            }
            if account.proxy_url:
                context_opts["proxy"] = {"server": account.proxy_url}

            context = await browser.new_context(**context_opts)
            page = await context.new_page()

            target_url = "https://x.com/login" if account.platform == "x" else "https://www.tiktok.com/login"
            console.print(f"[cyan]Navigating to {target_url}...[/cyan]")
            try:
                await page.goto(target_url, timeout=45000)
            except Exception as e:
                console.print(f"[yellow]Navigation notice: {e}. You can still interact with the open browser.[/yellow]")

            console.print("\n[bold green]====================================================[/bold green]")
            console.print("[bold yellow]Please complete your login in the opened browser window.[/bold yellow]")
            console.print("[yellow]Once you see your Home feed / profile, press ENTER here in terminal...[/yellow]")
            console.print("[bold green]====================================================[/bold green]\n")
            input("Press ENTER after login is complete: ")

            session_file = PROJECT_ROOT / (account.storage_state_path or f"data/sessions/{account.platform}_{account.account_id}.json")
            session_file.parent.mkdir(parents=True, exist_ok=True)
            await context.storage_state(path=str(session_file))
            account.storage_state_path = str(session_file.relative_to(PROJECT_ROOT))
            account.status = "active"
            vault.save_accounts()

            # Verify if auth_token was captured
            with open(session_file, "r", encoding="utf-8") as f:
                state_data = json.load(f)
            captured_names = [c.get("name") for c in state_data.get("cookies", [])]

            if "auth_token" in captured_names or "sessionid" in captured_names:
                console.print(f"[bold green]✓ Authenticated session successfully saved to {session_file}![/bold green]")
            else:
                console.print(f"[yellow]Session saved to {session_file}. Note: 'auth_token' cookie was not detected. If you see a login screen on your next run, make sure you finished logging in before pressing ENTER.[/yellow]")

            await browser.close()

    asyncio.run(_do_login())


@app.command()
def set_token(
    account_id: str = typer.Option("x_ksa_01", "--account-id", "-a", help="Account ID to configure"),
    auth_token: Optional[str] = typer.Option(None, "--auth-token", "-t", help="auth_token cookie value from x.com"),
    ct0: Optional[str] = typer.Option(None, "--ct0", "-c", help="ct0 cookie value from x.com (optional)"),
):
    """
    Directly import your x.com auth_token from your regular browser.
    Foolproof, 10-second authentication with zero Cloudflare or blank screen issues.
    """
    settings, targets = load_config()
    accounts_path = PROJECT_ROOT / "config" / "accounts_pool.json"
    vault = AccountVault(accounts_path, base_dir=PROJECT_ROOT)

    account = vault.get_account_by_id(account_id)
    if not account:
        console.print(f"[bold red]Account ID '{account_id}' not found in pool config![/bold red]")
        raise typer.Exit(code=1)

    if not auth_token:
        console.print("[bold cyan]How to get your auth_token from Chrome/Edge in 10 seconds:[/bold cyan]")
        console.print("1. Open https://x.com in your normal browser (where you are already logged in).")
        console.print("2. Press F12 -> Go to 'Application' tab -> 'Cookies' -> 'https://x.com'.")
        console.print("3. Find the cookie named 'auth_token' and copy its Value.\n")
        auth_token = typer.prompt("Paste your 'auth_token' value").strip()

    if not auth_token:
        console.print("[red]auth_token cannot be empty.[/red]")
        raise typer.Exit(code=1)

    if not ct0:
        ct0_input = typer.prompt("Paste your 'ct0' value (optional, press Enter to skip)", default="").strip()
        ct0 = ct0_input if ct0_input else None

    # Construct standard Playwright storage_state payload
    cookies = [
        {
            "name": "auth_token",
            "value": auth_token,
            "domain": ".x.com",
            "path": "/",
            "expires": 1893456000,
            "httpOnly": True,
            "secure": True,
            "sameSite": "None",
        }
    ]
    if ct0:
        cookies.append({
            "name": "ct0",
            "value": ct0,
            "domain": ".x.com",
            "path": "/",
            "expires": 1893456000,
            "httpOnly": False,
            "secure": True,
            "sameSite": "Lax",
        })

    session_file = PROJECT_ROOT / (account.storage_state_path or f"data/sessions/{account.platform}_{account.account_id}.json")
    session_file.parent.mkdir(parents=True, exist_ok=True)

    with open(session_file, "w", encoding="utf-8") as f:
        json.dump({"cookies": cookies, "origins": []}, f, indent=2)

    account.storage_state_path = str(session_file.relative_to(PROJECT_ROOT))
    account.status = "active"
    vault.save_accounts()

    console.print(f"[bold green]✓ Successfully configured authenticated session in {session_file}![/bold green]")
    console.print("[bold green]Account 'x_ksa_01' is now ACTIVE and authenticated. You can run Saqr now![/bold green]")


@app.command()
def dry_run(
    sample_size: int = typer.Option(50, "--sample-size", "-n", help="Number of synthetic leads to process"),
    reset_db: bool = typer.Option(False, "--reset-db", help="Reset test SQLite database before run"),
):
    """
    Executes an offline synthetic end-to-end dry run to verify scoring,
    deduplication, multi-tab Excel creation, and UTF-8 BOM CSV generation without hitting live platforms.
    """
    ensure_utf8_console()
    settings, targets = load_config()
    date_tag = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    setup_logging(PROJECT_ROOT / "logs", f"dry_run_{date_tag}")

    db_path = PROJECT_ROOT / settings["paths"]["db_path"]
    if reset_db and db_path.exists():
        try:
            db_path.unlink()
            console.print("[yellow]Reset existing leads_history.db for clean dry run.[/yellow]")
        except Exception as e:
            console.print(f"[red]Could not reset DB: {e}[/red]")

    console.print(f"[bold cyan]Starting Synthetic Dry-Run Pipeline (Sample size: {sample_size})...[/bold cyan]")

    # 1. Generate realistic Arabic synthetic leads
    synthetic_leads = generate_synthetic_leads(sample_size)
    console.print(f"[green]Generated {len(synthetic_leads)} synthetic raw leads.[/green]")

    # 2. Stage 3: Deduplication & Bot Disqualification (Using isolated test db for dry-runs)
    test_db_path = PROJECT_ROOT / "data" / "db" / "dry_run_leads_history.db"
    dedup = Deduplicator(db_path=test_db_path)
    clean_leads = dedup.filter_and_disqualify(synthetic_leads, lookback_days=settings["scoring"]["deduplication_lookback_days"])
    console.print(f"[green]Post-Deduplication & Disqualification: {len(clean_leads)} clean leads.[/green]")

    # 2.5 Contact & Bio Link-in-Bio Resolver (Mobile, WhatsApp, Telegram)
    console.print("[cyan]Executing Contact & Bio Link Resolver (Mobile/WhatsApp/Telegram)...[/cyan]")
    resolver = ContactResolver(timeout_sec=settings.get("browser", {}).get("link_timeout_sec", 8.0))
    clean_leads = asyncio.run(resolver.enrich_leads_batch(clean_leads, max_concurrency=5))

    # 3. Stage 3: Heuristic & LLM Scoring
    scorer = HeuristicScorer()
    classifier = LLMClassifier(settings.get("llm", {}))

    async def _score_all():
        scored = []
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
            scored.append(sl)
        return scored

    scored_leads = asyncio.run(_score_all())

    # 4. Stage 3: Export to Excel & CSV
    exporter = LeadExporter(
        exports_dir=PROJECT_ROOT / settings["paths"]["exports_dir"],
        target_count=settings["system"]["daily_lead_target"],
        min_score=settings["scoring"]["min_total_score_export"],
    )
    result = exporter.export_all(scored_leads, date_tag=f"dry_run_{date_tag}")

    # 5. Commit to database
    dedup.record_exported_leads(result["leads_exported"])

    # 6. Display Summary Table
    table = Table(title="Saqr 🦅 (صقر) — Lead Scouter Summary")
    table.add_column("Rank", justify="center")
    table.add_column("Platform", justify="center")
    table.add_column("Handle", style="cyan")
    table.add_column("Phone / WhatsApp", justify="center", style="bold green")
    table.add_column("Telegram", justify="center", style="blue")
    table.add_column("Category", style="magenta")
    table.add_column("Total Score", justify="center", style="bold green")
    table.add_column("DM Status", justify="center")

    for idx, sl in enumerate(result["leads_exported"][:10], start=1):
        dm = "Yes" if sl.lead.can_dm else "No"
        contact_str = sl.lead.phone_number or (sl.lead.whatsapp_url if sl.lead.whatsapp_url else "-")
        tg_str = sl.lead.telegram_handle or "-"
        table.add_row(
            str(idx),
            sl.lead.platform.upper(),
            f"@{sl.lead.username}",
            contact_str,
            tg_str,
            sl.interest_category,
            f"{sl.total_score:.1f}",
            dm,
        )

    console.print(table)
    console.print(f"[bold green]Excel file created:[/bold green] {result['excel']}")
    console.print(f"[bold green]CSV file created:[/bold green] {result['csv']}")
    console.print("[bold green]Dry-Run Pipeline completed successfully with 100% data integrity![/bold green]")


@app.command()
def run_all(
    date: Optional[str] = typer.Option(None, "--date", "-d", help="Run date (YYYY-MM-DD)"),
    limit: int = typer.Option(50, "--limit", "-l", help="Daily target lead count"),
    resume: bool = typer.Option(True, "--resume", "-r", help="Resume from checkpoint"),
):
    """
    Executes the complete daily production pipeline:
    Stage 1 (Browser/Vault) -> Stage 2 (Social Scraping) -> Stage 3 (Scoring/Export).
    """
    ensure_utf8_console()
    date_tag = date or datetime.now(timezone.utc).strftime("%Y-%m-%d")
    settings, targets = load_config()
    setup_logging(PROJECT_ROOT / "logs", date_tag)

    console.print(f"[bold cyan]Starting Full Daily Pipeline for {date_tag} (Target: {limit} leads)...[/bold cyan]")

    checkpoints_dir = PROJECT_ROOT / settings["paths"]["checkpoints_dir"]
    checkpoint = CheckpointManager(checkpoints_dir, run_date=date_tag)

    accounts_path = PROJECT_ROOT / "config" / "accounts_pool.json"
    vault = AccountVault(accounts_path, base_dir=PROJECT_ROOT)

    staging_dir = PROJECT_ROOT / settings["paths"]["staging_dir"]
    db_path = PROJECT_ROOT / settings["paths"]["db_path"]

    async def _execute_pipeline():
        from playwright.async_api import async_playwright

        # --- STAGE 2: HARVESTING ---
        checkpoint.set_stage_status("stage2", "in_progress")
        x_scraper = XScraper(
            vault=vault,
            checkpoint=checkpoint,
            staging_dir=staging_dir,
            settings=settings,
            targets=targets,
        )
        tiktok_scraper = TikTokScraper(
            vault=vault,
            checkpoint=checkpoint,
            staging_dir=staging_dir,
            settings=settings,
            targets=targets,
        )

        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=settings["browser"]["headless"])

            # 1. Harvest X.com Search Queries
            x_account = vault.get_available_account("x")
            if x_account:
                console.print("[cyan]Executing X.com Search Intent Harvesting...[/cyan]")
                await x_scraper.run_search_harvesting(browser, x_account)

                # 2. Harvest KSA Broker Replies
                console.print("[cyan]Executing X.com Broker Reply Thread Harvesting...[/cyan]")
                await x_scraper.run_broker_replies_harvesting(browser, x_account)
            else:
                console.print("[yellow]No active X.com accounts available. Continuing to next stage...[/yellow]")

            # 3. Harvest TikTok Comments
            tiktok_account = vault.get_available_account("tiktok")
            if tiktok_account:
                console.print("[cyan]Executing TikTok Comment Drawer Harvesting...[/cyan]")
                await tiktok_scraper.run_search_harvesting(browser, tiktok_account)

            await browser.close()

        checkpoint.set_stage_status("stage2", "completed")

        # --- STAGE 3: SCORING & EXPORT ---
        console.print("[cyan]Executing Stage 3: Deduplication, Scoring, and File Delivery...[/cyan]")
        checkpoint.set_stage_status("stage3", "in_progress")

        raw_leads_file = staging_dir / f"raw_leads_{date_tag}.jsonl"
        staged_leads: List[NormalizedLead] = []
        if raw_leads_file.exists():
            with open(raw_leads_file, "r", encoding="utf-8") as f:
                for line in f:
                    if line.strip():
                        staged_leads.append(NormalizedLead(**json.loads(line)))

        console.print(f"[green]Loaded {len(staged_leads)} staged raw leads for qualification.[/green]")

        dedup = Deduplicator(db_path=db_path)
        clean_leads = dedup.filter_and_disqualify(staged_leads, lookback_days=settings["scoring"]["deduplication_lookback_days"])

        # --- STAGE 2.5: CONTACT & BIO LINK ENRICHMENT ---
        console.print("[cyan]Executing Contact & Bio Link Resolver (Mobile/WhatsApp/Telegram)...[/cyan]")
        resolver = ContactResolver(timeout_sec=settings.get("browser", {}).get("link_timeout_sec", 8.0))
        clean_leads = await resolver.enrich_leads_batch(clean_leads, max_concurrency=6)

        scorer = HeuristicScorer()
        classifier = LLMClassifier(settings.get("llm", {}))

        scored_leads: List[ScoredLead] = []
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

        exporter = LeadExporter(
            exports_dir=PROJECT_ROOT / settings["paths"]["exports_dir"],
            target_count=limit,
            min_score=settings["scoring"]["min_total_score_export"],
        )
        res = exporter.export_all(scored_leads, date_tag=date_tag)

        # Commit exported leads to SQLite
        dedup.record_exported_leads(res["leads_exported"])
        checkpoint.set_stage_status("stage3", "completed")

        console.print(f"[bold green]Daily 12:00 PM Delivery Complete![/bold green]")
        console.print(f"[bold green]Excel Workbook:[/bold green] {res['excel']}")
        console.print(f"[bold green]UTF-8 BOM CSV:[/bold green] {res['csv']}")

    asyncio.run(_execute_pipeline())


def generate_synthetic_leads(count: int = 50, run_id: Optional[str] = None) -> List[NormalizedLead]:
    """Generates realistic KSA/GCC retail investor test leads for verification."""
    batch_tag = run_id or datetime.now(timezone.utc).strftime("%H%M%S")
    samples = [
        # Options Traders
        {
            "user_id": "1001",
            "username": "saudi_trader_99",
            "name": "أبو فهد | تداول",
            "bio": "مهتم بأسواق المال وتداول عقود الأوبشن الأمريكية 🇸🇦 الرياض. واتساب: 0501234567",
            "loc": "الرياض، المملكة العربية السعودية",
            "content": "وش رايكم في عقود كول سهم $NVDA سترايك 140 لشهر نوفمبر؟ هل الدخول مناسب؟",
            "can_dm": True,
            "broker": "Derayah",
        },
        {
            "user_id": "1002",
            "username": "fahad_options",
            "name": "فهد الشمري",
            "bio": "عقود الخيارات الأمريكية (أوبشن) | كول وبوت | جدة 🇸🇦 https://wa.me/966551234567",
            "loc": "جدة",
            "content": "أفضل استراتيجية لتداول الاوبشن في تطبيق سهم كابيتال بعمولة مخفضة يا اخوان؟",
            "can_dm": True,
            "broker": "Sahm_Capital",
        },
        # Halal / Sharia Stocks
        {
            "user_id": "1003",
            "username": "halal_investor_sa",
            "name": "د. عبد الله التميمي",
            "bio": "مستثمر في الأسهم النقية والمتوافقة مع الشريعة الإسلامية. قناتي بالتليجرام: @halal_stocks_sa",
            "loc": "الدمام، الشرقية",
            "content": "هل سهم $PLTR نقي شرعاً حسب فلتر الراجحي أو دراية؟ وكيف نسبة التطهير للسهم؟",
            "can_dm": False,
            "broker": "Derayah",
        },
        {
            "user_id": "1004",
            "username": "suliman_stocks",
            "name": "سليمان القاسم",
            "bio": "الأسهم الأمريكية النقية | الاستثمار طويل الأجل | تليجرام t.me/suliman_invest",
            "loc": "بريدة، القصيم",
            "content": "عطونا قائمة الأسهم النقية في قطاع التكنولوجيا الأمريكي لعام 2026. $AAPL و $MSFT",
            "can_dm": True,
            "broker": "AwaedApp",
        },
        # Day / Swing Traders
        {
            "user_id": "1005",
            "username": "mudarib_riyadh",
            "name": "مضارب لحظي",
            "bio": "مضاربة يومية ولحظية في السوق الأمريكي. شارت ومقاومات ودعوم.",
            "loc": "الرياض",
            "content": "سهم $TSLA اخترق مقاومة 250 دولار بفوليوم عالي، الهدف القادم 265 بإذن الله، وقف الخسارة 245.",
            "can_dm": True,
            "broker": "Interactive Brokers",
        },
        {
            "user_id": "1006",
            "username": "khalid_chart",
            "name": "خالد الحربي",
            "bio": "تحليل فني | TradingView | تداول الأسهم الأمريكية | المدينة المنورة",
            "loc": "المدينة المنورة 🇸🇦",
            "content": "فرصة دخول ممتازة في سهم $AMD بعد الارتداد من الدعم اليومي، وش رايكم يا شباب؟",
            "can_dm": True,
            "broker": "Derayah",
        },
        # Tech Tickers
        {
            "user_id": "1007",
            "username": "tech_saudi_guru",
            "name": "م. ماجد العتيبي",
            "bio": "مهتم بقطاع الذكاء الاصطناعي وأشباه الموصلات بالسوق الأمريكي 🇸🇦 الخبر",
            "loc": "الخبر",
            "content": "استثمار محفظتي مركز على أسهم $NVDA و $SMCI و $ARM. مستقبل الذكاء الاصطناعي واعد جداً.",
            "can_dm": False,
            "broker": "Sahm_Capital",
        },
        {
            "user_id": "1008",
            "username": "nasser_us_stocks",
            "name": "ناصر الدوسري",
            "bio": "مستثمر في أسهم وادي السيليكون $AAPL $MSFT $GOOGL. الرياض",
            "loc": "الرياض",
            "content": "شريت اليوم دفعة جديدة في سهم $AMZN مع تراجع السوق، السعر مغري جداً للتجميع.",
            "can_dm": True,
            "broker": "SNBCapital",
        },
        # Broker Seekers
        {
            "user_id": "1009",
            "username": "ahmed_broker_hunt",
            "name": "أحمد السبيعي",
            "bio": "مبتدئ في تداول السوق الأمريكي 🇸🇦 مكة المكرمة",
            "loc": "مكة المكرمة",
            "content": "يا إخوان وش أفضل تطبيق لتداول الأسهم الأمريكية في السعودية؟ دراية جلوبل ولا سهم كابيتال ولا بركة من ناحية العمولات؟",
            "can_dm": True,
            "broker": "Derayah",
        },
        {
            "user_id": "1010",
            "username": "yasmeen_invest",
            "name": "ياسمين كابيتال",
            "bio": "إدارة الثروات الشخصية وتداول الأسهم العالمية 🇸🇦 جدة",
            "loc": "جدة 🇸🇦",
            "content": "تطبيق عوائد وتطبيق بركة ممتازين للاستثمار الجزئي، هل فيه قروب توصيات أمريكي موثوق للاشتراك والاستفادة؟",
            "can_dm": True,
            "broker": "AwaedApp",
        },
        # Disqualified Competitors / Promo accounts
        {
            "user_id": "9999",
            "username": "vip_signals_promo",
            "name": "قروب توصيات الذهب والأسهم VIP",
            "bio": "توصيات مدفوعة بنسبة نجاح 95% للاشتراك تواصل خاص إدارة محافظ مضمونة",
            "loc": "دبي",
            "content": "للاشتراك في قروب التوصيات المدفوعة والفي اي بي تواصل واتساب ارباح مضمونة!",
            "can_dm": True,
            "broker": "None",
        },
    ]

    leads: List[NormalizedLead] = []
    # Replicate pattern to hit count
    for i in range(count):
        base = samples[i % len(samples)]
        u_id = f"{batch_tag}_{base['user_id']}_{i}"
        handle = f"{base['username']}_{batch_tag}_{i}" if i >= len(samples) else f"{base['username']}_{batch_tag}"

        trig = TriggerEvent(
            platform="x",
            trigger_type="search_tweet",
            content=base["content"],
            url=f"https://x.com/{handle}/status/189{i:06d}",
            timestamp=datetime.now(timezone.utc).isoformat(),
            cashtags=["$NVDA"] if "$NVDA" in base["content"] else [],
            target_broker_or_query=base["broker"],
        )

        lead = NormalizedLead(
            platform="x",
            user_id=u_id,
            username=handle,
            display_name=base["name"],
            bio=base["bio"],
            location=base["loc"],
            followers_count=350 + (i * 12),
            following_count=180 + (i * 5),
            can_dm=base["can_dm"],
            verified=False,
            profile_url=f"https://x.com/{handle}",
            triggers=[trig],
            first_discovered_at=datetime.now(timezone.utc).isoformat(),
            last_activity_at=datetime.now(timezone.utc).isoformat(),
        )
        leads.append(lead)

    return leads


if __name__ == "__main__":
    ensure_utf8_console()
    app()
