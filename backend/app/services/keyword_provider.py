from abc import ABC, abstractmethod
from typing import List, Optional, Dict, Any
from pydantic import BaseModel

class KeywordMetric(BaseModel):
    keyword: str
    search_volume: Optional[int] = None
    difficulty: Optional[float] = None
    cpc: Optional[float] = None
    source: str = "null_provider"

class KeywordProvider(ABC):
    """Abstract interface for keyword data providers.
    
    Enforces M4 data policy:
    Never invent search volume, keyword difficulty, traffic forecasts or competitor traffic.
    If a metric is not available from real data it is null / 'unknown'.
    """
    @abstractmethod
    async def get_metrics(self, keywords: List[str]) -> List[KeywordMetric]:
        pass

    @abstractmethod
    async def get_related(self, keyword: str) -> List[str]:
        pass

class NullProvider(KeywordProvider):
    """Default free-path provider returning explicit null/unknown for paid metrics."""
    async def get_metrics(self, keywords: List[str]) -> List[KeywordMetric]:
        return [
            KeywordMetric(
                keyword=k,
                search_volume=None,
                difficulty=None,
                cpc=None,
                source="unknown (null_provider — paid keyword API not configured)"
            )
            for k in keywords
        ]

    async def get_related(self, keyword: str) -> List[str]:
        return []

def get_keyword_provider() -> KeywordProvider:
    """Factory returning active KeywordProvider (defaults to NullProvider in M4)."""
    return NullProvider()
