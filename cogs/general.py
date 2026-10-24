import discord
from discord.ext import commands


class General(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @commands.command(name="help")
    async def help_command(self, ctx: commands.Context) -> None:
        embed = discord.Embed(
            title="Biozy — aide",
            description=(
                "Envoie un texte dans le salon configuré. Un embed suit les "
                "étapes du traitement. À la fin, clique sur le bouton pour "
                "recevoir tes suggestions en privé ; le suivi est supprimé "
                "après 1 minute."
            ),
            color=discord.Color.blurple(),
        )
        embed.add_field(
            name=".help",
            value="Affiche cette aide.",
            inline=False,
        )
        embed.add_field(
            name=".ping",
            value="Affiche la latence de Biozy.",
            inline=False,
        )
        embed.add_field(
            name=".configbio",
            value=(
                "Affiche le salon configuré. Utilise `.configbio #salon` "
                "pour le changer."
            ),
            inline=False,
        )
        embed.add_field(
            name=".configbio #salon",
            value="Définit le salon surveillé (administrateurs uniquement).",
            inline=False,
        )
        embed.add_field(
            name=".configbio off",
            value="Désactive la stylisation sur ce serveur.",
            inline=False,
        )
        embed.add_field(
            name=".viderbio",
            value=(
                "Nettoie le salon Biozy configuré après confirmation "
                "(administrateurs uniquement)."
            ),
            inline=False,
        )
        embed.add_field(
            name="Visibilité",
            value=(
                "Les suggestions ne sont visibles que par leur auteur via une "
                "réponse éphémère au bouton. Le bot a besoin de **Gérer les "
                "messages** pour retirer le texte d'origine et garder le "
                "salon propre. Le résultat disparaît après 1 minute."
            ),
            inline=False,
        )
        await ctx.send(embed=embed)

    @commands.command(name="ping")
    async def ping(self, ctx: commands.Context) -> None:
        latency_ms = round(self.bot.latency * 1000)
        await ctx.send(f"Pong ! Latence : {latency_ms} ms.")


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(General(bot))
