import logging
import os
from pathlib import Path
import sys

import aiohttp
import discord
from discord.ext import commands
from dotenv import load_dotenv

from services.config_store import ConfigStore
from services.fancytext import FancyTextAPI
from services.generatefancytext import GenerateFancyTextAPI
from services.styler import TextStyler


PROJECT_DIR = Path(__file__).resolve().parent
load_dotenv(PROJECT_DIR / ".env")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger("biozy")


class BiozyBot(commands.Bot):
    def __init__(self) -> None:
        intents = discord.Intents.none()
        intents.guilds = True
        intents.messages = True
        intents.message_content = True

        super().__init__(
            command_prefix=".",
            intents=intents,
            help_command=None,
        )
        self.config_store = ConfigStore(PROJECT_DIR / "data" / "config.json")
        self.http_session: aiohttp.ClientSession | None = None
        self.fancy_text = FancyTextAPI()
        self.generate_fancy_text = GenerateFancyTextAPI()
        self.styler: TextStyler | None = None

    async def setup_hook(self) -> None:
        try:
            self.config_store.load()
            self.http_session = aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=15)
            )
            await self.fancy_text.start(self.http_session)
            await self.generate_fancy_text.start(self.http_session)
            self.styler = TextStyler(
                self.fancy_text,
                self.generate_fancy_text,
            )

            cog_dir = PROJECT_DIR / "cogs"
            extensions = sorted(
                f"cogs.{path.stem}"
                for path in cog_dir.glob("*.py")
                if path.name != "__init__.py"
            )
            for extension in extensions:
                await self.load_extension(extension)
                logger.info("Loaded extension: %s", extension)
        except Exception as error:
            logger.error(
                "Startup initialization failed (type=%s).",
                type(error).__name__,
            )
            if self.http_session is not None and not self.http_session.closed:
                try:
                    await self.http_session.close()
                except Exception as close_error:
                    logger.error(
                        "Failed to close the HTTP session after startup failure "
                        "(type=%s).",
                        type(close_error).__name__,
                    )
                self.http_session = None
            raise

    async def on_ready(self) -> None:
        logger.info("Biozy is connected as %s.", self.user)

    async def on_error(self, event_method: str, *args: object, **kwargs: object) -> None:
        error = sys.exc_info()[1]
        logger.error(
            "Unhandled error in Discord event %s (type=%s).",
            event_method,
            type(error).__name__ if error is not None else "unknown",
        )

    async def on_command_error(
        self,
        ctx: commands.Context,
        error: commands.CommandError,
    ) -> None:
        if isinstance(error, commands.CommandNotFound):
            return
        if isinstance(error, commands.MissingPermissions):
            response = "You don't have permission to use this command."
        elif isinstance(error, commands.NoPrivateMessage):
            response = "This command must be used in a server."
        elif isinstance(error, commands.CommandOnCooldown):
            response = (
                f"Please wait {error.retry_after:.1f} second(s) before retrying."
            )
        else:
            cause = getattr(error, "original", error)
            logger.error(
                "Command %s failed (type=%s).",
                ctx.command.qualified_name if ctx.command else "unknown",
                type(cause).__name__,
            )
            response = (
                "An unexpected error occurred. Biozy is still running; "
                "please try again shortly."
            )

        try:
            await ctx.send(
                response,
                allowed_mentions=discord.AllowedMentions.none(),
            )
        except (discord.Forbidden, discord.HTTPException):
            logger.warning(
                "Could not send the command error response."
            )
        except Exception as send_error:
            logger.error(
                "Unexpected command error-response failure (type=%s).",
                type(send_error).__name__,
            )

    async def close(self) -> None:
        try:
            if self.http_session is not None and not self.http_session.closed:
                await self.http_session.close()
        finally:
            await super().close()


def main() -> None:
    token = os.getenv("DISCORD_TOKEN", "").strip()

    if not token:
        raise RuntimeError(
            "DISCORD_TOKEN is missing. Set it in the .env file."
        )

    bot = BiozyBot()
    try:
        bot.run(token)
    except Exception as error:
        logger.error(
            "The bot stopped because of an error (type=%s).",
            type(error).__name__,
        )
        raise


if __name__ == "__main__":
    main()
