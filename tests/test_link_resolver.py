import pytest
import httpx
from unittest.mock import AsyncMock, patch

from src.stage2_scrapers.models import NormalizedLead, TriggerEvent
from src.stage2_scrapers.link_resolver import (
    ContactResolver,
    clean_phone_number,
)


def test_clean_phone_number():
    assert clean_phone_number("0501234567") == "+966501234567"
    assert clean_phone_number("+966 50 123 4567") == "+966501234567"
    assert clean_phone_number("00966501234567") == "+966501234567"
    assert clean_phone_number("966501234567") == "+966501234567"
    assert clean_phone_number("+971 50 123 4567") == "+971501234567"
    assert clean_phone_number("+965 50123456") == "+96550123456"
    assert clean_phone_number("12345") is None
    assert clean_phone_number("") is None


def test_extract_from_text_direct_saudi_phone():
    resolver = ContactResolver()
    text = "متداول أوبشن في السوق الأمريكي بالرياض. للتواصل واتساب: 0551234567 أهلاً بكم"
    res = resolver.extract_from_text(text)
    assert res["phone_number"] == "+966551234567"
    assert res["whatsapp_url"] == "https://wa.me/966551234567"


def test_extract_from_text_whatsapp_url():
    resolver = ContactResolver()
    text = "استشارات تداول الأسهم الأمريكية https://wa.me/966541234567"
    res = resolver.extract_from_text(text)
    assert res["phone_number"] == "+966541234567"
    assert res["whatsapp_url"] == "https://wa.me/966541234567"


def test_extract_from_text_telegram():
    resolver = ContactResolver()
    text = "محلل شارت وفني | قناتي بالتليجرام: @saudi_options_club"
    res = resolver.extract_from_text(text)
    assert res["telegram_handle"] == "@saudi_options_club"

    text2 = "متابعة السوق اليومي عبر https://t.me/us_stocks_ksa"
    res2 = resolver.extract_from_text(text2)
    assert res2["telegram_handle"] == "@us_stocks_ksa"


def test_extract_urls():
    resolver = ContactResolver()
    text = "رابط حسابي https://linktr.ee/fahad_options وموقعي https://fahad.com وتابعني https://x.com/fahad"
    urls = resolver.extract_urls(text)
    assert "https://linktr.ee/fahad_options" in urls
    assert "https://fahad.com" in urls
    assert not any("x.com" in u for u in urls)


@pytest.mark.asyncio
async def test_resolve_external_url_linktree_mock():
    resolver = ContactResolver()
    mock_html = """
    <html>
      <body>
        <h1>فهد الشمري - تداول الأوبشن</h1>
        <a href="https://wa.me/966509998877">تواصل واتساب مباشر</a>
        <a href="https://t.me/fahad_signals">قناة التوصيات</a>
      </body>
    </html>
    """

    mock_response = AsyncMock()
    mock_response.status_code = 200
    mock_response.text = mock_html

    mock_client = AsyncMock()
    mock_client.get.return_value = mock_response

    res = await resolver.resolve_external_url("https://linktr.ee/fahad_options", mock_client)
    assert res["phone_number"] == "+966509998877"
    assert res["whatsapp_url"] == "https://wa.me/966509998877"
    assert res["telegram_handle"] == "@fahad_signals"


@pytest.mark.asyncio
async def test_enrich_lead_integration():
    resolver = ContactResolver()
    lead = NormalizedLead(
        platform="x",
        user_id="999",
        username="options_king",
        display_name="ملك الأوبشن",
        bio="متداول عقود أوبشن 🇸🇦 واتساب: 0503332211",
        location="الرياض",
    )

    async with httpx.AsyncClient() as client:
        enriched = await resolver.enrich_lead(lead, client)

    assert enriched.phone_number == "+966503332211"
    assert enriched.whatsapp_url == "https://wa.me/966503332211"
