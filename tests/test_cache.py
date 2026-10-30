import pytest
from app.services.cache import (
    get_cache_key,
    check_cache,
    cache_response,
    create_redis_client,
)
from unittest import mock
import json
import redis

"""
Test suite for the Cache Service
"""


@pytest.fixture
def mock_client():
    with mock.patch("app.services.cache.redis_client") as mock_client:
        yield mock_client


@pytest.fixture
def test_response():
    """Fixture to provide a sample response for testing."""
    return {
        "data": [
            {
                "gmt": "-5",
                "airport_name": "John F Kennedy International",
                "iata_code": "JFK",
                "icao_code": "KJFK",
                "country_name": "United States",
                "latitude": "40.642334",
                "longitude": "-73.78817",
                "timezone": "America/New_York",
                "country_iso2": "US",
            }
        ]
    }


@pytest.mark.describe("Cache Service Tests")
class TestCache:
    @pytest.mark.it("get_cache_key generates a valid cache key")
    def test_get_cache_key_returns_valid_key(self):
        url = "https://www.mockurl.com/endpoint"
        params = {"param1": "value1", "param2": "value2"}
        cache_key = get_cache_key(url, params)

        assert isinstance(cache_key, str)
        assert len(cache_key) == 64  # SHA-256 hash length
        assert cache_key.isalnum()  # Check if the key is alphanumeric

    @pytest.mark.it("get_cache_key handles exceptions gracefully")
    def test_get_cache_key_exception(self):
        url = "https://www.mockurl.com/endpoint"
        params = {"param1": "value1", "param2": "value2"}
        with mock.patch("hashlib.sha256") as mock_hash:
            mock_hash.side_effect = Exception("Hashing error")
            cache_key = get_cache_key(url, params)
            assert cache_key is None

    @pytest.mark.it("check_cache returns cached response on cache hit")
    def test_check_cache_hit(self, mock_client, test_response):
        cache_key = "test_cache_key"
        mock_client.get.return_value = json.dumps(test_response)
        result = check_cache(cache_key)
        assert result == test_response
        mock_client.get.assert_called_once_with(cache_key)

    @pytest.mark.it("check_cache returns None on cache miss")
    def test_check_cache_miss(self, mock_client):
        cache_key = "test_cache_key"
        mock_client.get.return_value = None
        result = check_cache(cache_key)
        assert result is None
        mock_client.get.assert_called_once_with(cache_key)

    @pytest.mark.it("cache_response stores data in Redis with expiration")
    def test_cache_response(self, mock_client, test_response):
        cache_key = "test_cache_key"
        cache_response(cache_key, test_response)
        mock_client.setex.assert_called_once_with(
            cache_key, 3600, json.dumps(test_response)
        )

    @pytest.mark.it("create_redis_client uses REDIS_URL when set")
    def test_create_redis_client_from_url(self):
        config = mock.Mock(REDIS_URL="rediss://user:secret@example.com:6380")
        with mock.patch("app.services.cache.redis.Redis") as mock_redis:
            create_redis_client(config)
        mock_redis.from_url.assert_called_once_with(
            "rediss://user:secret@example.com:6380",
            decode_responses=True,
            socket_connect_timeout=1,
            socket_timeout=1,
        )
        mock_redis.assert_not_called()

    @pytest.mark.it("create_redis_client falls back to REDIS_HOST and REDIS_PORT")
    def test_create_redis_client_from_host(self):
        config = mock.Mock(REDIS_URL=None, REDIS_HOST="redis", REDIS_PORT=6379)
        with mock.patch("app.services.cache.redis.Redis") as mock_redis:
            create_redis_client(config)
        mock_redis.assert_called_once_with(
            host="redis",
            port=6379,
            decode_responses=True,
            socket_connect_timeout=1,
            socket_timeout=1,
        )
        mock_redis.from_url.assert_not_called()

    @pytest.mark.it("create_redis_client ignores an empty REDIS_URL")
    def test_create_redis_client_empty_url(self):
        # Docker Compose passes REDIS_URL="" when it is not set
        config = mock.Mock(REDIS_URL="", REDIS_HOST="redis", REDIS_PORT=6379)
        with mock.patch("app.services.cache.redis.Redis") as mock_redis:
            create_redis_client(config)
        mock_redis.assert_called_once_with(
            host="redis",
            port=6379,
            decode_responses=True,
            socket_connect_timeout=1,
            socket_timeout=1,
        )
        mock_redis.from_url.assert_not_called()

    @pytest.mark.it("check_cache returns None when Redis is unavailable")
    def test_check_cache_redis_error(self, mock_client):
        mock_client.get.side_effect = redis.ConnectionError("Redis down")
        assert check_cache("test_cache_key") is None

    @pytest.mark.it("check_cache treats a value that isn't JSON as a miss")
    def test_check_cache_malformed_json(self, mock_client):
        mock_client.get.return_value = "{not json"
        assert check_cache("test_cache_key") is None
