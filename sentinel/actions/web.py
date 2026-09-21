"""Recherches web dans le navigateur par défaut."""
from __future__ import annotations

import webbrowser
from urllib.parse import quote_plus

from ..replies import R

ENGINES = {
    "google": "https://www.google.com/search?q={q}",
    "duckduckgo": "https://duckduckgo.com/?q={q}",
    "bing": "https://www.bing.com/search?q={q}",
    "youtube": "https://www.youtube.com/results?search_query={q}",
}


def search(cfg, query: str, engine: str | None = None) -> str:
    engine = engine if engine in ENGINES else cfg["search_engine"]
    template = ENGINES.get(engine, ENGINES["google"])
    webbrowser.open(template.format(q=quote_plus(query)))
    return R(cfg, "web", query=query)
