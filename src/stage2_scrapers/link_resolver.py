"""
Contact & Bio Link Resolver for Saqr
Extracts mobile numbers, WhatsApp direct links, and Telegram handles from:
1. Direct bio and trigger text (Arabic & English patterns)
2. External aggregator landing pages (Linktree, Carrd, Taplink, Beacons, Bio.site)
3. Personal websites and landing pages
"""

from __future__ import annotations

import asyncio
import logging
import re
from typing import Any, Dict, List, Optional, Set, Tuple
from urllib.parse import unquote, urlparse

import httpx

from src.stage2_scrapers.models import NormalizedLead

logger = logging.getLogger(__name__)

# --- Regex Patterns ---

# Saudi mobile regex: supports +9665XXXXXXXX, 009665XXXXXXXX, 9665XXXXXXXX, 05XXXXXXXX
# Handles optional spaces, dashes, or brackets between digits
SAUDI_PHONE_REGEX = re.compile(
    r"(?:(?:\+?966|00966|966)[\s\-\.]?|0)?(5[0-9]{1}[\s\-\.]?[0-9]{3}[\s\-\.]?[0-9]{4})\b"
)

# GCC mobile regexes (UAE, Kuwait, Qatar, Bahrain, Oman)
GCC_PHONE_REGEX = re.compile(
    r"(?:(?:\+?971|00971)[\s\-\.]?5[0-9]{8}\b)"  # UAE
    r"|(?:(?:\+?965|00965)[\s\-\.]?[569][0-9]{7}\b)"  # Kuwait
    r"|(?:(?:\+?974|00974)[\s\-\.]?[3567][0-9]{7}\b)"  # Qatar
    r"|(?:(?:\+?973|00973)[\s\-\.]?[36][0-9]{7}\b)"  # Bahrain
    r"|(?:(?:\+?968|00968)[\s\-\.]?[79][0-9]{7}\b)"  # Oman
)

# WhatsApp link patterns
WHATSAPP_LINK_REGEX = re.compile(
    r"(?:https?:\/\/)?(?:www\.)?(?:api\.whatsapp\.com\/send\/?\?(?:phone=)?|wa\.me\/|whatsapp:\/\/send\?phone=)(\+?[0-9]{9,15})",
    re.IGNORECASE,
)

# Telegram link and handle patterns
TELEGRAM_LINK_REGEX = re.compile(
    r"(?:https?:\/\/)?(?:www\.)?(?:t\.me|telegram\.me)\/([A-Za-z0-9_]{4,})",
    re.IGNORECASE,
)
TELEGRAM_TEXT_REGEX = re.compile(
    r"(?:تيليجرام|تليجرام|قناة\s*التليجرام|قناة\s*التيليجرام|قناتي|قروب|تليقرام|تلغرام)[\s\:\-]*@?([A-Za-z0-9_]{4,})",
    re.IGNORECASE,
)

# URL detection regex
URL_REGEX = re.compile(
    r"https?:\/\/(?:www\.)?[-a-zA-Z0-9@:%._\+~#=]{1,256}\.[a-zA-Z0-9()]{1,6}\b(?:[-a-zA-Z0-9()@:%_\+.~#?&//=]*)"
)

INVALID_TELEGRAM_HANDLES = {
    "http", "https", "share", "joinchat", "channel", "group", "bot", "contact", "telegram", "channel_id"
}


def clean_phone_number(raw: str) -> Optional[str]:
    """
    Standardize a phone number to international E.164 format (+9665XXXXXXXX).
    """
    if not raw:
        return None
    # Strip non-digits except initial +
    digits = re.sub(r"[^\d]", "", raw)
    if not digits:
        return None

    # Handle international prefixes
    if digits.startswith("00"):
        digits = digits[2:]

    # Handle Saudi numbers
    if digits.startswith("05") and len(digits) == 10:
        digits = "966" + digits[1:]  # 9665...
    elif digits.startswith("5") and len(digits) == 9:
        digits = "966" + digits

    if digits.startswith("9665") and len(digits) == 12:
        return f"+{digits}"

    # Handle GCC numbers
    for code, length in [("971", 12), ("965", 11), ("974", 11), ("973", 11), ("968", 11)]:
        if digits.startswith(code) and len(digits) == length:
            return f"+{digits}"

    if len(digits) >= 9:
        return f"+{digits}"

    return None


class ContactResolver:
    """
    Resolves contact info from lead bios, tweets, and external link aggregator pages.
    """

    def __init__(self, timeout_sec: float = 8.0):
        self.timeout_sec = timeout_sec
        self.headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/126.0.0.0 Safari/537.36"
            ),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "ar,en-US;q=0.9,en;q=0.8",
        }

    def extract_from_text(self, text: str) -> Dict[str, Optional[str]]:
        """
        Extract direct phone numbers, WhatsApp links, and Telegram handles from raw text.
        """
        results: Dict[str, Optional[str]] = {
            "phone_number": None,
            "whatsapp_url": None,
            "telegram_handle": None,
            "source": None,
        }
        if not text:
            return results

        # 1. WhatsApp link regex
        wa_match = WHATSAPP_LINK_REGEX.search(text)
        if wa_match:
            raw_num = wa_match.group(1)
            phone = clean_phone_number(raw_num)
            results["whatsapp_url"] = f"https://wa.me/{phone.replace('+', '')}" if phone else f"https://wa.me/{raw_num}"
            if phone:
                results["phone_number"] = phone
            results["source"] = "text_whatsapp_link"

        # 2. Saudi phone regex (if no phone found yet)
        if not results["phone_number"]:
            for match in SAUDI_PHONE_REGEX.finditer(text):
                full_match = match.group(0)
                cleaned = clean_phone_number(full_match)
                if cleaned:
                    results["phone_number"] = cleaned
                    results["whatsapp_url"] = f"https://wa.me/{cleaned.replace('+', '')}"
                    results["source"] = "text_saudi_phone"
                    break

        # 3. GCC phone regex
        if not results["phone_number"]:
            for match in GCC_PHONE_REGEX.finditer(text):
                full_match = match.group(0)
                cleaned = clean_phone_number(full_match)
                if cleaned:
                    results["phone_number"] = cleaned
                    results["whatsapp_url"] = f"https://wa.me/{cleaned.replace('+', '')}"
                    results["source"] = "text_gcc_phone"
                    break

        # 4. Telegram links
        tg_match = TELEGRAM_LINK_REGEX.search(text)
        if tg_match:
            handle = tg_match.group(1).strip()
            if handle.lower() not in INVALID_TELEGRAM_HANDLES:
                results["telegram_handle"] = f"@{handle}"
                if not results["source"]:
                    results["source"] = "text_telegram"

        # 5. Telegram Arabic text mentions
        if not results["telegram_handle"]:
            tg_text_match = TELEGRAM_TEXT_REGEX.search(text)
            if tg_text_match:
                handle = tg_text_match.group(1).strip()
                if handle.lower() not in INVALID_TELEGRAM_HANDLES:
                    results["telegram_handle"] = f"@{handle}"
                    if not results["source"]:
                        results["source"] = "text_telegram"

        return results

    def extract_urls(self, text: str) -> List[str]:
        """Extract valid external HTTP/HTTPS URLs from text."""
        if not text:
            return []
        matches = URL_REGEX.findall(text)
        cleaned = []
        for u in matches:
            u_clean = u.rstrip(".,;:)'\"")
            # Filter out internal social links
            parsed = urlparse(u_clean)
            domain = parsed.netloc.lower()
            if not any(soc in domain for soc in ["twitter.com", "x.com", "tiktok.com"]):
                cleaned.append(u_clean)
        return list(dict.fromkeys(cleaned))

    async def resolve_external_url(
        self, url: str, client: httpx.AsyncClient
    ) -> Dict[str, Optional[str]]:
        """
        Fetch HTML from an external link (Linktree, Carrd, website) and parse contact info.
        """
        results: Dict[str, Optional[str]] = {
            "phone_number": None,
            "whatsapp_url": None,
            "telegram_handle": None,
            "source": None,
        }

        try:
            logger.debug(f"Resolving bio URL: {url}")
            response = await client.get(url, headers=self.headers, timeout=self.timeout_sec, follow_redirects=True)
            if response.status_code != 200:
                return results

            html = response.text

            # 1. Look for href="https://wa.me/..." or href="whatsapp://..."
            wa_match = WHATSAPP_LINK_REGEX.search(html)
            if wa_match:
                raw_num = wa_match.group(1)
                phone = clean_phone_number(raw_num)
                results["whatsapp_url"] = f"https://wa.me/{phone.replace('+', '')}" if phone else f"https://wa.me/{raw_num}"
                if phone:
                    results["phone_number"] = phone
                results["source"] = f"link_page:{urlparse(url).netloc}"

            # 2. Look for tel:+966... links: href="tel:+966501234567"
            tel_matches = re.findall(r'href=[\'"]tel:([^\'"\s>]+)[\'"]', html, re.IGNORECASE)
            for raw_tel in tel_matches:
                cleaned_tel = clean_phone_number(raw_tel)
                if cleaned_tel:
                    results["phone_number"] = cleaned_tel
                    if not results["whatsapp_url"]:
                        results["whatsapp_url"] = f"https://wa.me/{cleaned_tel.replace('+', '')}"
                    results["source"] = f"link_page_tel:{urlparse(url).netloc}"
                    break

            # 3. Look for Telegram links
            tg_matches = TELEGRAM_LINK_REGEX.findall(html)
            for tg in tg_matches:
                if tg.lower() not in INVALID_TELEGRAM_HANDLES:
                    results["telegram_handle"] = f"@{tg}"
                    if not results["source"]:
                        results["source"] = f"link_page_telegram:{urlparse(url).netloc}"
                    break

            # 4. Text regex scan on the page content if phone still not found
            if not results["phone_number"]:
                text_results = self.extract_from_text(html)
                if text_results["phone_number"]:
                    results["phone_number"] = text_results["phone_number"]
                    results["whatsapp_url"] = text_results["whatsapp_url"]
                    results["source"] = f"link_page_text:{urlparse(url).netloc}"
                if not results["telegram_handle"] and text_results["telegram_handle"]:
                    results["telegram_handle"] = text_results["telegram_handle"]

        except Exception as e:
            logger.debug(f"Error resolving external URL {url}: {e}")

        return results

    async def enrich_lead(
        self, lead: NormalizedLead, client: httpx.AsyncClient
    ) -> NormalizedLead:
        """
        Enrich a single NormalizedLead with phone, WhatsApp, and Telegram info.
        """
        # Step 1: Scan direct bio text and trigger content
        combined_text = lead.get_combined_text()
        text_info = self.extract_from_text(combined_text)

        if text_info["phone_number"]:
            lead.phone_number = text_info["phone_number"]
        if text_info["whatsapp_url"]:
            lead.whatsapp_url = text_info["whatsapp_url"]
        if text_info["telegram_handle"]:
            lead.telegram_handle = text_info["telegram_handle"]
        if text_info["source"]:
            lead.contact_source = text_info["source"]

        # Step 2: If no phone number found yet, scan for external URLs in bio
        if not lead.phone_number:
            urls = self.extract_urls(lead.bio)
            for u in urls:
                page_info = await self.resolve_external_url(u, client)
                if page_info["phone_number"]:
                    lead.phone_number = page_info["phone_number"]
                    lead.whatsapp_url = page_info["whatsapp_url"]
                    lead.contact_source = page_info["source"]
                if not lead.telegram_handle and page_info["telegram_handle"]:
                    lead.telegram_handle = page_info["telegram_handle"]
                    if not lead.contact_source:
                        lead.contact_source = page_info["source"]

                # Stop if phone number found
                if lead.phone_number:
                    break

        return lead

    async def enrich_leads_batch(
        self, leads: List[NormalizedLead], max_concurrency: int = 5
    ) -> List[NormalizedLead]:
        """
        Concurrently enrich a batch of staged leads using an async worker pool.
        """
        logger.info(f"Beginning contact resolution & link enrichment for {len(leads)} leads...")
        semaphore = asyncio.Semaphore(max_concurrency)

        async with httpx.AsyncClient(timeout=self.timeout_sec, follow_redirects=True) as client:
            async def worker(lead: NormalizedLead) -> NormalizedLead:
                async with semaphore:
                    try:
                        return await self.enrich_lead(lead, client)
                    except Exception as e:
                        logger.debug(f"Error enriching lead @{lead.username}: {e}")
                        return lead

            tasks = [worker(l) for l in leads]
            enriched = await asyncio.gather(*tasks)

        # Summary logging
        with_phone = sum(1 for l in enriched if l.phone_number)
        with_wa = sum(1 for l in enriched if l.whatsapp_url)
        with_tg = sum(1 for l in enriched if l.telegram_handle)
        logger.info(
            f"Contact enrichment complete: {with_phone} phone numbers, {with_wa} WhatsApp links, {with_tg} Telegram handles."
        )

        return enriched
