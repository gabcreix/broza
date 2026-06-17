from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from datetime import datetime
from enum import Enum
from typing import Any, ClassVar

from pydantic import BaseModel

from core.models.config import QueryDefinition, SourceInstance
from core.models.raw import RawPayload


class AcquisitionMethod(str, Enum):
    API = "api"
    RSS = "rss"
    SCRAPING = "scraping"


class ConnectorCapabilities(BaseModel):
    keyword_search: bool
    date_filter: bool
    native_categories: bool
    pagination: bool


class ConnectorDescriptor(BaseModel):
    """Mirrors a row of config.connectors. The UI lists these to populate the source-type dropdown."""

    type: str
    display_name: str
    capabilities: ConnectorCapabilities
    acquisition: list[AcquisitionMethod]
    param_schema: dict[str, Any]


class Connector(ABC):
    """Contract every source adapter implements. `acquisition` declares the cascade this
    connector falls back through, in order (e.g. [API, RSS, SCRAPING]); the query planner
    uses `capabilities` to decide what it can push down versus what falls to the semantic funnel."""

    type: ClassVar[str]
    display_name: ClassVar[str]
    capabilities: ClassVar[ConnectorCapabilities]
    acquisition: ClassVar[list[AcquisitionMethod]]
    param_model: ClassVar[type[BaseModel]]

    def __init__(self, source: SourceInstance) -> None:
        self.source = source

    @classmethod
    def descriptor(cls) -> ConnectorDescriptor:
        return ConnectorDescriptor(
            type=cls.type,
            display_name=cls.display_name,
            capabilities=cls.capabilities,
            acquisition=cls.acquisition,
            param_schema=cls.param_model.model_json_schema(),
        )

    @abstractmethod
    def fetch(
        self, query: QueryDefinition | None, since: datetime | None
    ) -> AsyncIterator[RawPayload]:
        """Pull content matching `query` (pushed down as far as `capabilities` allows),
        updated after `since`. Yields raw payloads for the ingestion layer to land in Bronze."""


_REGISTRY: dict[str, type[Connector]] = {}


def register_connector(cls: type[Connector]) -> type[Connector]:
    _REGISTRY[cls.type] = cls
    return cls


def get_connector_class(connector_type: str) -> type[Connector]:
    try:
        return _REGISTRY[connector_type]
    except KeyError:
        raise KeyError(f"No connector registered for type {connector_type!r}") from None


def list_connector_descriptors() -> list[ConnectorDescriptor]:
    return [cls.descriptor() for cls in _REGISTRY.values()]
