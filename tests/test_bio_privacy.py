from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

import discord

from cogs.bio import (
    BioStyler,
    ProgressTracker,
    RESULT_DELETE_AFTER_SECONDS,
    make_copyable_suggestion,
)
from cogs.admin import ClearConfiguredChannelView
from services.styler import SuggestionBatch


def forbidden_error() -> discord.Forbidden:
    response = SimpleNamespace(status=403, reason="Forbidden")
    return discord.Forbidden(response, "Forbidden")


class BioPrivacyTests(unittest.IsolatedAsyncioTestCase):
    async def test_rate_limit_is_scoped_to_user_and_guild(self) -> None:
        cog = BioStyler(SimpleNamespace())

        self.assertFalse(cog._is_rate_limited(100, 7, 10.0))
        self.assertTrue(cog._is_rate_limited(100, 7, 12.0))
        self.assertFalse(cog._is_rate_limited(200, 7, 12.0))
        self.assertFalse(cog._is_rate_limited(100, 8, 12.0))

    async def test_unexpected_message_error_is_reported_without_propagating(self) -> None:
        cog = BioStyler(SimpleNamespace())
        cog._process_message = AsyncMock(
            side_effect=RuntimeError("PRIVATE_TEXT_DO_NOT_LOG")
        )
        cog._send_emergency_notice = AsyncMock()
        message = SimpleNamespace(
            guild=SimpleNamespace(id=123),
        )

        with self.assertLogs("cogs.bio", level="ERROR") as captured:
            await cog.on_message(message)

        cog._process_message.assert_awaited_once_with(message)
        cog._send_emergency_notice.assert_awaited_once_with(message)
        self.assertNotIn("PRIVATE_TEXT_DO_NOT_LOG", "\n".join(captured.output))

    async def test_message_is_not_deleted_without_manage_permission(self) -> None:
        cog = BioStyler(SimpleNamespace())
        message = SimpleNamespace(
            guild=SimpleNamespace(me=object()),
            channel=SimpleNamespace(
                permissions_for=MagicMock(
                    return_value=SimpleNamespace(manage_messages=False)
                )
            ),
            delete=AsyncMock(),
        )
        progress = SimpleNamespace(update=AsyncMock())

        deleted = await cog._delete_original(message, progress)

        self.assertFalse(deleted)
        message.delete.assert_not_awaited()
        progress.update.assert_awaited_once()

    async def test_deletion_permission_and_http_error_are_handled(self) -> None:
        cog = BioStyler(SimpleNamespace())
        message = SimpleNamespace(
            guild=SimpleNamespace(me=object()),
            channel=SimpleNamespace(
                permissions_for=MagicMock(
                    return_value=SimpleNamespace(manage_messages=True)
                )
            ),
            delete=AsyncMock(side_effect=forbidden_error()),
        )
        progress = SimpleNamespace(update=AsyncMock())

        deleted = await cog._delete_original(message, progress)

        self.assertFalse(deleted)
        message.delete.assert_awaited_once()
        progress.update.assert_awaited_once()

    async def test_progress_embed_exposes_button_not_public_suggestions(self) -> None:
        channel = SimpleNamespace(send=AsyncMock())
        author = SimpleNamespace(id=123, mention="<@123>", send=AsyncMock())
        message = SimpleNamespace(author=author, channel=channel, content="bio")
        progress = ProgressTracker(channel)
        progress.message = SimpleNamespace(edit=AsyncMock(), delete=AsyncMock())
        batch = SuggestionBatch(("first style", "second style"), (), True, True)

        with patch("cogs.bio.asyncio.sleep", new=AsyncMock()) as sleep:
            await BioStyler(SimpleNamespace())._deliver_batch(
                message,
                batch,
                progress,
            )
            await progress._delete_task

        channel.send.assert_not_awaited()
        author.send.assert_not_awaited()
        embed = progress.message.edit.await_args.kwargs["embed"]
        self.assertEqual(embed.title, "Biozy — traitement de la demande")
        self.assertNotIn("first style", str(embed.to_dict()))
        view = progress.message.edit.await_args.kwargs["view"]
        self.assertEqual(len(view.children), 1)
        self.assertIn("Afficher mes suggestions en privé", view.children[0].label)
        sleep.assert_awaited_once_with(RESULT_DELETE_AFTER_SECONDS)
        progress.message.delete.assert_awaited_once()

    async def test_progress_embed_stays_compact_and_shows_current_step_only(self) -> None:
        tracker = ProgressTracker(SimpleNamespace())
        tracker.steps["received"] = ("success", "Request received.")
        tracker.steps["thefancy"] = ("success", "Provider response received.")
        tracker.steps["compose"] = ("active", "Composing suggestions.")

        embed = tracker._build_embed()

        self.assertEqual(len(embed.fields), 1)
        self.assertEqual(embed.fields[0].name, "Étape 3/4 — Composition des styles")
        self.assertIn("Composing suggestions.", embed.fields[0].value)
        self.assertNotIn("Request received.", str(embed.to_dict()))

    async def test_button_delivers_every_copyable_suggestion_ephemerally(self) -> None:
        from cogs.bio import SuggestionView

        private_messages = [
            SimpleNamespace(delete=AsyncMock()),
            SimpleNamespace(delete=AsyncMock()),
        ]
        dismiss_progress = AsyncMock()
        view = SuggestionView(
            123,
            ("first style", "second\nstyle"),
            on_show=dismiss_progress,
        )
        interaction = SimpleNamespace(
            user=SimpleNamespace(id=123),
            response=SimpleNamespace(send_message=AsyncMock()),
            followup=SimpleNamespace(send=AsyncMock(return_value=private_messages[1])),
            original_response=AsyncMock(return_value=private_messages[0]),
        )
        button = view.children[0]

        with patch("cogs.bio.asyncio.sleep", new=AsyncMock()) as sleep:
            await button.callback(interaction)
            for task in tuple(view._delete_tasks):
                await task

        interaction.response.send_message.assert_awaited_once()
        dismiss_progress.assert_awaited_once()
        interaction.followup.send.assert_awaited_once()
        first = interaction.response.send_message.await_args
        second = interaction.followup.send.await_args
        self.assertIn("first style", first.args[0])
        self.assertIn("```text\nsecond style\n```", second.args[0])
        for call in (first, second):
            self.assertTrue(call.kwargs["ephemeral"])
            self.assertIsInstance(
                call.kwargs["allowed_mentions"],
                discord.AllowedMentions,
            )
        for private_message in private_messages:
            private_message.delete.assert_awaited_once()
        self.assertEqual(sleep.await_count, 2)

    async def test_button_does_not_show_suggestions_to_another_member(self) -> None:
        from cogs.bio import SuggestionView

        view = SuggestionView(123, ("private suggestion",))
        interaction = SimpleNamespace(
            user=SimpleNamespace(id=456),
            response=SimpleNamespace(send_message=AsyncMock()),
            followup=SimpleNamespace(send=AsyncMock()),
        )

        await view.children[0].callback(interaction)

        interaction.response.send_message.assert_awaited_once()
        interaction.followup.send.assert_not_awaited()
        self.assertTrue(
            interaction.response.send_message.await_args.kwargs["ephemeral"]
        )
        self.assertNotIn(
            "private suggestion",
            interaction.response.send_message.await_args.args[0],
        )

    def test_code_fences_do_not_break_when_text_contains_backticks(self) -> None:
        rendered = make_copyable_suggestion("texte ``` à copier")

        self.assertIn("~~~text", rendered)
        self.assertIn("texte ``` à copier", rendered)
        self.assertTrue(rendered.endswith("~~~"))
        self.assertLess(len(rendered), 2000)

    def test_copyable_suggestion_is_normalized_to_one_line(self) -> None:
        rendered = make_copyable_suggestion("texte\nsur deux lignes")

        self.assertIn("texte sur deux lignes", rendered)
        self.assertNotIn("texte\nsur deux lignes", rendered)

    async def test_failed_result_embed_falls_back_to_public_notice(self) -> None:
        channel = SimpleNamespace(send=AsyncMock(side_effect=discord.HTTPException(
            SimpleNamespace(status=500, reason="Internal Server Error"),
            "failed",
        )))
        author = SimpleNamespace(id=123, mention="<@123>", send=AsyncMock())
        message = SimpleNamespace(author=author, channel=channel, content="bio")
        progress = ProgressTracker(channel)
        progress.message = SimpleNamespace(
            edit=AsyncMock(side_effect=discord.HTTPException(
                SimpleNamespace(status=500, reason="Internal Server Error"),
                "failed",
            )),
            delete=AsyncMock(),
        )
        stale_progress_message = progress.message
        batch = SuggestionBatch(("first style", "second style"), (), True, True)
        cog = BioStyler(SimpleNamespace())
        cog._send_public_notice = AsyncMock()

        with patch("cogs.bio.asyncio.sleep", new=AsyncMock()) as sleep:
            await cog._deliver_batch(message, batch, progress)
            for task in tuple(progress._cleanup_tasks):
                await task

        channel.send.assert_awaited_once()
        author.send.assert_not_awaited()
        cog._send_public_notice.assert_awaited_once()
        stale_progress_message.delete.assert_awaited_once()
        sleep.assert_awaited_once_with(RESULT_DELETE_AFTER_SECONDS)

    async def test_progress_embed_never_contains_submitted_text(self) -> None:
        tracker = ProgressTracker(SimpleNamespace())
        tracker.steps["received"] = ("success", "Demande reçue.")
        tracker.steps["thefancy"] = ("warning", "API indisponible.")

        embed = tracker._build_embed()

        rendered = " ".join(
            [embed.description or ""]
            + [f"{field.name} {field.value}" for field in embed.fields]
        )
        self.assertNotIn("private bio", rendered)

    async def test_completed_progress_embed_is_deleted_after_one_minute(self) -> None:
        tracker = ProgressTracker(SimpleNamespace())
        tracker.message = SimpleNamespace(
            edit=AsyncMock(),
            delete=AsyncMock(),
        )

        with patch("cogs.bio.asyncio.sleep", new=AsyncMock()) as sleep:
            await tracker.complete("success", "Traitement terminé.")
            await tracker._delete_task

        sleep.assert_awaited_once_with(RESULT_DELETE_AFTER_SECONDS)
        tracker.message.delete.assert_awaited_once()

    async def test_progress_embed_can_be_dismissed_immediately(self) -> None:
        tracker = ProgressTracker(SimpleNamespace())
        message = SimpleNamespace(delete=AsyncMock())
        tracker.message = message

        await tracker.dismiss()

        message.delete.assert_awaited_once()
        self.assertIsNone(tracker.message)

    async def test_admin_clear_confirmation_purges_configured_channel(self) -> None:
        prompt = SimpleNamespace(id=789, delete=AsyncMock())
        channel = SimpleNamespace(
            id=456,
            mention="<#456>",
            permissions_for=MagicMock(
                return_value=SimpleNamespace(
                    manage_messages=True,
                    read_message_history=True,
                )
            ),
            purge=AsyncMock(return_value=[object(), object()]),
        )
        guild = SimpleNamespace(me=object())
        view = ClearConfiguredChannelView(channel, 123, guild)
        view.prompt = prompt
        interaction = SimpleNamespace(
            user=SimpleNamespace(id=123),
            created_at="before-confirmation",
            response=SimpleNamespace(defer=AsyncMock()),
            followup=SimpleNamespace(send=AsyncMock()),
        )

        await view.children[0].callback(interaction)

        channel.purge.assert_awaited_once()
        purge_kwargs = channel.purge.await_args.kwargs
        self.assertIsNone(purge_kwargs["limit"])
        self.assertEqual(purge_kwargs["before"], interaction.created_at)
        self.assertFalse(purge_kwargs["check"](prompt))
        self.assertTrue(purge_kwargs["check"](SimpleNamespace(id=790)))
        prompt.delete.assert_awaited_once()
        self.assertIn("2 message(s)", interaction.followup.send.await_args.args[0])

    async def test_admin_clear_cannot_be_confirmed_by_another_member(self) -> None:
        channel = SimpleNamespace()
        view = ClearConfiguredChannelView(
            channel,
            123,
            SimpleNamespace(me=object()),
        )
        interaction = SimpleNamespace(
            user=SimpleNamespace(id=456),
            response=SimpleNamespace(send_message=AsyncMock()),
        )

        allowed = await view.interaction_check(interaction)

        self.assertFalse(allowed)
        interaction.response.send_message.assert_awaited_once()
        self.assertTrue(
            interaction.response.send_message.await_args.kwargs["ephemeral"]
        )


if __name__ == "__main__":
    unittest.main()
