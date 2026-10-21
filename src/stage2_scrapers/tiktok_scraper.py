"""
TikTok KSA Lead Scraper
Intercepts /api/comment/list/ and /api/comment/list/reply/ endpoints
to harvest retail investors asking about US stocks, options, and brokers in comment drawers.
"""

from __future__ import annotations

import asyncio
import json
import logging
import urllib.parse
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional
from playwright.async_api import Browser, Page, Response

from src.stage1_browser.account_vault import AccountVault, SocialAccount
from src.stage1_browser.checkpoint import CheckpointManager
from src.stage1_browser.stealth_context import create_stealth_context, human_scroll
from src.stage2_scrapers.models import NormalizedLead, TriggerEvent

logger = logging.getLogger(__name__)


class TikTokScraper:
    def __init__(
        self,
        vault: AccountVault,
        checkpoint: CheckpointManager,
        staging_dir: Path | str,
        settings: Dict[str, Any],
        targets: Dict[str, Any],
    ):
        self.vault = vault
        self.checkpoint = checkpoint
        self.staging_dir = Path(staging_dir)
        self.staging_dir.mkdir(parents=True, exist_ok=True)
        self.settings = settings
        self.targets = targets

        self.discovered_leads: Dict[str, NormalizedLead] = {}
        self._staging_file = (
            self.staging_dir / f"raw_leads_{self.checkpoint.run_date}.jsonl"
        )
        self._load_existing_staged_leads()

    def _load_existing_staged_leads(self) -> None:
        """Load already staged leads from today's JSONL file."""
        if self._staging_file.exists():
            try:
                with open(self._staging_file, "r", encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if line:
                            data = json.loads(line)
                            lead = NormalizedLead(**data)
                            key = f"{lead.platform}:{lead.user_id}"
                            self.discovered_leads[key] = lead
            except Exception as e:
                logger.warning(f"Could not read staging file: {e}")

    def _persist_lead(self, lead: NormalizedLead) -> None:
        """Append or update lead in staging JSONL file."""
        key = f"{lead.platform}:{lead.user_id}"
        self.discovered_leads[key] = lead
        try:
            temp_file = self._staging_file.with_suffix(".tmp")
            with open(temp_file, "w", encoding="utf-8") as f:
                for l in self.discovered_leads.values():
                    f.write(l.model_dump_json() + "\n")
            temp_file.replace(self._staging_file)
            self.checkpoint.state["total_raw_leads_staged"] = len(self.discovered_leads)
            self.checkpoint.add_processed_user(lead.user_id)
            self.checkpoint.save()
        except Exception as e:
            logger.error(f"Error persisting lead to {self._staging_file}: {e}")

    def _is_intent_comment(self, text: str) -> bool:
        """Filter for comments demonstrating US-stock, options, or broker questions."""
        keywords = self.targets.get("tiktok_ksa_finance_targets", {}).get(
            "comment_intent_keywords", []
        )
        text_lower = text.lower()
        return any(kw.lower() in text_lower for kw in keywords)

    def _parse_comment_item(self, item: Dict[str, Any], video_url: str, query: str) -> Optional[NormalizedLead]:
        """Convert a TikTok comment payload item into a NormalizedLead."""
        try:
            text = item.get("text", "")
            if not self._is_intent_comment(text):
                return None

            user_obj = item.get("user", {})
            user_id = str(user_obj.get("uid") or user_obj.get("id") or item.get("cid", ""))
            unique_id = user_obj.get("unique_id", "")
            nickname = user_obj.get("nickname", unique_id)
            bio = user_obj.get("signature", "")

            if not user_id or not unique_id:
                return None

            create_time = item.get("create_time", 0)
            timestamp_str = (
                datetime.fromtimestamp(create_time, timezone.utc).isoformat()
                if create_time
                else datetime.now(timezone.utc).isoformat()
            )

            trigger = TriggerEvent(
                platform="tiktok",
                trigger_type="tiktok_comment",
                content=text,
                url=video_url,
                timestamp=timestamp_str,
                cashtags=[],
                target_broker_or_query=query,
            )

            key = f"tiktok:{user_id}"
            if key in self.discovered_leads:
                existing = self.discovered_leads[key]
                if not any(t.content == trigger.content for t in existing.triggers):
                    existing.triggers.append(trigger)
                existing.last_activity_at = datetime.now(timezone.utc).isoformat()
                return existing

            lead = NormalizedLead(
                platform="tiktok",
                user_id=user_id,
                username=unique_id,
                display_name=nickname,
                bio=bio,
                location="KSA / GCC",
                followers_count=0,
                following_count=0,
                can_dm=None,
                verified=user_obj.get("custom_verify", "") != "",
                profile_url=f"https://www.tiktok.com/@{unique_id}",
                triggers=[trigger],
                first_discovered_at=datetime.now(timezone.utc).isoformat(),
                last_activity_at=datetime.now(timezone.utc).isoformat(),
            )
            return lead
        except Exception as e:
            logger.debug(f"Error parsing TikTok comment item: {e}")
            return None

    def _parse_comments_response(self, data: Dict[str, Any], video_url: str, query: str) -> List[NormalizedLead]:
        """Parse list of comments from /api/comment/list/ response."""
        found: List[NormalizedLead] = []
        comments = data.get("comments") or []
        for c in comments:
            lead = self._parse_comment_item(c, video_url=video_url, query=query)
            if lead:
                found.append(lead)
        return found

    async def _setup_interceptor(self, page: Page, video_url: str, query: str) -> None:
        """Attach TikTok comment interceptor."""
        async def handle_response(response: Response) -> None:
            url = response.url
            if "/api/comment/list" in url:
                if response.status == 200:
                    try:
                        content_type = response.headers.get("content-type", "")
                        if "json" in content_type:
                            data = await response.json()
                            leads = self._parse_comments_response(data, video_url=video_url, query=query)
                            for l in leads:
                                self._persist_lead(l)
                            logger.info(f"Intercepted {len(leads)} intent leads from TikTok comments")
                    except Exception as e:
                        logger.debug(f"TikTok comment interception error: {e}")

        page.on("response", handle_response)

    async def run_search_harvesting(self, browser: Browser, account: SocialAccount) -> None:
        """Search TikTok for KSA US-stock videos and extract intent comments."""
        queries = self.targets.get("tiktok_ksa_finance_targets", {}).get("search_queries", [])
        logger.info(f"Beginning TikTok video comment harvesting across {len(queries)} queries")

        storage_path = self.vault.resolve_storage_state(account)
        context = await create_stealth_context(
            browser=browser,
            storage_state_path=storage_path,
            proxy_url=account.proxy_url,
            user_agent=account.user_agent,
            viewport=account.viewport,
            locale=self.settings["browser"]["locale"],
            timezone_id=self.settings["browser"]["timezone_id"],
        )
        page = await context.new_page()

        try:
            for q in queries:
                if self.checkpoint.is_tiktok_query_completed(q):
                    continue

                logger.info(f"Searching TikTok for: {q}")
                encoded_q = urllib.parse.quote(q)
                search_url = f"https://www.tiktok.com/search?q={encoded_q}"

                try:
                    res = await page.goto(search_url, wait_until="networkidle", timeout=30000)
                    if res and res.status in (429, 403):
                        account.trigger_circuit_breaker(res.status)
                        break

                    await human_scroll(page, iterations=3, min_pause=3.0, max_pause=6.0)

                    # Extract top video links
                    video_links = await page.evaluate("""() => {
                        const links = Array.from(document.querySelectorAll('a[href*="/video/"]'));
                        return links.slice(0, 3).map(a => a.href);
                    }""")

                    for v_url in video_links:
                        logger.info(f"Opening TikTok video: {v_url}")
                        await self._setup_interceptor(page, video_url=v_url, query=q)
                        await page.goto(v_url, wait_until="networkidle", timeout=30000)

                        # Click comment drawer button to trigger /api/comment/list/
                        try:
                            comment_btn = page.locator(
                                '[data-e2e="comment-icon"], [data-e2e="browse-comment-icon"]'
                            ).first
                            if await comment_btn.count() > 0:
                                await comment_btn.click()
                                await asyncio.sleep(2.5)
                        except Exception:
                            pass

                        await human_scroll(page, iterations=4, min_pause=3.5, max_pause=7.0)

                    self.checkpoint.mark_tiktok_query_completed(q)
                    account = self.vault.rotate_or_cooldown(account) or account
                except Exception as e:
                    logger.warning(f"Error exploring TikTok query '{q}': {e}")
                    await asyncio.sleep(4.0)

        finally:
            await context.close()
