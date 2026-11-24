import datetime
from pathlib import PurePath
from typing import TYPE_CHECKING, Any, Self

import aiohttp
import discord
from discord import app_commands, ui
from discord.ext import commands

from app.core.error_handler import handle_error
from app.core.settings import SETTINGS
from app.types import Interaction  # ruff: ignore[typing-only-first-party-import]
from app.ui import Button, FileUpload, Label, Modal, TextInput, View

if TYPE_CHECKING:
    import re

    from app.core.bot import MyBot

CLAIM_COOLDOWN = datetime.timedelta(minutes=10)
EXTRA_SPONSORS_URL = "https://api.seria.moe/sponsors/extra"


async def get_owner(bot: MyBot) -> discord.User:
    # Fetched by discord.py during login, so it's always set once interactions arrive
    app = bot.application
    assert app is not None
    # For team-owned apps, app.owner is a "team<id>" pseudo-user that can't receive DMs
    owner_id = app.team.owner_id if app.team and app.team.owner_id else app.owner.id
    return await bot.fetch_user(owner_id)


async def add_extra_sponsor(user_id: int) -> None:
    async with (
        aiohttp.ClientSession() as session,
        session.post(
            EXTRA_SPONSORS_URL,
            json={"user_ids": [user_id]},
            headers={"x-api-key": SETTINGS.seria_api_key},
        ) as resp,
    ):
        resp.raise_for_status()


async def resolve_claim(i: Interaction, user_id: int, user_message: str, status: str) -> None:
    user = await i.client.fetch_user(user_id)
    try:
        await user.send(user_message)
    except discord.Forbidden:
        status += " (couldn't DM the user)"

    assert i.message is not None
    await i.edit_original_response(content=f"{i.message.content}\n\n{status}", view=None)


class ApproveButton(ui.DynamicItem[Button], template=r"claim:approve:(?P<user_id>\d+)"):
    def __init__(self, user_id: int) -> None:
        super().__init__(
            Button(
                label="Approve",
                style=discord.ButtonStyle.success,
                custom_id=f"claim:approve:{user_id}",
            )
        )
        self.user_id = user_id

    @classmethod
    async def from_custom_id(
        cls, _i: Interaction, _item: ui.Item[Any], match: re.Match[str], /
    ) -> Self:
        return cls(int(match["user_id"]))

    async def callback(self, i: Interaction) -> None:
        # discord.py only logs dynamic item errors, so report them here
        try:
            await self.approve(i)
        except Exception as e:
            await handle_error(i, e)

    async def approve(self, i: Interaction) -> None:
        await i.response.defer()

        guild = i.client.get_guild(SETTINGS.guild_id)
        assert guild is not None
        try:
            member = await guild.fetch_member(self.user_id)
        except discord.NotFound:
            await add_extra_sponsor(self.user_id)
            status = "✅ Approved (added via API)"
        else:
            await member.add_roles(
                discord.Object(SETTINGS.sponsor_role_id), reason="Sponsor claim approved"
            )
            status = "✅ Approved (role granted)"

        owner = await get_owner(i.client)
        message = (
            "Your sponsor claim has been approved! "
            "Your sponsor perks should show up automatically within 1 hour. "
            f"If they don't, please contact [@{owner.name}](https://discord.com/users/{owner.id}) on Discord."
        )
        await resolve_claim(i, self.user_id, message, status)


class DenyModal(Modal):
    def __init__(self, user_id: int) -> None:
        super().__init__(title="Deny Sponsor Claim")
        self.user_id = user_id
        self.reason: Label[TextInput] = Label(
            text="Reason",
            component=TextInput(style=discord.TextStyle.paragraph, required=False, max_length=500),
        )
        self.add_item(self.reason)

    async def on_submit(self, i: Interaction) -> None:
        await i.response.defer()

        message = "Your sponsor claim has been denied."
        status = "❌ Denied"
        if reason := self.reason.component.value:
            message += f"\n**Reason:** {reason}"
            status += f": {reason}"
        await resolve_claim(i, self.user_id, message, status)


class DenyButton(ui.DynamicItem[Button], template=r"claim:deny:(?P<user_id>\d+)"):
    def __init__(self, user_id: int) -> None:
        super().__init__(
            Button(
                label="Deny", style=discord.ButtonStyle.danger, custom_id=f"claim:deny:{user_id}"
            )
        )
        self.user_id = user_id

    @classmethod
    async def from_custom_id(
        cls, _i: Interaction, _item: ui.Item[Any], match: re.Match[str], /
    ) -> Self:
        return cls(int(match["user_id"]))

    async def callback(self, i: Interaction) -> None:
        await i.response.send_modal(DenyModal(self.user_id))


class ClaimModal(Modal):
    def __init__(self, next_claim_at: dict[int, datetime.datetime]) -> None:
        super().__init__(title="Claim Sponsor Perks")
        self.next_claim_at = next_claim_at

        self.screenshots: Label[FileUpload] = Label(
            text="Screenshots",
            description="Up to 10 images that prove your sponsorship",
            component=FileUpload(max_values=10),
        )
        self.notes: Label[TextInput] = Label(
            text="Notes",
            description="Anything else you'd like to add (optional)",
            component=TextInput(style=discord.TextStyle.paragraph, required=False, max_length=1000),
        )
        self.add_item(self.screenshots)
        self.add_item(self.notes)

    async def on_submit(self, i: Interaction) -> None:
        attachments = self.screenshots.component.values
        # The file upload component can't restrict file types, so check them here
        non_images = [
            a.filename for a in attachments if not (a.content_type or "").startswith("image/")
        ]
        if non_images:
            names = ", ".join(f"`{name}`" for name in non_images)
            await i.response.send_message(
                f"Only images are allowed. Please run `/claim` again without: {names}",
                ephemeral=True,
            )
            return

        await i.response.defer(ephemeral=True, thinking=True)

        # Re-uploaded because modal attachment URLs expire; renamed so duplicate names don't collide
        files = [
            await a.to_file(filename=f"screenshot_{n}{PurePath(a.filename).suffix}")
            for n, a in enumerate(attachments, 1)
        ]
        content = f"**New sponsor claim** from {i.user.mention} (`{i.user.name}`, `{i.user.id}`)"
        if notes := self.notes.component.value:
            content += f"\n**Notes:**\n{notes}"

        view = View(timeout=None)
        view.add_item(ApproveButton(i.user.id)).add_item(DenyButton(i.user.id))
        owner = await get_owner(i.client)
        await owner.send(content, files=files, view=view)

        self.next_claim_at[i.user.id] = discord.utils.utcnow() + CLAIM_COOLDOWN
        await i.followup.send(
            "Your claim has been submitted! Please wait for approval, "
            "you'll receive a DM with the result.",
            ephemeral=True,
        )


class Sponsor(commands.Cog):
    def __init__(self, bot: MyBot) -> None:
        self.bot = bot
        self.next_claim_at: dict[int, datetime.datetime] = {}

    async def cog_load(self) -> None:
        self.bot.add_dynamic_items(ApproveButton, DenyButton)

    async def cog_unload(self) -> None:
        self.bot.remove_dynamic_items(ApproveButton, DenyButton)

    @app_commands.command(name="claim", description="Claim your sponsor perks")
    @app_commands.allowed_installs(guilds=True, users=True)
    @app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
    async def claim(self, i: Interaction) -> None:
        ready_at = self.next_claim_at.get(i.user.id)
        if ready_at is not None and ready_at > discord.utils.utcnow():
            await i.response.send_message(
                "You've already submitted a claim recently. "
                f"Please try again {discord.utils.format_dt(ready_at, 'R')}.",
                ephemeral=True,
            )
            return

        await i.response.send_modal(ClaimModal(self.next_claim_at))


async def setup(bot: MyBot) -> None:
    await bot.add_cog(Sponsor(bot))
