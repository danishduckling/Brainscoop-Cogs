from .MusicLeague import MusicLeague


async def setup(bot):
    await bot.add_cog(MusicLeague(bot))
