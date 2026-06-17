from __future__ import annotations

import json
import os
from contextlib import contextmanager
from typing import Any

import httpx
from playwright.sync_api import Page, sync_playwright

# A real browser carries a genuine TLS/JS fingerprint, so Cloudflare's edge challenge (the
# thing that 403s plain httpx against Reddit) solves itself on first page load and drops a
# cf_clearance cookie. After that, fetches issued from inside the page reuse that cookie and
# come back clean. This is the escape hatch for sources that block headless HTTP clients.
#
# The API here is intentionally synchronous: on Windows, psycopg's async mode forces the
# SelectorEventLoop while Playwright's async API needs the ProactorEventLoop to spawn its
# driver subprocess — mutually exclusive in one loop. Callers run this in a worker thread
# (asyncio.to_thread) so Playwright keeps its own loop and stays clear of the DB loop.

DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)

# Cloudflare frequently flags headless Chromium; set REDDIT_BROWSER_HEADLESS=0 (or run on a
# machine with a display) if the challenge won't clear headless.
_HEADLESS = os.environ.get("REDDIT_BROWSER_HEADLESS", "1") not in ("0", "false", "False")


@contextmanager
def browser_page(warmup_url: str, user_agent: str = DEFAULT_USER_AGENT):
    """Yield a Playwright page that has already cleared `warmup_url`'s edge challenge.

    Reuse the page for every request in a single fetch run — one browser per source, not per
    URL — and read JSON via `fetch_json` so the cf_clearance cookie carries over. Must be
    called from a thread without a running asyncio loop (e.g. via asyncio.to_thread).
    """
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=_HEADLESS)
        context = browser.new_context(
            user_agent=user_agent, locale="en-US", viewport={"width": 1280, "height": 800}
        )
        page = context.new_page()
        try:
            page.goto(warmup_url, wait_until="domcontentloaded", timeout=60_000)
            yield page
        finally:
            browser.close()


def fetch_json(page: Page, url: str, params: dict[str, Any] | None = None) -> Any:
    """Fetch a JSON document from inside the page (so it inherits the cleared cookies)."""
    full_url = str(httpx.URL(url, params=params or {}))
    result = page.evaluate(
        """async (u) => {
            const resp = await fetch(u, {
                credentials: 'include',
                headers: {'Accept': 'application/json'},
            });
            return {status: resp.status, body: await resp.text()};
        }""",
        full_url,
    )
    if result["status"] != 200:
        raise RuntimeError(f"GET {full_url} returned HTTP {result['status']}")
    return json.loads(result["body"])
