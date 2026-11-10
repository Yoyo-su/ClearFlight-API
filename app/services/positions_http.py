import asyncio
import concurrent.futures
import json
import threading
import time
import zlib

import httpx

from app.core.config import settings
from app.services.metar import MetarTimeout, MetarUpstreamError

"""
HTTP for the live position providers, with a hard per-request deadline
(CF-009 design r3 §5; owner decision after review round 5).

Synchronous clients can't be cancelled: a peer that trickles bytes, a slow
DNS answer or a stalled TLS handshake can hold a blocking call open, and an
abandoned thread can even send its request late. Here every request is an
asyncio task on one background event loop, run under
asyncio.timeout_at(deadline). Cancellation stops connect, DNS waits, TLS,
headers and body reads alike and closes the socket, so nothing is sent or
read after the deadline. The loop's clock is time.monotonic, the same clock
as the callers' deadlines.
"""

MIN_ATTEMPT_S = 2.0  # no new attempt starts with less time left
MAX_BODY_BYTES = 8_000_000
MAX_CONNECTIONS = 8  # requests in flight at once
POOL_WAIT_S = 0.5  # a full pool fails fast ("requests_busy"), never queues long


class Reply:
    """A fully read response: status, headers and body."""

    def __init__(self, status_code: int, headers, content: bytes):
        self.status_code = status_code
        self.headers = headers
        self.content = content

    def json(self):
        return json.loads(self.content)


class Decoder:
    """Incremental gzip/deflate decoding with a cap on the decoded size.

    Handles concatenated gzip members, zlib-wrapped or raw deflate, and checks
    that the stream really ended (a truncated body is an error).
    """

    def __init__(self, encoding: str):
        self.gzip = encoding in ("gzip", "x-gzip")
        self.obj = None  # deflate: chosen on the first bytes (zlib or raw)

    def new(self, first: bytes = b""):
        if self.gzip:
            return zlib.decompressobj(16 + zlib.MAX_WBITS)
        # A zlib header has CMF 0x78 (deflate, 32 KB window); else raw deflate.
        return zlib.decompressobj(
            zlib.MAX_WBITS if first[:1] == b"\x78" else -zlib.MAX_WBITS
        )

    def decode(self, data: bytes, room: int) -> bytes:
        out = []
        while data:
            if self.obj is None:
                self.obj = self.new(data)
            try:
                piece = self.obj.decompress(data, room + 1)
            except zlib.error:
                raise MetarUpstreamError("invalid_response", "bad compressed body")
            if self.obj.unconsumed_tail:
                raise MetarUpstreamError("response_too_large")
            out.append(piece)
            room -= len(piece)
            if room < 0:
                raise MetarUpstreamError("response_too_large")
            data = self.obj.unused_data if self.obj.eof else b""
            if data and self.gzip and data.strip(b"\0"):
                self.obj = None  # the next gzip member
            elif data and self.gzip:
                data = b""  # trailing zero padding after the last member
            elif data:
                raise MetarUpstreamError("invalid_response", "data after stream end")
        return b"".join(out)

    def finish(self, received: int) -> None:
        if received and (self.obj is None or not self.obj.eof):
            raise MetarUpstreamError("invalid_response", "truncated compressed body")


def decoder(encoding: str | None) -> Decoder | None:
    """A decoder for the response's Content-Encoding (None for identity)."""
    encoding = (encoding or "identity").strip().lower()
    if encoding in ("", "identity"):
        return None
    if encoding in ("gzip", "x-gzip", "deflate"):
        return Decoder(encoding)
    raise MetarUpstreamError("unsupported_encoding")


class Loop:
    """One event loop on a daemon thread, with one shared AsyncClient."""

    def __init__(self, transport: httpx.AsyncBaseTransport | None = None):
        self.loop = asyncio.new_event_loop()
        self.transport = transport
        self.client: httpx.AsyncClient | None = None
        self.thread = threading.Thread(
            target=self.loop.run_forever, name="positions-http", daemon=True
        )
        self.thread.start()

    def get_client(self) -> httpx.AsyncClient:
        # Created on the loop's thread, on first use.
        if self.client is None:
            self.client = httpx.AsyncClient(
                transport=self.transport,
                follow_redirects=False,  # each redirect would be another provider call
                limits=httpx.Limits(
                    max_connections=MAX_CONNECTIONS,
                    max_keepalive_connections=MAX_CONNECTIONS,
                ),
                headers={
                    "User-Agent": settings.METAR_USER_AGENT,
                    "Accept-Encoding": "identity",
                },
                trust_env=False,
            )
        return self.client

    def stop(self) -> None:
        async def close():
            if self.client is not None:
                await self.client.aclose()

        try:
            asyncio.run_coroutine_threadsafe(close(), self.loop).result(timeout=2)
        except (concurrent.futures.TimeoutError, RuntimeError):
            pass
        self.loop.call_soon_threadsafe(self.loop.stop)


_lock = threading.Lock()
_loop: Loop | None = None


def current() -> Loop:
    global _loop
    with _lock:
        if _loop is None:
            _loop = Loop()
        return _loop


def use_transport(transport: httpx.AsyncBaseTransport | None) -> None:
    """Replace the shared client's transport (tests; None restores the network)."""
    global _loop
    with _lock:
        if _loop is not None:
            _loop.stop()
        _loop = Loop(transport)


async def _send(client, method: str, url: str, deadline: float, **kwargs) -> Reply:
    left = deadline - time.monotonic()
    timeout = httpx.Timeout(min(settings.PROVIDER_TIMEOUT, left), pool=POOL_WAIT_S)
    try:
        async with asyncio.timeout_at(deadline):
            async with client.stream(
                method, url, timeout=timeout, **kwargs
            ) as response:
                decode = decoder(response.headers.get("Content-Encoding"))
                chunks, size, received = [], 0, 0
                async for raw in response.aiter_raw():
                    received += len(raw)
                    if decode is not None:
                        raw = decode.decode(raw, MAX_BODY_BYTES - size)
                    size += len(raw)
                    if size > MAX_BODY_BYTES:
                        raise MetarUpstreamError("response_too_large")
                    chunks.append(raw)
                if decode is not None:
                    decode.finish(received)
                return Reply(response.status_code, response.headers, b"".join(chunks))
    except TimeoutError:  # asyncio.timeout_at: the deadline passed
        raise MetarTimeout("deadline")
    except httpx.PoolTimeout:
        raise MetarUpstreamError("requests_busy")  # not retried
    except httpx.TimeoutException:
        raise MetarTimeout("timeout")
    except httpx.HTTPError as e:
        raise MetarUpstreamError("connection_error", type(e).__name__)


def send(method: str, url: str, deadline: float, **kwargs) -> Reply:
    """One HTTP request that can't outlive the deadline (see the module doc).

    Raises:
        MetarTimeout: the deadline or a socket timeout passed (504).
        MetarUpstreamError: connection, protocol or body errors (502), or
            "requests_busy" when every connection is in use.
    """
    if deadline - time.monotonic() < MIN_ATTEMPT_S:
        raise MetarTimeout("deadline")
    loop = current()
    future = asyncio.run_coroutine_threadsafe(
        _run(loop, method, url, deadline, **kwargs), loop.loop
    )
    try:
        # The task enforces the deadline itself; the margin only covers handing
        # the result back across threads.
        return future.result(timeout=max(0.0, deadline - time.monotonic()) + 1.0)
    except concurrent.futures.TimeoutError:
        future.cancel()
        raise MetarTimeout("deadline")


async def _run(loop: Loop, method: str, url: str, deadline: float, **kwargs) -> Reply:
    return await _send(loop.get_client(), method, url, deadline, **kwargs)


def get(url: str, deadline: float, **kwargs) -> Reply:
    return send("GET", url, deadline, **kwargs)


def post(url: str, deadline: float, **kwargs) -> Reply:
    return send("POST", url, deadline, **kwargs)
