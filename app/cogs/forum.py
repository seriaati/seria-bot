from typing import TYPE_CHECKING

import discord
from discord import app_commands
from discord.ext import commands

from app.core.settings import SETTINGS
from app.types import Interaction  # ruff: ignore[typing-only-first-party-import]

if TYPE_CHECKING:
    from app.core.bot import MyBot


class Forum(commands.Cog):
    def __init__(self, bot: MyBot) -> None:
        self.bot = bot
        self.ctx_menu = app_commands.ContextMenu(
            name="Convert to Forum Post", callback=self.convert_to_thread
        )
        self.bot.tree.add_command(self.ctx_menu)

    async def cog_unload(self) -> None:
        self.bot.tree.remove_command(self.ctx_menu.name, type=self.ctx_menu.type)

    @app_commands.guild_only()
    @app_commands.default_permissions(manage_messages=True)
    async def convert_to_thread(self, i: Interaction, message: discord.Message) -> None:
        await i.response.defer(ephemeral=True)

        forum = self.bot.get_channel(SETTINGS.forum_channel_id)
        if not isinstance(forum, discord.ForumChannel):
            msg = f"Channel {SETTINGS.forum_channel_id} is not a forum channel"
            raise TypeError(msg)

        name = (
            message.content.split("\n", 1)[0][:100] or f"Message from {message.author.display_name}"
        )
        suffix = f"\n\n-# Original message: {message.jump_url}"
        content = message.content[: 2000 - len(suffix)] + suffix
        files = [await a.to_file() for a in message.attachments]

        thread, _ = await forum.create_thread(name=name, content=content, files=files)
        await i.followup.send(f"Created post: {thread.jump_url}", ephemeral=True)


async def setup(bot: MyBot) -> None:
    await bot.add_cog(Forum(bot))
