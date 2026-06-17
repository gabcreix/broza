from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Any

import feedparser
import httpx
import trafilatura
from pydantic import BaseModel, HttpUrl

from core.connectors.base import (
    AcquisitionMethod,
    Connector,
    ConnectorCapabilities,
    register_connector,
)
from core.models.config import QueryDefinition
from core.models.raw import RawPayload

CONNECTOR_VERSION = "1"
USER_AGENT = "broza/0.1 (content aggregation research bot)"


class RssParams(BaseModel):
    feed_url: HttpUrl


@register_connector
class PressRssConnector(Connector):
    """Press articles via RSS. The feed only gives entry metadata, never the full body, so
    'contenido completo' for this source type means fetching the article page and running
    trafilatura over it — RSS for discovery, scraping for the body."""

    type = "press_rss"
    display_name = "Prensa (RSS)"
    capabilities = ConnectorCapabilities(
        keyword_search=False, date_filter=False, native_categories=False, pagination=False
    )
    acquisition = [AcquisitionMethod.RSS, AcquisitionMethod.SCRAPING]
    param_model = RssParams

    @property
    def params(self) -> RssParams:
        return RssParams.model_validate(self.source.params)

    async def fetch(
        self, query: QueryDefinition | None, since: datetime | None
    ) -> AsyncIterator[RawPayload]:
        async with httpx.AsyncClient(
            headers={"User-Agent": USER_AGENT}, timeout=30, follow_redirects=True
        ) as client:
            feed_resp = await client.get(str(self.params.feed_url))
            feed_resp.raise_for_status()
            feed = feedparser.parse(feed_resp.content)

            for entry in feed.entries:
                published = self._entry_published_at(entry)
                if since is not None and published is not None and published <= since:
                    continue

                full_text = await self._fetch_full_text(client, entry.link)

                yield RawPayload(
                    external_id=entry.get("id", entry.link),
                    fetched_at=datetime.now(timezone.utc),
                    connector_version=CONNECTOR_VERSION,
                    payload={
                        "title": entry.get("title"),
                        "link": entry.link,
                        "author": entry.get("author"),
                        "summary": entry.get("summary"),
                        "published": entry.get("published"),
                        "full_text": full_text,
                    },
                )

    @staticmethod
    def _entry_published_at(entry: Any) -> datetime | None:
        raw = entry.get("published")
        if not raw:
            return None
        try:
            return parsedate_to_datetime(raw)
        except (TypeError, ValueError):
            return None

    @staticmethod
    async def _fetch_full_text(client: httpx.AsyncClient, url: str) -> str | None:
        resp = await client.get(url)
        resp.raise_for_status()
        return trafilatura.extract(resp.text)
