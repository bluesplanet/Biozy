import asyncio
import logging
import re
import time
from collections import OrderedDict

import discord
from discord.ext import commands

from services.config_store import ConfigStoreError
from services.styler import ProgressCallback, SuggestionBatch


logger = logging.getLogger(__name__)
MAX_INPUT_LENGTH = 500
MAX_PROCESSED_MESSAGE_IDS = 4096
MAX_COOLDOWN_ENTRIES = 8192
USER_COOLDOWN_SECONDS = 15
RESULT_DELETE_AFTER_SECONDS = 60
NOTICE_DELETE_AFTER_SECONDS = 10

STAGE_LABELS = {
    "received": "Réception et validation",
    "privacy": "Suppression du message d'origine",
    "thefancy": "Étape 1/4 — TheFancyText",
    "generatefancy": "Étape 2/4 — GenerateFancyText",
    "compose": "Étape 3/4 — Composition des styles",
    "clean": "Étape 4/4 — Vérification des résultats",
    "done": "Traitement terminé",
    "error": "Error",
}
STATE_LABELS = {
    "active": "In progress",
    "success": "Completed",
    "warning": "Warning",
    "error": "Error",
}


class ProgressTracker:
    def __init__(self, channel: discord.abc.Messageable) -> None:
        self.channel = channel
        self.message: discord.Message | None = None
        self.steps: OrderedDict[str, tuple[str, str]] = OrderedDict()
        self._edit_lock = asyncio.Lock()
        self._delete_task: asyncio.Task[None] | None = None
        self._cleanup_tasks: set[asyncio.Task[None]] = set()

    async def start(self) -> None:
        self.steps["received"] = (
            "active",
            "Demande reçue. Biozy vérifie le texte et prépare le traitement.",
        )
        try:
            self.message = await self.channel.send(embed=self._build_embed())
        except (discord.Forbidden, discord.HTTPException):
            logger.warning("Could not create the progress embed.")

    async def update(self, stage: str, state: str, detail: str) -> None:
        async with self._edit_lock:
            self.steps[stage] = (state, detail)
            if self.message is None:
                return
            try:
                await self.message.edit(embed=self._build_embed())
            except (discord.Forbidden, discord.HTTPException):
                logger.warning(
                    "Could not update the progress embed."
                )

    async def complete(
        self,
        state: str,
        detail: str,
        view: discord.ui.View | None = None,
    ) -> bool:
        async with self._edit_lock:
            self.steps["done"] = (state, detail)
            embed = self._build_embed()
            if self.message is not None:
                try:
                    await self.message.edit(embed=embed, view=view)
                except (discord.Forbidden, discord.HTTPException):
                    logger.warning(
                        "Could not replace the progress embed."
                    )
                    self._schedule_message_cleanup(self.message)
                    self.message = None

            if self.message is None:
                try:
                    self.message = await self.channel.send(
                        embed=embed,
                        view=view,
                        allowed_mentions=discord.AllowedMentions.none(),
                    )
                except (discord.Forbidden, discord.HTTPException):
                    logger.warning("Could not display the final result.")
                    return False

            if self._delete_task is not None:
                self._delete_task.cancel()
            self._delete_task = asyncio.create_task(
                self._delete_after_completion()
            )
            return True

    def _schedule_message_cleanup(self, message: discord.Message) -> None:
        task = asyncio.create_task(self._delete_message_later(message))
        self._cleanup_tasks.add(task)
        task.add_done_callback(self._cleanup_tasks.discard)

    @staticmethod
    async def _delete_message_later(message: discord.Message) -> None:
        await asyncio.sleep(RESULT_DELETE_AFTER_SECONDS)
        try:
            await message.delete()
        except (discord.NotFound, discord.Forbidden, discord.HTTPException):
            logger.info("Could not delete an older progress embed.")
        except Exception:
            logger.error("Unexpected failure deleting an older progress embed.")

    async def _delete_after_completion(self) -> None:
        await asyncio.sleep(RESULT_DELETE_AFTER_SECONDS)
        if self.message is None:
            return
        try:
            await self.message.delete()
        except (discord.NotFound, discord.Forbidden, discord.HTTPException):
            logger.info("Could not delete the completed progress embed.")
        except Exception:
            logger.error("Unexpected failure deleting the completed progress embed.")

    def _build_embed(self) -> discord.Embed:
        states = {state for state, _ in self.steps.values()}
        if "error" in states:
            color = discord.Color.red()
        elif "warning" in states:
            color = discord.Color.orange()
        elif self.steps.get("done", (None,))[0] == "success":
            color = discord.Color.green()
        else:
            color = discord.Color.blue()

        embed = discord.Embed(
            title="Biozy — traitement de la demande",
            description=(
                "Suivi des étapes réellement exécutées : réception, suppression "
                "du message, appels aux services de styles, composition et "
                "vérification. Le texte soumis et les suggestions ne sont "
                "jamais affichés dans ce salon."
            ),
            color=color,
        )
        for stage, (state, detail) in self.steps.items():
            label = STAGE_LABELS.get(stage, stage)
            state_label = STATE_LABELS.get(state, state)
            embed.add_field(
                name=label,
                value=f"**{state_label}** — {detail}",
                inline=False,
            )
        return embed


def make_copyable_suggestion(suggestion: str) -> str:
    suggestion = " ".join(suggestion.split())
    longest_backtick_run = max(
        (len(run) for run in re.findall(r"`+", suggestion)),
        default=0,
    )
    longest_tilde_run = max(
        (len(run) for run in re.findall(r"~+", suggestion)),
        default=0,
    )
    delimiter, longest_run = min(
        (("`", longest_backtick_run), ("~", longest_tilde_run)),
        key=lambda item: item[1],
    )
    fence = delimiter * max(3, longest_run + 1)
    return f"{fence}text\n{suggestion}\n{fence}"


class SuggestionView(discord.ui.View):
    def __init__(
        self,
        author_id: int,
        suggestions: tuple[str, ...],
    ) -> None:
        super().__init__(timeout=RESULT_DELETE_AFTER_SECONDS)
        self.author_id = author_id
        self.suggestions = suggestions
        self._last_click: float | None = None
        self._delete_tasks: set[asyncio.Task[None]] = set()

    @discord.ui.button(
        label="Afficher mes suggestions en privé",
        style=discord.ButtonStyle.primary,
    )
    async def show_suggestions(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ) -> None:
        if interaction.user.id != self.author_id:
            await interaction.response.send_message(
                "Only the person who submitted the text can view these suggestions.",
                ephemeral=True,
            )
            return

        now = time.monotonic()
        if self._last_click is not None and now - self._last_click < 5:
            await interaction.response.send_message(
                "Please wait a few seconds before requesting the suggestions again.",
                ephemeral=True,
            )
            return
        self._last_click = now

        try:
            for index, suggestion in enumerate(self.suggestions):
                content = make_copyable_suggestion(suggestion)
                if index == 0:
                    await interaction.response.send_message(
                        content,
                        ephemeral=True,
                        allowed_mentions=discord.AllowedMentions.none(),
                    )
                    private_message = await interaction.original_response()
                else:
                    private_message = await interaction.followup.send(
                        content,
                        ephemeral=True,
                        allowed_mentions=discord.AllowedMentions.none(),
                        wait=True,
                    )
                self._schedule_private_cleanup(private_message)
        except asyncio.CancelledError:
            raise
        except (discord.Forbidden, discord.HTTPException) as error:
            logger.warning(
                "Discord rejected private suggestions (type=%s).",
                type(error).__name__,
            )
            await self._send_interaction_error(interaction)
        except Exception as error:
            logger.error(
                "Unexpected error while sending private suggestions "
                "(type=%s).",
                type(error).__name__,
            )
            await self._send_interaction_error(interaction)

    async def on_error(
        self,
        interaction: discord.Interaction,
        error: Exception,
        item: discord.ui.Item[discord.ui.View],
    ) -> None:
        logger.error(
            "Suggestion button failed (type=%s).",
            type(error).__name__,
        )
        await self._send_interaction_error(interaction)

    @staticmethod
    async def _send_interaction_error(
        interaction: discord.Interaction,
    ) -> None:
        content = (
            "I couldn't display all suggestions. Please click the button again."
        )
        try:
            if interaction.response.is_done():
                await interaction.followup.send(
                    content,
                    ephemeral=True,
                    allowed_mentions=discord.AllowedMentions.none(),
                )
            else:
                await interaction.response.send_message(
                    content,
                    ephemeral=True,
                    allowed_mentions=discord.AllowedMentions.none(),
                )
        except (discord.NotFound, discord.Forbidden, discord.HTTPException):
            logger.info("Could not report the interaction failure.")
        except Exception as error:
            logger.error(
                "Unexpected interaction error-response failure (type=%s).",
                type(error).__name__,
            )

    def _schedule_private_cleanup(self, message: discord.WebhookMessage) -> None:
        task = asyncio.create_task(self._delete_private_message_later(message))
        self._delete_tasks.add(task)
        task.add_done_callback(self._delete_tasks.discard)

    @staticmethod
    async def _delete_private_message_later(
        message: discord.WebhookMessage,
    ) -> None:
        await asyncio.sleep(RESULT_DELETE_AFTER_SECONDS)
        try:
            await message.delete()
        except (discord.NotFound, discord.Forbidden, discord.HTTPException):
            logger.info("Could not delete an ephemeral suggestion.")
        except Exception:
            logger.error("Unexpected failure deleting an ephemeral suggestion.")


class BioStyler(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self._seen_message_ids: OrderedDict[int, None] = OrderedDict()
        self._last_requests: OrderedDict[tuple[int, int], float] = OrderedDict()
        self._notice_tasks: set[asyncio.Task[None]] = set()

    async def cog_unload(self) -> None:
        for task in self._notice_tasks:
            task.cancel()
        self._notice_tasks.clear()

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message) -> None:
        try:
            await self._process_message(message)
        except asyncio.CancelledError:
            raise
        except Exception as error:
            logger.error(
                "Unexpected error while processing a message "
                "(guild=%s, type=%s).",
                message.guild.id if message.guild else "DM",
                type(error).__name__,
            )
            if message.guild is not None:
                try:
                    await self._send_emergency_notice(message)
                except Exception as notice_error:
                    logger.error(
                        "Unexpected failure while sending the emergency notice "
                        "(type=%s).",
                        type(notice_error).__name__,
                    )

    async def _process_message(self, message: discord.Message) -> None:
        if message.author.bot or message.guild is None:
            return
        if not message.content.strip() or message.content.lstrip().startswith("."):
            return

        try:
            configured_channel_id = self.bot.config_store.get_channel(
                message.guild.id
            )
        except ConfigStoreError:
            logger.error(
                "Could not read the configuration for guild %s.",
                message.guild.id,
            )
            await self._send_emergency_notice(message)
            return
        if configured_channel_id != message.channel.id:
            return
        if message.id in self._seen_message_ids:
            return

        self._seen_message_ids[message.id] = None
        if len(self._seen_message_ids) > MAX_PROCESSED_MESSAGE_IDS:
            self._seen_message_ids.popitem(last=False)

        now = time.monotonic()
        rate_limited = self._is_rate_limited(
            message.guild.id,
            message.author.id,
            now,
        )

        progress = ProgressTracker(message.channel)
        await progress.start()

        deleted = await self._delete_original(message, progress)
        if not deleted:
            await self._send_public_notice(
                message,
                "I couldn't delete your message. It may remain visible in "
                "the channel; delete it manually if you don't want it to stay "
                "visible.",
            )

        if len(message.content) > MAX_INPUT_LENGTH:
            await progress.update(
                "received",
                "error",
                "The text exceeds the 500-character limit.",
            )
            await progress.update(
                "error",
                "error",
                "The request was not sent to the APIs.",
            )
            await self._send_public_error(
                message,
                "Your text is too long. The limit is 500 characters.",
                progress,
            )
            return

        await progress.update(
            "received",
            "success",
            "Texte validé ; le contenu n'est pas affiché.",
        )

        if rate_limited:
            await progress.complete(
                "warning",
                "Request rate limited. Please wait before sending another one.",
            )
            await self._send_public_notice(
                message,
                "Biozy limits repeated requests. Please wait a few seconds "
                "before trying again.",
            )
            return

        styler = getattr(self.bot, "styler", None)
        if styler is None:
            await progress.update(
                "error",
                "error",
                "The styling service is unavailable.",
            )
            await self._send_public_error(
                message,
                "Biozy can't process this request right now.",
                progress,
            )
            return

        try:
            batch = await styler.generate(message.content, progress.update)
        except Exception as error:
            logger.error(
                "Request processing failed (type=%s).",
                type(error).__name__,
            )
            await progress.update(
                "error",
                "error",
                "Text styling could not be completed.",
            )
            await self._send_public_error(
                message,
                "I couldn't create suggestions right now.",
                progress,
            )
            return

        await self._deliver_batch(message, batch, progress)

    @staticmethod
    async def _send_emergency_notice(message: discord.Message) -> None:
        try:
            await message.channel.send(
                "Biozy encountered an error while processing this request. "
                "The bot is still running; please try again shortly.",
                delete_after=NOTICE_DELETE_AFTER_SECONDS,
                allowed_mentions=discord.AllowedMentions.none(),
            )
        except (discord.Forbidden, discord.HTTPException):
            logger.warning(
                "Could not send the emergency error notice."
            )

    def _is_rate_limited(
        self,
        guild_id: int,
        user_id: int,
        now: float,
    ) -> bool:
        request_key = (guild_id, user_id)
        last_request = self._last_requests.get(request_key)
        if last_request is not None and now - last_request < USER_COOLDOWN_SECONDS:
            return True

        self._last_requests[request_key] = now
        self._last_requests.move_to_end(request_key)
        if len(self._last_requests) > MAX_COOLDOWN_ENTRIES:
            self._last_requests.popitem(last=False)
        return False

    async def _delete_original(
        self,
        message: discord.Message,
        progress: ProgressTracker,
    ) -> bool:
        bot_member = message.guild.me
        if bot_member is None:
            await progress.update(
                "privacy",
                "warning",
                "The bot's channel permissions are unavailable.",
            )
            return False
        permissions = message.channel.permissions_for(bot_member)
        if not permissions.manage_messages:
            await progress.update(
                "privacy",
                "warning",
                "The bot is missing permission to delete the original message.",
            )
            return False

        try:
            await message.delete()
        except discord.NotFound:
            return True
        except (discord.Forbidden, discord.HTTPException):
            await progress.update(
                "privacy",
                "warning",
                "Deleting the original message failed.",
            )
            return False

        await progress.update(
            "privacy",
            "success",
            "The original message was deleted.",
        )
        return True

    async def _deliver_batch(
        self,
        message: discord.Message,
        batch: SuggestionBatch,
        progress: ProgressTracker,
    ) -> None:
        warning = bool(batch.warnings)
        detail = (
            f"{len(batch.suggestions)} suggestions prêtes. "
            "Clique sur le bouton pour les recevoir en privé. "
            "Ce suivi sera supprimé après 1 minute."
        )
        if warning:
            detail += " A provider was unavailable; fallback results were used."

        view = SuggestionView(message.author.id, batch.suggestions)
        shown = await progress.complete(
            "warning" if warning else "success",
            detail,
            view,
        )
        if not shown:
            await self._send_public_notice(
                message,
                "I couldn't display the suggestions. Check my Send Messages "
                "and Embed Links permissions in this channel.",
            )

    async def _send_public_error(
        self,
        message: discord.Message,
        content: str,
        progress: ProgressTracker,
    ) -> None:
        await progress.complete("error", content)
        await self._send_public_notice(message, content)

    async def _send_public_notice(
        self,
        message: discord.Message,
        content: str,
    ) -> None:
        try:
            notice = await message.channel.send(
                f"{message.author.mention} — {content}",
                allowed_mentions=discord.AllowedMentions(users=[message.author]),
            )
        except (discord.Forbidden, discord.HTTPException):
            logger.warning("Could not send the temporary public notice.")
            return

        task = asyncio.create_task(self._delete_notice_later(notice))
        self._notice_tasks.add(task)
        task.add_done_callback(self._notice_tasks.discard)

    @staticmethod
    async def _delete_notice_later(notice: discord.Message) -> None:
        try:
            await asyncio.sleep(NOTICE_DELETE_AFTER_SECONDS)
            await notice.delete()
        except asyncio.CancelledError:
            raise
        except (discord.NotFound, discord.Forbidden, discord.HTTPException):
            logger.info("Could not delete a temporary public notice.")
        except Exception:
            logger.error("Unexpected failure deleting a temporary public notice.")


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(BioStyler(bot))
