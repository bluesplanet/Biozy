import logging

import discord
from discord.ext import commands

from services.config_store import ConfigStoreError


logger = logging.getLogger(__name__)
CONFIRMATION_TIMEOUT_SECONDS = 30


class ClearConfiguredChannelView(discord.ui.View):
    def __init__(
        self,
        channel: discord.TextChannel,
        requester_id: int,
        guild: discord.Guild,
    ) -> None:
        super().__init__(timeout=CONFIRMATION_TIMEOUT_SECONDS)
        self.channel = channel
        self.requester_id = requester_id
        self.guild = guild
        self.prompt: discord.Message | None = None
        self.finished = False

    async def interaction_check(
        self,
        interaction: discord.Interaction,
    ) -> bool:
        if interaction.user.id != self.requester_id:
            await interaction.response.send_message(
                "Only the administrator who started this command can confirm it.",
                ephemeral=True,
            )
            return False
        return True

    async def on_timeout(self) -> None:
        await self._delete_prompt()

    async def on_error(
        self,
        interaction: discord.Interaction,
        error: Exception,
        item: discord.ui.Item[discord.ui.View],
    ) -> None:
        logger.error(
            "Unexpected admin confirmation interaction error (type=%s).",
            type(error).__name__,
            exc_info=(type(error), error, error.__traceback__),
        )
        try:
            response = (
                interaction.followup.send
                if interaction.response.is_done()
                else interaction.response.send_message
            )
            await response(
                "An unexpected error interrupted this action. "
                "No further cleanup will be attempted.",
                ephemeral=True,
                allowed_mentions=discord.AllowedMentions.none(),
            )
        except (discord.NotFound, discord.Forbidden, discord.HTTPException):
            logger.warning("Could not report admin interaction failure.")
        finally:
            self.finished = True
            await self._delete_prompt()
            self.stop()

    async def _delete_prompt(self) -> None:
        if self.prompt is None:
            return
        try:
            await self.prompt.delete()
        except discord.NotFound:
            pass
        except (discord.Forbidden, discord.HTTPException):
            logger.warning("Could not delete the cleanup confirmation prompt.")
        except Exception as error:
            logger.error(
                "Unexpected confirmation-prompt deletion failure (type=%s).",
                type(error).__name__,
            )

    @discord.ui.button(
        label="Confirmer la suppression",
        style=discord.ButtonStyle.danger,
    )
    async def confirm(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ) -> None:
        if self.finished:
            await interaction.response.send_message(
                "Cette confirmation a déjà été utilisée.",
                ephemeral=True,
            )
            return

        bot_member = self.guild.me
        permissions = (
            self.channel.permissions_for(bot_member)
            if bot_member is not None
            else None
        )
        if permissions is None or not (
            permissions.manage_messages and permissions.read_message_history
        ):
            self.finished = True
            await interaction.response.send_message(
                "I no longer have **Manage Messages** and **Read Message History** "
                "permissions in the configured channel.",
                ephemeral=True,
            )
            await self._delete_prompt()
            self.stop()
            return

        self.finished = True
        for child in self.children:
            if isinstance(child, discord.ui.Button):
                child.disabled = True
        await interaction.response.defer(ephemeral=True, thinking=True)

        deleted_count = 0
        try:
            deleted = await self.channel.purge(
                limit=None,
                before=interaction.created_at,
                check=lambda message: (
                    self.prompt is None or message.id != self.prompt.id
                ),
                reason=f"Nettoyage confirmé par l'administrateur {self.requester_id}",
            )
            deleted_count = len(deleted)
        except (discord.Forbidden, discord.HTTPException):
            logger.exception(
                "Channel cleanup failed for %s after %s deletions.",
                self.channel.id,
                deleted_count,
            )
            result = (
                "Cleanup failed or was interrupted. Some messages may already "
                "have been deleted; check the bot's permissions and try again."
            )
        else:
            result = (
                f"Cleanup complete: {deleted_count} message(s) deleted in "
                f"{self.channel.mention}."
            )

        try:
            await interaction.followup.send(
                result,
                ephemeral=True,
                allowed_mentions=discord.AllowedMentions.none(),
            )
        except (discord.NotFound, discord.Forbidden, discord.HTTPException):
            logger.warning("Could not send the channel-cleanup result.")
        finally:
            await self._delete_prompt()
            self.stop()

    @discord.ui.button(
        label="Annuler",
        style=discord.ButtonStyle.secondary,
    )
    async def cancel(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ) -> None:
        if self.finished:
            await interaction.response.send_message(
                "This confirmation has already been used.",
                ephemeral=True,
            )
            return
        self.finished = True
        await interaction.response.send_message(
            "Cleanup cancelled.",
            ephemeral=True,
        )
        await self._delete_prompt()
        self.stop()


class BioAdmin(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @commands.command(name="viderbio")
    @commands.guild_only()
    @commands.has_guild_permissions(administrator=True)
    async def clear_bio_channel(self, ctx: commands.Context) -> None:
        try:
            channel_id = self.bot.config_store.get_channel(ctx.guild.id)
        except ConfigStoreError:
            logger.exception(
                "Could not read the configuration for guild %s.",
                ctx.guild.id,
            )
            await ctx.send(
                "I couldn't read the Biozy channel configuration."
            )
            return

        if channel_id is None:
            await ctx.send(
                "No Biozy channel is configured. Set one with "
                "`.configbio #channel`."
            )
            return

        channel = ctx.guild.get_channel(channel_id)
        if not isinstance(channel, discord.TextChannel):
            await ctx.send(
                "The configured Biozy channel was not found or is not a text "
                "channel. Set one with `.configbio #channel`."
            )
            return

        bot_member = ctx.guild.me
        permissions = (
            channel.permissions_for(bot_member)
            if bot_member is not None
            else None
        )
        if permissions is None or not (
            permissions.view_channel
            and permissions.read_message_history
            and permissions.manage_messages
        ):
            await ctx.send(
                "I need **View Channel**, **Read Message History**, and "
                "**Manage Messages** permissions in the Biozy channel."
            )
            return

        view = ClearConfiguredChannelView(
            channel,
            ctx.author.id,
            ctx.guild,
        )
        prompt = await ctx.send(
            f"⚠️ Confirm deletion of all deletable messages in "
            f"{channel.mention}. This action cannot be undone. "
            f"Confirmation expires in {CONFIRMATION_TIMEOUT_SECONDS} seconds.",
            view=view,
            allowed_mentions=discord.AllowedMentions.none(),
        )
        view.prompt = prompt

    @staticmethod
    async def _send_error(ctx: commands.Context, content: str) -> None:
        try:
            await ctx.send(content)
        except (discord.Forbidden, discord.HTTPException):
            logger.warning("Could not send a viderbio error response.")
        except Exception as error:
            logger.error(
                "Unexpected viderbio error-response failure (type=%s).",
                type(error).__name__,
            )

    @clear_bio_channel.error
    async def clear_bio_channel_error(
        self,
        ctx: commands.Context,
        error: commands.CommandError,
    ) -> None:
        if isinstance(error, commands.MissingPermissions):
            await self._send_error(
                ctx,
                "Only server administrators can use this command."
            )
        elif isinstance(error, commands.NoPrivateMessage):
            await self._send_error(
                ctx,
                "This command can only be used in a Discord server.",
            )
        else:
            logger.error(
                "Error in the viderbio command (type=%s).",
                type(error).__name__,
            )
            await self._send_error(
                ctx,
                "An error occurred while preparing the cleanup.",
            )


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(BioAdmin(bot))
