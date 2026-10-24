from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock

import discord
from discord.ext import commands

from main import BiozyBot


class ErrorHandlingTests(unittest.IsolatedAsyncioTestCase):
    async def test_command_failure_gets_english_response_without_exception_text(self) -> None:
        bot = BiozyBot()
        ctx = SimpleNamespace(
            command=None,
            send=AsyncMock(),
        )
        error = commands.CommandInvokeError(
            RuntimeError("PRIVATE_INPUT_SHOULD_NOT_BE_LOGGED")
        )

        with self.assertLogs("biozy", level="ERROR") as captured:
            await bot.on_command_error(ctx, error)

        ctx.send.assert_awaited_once()
        self.assertIn("unexpected error", ctx.send.await_args.args[0].lower())
        self.assertIsInstance(
            ctx.send.await_args.kwargs["allowed_mentions"],
            discord.AllowedMentions,
        )
        self.assertNotIn(
            "PRIVATE_INPUT_SHOULD_NOT_BE_LOGGED",
            "\n".join(captured.output),
        )

    async def test_command_error_response_failure_is_logged_and_suppressed(self) -> None:
        bot = BiozyBot()
        ctx = SimpleNamespace(
            command=None,
            send=AsyncMock(
                side_effect=discord.Forbidden(
                    SimpleNamespace(status=403, reason="Forbidden"),
                    "Forbidden",
                )
            ),
        )

        with self.assertLogs("biozy", level="WARNING"):
            await bot.on_command_error(ctx, commands.MissingPermissions(["manage_messages"]))

        ctx.send.assert_awaited_once()


if __name__ == "__main__":
    unittest.main()
