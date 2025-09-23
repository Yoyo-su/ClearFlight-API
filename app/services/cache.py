from app.core.config import settings
import redis
import json
import hashlib

# Initialise Redis client
redis_client = redis.Redis(
    host=settings.REDIS_HOST,
    port=settings.REDIS_PORT,
    decode_responses=True,
)
cache_expiry = settings.CACHE_EXPIRE



def get_cache_key(url, params=None):
    """This function generates a unique cache key based on the URL and optional parameters.

    Args:
        url (str): The URL for which the cache key is generated.
        params (dict, optional): A dictionary of parameters to include in the cache key. Defaults to None.

    Returns:
        str or None: A SHA-256 hash of the URL and parameters, used as the cache key.
        Returns None if an error occurs.
    """
    try:
        raw_key = url
        if params:
            raw_key += json.dumps(params, sort_keys=True)
        return hashlib.sha256(raw_key.encode()).hexdigest()
    except Exception as e:
        print(f"Error generating cache key: {e}")
        return None


def check_cache(cache_key):
    """This function checks if a response is cached in Redis using the provided cache key.

    Args:
        cache_key (str): The cache key to query in Redis.

    Returns:
        dict or None: Returns the cached data as a dictionary if found, otherwise returns None.
    """
    try:
        # Check cache first
        cached_response = redis_client.get(cache_key)
        if cached_response:
            print("Cache hit!")
            return json.loads(cached_response)
        print("Cache miss!")
        return None
    except redis.RedisError as e:
        print(f"Error checking cache: {e}")
        return None


def cache_response(cache_key, data, cache_expiry=cache_expiry):
    """This function caches the response data in Redis with a specified expiry time.

    Args:
        cache_key (str): The cache key under which the data will be stored.
        data (dict): The data to be cached, which will be converted to JSON format.
        cache_expiry (int, optional): The time in seconds after which the cache will expire. Defaults to 3600 seconds (1 hour).
    """
    try:
        redis_client.setex(cache_key, cache_expiry, json.dumps(data))
        print("Response cached successfully.")
    except redis.RedisError as e:
        print(f"Error caching response: {e}")
