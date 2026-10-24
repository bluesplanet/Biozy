import asyncio
from collections import OrderedDict
import time

import aiohttp


API_URL = "https://www.generatefancytext.com/api/generate.json"
MAX_TEXT_LENGTH = 500
MIN_REQUEST_INTERVAL = 1.3
CACHE_SIZE = 32
CACHE_TTL_SECONDS = 900


class GenerateFancyTextAPIError(Exception):
    """Raised when GenerateFancyText cannot provide valid styles."""


class GenerateFancyTextAPI:
    def __init__(self) -> None:
        self._session: aiohttp.ClientSession | None = None
        self._request_lock = asyncio.Lock()
        self._last_request = 0.0
        self._cache: OrderedDict[
            str,
            tuple[float, tuple[str, ...]],
        ] = OrderedDict()

    async def start(self, session: aiohttp.ClientSession) -> None:
        self._session = session

    async def fetch_styles(self, text: str) -> list[str]:
        if not text.strip() or len(text) > MAX_TEXT_LENGTH:
            raise GenerateFancyTextAPIError(
                "Invalid text for GenerateFancyText."
            )
        if self._session is None or self._session.closed:
            raise GenerateFancyTextAPIError("The HTTP session is unavailable.")

        cached = self._get_cached(text)
        if cached is not None:
            return cached

        async with self._request_lock:
            cached = self._get_cached(text)
            if cached is not None:
                return cached

            loop = asyncio.get_running_loop()
            delay = MIN_REQUEST_INTERVAL - (loop.time() - self._last_request)
            if delay > 0:
                await asyncio.sleep(delay)
            self._last_request = loop.time()

            try:
                async with self._session.get(
                    API_URL,
                    params={"text": text},
                ) as response:
                    if response.status == 429:
                        raise GenerateFancyTextAPIError(
                            "GenerateFancyText is temporarily rate limiting requests."
                        )
                    if response.status >= 400:
                        raise GenerateFancyTextAPIError(
                            "GenerateFancyText returned "
                            f"HTTP {response.status}."
                        )
                    try:
                        payload = await response.json(content_type=None)
                    except (aiohttp.ContentTypeError, ValueError):
                        raise GenerateFancyTextAPIError(
                            "GenerateFancyText returned invalid JSON."
                        ) from None
            except GenerateFancyTextAPIError:
                raise
            except (aiohttp.ClientError, asyncio.TimeoutError):
                raise GenerateFancyTextAPIError(
                    "GenerateFancyText is temporarily unavailable."
                ) from None

        if (
            not isinstance(payload, dict)
            or payload.get("success") is not True
            or not isinstance(payload.get("results"), list)
        ):
            raise GenerateFancyTextAPIError(
                "GenerateFancyText response does not contain valid results."
            )

        styles = [
            item["result"]
            for item in payload["results"]
            if isinstance(item, dict)
            and isinstance(item.get("result"), str)
            and item["result"].strip()
        ]
        if styles:
            self._cache[text] = (time.monotonic(), tuple(styles))
            self._cache.move_to_end(text)
            if len(self._cache) > CACHE_SIZE:
                self._cache.popitem(last=False)
        return styles

    def _get_cached(self, text: str) -> list[str] | None:
        cached = self._cache.get(text)
        if cached is None:
            return None
        created_at, styles = cached
        if time.monotonic() - created_at >= CACHE_TTL_SECONDS:
            del self._cache[text]
            return None
        self._cache.move_to_end(text)
        return list(styles)
