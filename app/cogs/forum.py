from typing import TYPE_CHECKING

import discord
from discord import app_commands
from discord.ext import commands

from app.core.settings import SETTINGS
from app.types import Interaction  # ruff: ignore[typing-only-first-party-import]
from app.ui import Label, Modal, Select

if TYPE_CHECKING:
    from app.core.bot import MyBot


async def create_post(
    i: Interaction,
    forum: discord.ForumChannel,
    message: discord.Message,
    tags: list[discord.ForumTag],
) -> None:
    await i.response.defer(ephemeral=True)

    name = message.content.split("\n", 1)[0][:100] or f"Message from {message.author.display_name}"
    suffix = f"\n\n-# Original message: {message.jump_url}"
    content = message.content[: 2000 - len(suffix)] + suffix
    files = [await a.to_file() for a in message.attachments]

    thread, _ = await forum.create_thread(
        name=name, content=content, files=files, applied_tags=tags
    )
    await i.followup.send(f"Created post: {thread.jump_url}", ephemeral=True)


class TagModal(Modal):
    def __init__(self, forum: discord.ForumChannel, message: discord.Message) -> None:
        super().__init__(title="Convert to Forum Post")
        self.forum = forum
        self.message = message
        self.tags: Label[Select] = Label(
            text="Tags",
            component=Select(
                options=[
                    discord.SelectOption(label=t.name, value=str(t.id), emoji=t.emoji)
                    for t in forum.available_tags
                ],
                min_values=1 if forum.flags.require_tag else 0,
                max_values=min(5, len(forum.available_tags)),
                required=forum.flags.require_tag,
            ),
        )
        self.add_item(self.tags)

    async def on_submit(self, i: Interaction) -> None:
        selected = self.tags.component.values
        tags = [t for t in self.forum.available_tags if str(t.id) in selected]
        await create_post(i, self.forum, self.message, tags)


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
        forum = self.bot.get_channel(SETTINGS.forum_channel_id)
        if not isinstance(forum, discord.ForumChannel):
            msg = f"Channel {SETTINGS.forum_channel_id} is not a forum channel"
            raise TypeError(msg)

        if forum.available_tags:
            await i.response.send_modal(TagModal(forum, message))
        else:
            await create_post(i, forum, message, [])


async def setup(bot: MyBot) -> None:
    await bot.add_cog(Forum(bot))
