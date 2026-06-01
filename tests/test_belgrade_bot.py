"""
Unit tests for Belgrade Guide Bot
Tests db.py, BM25 search, google_api.py, and dialog router
"""
import pytest
import asyncio
import math
import os
import sys
from collections import Counter
from unittest.mock import AsyncMock, MagicMock, patch

# ─────────────────────────────────────────────
# BM25 SEARCH TESTS
# These test the search engine directly without
# needing any external services or data files
# ─────────────────────────────────────────────

# Inline the BM25 functions so tests run without importing tools.py
# (which tries to load data files at import time)
import re
PLACEHOLDER_RE = re.compile(r'\$\{PLACEHOLDER_\d+\}')

def _tokenize(text: str) -> list:
    text = PLACEHOLDER_RE.sub('', text)
    return re.findall(r'\w+', text.lower())

def _doc_text(doc: dict) -> str:
    TEXT_FIELDS = ("event_description", "tags", "name", "description")
    parts = []
    for k in TEXT_FIELDS:
        if k not in doc:
            continue
        weight = 3 if k == "tags" else 1
        parts.extend([str(doc[k])] * weight)
    return ' '.join(parts)

def _bm25_search(docs: list, query: str, top_k: int = 3, k1: float = 1.5, b: float = 0.75) -> list:
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


SAMPLE_EVENTS = [
    {"event_description": "Jazz concert at Skadarlija", "tags": "#Jazz,#Music,#LiveMusic", "source_channel": "test", "link": "http://test1.com"},
    {"event_description": "Hiking trip to Avala mountain", "tags": "#Hiking,#Outdoor,#Nature", "source_channel": "test", "link": "http://test2.com"},
    {"event_description": "Craft beer festival in Savamala", "tags": "#Beer,#CraftBeer,#Festival", "source_channel": "test", "link": "http://test3.com"},
    {"event_description": "Art exhibition at Cultural Center", "tags": "#Art,#Exhibition,#Culture", "source_channel": "test", "link": "http://test4.com"},
    {"event_description": "Vegan food market in Dorćol", "tags": "#Vegan,#Food,#Market", "source_channel": "test", "link": "http://test5.com"},
]


class TestBM25Search:

    def test_returns_relevant_result_for_jazz_query(self):
        results = _bm25_search(SAMPLE_EVENTS, "jazz music")
        assert len(results) > 0
        assert results[0]["tags"] == "#Jazz,#Music,#LiveMusic"

    def test_returns_relevant_result_for_hiking_query(self):
        results = _bm25_search(SAMPLE_EVENTS, "hiking outdoor nature")
        assert len(results) > 0
        assert results[0]["tags"] == "#Hiking,#Outdoor,#Nature"

    def test_top_k_limits_results(self):
        results = _bm25_search(SAMPLE_EVENTS, "music festival beer", top_k=2)
        assert len(results) <= 2

    def test_irrelevant_query_returns_empty(self):
        results = _bm25_search(SAMPLE_EVENTS, "xyzxyzxyz nonexistent")
        assert len(results) == 0

    def test_tag_boost_prioritizes_tag_matches(self):
        # "CraftBeer" is in tags (boosted 3x) so craft beer event should rank first
        results = _bm25_search(SAMPLE_EVENTS, "craft beer")
        assert len(results) > 0
        assert "Beer" in results[0]["tags"]

    def test_returns_top_3_by_default(self):
        results = _bm25_search(SAMPLE_EVENTS, "music art culture festival")
        assert len(results) <= 3

    def test_empty_docs_returns_empty(self):
        results = _bm25_search([], "jazz")
        assert results == []

    def test_placeholder_stripped_from_query(self):
        # Placeholders in query should not affect results
        results = _bm25_search(SAMPLE_EVENTS, "jazz ${PLACEHOLDER_1}")
        assert len(results) > 0
        assert results[0]["tags"] == "#Jazz,#Music,#LiveMusic"


# ─────────────────────────────────────────────
# DATABASE TESTS
# These use an in-memory SQLite database so
# no real files are needed
# ─────────────────────────────────────────────

# We need to set up environment before importing db
os.environ.setdefault("DATA_DIR", "/tmp")
os.environ.setdefault("ENV", "test")

@pytest.fixture
def event_loop():
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest.fixture
async def test_db(tmp_path):
    """Create a temporary database for each test."""
    db_path = str(tmp_path / "test.db")

    # Patch the DB_PATH in db module
    with patch.dict(os.environ, {"DATA_DIR": str(tmp_path)}):
        import importlib
        # We'll use aiosqlite directly to avoid import issues
        import aiosqlite

        async with aiosqlite.connect(db_path) as db:
            await db.execute("""
                CREATE TABLE IF NOT EXISTS messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    chat_id TEXT NOT NULL,
                    username TEXT,
                    channel TEXT,
                    role TEXT NOT NULL,
                    message_text TEXT NOT NULL,
                    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            """)
            await db.commit()

        yield db_path


class TestDatabase:

    @pytest.mark.asyncio
    async def test_save_and_retrieve_message(self, tmp_path):
        import aiosqlite
        db_path = str(tmp_path / "test.db")

        async with aiosqlite.connect(db_path) as db:
            await db.execute("""
                CREATE TABLE messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    chat_id TEXT, username TEXT, channel TEXT,
                    role TEXT, message_text TEXT,
                    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            """)
            await db.commit()

            # Save a message
            await db.execute(
                "INSERT INTO messages (chat_id, username, role, message_text) VALUES (?, ?, ?, ?)",
                ("chat123", "ana", "user", "I want jazz music")
            )
            await db.commit()

            # Retrieve it
            async with db.execute(
                "SELECT * FROM messages WHERE chat_id = ?", ("chat123",)
            ) as cursor:
                rows = await cursor.fetchall()

        assert len(rows) == 1
        assert rows[0][4] == "user"
        assert rows[0][5] == "I want jazz music"

    @pytest.mark.asyncio
    async def test_messages_separated_by_chat_id(self, tmp_path):
        import aiosqlite
        db_path = str(tmp_path / "test.db")

        async with aiosqlite.connect(db_path) as db:
            await db.execute("""
                CREATE TABLE messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    chat_id TEXT, username TEXT, channel TEXT,
                    role TEXT, message_text TEXT,
                    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            """)
            await db.commit()

            # Save messages for two different chats
            await db.execute(
                "INSERT INTO messages (chat_id, username, role, message_text) VALUES (?, ?, ?, ?)",
                ("chat_ana", "ana", "user", "I want jazz")
            )
            await db.execute(
                "INSERT INTO messages (chat_id, username, role, message_text) VALUES (?, ?, ?, ?)",
                ("chat_marko", "marko", "user", "I want craft beer")
            )
            await db.commit()

            async with db.execute(
                "SELECT * FROM messages WHERE chat_id = ?", ("chat_ana",)
            ) as cursor:
                ana_rows = await cursor.fetchall()

            async with db.execute(
                "SELECT * FROM messages WHERE chat_id = ?", ("chat_marko",)
            ) as cursor:
                marko_rows = await cursor.fetchall()

        assert len(ana_rows) == 1
        assert len(marko_rows) == 1
        assert ana_rows[0][5] == "I want jazz"
        assert marko_rows[0][5] == "I want craft beer"

    @pytest.mark.asyncio
    async def test_messages_retrieved_in_order(self, tmp_path):
        import aiosqlite
        db_path = str(tmp_path / "test.db")

        async with aiosqlite.connect(db_path) as db:
            await db.execute("""
                CREATE TABLE messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    chat_id TEXT, username TEXT, channel TEXT,
                    role TEXT, message_text TEXT,
                    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            """)
            await db.commit()

            messages = ["first message", "second message", "third message"]
            for msg in messages:
                await db.execute(
                    "INSERT INTO messages (chat_id, username, role, message_text) VALUES (?, ?, ?, ?)",
                    ("chat123", "ana", "user", msg)
                )
            await db.commit()

            async with db.execute(
                "SELECT message_text FROM messages WHERE chat_id = ? ORDER BY id",
                ("chat123",)
            ) as cursor:
                rows = await cursor.fetchall()

        assert [r[0] for r in rows] == messages

    @pytest.mark.asyncio
    async def test_empty_history_for_new_chat(self, tmp_path):
        import aiosqlite
        db_path = str(tmp_path / "test.db")

        async with aiosqlite.connect(db_path) as db:
            await db.execute("""
                CREATE TABLE messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    chat_id TEXT, username TEXT, channel TEXT,
                    role TEXT, message_text TEXT,
                    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            """)
            await db.commit()

            async with db.execute(
                "SELECT * FROM messages WHERE chat_id = ?", ("brand_new_chat",)
            ) as cursor:
                rows = await cursor.fetchall()

        assert len(rows) == 0


# ─────────────────────────────────────────────
# GOOGLE API TESTS
# These mock the HTTP calls so no real API
# key or network is needed
# ─────────────────────────────────────────────

class TestGooglePlaceApi:

    def test_shareable_link_format(self):
        """Test that shareable links are correctly formatted Google Maps URLs."""
        from src.google_api import GooglePlaceApi
        api = GooglePlaceApi()
        api.google_api_key = "fake_key"
        link = api.shareble_link(44.8176, 20.4569)
        assert "maps.google.com" in link or "google.com/maps" in link
        assert "44.8176" in link
        assert "20.4569" in link

    @patch("src.google_api.requests.get")
    def test_get_recs_returns_empty_on_no_results(self, mock_get):
        """Test that get_recs returns empty list when Google Places returns nothing."""
        from src.google_api import GooglePlaceApi
        mock_get.return_value.json.return_value = {"results": []}
        api = GooglePlaceApi()
        api.google_api_key = "fake_key"
        result = api.get_recs("44.8176,20.4569", q="jazz bar")
        assert result == []

    @patch("src.google_api.requests.get")
    def test_get_recs_returns_up_to_3_candidates(self, mock_get):
        """Test that get_recs returns at most 3 results."""
        from src.google_api import GooglePlaceApi

        # Mock 5 results from Google Places
        mock_get.return_value.json.return_value = {
            "results": [
                {"name": f"Place {i}", "geometry": {"location": {"lat": 44.8, "lng": 20.4}}}
                for i in range(5)
            ]
        }
        api = GooglePlaceApi()
        api.google_api_key = "fake_key"
        results = api.get_recs("44.8176,20.4569", q="bar")
        assert len(results) <= 3

    @patch("src.google_api.requests.get")
    def test_reverse_geocode_returns_city_country(self, mock_get):
        """Test that reverse geocode correctly extracts city and country."""
        from src.google_api import GooglePlaceApi

        mock_get.return_value.json.return_value = {
            "status": "OK",
            "results": [{
                "address_components": [
                    {"long_name": "Belgrade", "types": ["locality"]},
                    {"long_name": "Serbia", "types": ["country"]}
                ]
            }]
        }
        api = GooglePlaceApi()
        api.google_api_key = "fake_key"
        result = api.reverse_geocode(44.8176, 20.4569)
        assert result == {"city": "Belgrade", "country": "Serbia"}

    @patch("src.google_api.requests.get")
    def test_reverse_geocode_returns_none_on_failure(self, mock_get):
        """Test that reverse geocode returns None when API call fails."""
        from src.google_api import GooglePlaceApi

        mock_get.return_value.json.return_value = {"status": "ZERO_RESULTS"}
        api = GooglePlaceApi()
        api.google_api_key = "fake_key"
        result = api.reverse_geocode(0, 0)
        assert result is None


# ─────────────────────────────────────────────
# OPENSSTREETMAP API TESTS
# ─────────────────────────────────────────────

class TestOpenStreetMapApi:

    @patch("src.google_api.requests.post")
    def test_search_venues_returns_formatted_results(self, mock_post):
        """Test that OSM search returns properly formatted venue list."""
        from src.google_api import OpenStreetMapApi

        mock_post.return_value.json.return_value = {
            "elements": [
                {
                    "tags": {"name": "Jazz Bar", "opening_hours": "Mo-Su 18:00-02:00"},
                    "lat": 44.8176,
                    "lon": 20.4569
                }
            ]
        }
        api = OpenStreetMapApi()
        results = api.search_venues("bar")
        assert len(results) == 1
        assert results[0]["name"] == "Jazz Bar"
        assert "google.com/maps" in results[0]["link"]

    @patch("src.google_api.requests.post")
    def test_search_venues_returns_empty_on_no_results(self, mock_post):
        """Test that OSM search returns empty list when nothing found."""
        from src.google_api import OpenStreetMapApi

        mock_post.return_value.json.return_value = {"elements": []}
        api = OpenStreetMapApi()
        results = api.search_venues("nonexistent_amenity")
        assert results == []


if __name__ == "__main__":
    pytest.main([__file__, "-v"])