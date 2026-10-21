"""
Playwright Async Stealth Context & Network Route Optimization
Provides ar-SA / Asia/Riyadh emulation, anti-bot evasions, asset blocking, and humanized jitter.
"""

from __future__ import annotations

import asyncio
import logging
import random
from typing import Any, Dict, List, Optional
from playwright.async_api import Browser, BrowserContext, Page, Route

logger = logging.getLogger(__name__)

STEALTH_SCRIPTS = """
// 1. Hide navigator.webdriver
Object.defineProperty(navigator, 'webdriver', {
    get: () => undefined,
});

// 2. Mock Chrome runtime
window.chrome = {
    runtime: {},
    loadTimes: function() {},
    csi: function() {},
    app: {}
};

// 3. Emulate navigator.languages & plugins
Object.defineProperty(navigator, 'languages', {
    get: () => ['ar-SA', 'ar', 'en-US', 'en'],
});

Object.defineProperty(navigator, 'plugins', {
    get: () => [1, 2, 3, 4, 5],
});

// 4. WebGL vendor masking
const getParameter = WebGLRenderingContext.prototype.getParameter;
WebGLRenderingContext.prototype.getParameter = function(parameter) {
    // UNMASKED_VENDOR_WEBGL
    if (parameter === 37445) {
        return 'Intel Inc.';
    }
    // UNMASKED_RENDERER_WEBGL
    if (parameter === 37446) {
        return 'Intel Iris Pro OpenGL Engine';
    }
    return getParameter.apply(this, arguments);
};
"""

BLOCKED_RESOURCE_TYPES = {"image", "media", "font", "stylesheet"}
BLOCKED_EXTENSIONS = [".mp4", ".m3u8", ".webm", ".woff", ".woff2", ".ttf", ".otf"]


async def route_interceptor(route: Route) -> None:
    """
    Aborts heavy media, tracking scripts, and fonts while allowing
    documents, scripts, and XHR/Fetch GraphQL calls.
    """
    request = route.request
    resource_type = request.resource_type
    url_lower = request.url.lower()

    # Block heavy resource types
    if resource_type in BLOCKED_RESOURCE_TYPES:
        await route.abort()
        return

    # Block video streams and fonts by extension
    if any(url_lower.endswith(ext) or ext in url_lower for ext in BLOCKED_EXTENSIONS):
        await route.abort()
        return

    # Allow everything else (HTML, JS, Fetch, XHR)
    await route.continue_()


async def create_stealth_context(
    browser: Browser,
    storage_state_path: Optional[str] = None,
    proxy_url: Optional[str] = None,
    user_agent: Optional[str] = None,
    viewport: Optional[Dict[str, int]] = None,
    locale: str = "ar-SA",
    timezone_id: str = "Asia/Riyadh",
) -> BrowserContext:
    """
    Instantiates a customized stealth BrowserContext configured for KSA/GCC localization.
    """
    context_options: Dict[str, Any] = {
        "locale": locale,
        "timezone_id": timezone_id,
        "geolocation": {"latitude": 24.7136, "longitude": 46.6753, "accuracy": 100},
        "permissions": ["geolocation"],
        "user_agent": user_agent
        or (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
        ),
        "viewport": viewport or {"width": 1440, "height": 900},
        "bypass_csp": True,
        "ignore_https_errors": True,
    }

    if storage_state_path:
        context_options["storage_state"] = storage_state_path

    if proxy_url:
        context_options["proxy"] = {"server": proxy_url}

    context = await browser.new_context(**context_options)

    # Inject evasions prior to document scripts loading
    await context.add_init_script(STEALTH_SCRIPTS)

    # Attach network route filter to new pages
    context.on("page", lambda p: asyncio.create_task(p.route("**/*", route_interceptor)))

    return context


async def human_scroll(
    page: Page,
    iterations: int = 5,
    min_pause: float = 3.5,
    max_pause: float = 8.2,
    upward_chance: float = 0.15,
) -> None:
    """
    Simulates human reading behavior with randomized downward scrolls,
    intermittent upward micro-adjustments, and deliberate reading pauses.
    """
    for i in range(iterations):
        scroll_distance = random.randint(450, 850)

        # 15% probability of upward scroll to simulate reading previous item
        if random.random() < upward_chance:
            upward_pixels = random.randint(-200, -100)
            await page.evaluate(f"window.scrollBy({{top: {upward_pixels}, behavior: 'smooth'}})")
            await asyncio.sleep(random.uniform(1.0, 2.2))

        # Downward scroll
        await page.evaluate(f"window.scrollBy({{top: {scroll_distance}, behavior: 'smooth'}})")

        # Human reading pause
        pause_duration = random.uniform(min_pause, max_pause)
        logger.debug(f"Human scroll iteration {i+1}/{iterations} — pausing for {pause_duration:.2f}s")
        await asyncio.sleep(pause_duration)
