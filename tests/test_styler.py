import asyncio
import unittest
from unittest.mock import AsyncMock

from services.fancytext import FancyTextAPIError
from services.generatefancytext import GenerateFancyTextAPIError
from services.styler import TextStyler


class FakeAPI:
    def __init__(self, styles: list[str] | None = None, error: Exception | None = None):
        self.styles = styles or []
        self.error = error

    async def fetch_styles(self, text: str) -> list[str]:
        if self.error is not None:
            raise self.error
        return list(self.styles)


class TextStylerTests(unittest.IsolatedAsyncioTestCase):
    async def test_api_providers_are_requested_concurrently(self) -> None:
        started = 0
        both_started = asyncio.Event()

        class ConcurrentAPI:
            def __init__(self, styles: list[str]) -> None:
                self.styles = styles

            async def fetch_styles(self, text: str) -> list[str]:
                nonlocal started
                started += 1
                if started == 2:
                    both_started.set()
                await asyncio.wait_for(both_started.wait(), timeout=1)
                return self.styles

        styler = TextStyler(
            ConcurrentAPI(["𝓗𝓮𝓵𝓵𝓸"]),
            ConcurrentAPI(["𝔥𝔢𝔩𝔩𝔬"]),
        )

        batch = await styler.generate("Hello", AsyncMock())

        self.assertEqual(started, 2)
        self.assertTrue(batch.used_thefancytext)
        self.assertTrue(batch.used_generatefancytext)

    async def test_distinct_results_from_both_apis(self) -> None:
        styler = TextStyler(
            FakeAPI(["𝓗𝓮𝓵𝓵𝓸", "𝗛𝗲𝗹𝗹𝗼", "𝓗𝓮𝓵𝓵𝓸"]),
            FakeAPI(["𝔥𝔢𝔩𝔩𝔬", "𝙷𝚎𝚕𝚕𝚘"]),
        )
        progress = AsyncMock()

        batch = await styler.generate("Hello", progress)

        self.assertEqual(len(batch.suggestions), 5)
        self.assertEqual(len(set(batch.suggestions)), 5)
        self.assertTrue(batch.used_thefancytext)
        self.assertTrue(batch.used_generatefancytext)
        self.assertEqual(batch.warnings, ())

    async def test_api_errors_use_local_fallback(self) -> None:
        styler = TextStyler(
            FakeAPI(error=FancyTextAPIError("unavailable")),
            FakeAPI(error=GenerateFancyTextAPIError("unavailable")),
        )

        batch = await styler.generate("Me and You", AsyncMock())

        self.assertEqual(len(batch.suggestions), 5)
        self.assertEqual(len(set(batch.suggestions)), 5)
        self.assertEqual(len(batch.warnings), 2)
        self.assertFalse(batch.used_thefancytext)
        self.assertFalse(batch.used_generatefancytext)
        self.assertTrue(all("Me and You" in item for item in batch.suggestions))

    async def test_unexpected_provider_error_uses_other_api_and_local_fallback(self) -> None:
        styler = TextStyler(
            FakeAPI(error=RuntimeError("provider bug")),
            FakeAPI(["𝓗𝓮𝓵𝓵𝓸"]),
        )
        progress = AsyncMock()

        batch = await styler.generate("Hello", progress)

        self.assertTrue(batch.suggestions)
        self.assertEqual(batch.warnings, ("TheFancyText failed unexpectedly.",))
        self.assertTrue(batch.used_generatefancytext)
        progress.assert_any_await(
            "thefancy",
            "warning",
            "TheFancyText failed unexpectedly; fallback sources will be used.",
        )

    async def test_regeneration_avoids_previous_results(self) -> None:
        styler = TextStyler(
            FakeAPI(["𝓗𝓮𝓵𝓵𝓸", "𝗛𝗲𝗹𝗹𝗼", "𝔥𝔢𝔩𝔩𝔬"]),
            FakeAPI(["𝙷𝚎𝚕𝚕𝚘", "𝐇𝐞𝐥𝐥𝐨"]),
        )

        first = await styler.generate("Hello", AsyncMock())
        second = await styler.generate(
            "Hello",
            AsyncMock(),
            exclude=first.suggestions,
        )

        self.assertTrue(second.suggestions)
        self.assertFalse(set(first.suggestions) & set(second.suggestions))

    async def test_blank_or_oversized_text_is_rejected(self) -> None:
        styler = TextStyler(FakeAPI(), FakeAPI())

        with self.assertRaises(ValueError):
            await styler.generate("  ", AsyncMock())
        with self.assertRaises(ValueError):
            await styler.generate("x" * 501, AsyncMock())


if __name__ == "__main__":
    unittest.main()
