from langchain_core.tools import tool

from .google_api import place_recommender, osm_api
import json
import math
import re
from collections import Counter

import re
import math
import json
from collections import Counter
import os

PLACEHOLDER_RE = re.compile(r'\$\{PLACEHOLDER_\d+\}')

EVENTS_PATH = "/srv/data/events_dataset.jsonl"
TICKETS_PATH = "/srv/data/concerts_en.json"
ONTOPO_PATH = "/srv/data/ontopo_venues_en.json"


def _load_json(path: str) -> list[dict]:
    with open(path, "r", encoding="utf-8") as f:
        raw = f.read().strip()
    if raw.startswith("["):
        return json.loads(raw)

    results = []
    for i, line in enumerate(raw.splitlines(), 1):
        line = line.strip()
        if not line:
            continue
        try:
            results.append(json.loads(line))
        except json.JSONDecodeError:
            pass
    return results


events = _load_json(EVENTS_PATH)
concerts = _load_json(TICKETS_PATH)
restaurants = _load_json(ONTOPO_PATH)


def _tokenize(text: str) -> list[str]:
    text = PLACEHOLDER_RE.sub('', text)
    return re.findall(r'\w+', text.lower())


TEXT_FIELDS = (
"event_description", "tags", "name", "venue", "date", "city", "price_from_rsd", "category", "subcategory",
"description", "location", "michelin")


def _doc_text(doc: dict) -> str:
    parts = []
    for k in TEXT_FIELDS:
        if k not in doc:
            continue
        # Boost tags by repeating them — they're high signal
        weight = 3 if k == "tags" else 1
        parts.extend([str(doc[k])] * weight)
    return ' '.join(parts)


def _bm25_search(docs: list[dict], query: str, top_k: int = 3, k1: float = 1.5, b: float = 0.75) -> list[dict]:
    tokenized_docs = [_tokenize(_doc_text(d)) for d in docs]
    query_tokens = _tokenize(query)
    N = len(tokenized_docs)
    avgdl = sum(len(d) for d in tokenized_docs) / N if N else 1

    df = Counter()
    for td in tokenized_docs:
        for t in set(td):
            df[t] += 1
    idf = {t: math.log((N - df[t] + 0.5) / (df[t] + 0.5) + 1) for t in df}

    scores = []
    for i, td in enumerate(tokenized_docs):
        tf_map = Counter(td)
        dl = len(td)
        score = sum(
            idf.get(t, 0) * (tf_map[t] * (k1 + 1)) / (tf_map[t] + k1 * (1 - b + b * dl / avgdl))
            for t in query_tokens
        )
        scores.append((score, i))

    scores = [(s, i) for s, i in scores if s > 0.1]
    scores.sort(reverse=True)

    return [docs[i] for _, i in scores[:top_k]]


def _format_telegram_event(event: dict) -> str:
    desc = event.get('event_description')
    desc = PLACEHOLDER_RE.sub('', desc).strip()
    return (
        f"📢 {desc}\n"
        f"🏷 {event.get('tags', 'N/A')}\n"
        f"📡 Source: @{event.get('source_channel', 'N/A')}\n"
        f"🔗 {event.get('link', 'N/A')}"
    )


@tool
def find_telegram_event(
        query: str,
        constraints: str = ""
) -> str:
    """Find a Telegram event in Belgrade matching the query and constraints."""

    # events = _load_json(EVENTS_PATH)
    if not events:
        return "No events found in database."

    combined_query = f"{query} {constraints}".strip()
    results = _bm25_search(events, combined_query, top_k=1)
    if not results:
        return "No matching event found."

    return _format_telegram_event(results[0])


@tool
def find_concerts(query: str) -> str:
    """Find concerts in Belgrade matching the query."""
    # concerts = _load_json(TICKETS_PATH)
    if not concerts:
        return "No concerts found in database."

    results = _bm25_search(concerts, query, top_k=1)
    if not results:
        return "No matching concert found."

    return "\n\n".join(
        f"🎤 {c.get('name', 'N/A')}\n"
        f"📅 {c.get('date', 'N/A')}\n"
        f"📍 {c.get('venue', 'N/A')}\n"
        f"🔗 {c.get('url', 'N/A')}"
        for c in results
    )


@tool
def find_restaurants(query: str) -> str:
    """Find restaurants in Belgrade matching the query."""
    # restaurants = _load_json(ONTOPO_PATH)
    if not restaurants:
        return "No restaurants found in database."

    results = _bm25_search(restaurants, query, top_k=1)
    if not results:
        return "No matching restaurant found."

    return "\n\n".join(
        f"🎤 {c.get('name', 'N/A')}\n"
        f"📍 {c.get('location', 'N/A')}\n"
        f"Make a reservation:\n {c.get('url', 'N/A')}"
        for c in results
    )


@tool
def find_venue(query: str) -> str:
    """Find a venue in Belgrade using a descriptive search query.
    The query should capture the group's preferences, e.g. 'quiet jazz bar',
    'Italian restaurant outdoor seating', 'craft beer bar live music'.
    Returns an HTML link to the venue, or an error message if nothing found."""
    BELGRADE_LAT_LNG = "44.8176,20.4569"
    result = place_recommender.get_recs(BELGRADE_LAT_LNG, q=query)
    if not result:
        return "No places found."
    return f'<a href="{result["link"]}">{result["name"]}</a>'


@tool
def find_venue_osm(amenity_type: str) -> str:
    """Find a venue in Belgrade using OpenStreetMap. Free alternative to Google Places.
    Use this when Google Places is unavailable or for broader venue discovery.

    amenity_type should be one of: bar, pub, restaurant, cafe, nightclub, theatre, cinema

    Returns a list of matching venues with names, opening hours and map links.
    """
    results = osm_api.search_venues(amenity_type)
    if not results:
        return "No venues found."

    formatted = []
    for v in results:
        formatted.append(
            f"📍 {v['name']}\n"
            f"🕐 {v['opening_hours']}\n"
            f"🔗 {v['link']}"
        )
    return "\n\n".join(formatted)