"""
X.com (Twitter) Lead Scraper
Intercepts GraphQL payloads (SearchTimeline, TweetDetail, UserTweets)
to harvest high-intent Saudi/GCC retail investors from search queries and broker reply threads.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import urllib.parse
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Set
from playwright.async_api import Browser, Page, Response

from src.stage1_browser.account_vault import AccountVault, SocialAccount
from src.stage1_browser.checkpoint import CheckpointManager
from src.stage1_browser.stealth_context import create_stealth_context, human_scroll
from src.stage2_scrapers.models import NormalizedLead, TriggerEvent

logger = logging.getLogger(__name__)

CASHTAG_REGEX = re.compile(r"\$[A-Za-z]{1,6}\b")


class XScraper:
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
                logger.info(f"Loaded {len(self.discovered_leads)} previously staged leads")
            except Exception as e:
                logger.warning(f"Could not read staging file: {e}")

    def _persist_lead(self, lead: NormalizedLead) -> None:
        """Append or update lead in staging JSONL file."""
        key = f"{lead.platform}:{lead.user_id}"
        self.discovered_leads[key] = lead
        # Rewrite staging file with deduplicated leads
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

    def _extract_cashtags(self, text: str) -> List[str]:
        """Find all uppercase cashtags like $NVDA, $TSLA."""
        return list(set(CASHTAG_REGEX.findall(text.upper())))

    def parse_user_and_tweet_data(
        self, user_result: Dict[str, Any], tweet_data: Dict[str, Any], trigger_type: str, query_source: str
    ) -> Optional[NormalizedLead]:
        """
        Parses X GraphQL user and tweet structures into NormalizedLead and TriggerEvent.
        """
        try:
            # Handle user_results.result
            u_res = user_result.get("result", user_result)
            rest_id = u_res.get("rest_id", "")
            legacy_user = u_res.get("legacy", {})

            screen_name = legacy_user.get("screen_name") or u_res.get("screen_name")
            if not screen_name or not rest_id:
                return None

            name = legacy_user.get("name", screen_name)
            bio = legacy_user.get("description", "")
            location = legacy_user.get("location", "")
            followers_count = legacy_user.get("followers_count", 0)
            following_count = legacy_user.get("friends_count", 0)
            can_dm = legacy_user.get("can_dm")
            verified = legacy_user.get("verified", False) or u_res.get("is_blue_verified", False)

            # Tweet info
            legacy_tweet = tweet_data.get("legacy", tweet_data)
            tweet_id = tweet_data.get("rest_id") or legacy_tweet.get("id_str", "")
            tweet_text = legacy_tweet.get("full_text") or legacy_tweet.get("text", "")
            created_at = legacy_tweet.get("created_at", datetime.now(timezone.utc).isoformat())

            tweet_url = f"https://x.com/{screen_name}/status/{tweet_id}" if tweet_id else f"https://x.com/{screen_name}"
            cashtags = self._extract_cashtags(tweet_text)

            trigger = TriggerEvent(
                platform="x",
                trigger_type=trigger_type,
                content=tweet_text,
                url=tweet_url,
                timestamp=created_at,
                cashtags=cashtags,
                target_broker_or_query=query_source,
            )

            key = f"x:{rest_id}"
            if key in self.discovered_leads:
                existing = self.discovered_leads[key]
                # Avoid duplicate triggers
                if not any(t.url == trigger.url for t in existing.triggers):
                    existing.triggers.append(trigger)
                existing.last_activity_at = datetime.now(timezone.utc).isoformat()
                return existing

            lead = NormalizedLead(
                platform="x",
                user_id=rest_id,
                username=screen_name,
                display_name=name,
                bio=bio,
                location=location,
                followers_count=followers_count,
                following_count=following_count,
                can_dm=can_dm,
                verified=verified,
                profile_url=f"https://x.com/{screen_name}",
                triggers=[trigger],
                first_discovered_at=datetime.now(timezone.utc).isoformat(),
                last_activity_at=datetime.now(timezone.utc).isoformat(),
            )
            return lead
        except Exception as e:
            logger.debug(f"Error parsing user/tweet GraphQL item: {e}")
            return None

    def _parse_graphql_json(self, data: Dict[str, Any], trigger_type: str, query_source: str) -> List[NormalizedLead]:
        """
        Recursively extracts tweets and author profiles from arbitrary X GraphQL response payloads.
        """
        found_leads: List[NormalizedLead] = []

        def recurse(node: Any) -> None:
            if isinstance(node, dict):
                # Check for tweet result
                if "__typename" in node and node["__typename"] in {"Tweet", "TweetWithVisibilityResults"}:
                    tweet_result = node.get("tweet", node)
                    core = tweet_result.get("core", {})
                    user_res = core.get("user_results", {})
                    if user_res:
                        lead = self.parse_user_and_tweet_data(user_res, tweet_result, trigger_type, query_source)
                        if lead:
                            found_leads.append(lead)
                # Check legacy tweet + user_id_str
                elif "full_text" in node and "user_id_str" in node:
                    # Generic tweet object
                    pass

                for v in node.values():
                    recurse(v)
            elif isinstance(node, list):
                for item in node:
                    recurse(item)

        recurse(data)
        return found_leads

    async def _setup_interceptor(self, page: Page, trigger_type: str, query_source: str) -> None:
        """Attach network response handler for X GraphQL calls."""
        async def handle_response(response: Response) -> None:
            url = response.url
            if any(ep in url for ep in ["/SearchTimeline", "/TweetDetail", "/UserTweets", "/TweetResultByRestId"]):
                if response.status == 200:
                    try:
                        content_type = response.headers.get("content-type", "")
                        if "json" in content_type:
                            data = await response.json()
                            leads = self._parse_graphql_json(data, trigger_type=trigger_type, query_source=query_source)
                            for l in leads:
                                self._persist_lead(l)
                            logger.info(f"Intercepted {len(leads)} leads from {url.split('?')[0]}")
                    except Exception as e:
                        logger.debug(f"GraphQL interception error on {url}: {e}")
                elif response.status in (429, 403):
                    logger.warning(f"Encountered HTTP {response.status} from X.com on {url}")

        page.on("response", handle_response)

    async def run_search_harvesting(self, browser: Browser, account: SocialAccount) -> None:
        """
        Mode A: Iterate through target search queries using 'Latest' (f=live).
        """
        query_categories = self.targets.get("x_search_queries", {})
        all_queries: List[str] = []
        for cat_name, q_list in query_categories.items():
            for q in q_list:
                all_queries.append(q)

        logger.info(f"Beginning X Search harvesting across {len(all_queries)} queries")

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
            for query in all_queries:
                if self.checkpoint.is_x_query_completed(query):
                    logger.info(f"Skipping completed X query: {query}")
                    continue

                logger.info(f"Executing X search query: {query}")
                await self._setup_interceptor(page, trigger_type="search_tweet", query_source=query)

                encoded_query = urllib.parse.quote(query)
                search_url = f"https://x.com/search?q={encoded_query}&f=live"

                try:
                    res = await page.goto(search_url, wait_until="networkidle", timeout=30000)
                    if res and res.status in (429, 403):
                        account.trigger_circuit_breaker(res.status)
                        break

                    # Human scrolling to trigger GraphQL pagination
                    await human_scroll(page, iterations=3, min_pause=3.0, max_pause=6.0)
                    self.checkpoint.mark_x_query_completed(query)

                    # Account rotation check
                    account = self.vault.rotate_or_cooldown(account) or account
                except Exception as e:
                    logger.warning(f"Error navigating X search '{query}': {e}")
                    await asyncio.sleep(4.0)

        finally:
            await context.close()

    async def run_broker_replies_harvesting(self, browser: Browser, account: SocialAccount) -> None:
        """
        Mode B: Harvest replies and quote-tweets under posts from official KSA brokerages.
        """
        brokers = self.targets.get("x_seed_accounts", {}).get("ksa_brokers_and_platforms", [])
        logger.info(f"Beginning X broker replies harvesting across {len(brokers)} brokers")

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
            for b in brokers:
                handle = b["handle"]
                if self.checkpoint.is_x_broker_completed(handle):
                    logger.info(f"Skipping completed broker: @{handle}")
                    continue

                logger.info(f"Harvesting replies under broker @{handle}")
                await self._setup_interceptor(page, trigger_type="broker_reply", query_source=f"@{handle}")

                profile_url = f"https://x.com/{handle}/with_replies"
                try:
                    res = await page.goto(profile_url, wait_until="networkidle", timeout=30000)
                    if res and res.status in (429, 403):
                        account.trigger_circuit_breaker(res.status)
                        break

                    # Scroll to trigger UserTweets GraphQL
                    await human_scroll(page, iterations=4, min_pause=3.5, max_pause=7.0)
                    self.checkpoint.mark_x_broker_completed(handle)

                    account = self.vault.rotate_or_cooldown(account) or account
                except Exception as e:
                    logger.warning(f"Error navigating broker @{handle}: {e}")
                    await asyncio.sleep(4.0)
        finally:
            await context.close()
