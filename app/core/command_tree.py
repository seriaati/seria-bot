import datetime
from typing import TYPE_CHECKING

import discord
from discord import app_commands

from app.core.error_handler import handle_error

if TYPE_CHECKING:
    from app.types import Interaction


class CommandTree(app_commands.CommandTree):
    async def on_error(self, i: Interaction, error: app_commands.AppCommandError) -> None:
        if isinstance(error, app_commands.CommandOnCooldown):
            ready_at = discord.utils.utcnow() + datetime.timedelta(seconds=error.retry_after)
            await i.response.send_message(
                "This command is on cooldown. "
                f"Please try again {discord.utils.format_dt(ready_at, 'R')}.",
                ephemeral=True,
            )
            return

        await handle_error(i, error)
