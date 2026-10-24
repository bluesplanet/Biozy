import logging

import discord
from discord.ext import commands

from services.config_store import ConfigStoreError


logger = logging.getLogger(__name__)


class BioConfig(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @commands.command(name="configbio")
    @commands.has_guild_permissions(administrator=True)
    @commands.guild_only()
    async def configbio(
        self,
        ctx: commands.Context,
        *,
        destination: str | None = None,
    ) -> None:
        if destination is None:
            try:
                channel_id = self.bot.config_store.get_channel(ctx.guild.id)
            except ConfigStoreError:
                logger.exception(
                    "Could not read the configuration for guild %s.",
                    ctx.guild.id,
                )
                await ctx.send(
                    "I couldn't read the configuration. Check "
                    "`data/config.json`."
                )
                return
            if channel_id is None:
                await ctx.send(
                    "No channel is configured. Use `.configbio #channel` "
                    "to choose one."
                )
                return
            channel = ctx.guild.get_channel(channel_id)
            if channel is None:
                await ctx.send(
                    "The configured channel is no longer accessible. Set a "
                    "new channel with `.configbio #channel`."
                )
                return

            bot_member = ctx.guild.me
            permissions = channel.permissions_for(bot_member)
            privacy_note = (
                "La permission **Gérer les messages** est accordée."
                if permissions.manage_messages
                else "Attention : sans **Gérer les messages**, le message "
                "d'origine ne pourra pas être supprimé automatiquement."
            )
            await ctx.send(
                f"Salon surveillé : {channel.mention}\n{privacy_note}"
            )
            return

        if destination and destination.lower() == "off":
            await self._disable(ctx)
            return

        try:
            channel = await commands.TextChannelConverter().convert(
                ctx,
                destination,
            )
        except commands.BadArgument:
            await ctx.send(
                "Channel not found. Mention a text channel, for example "
                "`.configbio #bios`."
            )
            return

        bot_member = ctx.guild.me
        permissions = channel.permissions_for(bot_member)
        if not (
            permissions.view_channel
            and permissions.send_messages
            and permissions.embed_links
        ):
            await ctx.send(
                f"I don't have the required permissions in {channel.mention}. "
                "I need to view the channel, send messages, and embed links "
                "for progress updates."
            )
            return

        try:
            self.bot.config_store.set_channel(ctx.guild.id, channel.id)
        except ConfigStoreError:
            logger.exception(
                "Failed to save configuration for guild %s.",
                ctx.guild.id,
            )
            await ctx.send(
                "I couldn't save the configuration. Check the permissions "
                "on `data/config.json`."
            )
            return

        privacy_note = (
            "La suppression automatique des messages est possible."
            if permissions.manage_messages
            else "Attention : il me manque **Gérer les messages** pour supprimer "
            "automatiquement les textes publiés."
        )
        await ctx.send(
            f"Stylisation activée dans {channel.mention}. {privacy_note}"
        )

    async def _disable(self, ctx: commands.Context) -> None:
        try:
            self.bot.config_store.disable_guild(ctx.guild.id)
        except ConfigStoreError:
            logger.exception(
                "Failed to disable Biozy for guild %s.",
                ctx.guild.id,
            )
            await ctx.send(
                "I couldn't save the disabled state. Check the permissions "
                "on `data/config.json`."
            )
            return

        await ctx.send("Stylisation désactivée sur ce serveur.")

    @staticmethod
    async def _send_error(ctx: commands.Context, content: str) -> None:
        try:
            await ctx.send(content)
        except (discord.Forbidden, discord.HTTPException):
            logger.warning("Could not send a configbio error response.")
        except Exception as error:
            logger.error(
                "Unexpected configbio error-response failure (type=%s).",
                type(error).__name__,
            )

    @configbio.error
    async def configbio_error(
        self,
        ctx: commands.Context,
        error: commands.CommandError,
    ) -> None:
        if isinstance(error, commands.MissingPermissions):
            await self._send_error(
                ctx,
                "Only server administrators can configure Biozy."
            )
        elif isinstance(error, commands.NoPrivateMessage):
            await self._send_error(
                ctx,
                "This command can only be used in a Discord server.",
            )
        else:
            logger.error(
                "Error in the configbio command (type=%s).",
                type(error).__name__,
            )
            await self._send_error(
                ctx,
                "An error occurred while configuring Biozy.",
            )


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(BioConfig(bot))
