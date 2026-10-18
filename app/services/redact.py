import re
import requests

ACCESS_KEY_PATTERN = re.compile(r"(access_key=)[^&\s'\"]+")


def redact_request_error(error: requests.exceptions.RequestException, secret=None):
    """This function returns a copy of a requests exception with provider
    credentials removed from its message. Requests includes the request URL,
    and therefore the access_key query parameter, in HTTP and connection errors.

    Args:
        error (RequestException): The original requests exception.
        secret (str, optional): The API key to mask wherever it appears. Defaults to None.

    Returns:
        RequestException: An exception of the same type with a redacted message.
    """
    message = ACCESS_KEY_PATTERN.sub(r"\1[REDACTED]", str(error))
    if secret:
        message = message.replace(secret, "[REDACTED]")
    return type(error)(message)
