from redbot.core import commands


class MusicLeague(commands.Cog):
    """Server-specific Music League commands."""

    def __init__(self, bot):
        self.bot = bot

    @commands.hybrid_command()
    async def musicleague(self, ctx):
        """Show the current Music League cog status."""
        await ctx.send(
            "Music League features are under development.",
            ephemeral=ctx.interaction is not None,
        )
