from __future__ import annotations

# Public endpoints (Reddit's .json, news article pages) reject obviously automated
# User-Agents, so connectors present a normal browser UA. Override per-source where a
# site asks for a descriptive UA (e.g. REDDIT_USER_AGENT).
DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)


def browser_headers(user_agent: str = DEFAULT_USER_AGENT) -> dict[str, str]:
    return {
        "User-Agent": user_agent,
        "Accept": "text/html,application/xhtml+xml,application/json;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9,es;q=0.8",
    }
