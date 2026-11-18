import json
from datetime import datetime, timedelta
from io import BytesIO
from urllib.parse import urlsplit

import discord
import pytz
from discord.ext import tasks
from red_commons.logging import getLogger
from redbot.core import Config, commands
from redbot.core.utils.chat_formatting import pagify

LOGGER = getLogger("red.brainscoop-cogs.MusicLeague")


class MusicLeague(commands.Cog):
    """Server-specific Music League commands."""

    def __init__(self, bot):
        self.bot = bot
        self.config = Config.get_conf(self, identifier=817362450991, force_registration=True)
        self.config.register_guild(
            announcement_channel_id=None,
            rounds={},
            submissions=[],
            timezone="UTC",
        )

    async def cog_load(self):
        self.weekly_schedule.start()

    async def cog_unload(self):
        self.weekly_schedule.cancel()

    async def _get_weekly_state(self, guild):
        guild_config = self.config.guild(guild)
        timezone_name = await guild_config.timezone()
        local_now = datetime.now(pytz.timezone(timezone_name))
        days_since_sunday = (local_now.weekday() + 1) % 7
        week_start = (local_now.date() - timedelta(days=days_since_sunday)).isoformat()
        phase = "submissions" if local_now.weekday() in {6, 0, 1} else "voting"
        legacy_submissions = await guild_config.submissions()

        async with guild_config.rounds() as rounds:
            current_round = rounds.setdefault(
                week_start,
                {"announced_phase": None, "submissions": [], "votes": {}},
            )
            current_round.setdefault("votes", {})
            if legacy_submissions:
                existing_user_ids = {
                    song["user_id"] for song in current_round["submissions"]
                }
                current_round["submissions"].extend(
                    song
                    for song in legacy_submissions
                    if song["user_id"] not in existing_user_ids
                )

        if legacy_submissions:
            await guild_config.submissions.set([])

        return week_start, phase, timezone_name

    async def _announce_phase(self, guild):
        week_start, phase, timezone_name = await self._get_weekly_state(guild)
        guild_config = self.config.guild(guild)
        channel_id = await guild_config.announcement_channel_id()
        if channel_id is None:
            return False

        channel = guild.get_channel(channel_id)
        if not isinstance(channel, discord.TextChannel):
            LOGGER.warning(
                "Music League announcement channel %s is missing in guild %s",
                channel_id,
                guild.id,
            )
            return False

        rounds = await guild_config.rounds()
        current_round = rounds[week_start]
        if current_round.get("announced_phase") == phase:
            return True

        if phase == "submissions":
            message = (
                f"The Music League playlist for the week of {week_start} is open "
                f"for submissions ({timezone_name}). Use `/musicleague submit`."
            )
        else:
            message = (
                f"Voting is open for the Music League playlist for the week of "
                f"{week_start} ({timezone_name}). Use `/musicleague playlist`."
            )

        try:
            await channel.send(
                message,
                allowed_mentions=discord.AllowedMentions.none(),
            )
        except discord.Forbidden:
            LOGGER.error(
                "Cannot post Music League announcements in channel %s for guild %s",
                channel_id,
                guild.id,
            )
            return False
        except discord.HTTPException:
            LOGGER.exception(
                "Failed to post Music League announcement in channel %s for guild %s",
                channel_id,
                guild.id,
            )
            return False

        async with guild_config.rounds() as rounds:
            rounds[week_start]["announced_phase"] = phase
        return True

    @commands.hybrid_group(invoke_without_command=True)
    @commands.guild_only()
    async def musicleague(self, ctx):
        """Manage the server's Music League."""
        week_start, phase, timezone_name = await self._get_weekly_state(ctx.guild)
        phase_description = (
            "submissions are open"
            if phase == "submissions"
            else "voting is open"
        )
        await ctx.send(
            f"For the week of {week_start}, {phase_description}. "
            f"The schedule uses {timezone_name}.",
            ephemeral=ctx.interaction is not None,
        )

    @musicleague.command()
    @commands.admin_or_permissions(manage_guild=True)
    async def timezone(self, ctx, timezone_name: str):
        """Set the time zone used for weekly round changes."""
        timezone_name = timezone_name.strip()
        try:
            timezone = pytz.timezone(timezone_name)
        except pytz.UnknownTimeZoneError:
            await ctx.send(
                "Enter a valid IANA time zone, such as `UTC` or `America/New_York`.",
                ephemeral=ctx.interaction is not None,
            )
            return

        await self.config.guild(ctx.guild).timezone.set(timezone.zone)
        await self._announce_phase(ctx.guild)
        await ctx.send(
            f"Music League schedule time zone set to `{timezone.zone}`.",
            ephemeral=ctx.interaction is not None,
        )

    @musicleague.command(name="channel")
    @commands.admin_or_permissions(manage_guild=True)
    async def set_announcement_channel(self, ctx, channel: discord.TextChannel):
        """Choose where weekly phase announcements are posted."""
        guild_config = self.config.guild(ctx.guild)
        await guild_config.announcement_channel_id.set(channel.id)
        week_start, _, _ = await self._get_weekly_state(ctx.guild)
        async with guild_config.rounds() as rounds:
            rounds[week_start]["announced_phase"] = None
        announced = await self._announce_phase(ctx.guild)
        if not announced:
            await ctx.send(
                "The channel was saved, but I couldn't post the current phase. "
                "Check that I can view and send messages there.",
                ephemeral=ctx.interaction is not None,
            )
            return
        await ctx.send(
            f"Weekly Music League announcements will be posted in {channel.mention}.",
            ephemeral=ctx.interaction is not None,
        )

    @musicleague.command()
    async def submit(self, ctx, title: str, url: str):
        """Submit or replace your song during the submission phase."""
        if ctx.interaction is None:
            await ctx.send("Use the slash command to submit your song privately.")
            return

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

        week_start, phase, _ = await self._get_weekly_state(ctx.guild)
        if phase != "submissions":
            await ctx.send(
                "Submissions are closed for this playlist. Voting runs Wednesday through Saturday.",
                ephemeral=ctx.interaction is not None,
            )
            return

        async with self.config.guild(ctx.guild).rounds() as rounds:
            submissions = rounds[week_start]["submissions"]
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
        """Show the current playlist during the voting phase."""
        week_start, phase, _ = await self._get_weekly_state(ctx.guild)
        if phase != "voting":
            await ctx.send(
                "This playlist will be available when voting opens on Wednesday.",
                ephemeral=ctx.interaction is not None,
            )
            return

        rounds = await self.config.guild(ctx.guild).rounds()
        submissions = rounds[week_start]["submissions"]
        if not submissions:
            await ctx.send(
                "The Music League playlist for this week is empty.",
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

    @musicleague.command()
    async def vote(self, ctx, song_number: int, points: int):
        """Allocate 1 to 3 points to a song in the current playlist."""
        if ctx.interaction is None:
            await ctx.send("Use the slash command to keep your ballot private.")
            return

        week_start, phase, _ = await self._get_weekly_state(ctx.guild)
        if phase != "voting":
            await ctx.send(
                "Voting is only open Wednesday through Saturday.",
                ephemeral=ctx.interaction is not None,
            )
            return

        error = None
        response = None
        async with self.config.guild(ctx.guild).rounds() as rounds:
            current_round = rounds[week_start]
            submissions = current_round["submissions"]
            if song_number < 1 or song_number > len(submissions):
                error = "Choose a song number from the current playlist."
            elif points not in {1, 2, 3}:
                error = "Each song can receive 1, 2, or 3 points."
            else:
                song_user_id = str(submissions[song_number - 1]["user_id"])
                voter_id = str(ctx.author.id)
                ballot = current_round.setdefault("votes", {}).setdefault(voter_id, {})
                existing_points = ballot.get(song_user_id, 0)
                total_points = sum(ballot.values()) - existing_points + points
                if total_points > 7:
                    error = "Your ballot cannot exceed 7 total points."
                else:
                    ballot[song_user_id] = points
                    if total_points == 7:
                        response = "Vote saved. Your ballot is complete (7/7)."
                    else:
                        response = f"Vote saved. You have {total_points}/7 points allocated."

        if error is not None:
            await ctx.send(error, ephemeral=True)
        elif response is not None:
            await ctx.send(response, ephemeral=True)
        else:
            raise RuntimeError("Vote command did not produce a response.")

    @musicleague.command()
    async def unvote(self, ctx, song_number: int):
        """Remove your points from a song in the current ballot."""
        if ctx.interaction is None:
            await ctx.send("Use the slash command to keep your ballot private.")
            return

        week_start, phase, _ = await self._get_weekly_state(ctx.guild)
        if phase != "voting":
            await ctx.send(
                "Voting is only open Wednesday through Saturday.",
                ephemeral=ctx.interaction is not None,
            )
            return

        error = None
        response = None
        async with self.config.guild(ctx.guild).rounds() as rounds:
            current_round = rounds[week_start]
            submissions = current_round["submissions"]
            if song_number < 1 or song_number > len(submissions):
                error = "Choose a song number from the current playlist."
            else:
                song_user_id = str(submissions[song_number - 1]["user_id"])
                ballot = current_round.setdefault("votes", {}).get(
                    str(ctx.author.id),
                    {},
                )
                if song_user_id not in ballot:
                    error = "You haven't voted for that song."
                else:
                    del ballot[song_user_id]
                    if not ballot:
                        current_round["votes"].pop(str(ctx.author.id), None)
                    total_points = sum(ballot.values())
                    response = (
                        f"Vote removed. You have {total_points}/7 points allocated."
                    )

        if error is not None:
            await ctx.send(error, ephemeral=True)
        elif response is not None:
            await ctx.send(response, ephemeral=True)
        else:
            raise RuntimeError("Unvote command did not produce a response.")

    @musicleague.command()
    async def myvotes(self, ctx):
        """Privately show your current ballot and point total."""
        if ctx.interaction is None:
            await ctx.send("Use the slash command to view your ballot privately.")
            return

        week_start, phase, _ = await self._get_weekly_state(ctx.guild)
        if phase != "voting":
            await ctx.send(
                "Voting is only open Wednesday through Saturday.",
                ephemeral=True,
            )
            return

        rounds = await self.config.guild(ctx.guild).rounds()
        current_round = rounds[week_start]
        submissions = {
            str(song["user_id"]): song for song in current_round["submissions"]
        }
        ballot = current_round.get("votes", {}).get(str(ctx.author.id), {})
        if not ballot:
            await ctx.send(
                "You haven't allocated any points yet (0/7).",
                ephemeral=True,
            )
            return

        lines = [
            f"{discord.utils.escape_markdown(submissions[song_user_id]['title'])}: "
            f"{points} point{'s' if points != 1 else ''}"
            for song_user_id, points in ballot.items()
            if song_user_id in submissions
        ]
        total_points = sum(ballot.values())
        await ctx.send(
            f"Your ballot ({total_points}/7):\n" + "\n".join(lines),
            ephemeral=True,
        )

    @tasks.loop(minutes=15)
    async def weekly_schedule(self):
        for guild in self.bot.guilds:
            await self._announce_phase(guild)

    @weekly_schedule.before_loop
    async def before_weekly_schedule(self):
        await self.bot.wait_until_ready()

    async def red_get_data_for_user(self, *, user_id: int):
        user_data = []
        for guild_id in await self.config.all_guilds():
            guild_config = self.config.guild_from_id(guild_id)
            rounds = await guild_config.rounds()
            for week_start, round_data in rounds.items():
                user_data.extend(
                    {"guild_id": guild_id, "week_start": week_start, **song}
                    for song in round_data["submissions"]
                    if song["user_id"] == user_id
                )
                ballot = round_data.get("votes", {}).get(str(user_id))
                if ballot:
                    user_data.append(
                        {
                            "guild_id": guild_id,
                            "week_start": week_start,
                            "votes": ballot,
                        }
                    )
            legacy_submissions = await guild_config.submissions()
            user_data.extend(
                {"guild_id": guild_id, "week_start": None, **song}
                for song in legacy_submissions
                if song["user_id"] == user_id
            )

        if not user_data:
            return {}
        data = json.dumps(user_data, indent=2).encode("utf-8")
        return {"music_league_data.json": BytesIO(data)}

    async def red_delete_data_for_user(self, *, requester: str, user_id: int) -> None:
        for guild_id in await self.config.all_guilds():
            guild_config = self.config.guild_from_id(guild_id)
            async with guild_config.rounds() as rounds:
                for round_data in rounds.values():
                    round_data["submissions"] = [
                        song
                        for song in round_data["submissions"]
                        if song["user_id"] != user_id
                    ]
                    votes = round_data.setdefault("votes", {})
                    votes.pop(str(user_id), None)
                    for ballot in votes.values():
                        ballot.pop(str(user_id), None)
            async with guild_config.submissions() as submissions:
                submissions[:] = [
                    song for song in submissions if song["user_id"] != user_id
                ]
