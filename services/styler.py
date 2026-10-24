import asyncio
import logging
import random
from collections.abc import Awaitable, Callable, Collection
from dataclasses import dataclass

from services.fancytext import FancyTextAPI, FancyTextAPIError, MAX_TEXT_LENGTH
from services.generatefancytext import (
    GenerateFancyTextAPI,
    GenerateFancyTextAPIError,
)


MAX_SUGGESTIONS = 5
MAX_SUGGESTION_LENGTH = 950
ProgressCallback = Callable[[str, str, str], Awaitable[None]]
logger = logging.getLogger(__name__)

DECORATIONS = (
    ("꧁ ", " ꧂"),
    ("★彡 ", " 彡★"),
    ("♡ ", " ♡"),
    ("『", "』"),
    ("✧ ", " ✧"),
    ("༺ ", " ༻"),
    ("「", "」"),
    ("ღ ", " ღ"),
    ("•° ", " °•"),
    ("〔", "〕"),
)


@dataclass(frozen=True)
class SuggestionBatch:
    suggestions: tuple[str, ...]
    warnings: tuple[str, ...]
    used_thefancytext: bool
    used_generatefancytext: bool


class TextStyler:
    def __init__(
        self,
        thefancytext: FancyTextAPI,
        generatefancytext: GenerateFancyTextAPI,
    ) -> None:
        self.thefancytext = thefancytext
        self.generatefancytext = generatefancytext

    async def generate(
        self,
        text: str,
        progress: ProgressCallback,
        exclude: Collection[str] = (),
    ) -> SuggestionBatch:
        if not text.strip():
            raise ValueError("Text cannot be empty.")
        if len(text) > MAX_TEXT_LENGTH:
            raise ValueError("Text exceeds the 500-character limit.")

        warnings: list[str] = []
        api_results: dict[str, list[str]] = {
            "TheFancyText": [],
            "GenerateFancyText": [],
        }

        async def fetch_thefancytext() -> None:
            await progress(
                "thefancy",
                "active",
                "Appel à TheFancyText en cours.",
            )
            try:
                api_results["TheFancyText"] = (
                    await self.thefancytext.fetch_styles(text)
                )
            except FancyTextAPIError:
                warnings.append("TheFancyText is unavailable.")
                await progress(
                    "thefancy",
                    "warning",
                    "TheFancyText is unavailable; other sources will be used.",
                )
            else:
                await progress(
                    "thefancy",
                    "success",
                    "Variantes TheFancyText récupérées.",
                )

        async def fetch_generatefancytext() -> None:
            await progress(
                "generatefancy",
                "active",
                "Appel à GenerateFancyText en cours.",
            )
            try:
                api_results["GenerateFancyText"] = (
                    await self.generatefancytext.fetch_styles(text)
                )
            except GenerateFancyTextAPIError:
                warnings.append("GenerateFancyText is unavailable.")
                await progress(
                    "generatefancy",
                    "warning",
                    "GenerateFancyText is unavailable; other sources will be used.",
                )
            else:
                await progress(
                    "generatefancy",
                    "success",
                    "Variantes GenerateFancyText récupérées.",
                )

        provider_results = await asyncio.gather(
            fetch_thefancytext(),
            fetch_generatefancytext(),
            return_exceptions=True,
        )
        provider_stages = (
            ("thefancy", "TheFancyText"),
            ("generatefancy", "GenerateFancyText"),
        )
        for (stage, provider), provider_result in zip(
            provider_stages,
            provider_results,
            strict=True,
        ):
            if isinstance(provider_result, asyncio.CancelledError):
                raise provider_result
            if isinstance(provider_result, Exception):
                logger.error(
                    "%s failed unexpectedly (type=%s).",
                    provider,
                    type(provider_result).__name__,
                )
                warnings.append(f"{provider} failed unexpectedly.")
                try:
                    await progress(
                        stage,
                        "warning",
                        f"{provider} failed unexpectedly; fallback sources will be used.",
                    )
                except asyncio.CancelledError:
                    raise
                except Exception as progress_error:
                    logger.error(
                        "Could not update the progress message for %s "
                        "(type=%s).",
                        provider,
                        type(progress_error).__name__,
                    )

        await progress("compose", "active", "Composition des variantes.")
        source_candidates: list[list[str]] = []
        for source in ("TheFancyText", "GenerateFancyText"):
            seen_in_source: set[str] = set()
            candidates = []
            for candidate in api_results[source]:
                cleaned = candidate.strip()
                if (
                    cleaned
                    and cleaned != text
                    and len(cleaned) <= MAX_SUGGESTION_LENGTH
                    and cleaned not in seen_in_source
                ):
                    seen_in_source.add(cleaned)
                    candidates.append(cleaned)
            random.shuffle(candidates)
            source_candidates.append(candidates)

        bases = self._interleave(source_candidates)
        if not bases:
            bases = [text]
        elif text not in bases:
            bases.append(text)

        await progress(
            "clean",
            "active",
            "Suppression des doublons et des variantes invalides.",
        )
        suggestions: list[str] = []
        excluded = set(exclude)
        decoration_order = list(DECORATIONS)
        random.shuffle(decoration_order)

        for decoration in decoration_order:
            prefix, suffix = decoration
            candidates = []
            for base in bases:
                if base.startswith(prefix) and base.endswith(suffix):
                    continue

                styled = f"{prefix}{base}{suffix}"
                if (
                    len(styled) <= MAX_SUGGESTION_LENGTH
                    and styled not in excluded
                    and styled not in suggestions
                ):
                    candidates.append(styled)

            if candidates:
                random.shuffle(candidates)
                suggestions.append(candidates[0])
            if len(suggestions) >= MAX_SUGGESTIONS:
                break

        if not suggestions:
            raise ValueError("No usable suggestions could be created.")

        await progress(
            "clean",
            "success",
            f"{len(suggestions)} suggestions distinctes sont prêtes.",
        )
        return SuggestionBatch(
            suggestions=tuple(suggestions),
            warnings=tuple(warnings),
            used_thefancytext=bool(api_results["TheFancyText"]),
            used_generatefancytext=bool(api_results["GenerateFancyText"]),
        )

    @staticmethod
    def _interleave(sources: list[list[str]]) -> list[str]:
        interleaved: list[str] = []
        seen: set[str] = set()
        while any(sources):
            for source in sources:
                if source:
                    candidate = source.pop()
                    if candidate not in seen:
                        interleaved.append(candidate)
                        seen.add(candidate)
        return interleaved
