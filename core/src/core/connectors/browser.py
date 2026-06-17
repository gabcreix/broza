from __future__ import annotations

import asyncio
import json
import os
import sys
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
def _subprocess_capable_loop_policy():
    """Playwright spawns its driver as a subprocess; on Windows that needs the Proactor loop,
    but the app sets the Selector policy globally because psycopg's async mode requires it.
    Swap to Proactor just while Playwright builds its own loop, then restore. The app's main
    loop is already created and running, so the swap only affects Playwright's new loop.
    No-op off Windows, where any loop can spawn subprocesses."""
    if sys.platform != "win32":
        yield
        return
    previous = asyncio.get_event_loop_policy()
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
    try:
        yield
    finally:
        asyncio.set_event_loop_policy(previous)


@contextmanager
def browser_page(warmup_url: str, user_agent: str = DEFAULT_USER_AGENT):
    """Yield a Playwright page that has already cleared `warmup_url`'s edge challenge.

    Reuse the page for every request in a single fetch run — one browser per source, not per
    URL — and read JSON via `fetch_json` so the cf_clearance cookie carries over. Must be
    called from a thread without a running asyncio loop (e.g. via asyncio.to_thread).
    """
    with _subprocess_capable_loop_policy(), sync_playwright() as pw:
        browser = pw.chromium.launch(headless=_HEADLESS)
        context = browser.new_context(
            user_agent=user_agent, locale="en-US", viewport={"width": 1280, "height": 800}
        )
        page = context.new_page()
        try:
            # Warm up: let Cloudflare's challenge run and drop cf_clearance before we ask for
            # data. "load" (not "domcontentloaded") so the post-challenge redirect settles.
            page.goto(warmup_url, wait_until="load", timeout=60_000)
            yield page
        finally:
            browser.close()


def fetch_json(page: Page, url: str, params: dict[str, Any] | None = None) -> Any:
    """Navigate the page straight to a JSON endpoint and read the response body.

    Reading the navigation's own response (rather than an in-page fetch) avoids the "execution
    context destroyed" race when the site is still redirecting, and the navigation carries the
    cf_clearance cookie set during warm-up.
    """
    full_url = str(httpx.URL(url, params=params or {}))
    response = page.goto(full_url, wait_until="domcontentloaded", timeout=60_000)
    if response is None:
        raise RuntimeError(f"GET {full_url} produced no response")
    if response.status != 200:
        raise RuntimeError(f"GET {full_url} returned HTTP {response.status}")
    return json.loads(response.text())
