"""
Lightning.py - A Discord bot
Copyright (C) 2019-2021 LightSage

This program is free software: you can redistribute it and/or modify
it under the terms of the GNU Affero General Public License as published
by the Free Software Foundation at version 3 of the License.

This program is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
GNU Affero General Public License for more details.

You should have received a copy of the GNU Affero General Public License
along with this program.  If not, see <https://www.gnu.org/licenses/>.
"""
import asyncio
import io
import logging
import random
import re

import discord
from discord.ext import commands

from lightning import (CommandLevel, LightningBot, LightningCog,
                       LightningContext, command, errors, group)
from lightning.converters import EmojiRE, Whitelisted_URL
from lightning.utils.checks import has_guild_permissions, is_one_of_guilds
from lightning.utils.modlogformats import action_format
from lightning.utils.paginator import BasicEmbedMenu, InfoMenuPages

ROO_EMOTES = [604331487583535124, 604446987844190228, 606517600167526498, 610921560068456448]
log = logging.getLogger(__name__)


class Emoji(LightningCog):

    @property
    def apne(self):
        return self.bot.config['bot']['nitro_emoji_guilds'] or []

    @command(aliases=['nemoji', 'nitro'])
    @commands.cooldown(3, 15.0, commands.BucketType.channel)
    async def nitroemoji(self, ctx: LightningContext, emoji: str) -> None:
        """Posts either an animated emoji or non-animated emoji if found

        Note: The server which the emoji is from must be approved by the bot owner."""
        emojiname: str = emoji.strip(':;')
        emoji: str = discord.utils.get(self.bot.emojis, name=emojiname)

        if emoji and emoji.guild_id in self.apne:
            await ctx.send(str(emoji))
            return

        emojiname = emojiname.lower()
        rand = list(filter(lambda m: emojiname in m.name.lower() and m.is_usable() and m.guild_id in self.apne,
                           self.bot.emojis))

        if rand:
            em = random.choice(rand)
            await ctx.emoji_send(em)
        else:
            await ctx.send("No emoji found")

    @group(aliases=['emote'], invoke_without_command=True)
    async def emoji(self, ctx: LightningContext) -> None:
        """Emoji management commands"""
        await ctx.send_help("emoji")

    @emoji.command()
    @commands.is_owner()
    async def approvenitro(self, ctx: LightningContext, guild: discord.Guild) -> None:
        """Approves a guild for the nitro emoji command"""
        self.bot.config['bot']['nitro_emoji_guilds'].append(guild.id)
        await self.bot.config.save()
        await ctx.tick(True)

    @emoji.command(aliases=['copy'], level=CommandLevel.Admin)
    @commands.guild_only()
    @commands.bot_has_permissions(manage_emojis=True)
    @has_guild_permissions(manage_emojis=True)
    async def add(self, ctx: LightningContext, *args) -> None:
        """Adds an emoji to the server"""
        error_msg = "Expected a custom emote. To add an emoji with a link, you must provide the name and url"\
                    " like <name> <url>."
        if len(args) == 1:
            regexmatch = re.match(r"<(a?):([A-Za-z0-9_]+):([0-9]+)>", args[0])
            if not regexmatch:
                raise errors.EmojiError("That's not a custom emoji \N{THINKING FACE}")
            try:
                emoji = await commands.PartialEmojiConverter().convert(ctx, args[0])
            except commands.BadArgument:
                raise commands.BadArgument(error_msg)
            emoji_name = emoji.name
            url = str(emoji.url)
        elif len(args) == 2:
            url = args[1]
            emoji_name = args[0]
        elif len(args) >= 3 or len(args) == 0:
            raise commands.BadArgument(error_msg)

        wurl = Whitelisted_URL(url)
        if len(emoji_name) > 32:
            await ctx.send("Emoji name cannot be longer than 32 characters!")
            return

        emoji_link = await ctx.request(str(wurl))
        _bytes = io.BytesIO()
        _bytes.write(emoji_link)
        _bytes.seek(0)

        try:
            coro = ctx.guild.create_custom_emoji(name=emoji_name, image=_bytes.read(),
                                                 reason=action_format(ctx.author, "Emoji added by"))
            emoji = await asyncio.wait_for(coro, timeout=15.0)
        except asyncio.TimeoutError:
            await ctx.send("The bot is ratelimited or creation took too long. Try again later.")
            return
        except discord.HTTPException as e:
            if e.code == 30008:
                await ctx.send("Unable to add that emoji because this server's emoji list is full.")
                return
            elif e.code == 50035:
                await ctx.send("Image is too big to upload. Emojis cannot be larger than 256kb")
                return

            log.debug(f"Tried to upload {str(wurl)} but failed with {e}")
            raise
        else:
            await ctx.send(f"Successfully created {emoji} `{emoji}`")

    @emoji.command(level=CommandLevel.Admin)
    @commands.guild_only()
    @commands.bot_has_permissions(manage_emojis=True)
    @has_guild_permissions(manage_emojis=True)
    async def delete(self, ctx: LightningContext, emote: discord.Emoji) -> None:
        """Deletes an emoji from the server"""
        if ctx.guild.id != emote.guild_id:
            await ctx.send("This emoji isn't in this server!")
            return

        await emote.delete(reason=action_format(ctx.author, "Emoji removed by"))
        await ctx.send(f"{emote.name} is now deleted.")

    @emoji.command(level=CommandLevel.Admin)
    @commands.guild_only()
    @commands.bot_has_permissions(manage_emojis=True)
    @has_guild_permissions(manage_emojis=True)
    async def rename(self, ctx: LightningContext, old_name: discord.Emoji, new_name: str) -> None:
        """Renames an emoji from the server"""
        if ctx.guild.id != old_name.guild_id:
            await ctx.send("This emoji does not belong to this server!")
            return

        try:
            await old_name.edit(name=new_name, reason=action_format(ctx.author, "Emoji renamed by"))
        except discord.HTTPException as e:
            await self.bot.log_command_error(ctx, e)
            return

        await ctx.send(f"Renamed {old_name} to {new_name}")

    @commands.guild_only()
    @emoji.command(name='list', aliases=['all'])
    async def listemotes(self, ctx: LightningContext) -> None:
        """Sends a paginator with a list of the server's usable emotes"""
        if len(ctx.guild.emojis) == 0:
            await ctx.send("This server has no emojis. Add some emojis then run the command again.")
            return

        server_emotes = sorted([emoji for emoji in ctx.guild.emojis if emoji.is_usable()], key=lambda x: x.name)
        emotes = []
        for emoji in server_emotes:
            emotes.append(f'{emoji} -- `{emoji}`')
        if not emotes:
            await ctx.send("This server has no emojis that are usable by me.")
            return

        pages = InfoMenuPages(BasicEmbedMenu(emotes, per_page=20), clear_reactions_after=True, check_embeds=True)
        await pages.start(ctx)

    @emoji.command()
    async def info(self, ctx: LightningContext, emote: EmojiRE) -> None:
        """Gives some info on an emote.

        Unicode emoji are not supported."""
        embed = discord.Embed(title=emote.name, color=0xFFFF00)
        embed.description = f"[Emoji Link]({emote.url})"
        embed.add_field(name="ID", value=emote.id)
        embed.set_thumbnail(url=emote.url)

        managed = getattr(emote, 'managed', None)
        created = getattr(emote, 'created_at', None)
        if managed:
            embed.description += ("\n\nThis emoji is managed by a Twitch integration")
        if created:
            embed.set_footer(text="Emoji created at")
            embed.timestamp = created

        await ctx.send(embed=embed)

    @info.error
    async def emoji_error(self, ctx: LightningContext, error) -> None:
        if isinstance(error, commands.MissingRequiredArgument):
            await ctx.send(error)
        elif isinstance(error, commands.BadArgument):
            await ctx.send(error)

    @command(aliases=['listrooemojis'])
    @is_one_of_guilds(*ROO_EMOTES)
    @commands.has_permissions(manage_emojis=True)
    async def refreshemojilist(self, ctx: LightningContext) -> None:
        """Refreshes the emoji list channel.

        This purges 25 messages from the emoji-list channel and sends a new list of emojis
        """
        if len(ctx.guild.emojis) == 0:
            await ctx.send("This server has no emotes!")
            return

        channel = discord.utils.get(ctx.guild.channels, name="emoji-list")
        if not channel:
            return

        # We shouldn't have more than 25 messages in the emoji-list channel
        try:
            await channel.purge(25)
        except Exception as e:
            # Notify that we tried
            await ctx.send(f"Somehow failed to purge messages: `{e}`")

        paginator = commands.Paginator(suffix='', prefix='')
        for emoji in ctx.guild.emojis:
            paginator.add_line(f'{emoji} -- `{emoji}`')

        for page in paginator.pages:
            await channel.send(page)

    @LightningCog.listener()
    async def on_guild_emojis_update(self, guild, before, after) -> None:
        if guild.id not in ROO_EMOTES:
            return

        channel = discord.utils.get(guild.channels, name="emoji-list")
        if not channel:
            return

        rm_emoji = [f"{emoji} -- `{emoji.id}`" for emoji in before if emoji not in after]
        mk_emoji = [f"{emoji} -- `{emoji}`" for emoji in after if emoji not in before]
        if len(rm_emoji) != 0:
            msg = "⚠ Emoji Removed: "
            msg += ", ".join(rm_emoji)
            await channel.send(msg)
        if len(mk_emoji) != 0:
            msg = "✅ Emoji Added: "
            msg += ", ".join(mk_emoji)
            await channel.send(msg)


def setup(bot: LightningBot) -> None:
    bot.add_cog(Emoji(bot))
