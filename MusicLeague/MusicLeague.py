import json
from io import BytesIO
from urllib.parse import urlsplit

import discord
from redbot.core import Config, commands
from redbot.core.utils.chat_formatting import pagify


class MusicLeague(commands.Cog):
    """Server-specific Music League commands."""

    def __init__(self, bot):
        self.bot = bot
        self.config = Config.get_conf(self, identifier=817362450991, force_registration=True)
        self.config.register_guild(submissions=[])

    @commands.hybrid_group(invoke_without_command=True)
    @commands.guild_only()
    async def musicleague(self, ctx):
        """Manage the server's Music League."""
        await ctx.send(
            "Use `/musicleague submit` or `/musicleague playlist`.",
            ephemeral=ctx.interaction is not None,
        )

    @musicleague.command()
    async def submit(self, ctx, title: str, url: str):
        """Submit or replace your song in the current playlist."""
        title = title.strip()
        url = url.strip()
        try:
            parsed_url = urlsplit(url)
            valid_url = parsed_url.scheme.lower() in {"http", "https"} and bool(parsed_url.hostname)
        except ValueError:
            valid_url = False

        if not title:
            await ctx.send("Enter a song title.", ephemeral=ctx.interaction is not None)
            return
        if not valid_url:
            await ctx.send(
                "Enter a full HTTP or HTTPS link to the song.",
                ephemeral=ctx.interaction is not None,
            )
            return

        async with self.config.guild(ctx.guild).submissions() as submissions:
            existing = next(
                (song for song in submissions if song["user_id"] == ctx.author.id),
                None,
            )
            if existing is None:
                submissions.append(
                    {"user_id": ctx.author.id, "title": title, "url": url}
                )
                response = "Your song was added to the playlist."
            else:
                existing.update(title=title, url=url)
                response = "Your playlist submission was updated."

        await ctx.send(response, ephemeral=ctx.interaction is not None)

    @musicleague.command()
    async def playlist(self, ctx):
        """Show the songs in the current playlist."""
        submissions = await self.config.guild(ctx.guild).submissions()
        if not submissions:
            await ctx.send(
                "The Music League playlist is empty.",
                ephemeral=ctx.interaction is not None,
            )
            return

        entries = [
            f"**{index}. {discord.utils.escape_markdown(song['title'])}** "
            f"- <@{song['user_id']}>\n<{song['url']}>"
            for index, song in enumerate(submissions, start=1)
        ]
        for page in pagify("\n\n".join(entries), page_length=1900):
            await ctx.send(page, allowed_mentions=discord.AllowedMentions.none())

    async def red_get_data_for_user(self, *, user_id: int):
        submissions = []
        for guild_id in await self.config.all_guilds():
            guild_submissions = await self.config.guild_from_id(guild_id).submissions()
            submissions.extend(
                {"guild_id": guild_id, **song}
                for song in guild_submissions
                if song["user_id"] == user_id
            )

        if not submissions:
            return {}
        data = json.dumps(submissions, indent=2).encode("utf-8")
        return {"music_league_submissions.json": BytesIO(data)}

    async def red_delete_data_for_user(self, *, requester: str, user_id: int) -> None:
        for guild_id in await self.config.all_guilds():
            async with self.config.guild_from_id(guild_id).submissions() as submissions:
                submissions[:] = [
                    song for song in submissions if song["user_id"] != user_id
                ]
