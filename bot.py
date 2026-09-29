import os
import re
import sqlite3
from datetime import datetime, timezone, timedelta

import discord
from discord.ext import commands
from discord import app_commands


# =========================================================
# CONFIG
# =========================================================

GUILD_ID = 1552902541061394432
CITIZEN_ROLE_ID = 1552903102204747856
MASTER_ROLE_ID = 1552903005500866650

TOKEN = os.getenv("BOT_TOKEN")

DB_FILE = "modern_city.db"


# =========================================================
# ADVANCED ANTI-LINK
# =========================================================

URL_PATTERN = re.compile(
    r"""(?ix)
    (?:
        https?://[^\s<>()]+
        |
        www\.[^\s<>()]+
        |
        discord\.gg/[^\s<>()]+
        |
        discord\.com/invite/[^\s<>()]+
        |
        discordapp\.com/invite/[^\s<>()]+
        |
        (?<![@\w.-])
        (?:[a-z0-9-]+\.)+
        (?:
            com|net|org|gg|io|in|co|xyz|me|dev|app|
            info|biz|site|online|store|tech|pro|live
        )
        (?:[/?#][^\s<>()]*)?
    )
    """
)


# =========================================================
# INTENTS
# =========================================================

intents = discord.Intents.default()

intents.members = True
intents.presences = True
intents.message_content = True


bot = commands.Bot(
    command_prefix="!",
    intents=intents
)


# =========================================================
# DATABASE
# =========================================================

db = sqlite3.connect(
    DB_FILE,
    check_same_thread=False
)

db.row_factory = sqlite3.Row


def init_database():

    cursor = db.cursor()

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS warnings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            guild_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            reason TEXT NOT NULL,
            issuer_id INTEGER NOT NULL,
            created_at TEXT NOT NULL
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS verification (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            guild_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            organization TEXT NOT NULL,
            character_name TEXT NOT NULL,
            character_age TEXT NOT NULL,
            experience TEXT NOT NULL,
            status TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS activity (
            guild_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            active_seconds REAL DEFAULT 0,
            idle_seconds REAL DEFAULT 0,
            current_status TEXT DEFAULT 'offline',
            last_change TEXT NOT NULL,
            idle_since TEXT,
            PRIMARY KEY(guild_id, user_id)
        )
    """)

    db.commit()


def utc_now():
    return datetime.now(timezone.utc)


def iso_time(dt):
    return dt.astimezone(timezone.utc).isoformat()


def parse_time(value):
    return datetime.fromisoformat(value)


def format_duration(seconds):

    seconds = int(max(0, seconds))

    days, seconds = divmod(seconds, 86400)
    hours, seconds = divmod(seconds, 3600)
    minutes, seconds = divmod(seconds, 60)

    result = []

    if days:
        result.append(f"{days}d")

    if hours:
        result.append(f"{hours}h")

    if minutes:
        result.append(f"{minutes}m")

    if not result or seconds:
        result.append(f"{seconds}s")

    return " ".join(result)


# =========================================================
# STATUS HELPERS
# =========================================================

def get_status(status):

    if status == discord.Status.online:
        return "online"

    if status == discord.Status.idle:
        return "idle"

    if status == discord.Status.dnd:
        return "dnd"

    return "offline"


def ensure_activity(member):

    if member.bot:
        return

    cursor = db.cursor()

    exists = cursor.execute(
        """
        SELECT 1
        FROM activity
        WHERE guild_id=? AND user_id=?
        """,
        (
            member.guild.id,
            member.id
        )
    ).fetchone()

    if exists:
        return

    status = get_status(member.status)

    cursor.execute(
        """
        INSERT INTO activity(
            guild_id,
            user_id,
            active_seconds,
            idle_seconds,
            current_status,
            last_change,
            idle_since
        )
        VALUES(?,?,?,?,?,?,?)
        """,
        (
            member.guild.id,
            member.id,
            0,
            0,
            status,
            iso_time(utc_now()),
            iso_time(utc_now())
            if status == "idle"
            else None
        )
    )

    db.commit()


def update_activity(member, new_status):

    if member.bot:
        return

    now = utc_now()

    cursor = db.cursor()

    row = cursor.execute(
        """
        SELECT *
        FROM activity
        WHERE guild_id=? AND user_id=?
        """,
        (
            member.guild.id,
            member.id
        )
    ).fetchone()

    if not row:
        ensure_activity(member)
        return

    old_status = row["current_status"]

    elapsed = max(
        0,
        (
            now - parse_time(row["last_change"])
        ).total_seconds()
    )

    active_seconds = float(row["active_seconds"])
    idle_seconds = float(row["idle_seconds"])

    if old_status in ("online", "dnd"):
        active_seconds += elapsed

    elif old_status == "idle":
        idle_seconds += elapsed

    idle_since = row["idle_since"]

    if new_status == "idle" and old_status != "idle":
        idle_since = iso_time(now)

    elif new_status != "idle":
        idle_since = None

    cursor.execute(
        """
        UPDATE activity
        SET
            active_seconds=?,
            idle_seconds=?,
            current_status=?,
            last_change=?,
            idle_since=?
        WHERE guild_id=? AND user_id=?
        """,
        (
            active_seconds,
            idle_seconds,
            new_status,
            iso_time(now),
            idle_since,
            member.guild.id,
            member.id
        )
    )

    db.commit()


def get_total_activity(row):

    total = (
        float(row["active_seconds"])
        + float(row["idle_seconds"])
    )

    if row["current_status"] in (
        "online",
        "idle",
        "dnd"
    ):
        total += max(
            0,
            (
                utc_now()
                - parse_time(row["last_change"])
            ).total_seconds()
        )

    return total


def get_active_activity(row):

    total = float(row["active_seconds"])

    if row["current_status"] in (
        "online",
        "dnd"
    ):
        total += max(
            0,
            (
                utc_now()
                - parse_time(row["last_change"])
            ).total_seconds()
        )

    return total


def get_idle_activity(row):

    total = float(row["idle_seconds"])

    if row["current_status"] == "idle":
        total += max(
            0,
            (
                utc_now()
                - parse_time(row["last_change"])
            ).total_seconds()
        )

    return total


# =========================================================
# PERMISSION HELPERS
# =========================================================

STAFF_ROLE_NAMES = {
    "Founder",
    "Owner",
    "Administrator",
    "Head Administrator",
    "Senior Administrator",
    "Moderator",
    "Senior Moderator",
}


def is_master(member):

    return any(
        role.id == MASTER_ROLE_ID
        for role in member.roles
    )


def is_staff(member):

    if is_master(member):
        return True

    if member.guild_permissions.administrator:
        return True

    return any(
        role.name in STAFF_ROLE_NAMES
        for role in member.roles
    )


# =========================================================
# READY
# =========================================================

@bot.event
async def on_ready():

    init_database()

    guild = bot.get_guild(GUILD_ID)

    if guild:

        for member in guild.members:
            ensure_activity(member)

    try:

        synced = await bot.tree.sync()

        print(
            f"SYNCED {len(synced)} COMMANDS"
        )

    except Exception as error:

        print(
            f"SYNC ERROR: {error}"
        )

    print(
        f"ONLINE: {bot.user} | {bot.user.id}"
    )


# =========================================================
# MEMBER JOIN
# =========================================================

@bot.event
async def on_member_join(member):

    if member.guild.id != GUILD_ID:
        return

    ensure_activity(member)


# =========================================================
# PRESENCE TRACKING
# =========================================================

@bot.event
async def on_presence_update(before, after):

    if after.guild.id != GUILD_ID:
        return

    if after.bot:
        return

    old_status = get_status(
        before.status
    )

    new_status = get_status(
        after.status
    )

    if old_status != new_status:

        update_activity(
            after,
            new_status
        )


# =========================================================
# ANTI-LINK
# =========================================================

@bot.event
async def on_message(message):

    if message.author.bot:
        return

    if message.guild:

        if message.guild.id == GUILD_ID:

            member = message.author

            # MASTER BYPASS
            if not is_master(member):

                content = message.content or ""

                detected = URL_PATTERN.search(
                    content
                )

                if detected:

                    # DELETE
                    try:

                        await message.delete()

                    except discord.HTTPException:
                        pass

                    # TIMEOUT
                    try:

                        await member.timeout(
                            timedelta(minutes=10),
                            reason="Unauthorized link detected"
                        )

                        print(
                            f"ANTI-LINK: "
                            f"{member} timed out"
                        )

                    except discord.Forbidden:

                        print(
                            f"ANTI-LINK ERROR: "
                            f"Cannot timeout {member}"
                        )

                    except discord.HTTPException as error:

                        print(
                            f"ANTI-LINK ERROR: {error}"
                        )

                    return

    await bot.process_commands(message)


# =========================================================
# VERIFICATION MODAL
# =========================================================

class VerificationModal(
    discord.ui.Modal,
    title="Organization Application"
):

    character_name = discord.ui.TextInput(
        label="Character Name",
        placeholder="Enter character name",
        max_length=80
    )

    character_age = discord.ui.TextInput(
        label="Character Age",
        placeholder="Enter character age",
        max_length=3
    )

    experience = discord.ui.TextInput(
        label="RP Experience",
        placeholder="Tell us about your RP experience",
        style=discord.TextStyle.paragraph,
        max_length=1000
    )

    def __init__(self, organization):

        super().__init__()

        self.organization = organization

    async def on_submit(self, interaction):

        cursor = db.cursor()

        cursor.execute(
            """
            INSERT INTO verification(
                guild_id,
                user_id,
                organization,
                character_name,
                character_age,
                experience,
                status,
                created_at
            )
            VALUES(?,?,?,?,?,?,?,?)
            """,
            (
                interaction.guild.id,
                interaction.user.id,
                self.organization,
                self.character_name.value,
                self.character_age.value,
                self.experience.value,
                "pending",
                iso_time(utc_now())
            )
        )

        request_id = cursor.lastrowid

        db.commit()

        embed = discord.Embed(
            title="📋 New Organization Application",
            color=discord.Color.blurple()
        )

        embed.add_field(
            name="Applicant",
            value=interaction.user.mention,
            inline=False
        )

        embed.add_field(
            name="Organization",
            value=self.organization,
            inline=True
        )

        embed.add_field(
            name="Character",
            value=self.character_name.value,
            inline=True
        )

        embed.add_field(
            name="Age",
            value=self.character_age.value,
            inline=True
        )

        embed.add_field(
            name="Experience",
            value=self.experience.value,
            inline=False
        )

        embed.set_footer(
            text=f"Application #{request_id}"
        )

        await interaction.response.send_message(
            "✅ Application submitted successfully.",
            ephemeral=True
        )

        print(
            f"APPLICATION #{request_id}"
        )


class OrganizationButton(
    discord.ui.Button
):

    def __init__(self, organization):

        super().__init__(
            label=organization,
            style=discord.ButtonStyle.primary,
            custom_id=f"org_apply_{organization}"
        )

        self.organization = organization

    async def callback(self, interaction):

        await interaction.response.send_modal(
            VerificationModal(
                self.organization
            )
        )


class OrganizationPanel(
    discord.ui.View
):

    def __init__(self):

        super().__init__(
            timeout=None
        )

        organizations = [
            "Government",
            "Army",
            "EMERCOM",
            "Yuzhny Hospital"
        ]

        for organization in organizations:

            self.add_item(
                OrganizationButton(
                    organization
                )
            )


@bot.tree.command(
    name="orgpanel",
    description="Show organization application panel."
)
async def orgpanel(interaction):

    if not is_staff(interaction.user):

        return await interaction.response.send_message(
            "❌ Staff only.",
            ephemeral=True
        )

    embed = discord.Embed(
        title="🏛️ Modern City Organizations",
        description=(
            "Select an organization below "
            "to submit your application."
        ),
        color=discord.Color.blurple()
    )

    await interaction.response.send_message(
        embed=embed,
        view=OrganizationPanel()
    )


# =========================================================
# WARN
# =========================================================

@bot.tree.command(
    name="warn",
    description="Warn a member."
)
@app_commands.describe(
    member="Member",
    reason="Warning reason"
)
async def warn(
    interaction,
    member: discord.Member,
    reason: str
):

    if not is_staff(interaction.user):

        return await interaction.response.send_message(
            "❌ Staff only.",
            ephemeral=True
        )

    db.execute(
        """
        INSERT INTO warnings(
            guild_id,
            user_id,
            reason,
            issuer_id,
            created_at
        )
        VALUES(?,?,?,?,?)
        """,
        (
            interaction.guild.id,
            member.id,
            reason,
            interaction.user.id,
            iso_time(utc_now())
        )
    )

    db.commit()

    await interaction.response.send_message(
        f"⚠️ {member.mention} has been warned.\n"
        f"**Reason:** {reason}"
    )


# =========================================================
# WARNINGS
# =========================================================

@bot.tree.command(
    name="warnings",
    description="View member warnings."
)
@app_commands.describe(
    member="Member"
)
async def warnings(
    interaction,
    member: discord.Member
):

    if not is_staff(interaction.user):

        return await interaction.response.send_message(
            "❌ Staff only.",
            ephemeral=True
        )

    rows = db.execute(
        """
        SELECT *
        FROM warnings
        WHERE guild_id=? AND user_id=?
        ORDER BY id DESC
        LIMIT 15
        """,
        (
            interaction.guild.id,
            member.id
        )
    ).fetchall()

    if not rows:

        return await interaction.response.send_message(
            f"✅ {member.mention} has no warnings."
        )

    text = []

    for index, row in enumerate(
        rows,
        start=1
    ):

        text.append(
            f"**{index}.** {row['reason']}\n"
            f"By <@{row['issuer_id']}>"
        )

    embed = discord.Embed(
        title=f"⚠️ Warnings • {member}",
        description="\n\n".join(text),
        color=discord.Color.orange()
    )

    await interaction.response.send_message(
        embed=embed
    )


# =========================================================
# CLEAR WARNINGS
# =========================================================

@bot.tree.command(
    name="clearwarnings",
    description="Clear member warnings."
)
@app_commands.describe(
    member="Member"
)
async def clearwarnings(
    interaction,
    member: discord.Member
):

    if not is_staff(interaction.user):

        return await interaction.response.send_message(
            "❌ Staff only.",
            ephemeral=True
        )

    db.execute(
        """
        DELETE FROM warnings
        WHERE guild_id=? AND user_id=?
        """,
        (
            interaction.guild.id,
            member.id
        )
    )

    db.commit()

    await interaction.response.send_message(
        f"🧹 Cleared warnings for {member.mention}."
    )


# =========================================================
# KICK
# =========================================================

@bot.tree.command(
    name="kick",
    description="Kick a member."
)
@app_commands.describe(
    member="Member",
    reason="Reason"
)
async def kick(
    interaction,
    member: discord.Member,
    reason: str = "No reason provided"
):

    if not is_staff(interaction.user):

        return await interaction.response.send_message(
            "❌ Staff only.",
            ephemeral=True
        )

    try:

        await member.kick(
            reason=reason
        )

        await interaction.response.send_message(
            f"👢 Kicked {member.mention}."
        )

    except discord.Forbidden:

        await interaction.response.send_message(
            "❌ I cannot kick this member.",
            ephemeral=True
        )


# =========================================================
# BAN
# =========================================================

@bot.tree.command(
    name="ban",
    description="Ban a member."
)
@app_commands.describe(
    member="Member",
    reason="Reason"
)
async def ban(
    interaction,
    member: discord.Member,
    reason: str = "No reason provided"
):

    if not is_staff(interaction.user):

        return await interaction.response.send_message(
            "❌ Staff only.",
            ephemeral=True
        )

    try:

        await member.ban(
            reason=reason
        )

        await interaction.response.send_message(
            f"🔨 Banned {member.mention}."
        )

    except discord.Forbidden:

        await interaction.response.send_message(
            "❌ I cannot ban this member.",
            ephemeral=True
        )


# =========================================================
# TIMEOUT
# =========================================================

@bot.tree.command(
    name="timeout",
    description="Timeout a member."
)
@app_commands.describe(
    member="Member",
    minutes="Duration in minutes",
    reason="Reason"
)
async def timeout(
    interaction,
    member: discord.Member,
    minutes: int,
    reason: str = "No reason provided"
):

    if not is_staff(interaction.user):

        return await interaction.response.send_message(
            "❌ Staff only.",
            ephemeral=True
        )

    if minutes < 1 or minutes > 40320:

        return await interaction.response.send_message(
            "❌ Duration must be 1 to 40320 minutes.",
            ephemeral=True
        )

    try:

        await member.timeout(
            timedelta(minutes=minutes),
            reason=reason
        )

        await interaction.response.send_message(
            f"🔇 {member.mention} timed out "
            f"for **{minutes} minutes**."
        )

    except discord.Forbidden:

        await interaction.response.send_message(
            "❌ I cannot timeout this member.",
            ephemeral=True
        )


# =========================================================
# CLEAR
# =========================================================

@bot.tree.command(
    name="clear",
    description="Delete messages."
)
@app_commands.describe(
    amount="Number of messages"
)
async def clear(
    interaction,
    amount: int
):

    if not is_staff(interaction.user):

        return await interaction.response.send_message(
            "❌ Staff only.",
            ephemeral=True
        )

    if amount < 1 or amount > 100:

        return await interaction.response.send_message(
            "❌ Amount must be between 1 and 100.",
            ephemeral=True
        )

    await interaction.response.defer(
        ephemeral=True
    )

    deleted = await interaction.channel.purge(
        limit=amount
    )

    await interaction.followup.send(
        f"🧹 Deleted **{len(deleted)}** messages.",
        ephemeral=True
    )


# =========================================================
# ACTIVITY
# =========================================================

@bot.tree.command(
    name="activity",
    description="View tracked server activity."
)
@app_commands.describe(
    member="Member to check"
)
async def activity(
    interaction,
    member: discord.Member | None = None
):

    member = member or interaction.user

    if (
        member.id != interaction.user.id
        and not is_staff(interaction.user)
    ):

        return await interaction.response.send_message(
            "❌ You can only view your own activity.",
            ephemeral=True
        )

    ensure_activity(member)

    row = db.execute(
        """
        SELECT *
        FROM activity
        WHERE guild_id=? AND user_id=?
        """,
        (
            interaction.guild.id,
            member.id
        )
    ).fetchone()

    total = get_total_activity(row)
    active = get_active_activity(row)
    idle = get_idle_activity(row)

    embed = discord.Embed(
        title=f"📊 Activity • {member.display_name}",
        color=discord.Color.blurple()
    )

    embed.add_field(
        name="Status",
        value=row["current_status"].upper(),
        inline=True
    )

    embed.add_field(
        name="Total Tracked",
        value=format_duration(total),
        inline=True
    )

    embed.add_field(
        name="Active Time",
        value=format_duration(active),
        inline=True
    )

    embed.add_field(
        name="AFK / Idle",
        value=format_duration(idle),
        inline=True
    )

    if member.joined_at:

        embed.add_field(
            name="Server Joined",
            value=discord.utils.format_dt(
                member.joined_at,
                "R"
            ),
            inline=True
        )

    await interaction.response.send_message(
        embed=embed
    )


# =========================================================
# ACTIVITY BOARD
# =========================================================

@bot.tree.command(
    name="activityboard",
    description="Show activity leaderboard."
)
async def activityboard(interaction):

    if not is_staff(interaction.user):

        return await interaction.response.send_message(
            "❌ Staff only.",
            ephemeral=True
        )

    rows = db.execute(
        """
        SELECT *
        FROM activity
        WHERE guild_id=?
        """,
        (
            interaction.guild.id,
        )
    ).fetchall()

    rows = sorted(
        rows,
        key=get_total_activity,
        reverse=True
    )

    lines = []

    position = 1

    for row in rows:

        member = interaction.guild.get_member(
            row["user_id"]
        )

        if not member or member.bot:
            continue

        lines.append(
            f"**{position}.** "
            f"{member.mention} • "
            f"`{format_duration(get_total_activity(row))}`"
        )

        position += 1

        if position > 15:
            break

    embed = discord.Embed(
        title="🏆 Server Activity",
        description="\n".join(lines)
        or "No activity data yet.",
        color=discord.Color.gold()
    )

    await interaction.response.send_message(
        embed=embed
    )


# =========================================================
# AFK LIST
# =========================================================

@bot.tree.command(
    name="afklist",
    description="Show currently idle members."
)
async def afklist(interaction):

    if not is_staff(interaction.user):

        return await interaction.response.send_message(
            "❌ Staff only.",
            ephemeral=True
        )

    rows = db.execute(
        """
        SELECT *
        FROM activity
        WHERE guild_id=?
        AND current_status='idle'
        ORDER BY idle_since ASC
        """,
        (
            interaction.guild.id,
        )
    ).fetchall()

    lines = []

    now = utc_now()

    for row in rows:

        member = interaction.guild.get_member(
            row["user_id"]
        )

        if not member or member.bot:
            continue

        if row["idle_since"]:

            idle_since = parse_time(
                row["idle_since"]
            )

            duration = (
                now - idle_since
            ).total_seconds()

        else:

            duration = 0

        lines.append(
            f"{member.mention} • "
            f"`{format_duration(duration)}`"
        )

        if len(lines) >= 20:
            break

    embed = discord.Embed(
        title="💤 Current AFK / Idle",
        description="\n".join(lines)
        or "Nobody is currently idle.",
        color=discord.Color.orange()
    )

    await interaction.response.send_message(
        embed=embed
    )


# =========================================================
# SERVER ACTIVITY
# =========================================================

@bot.tree.command(
    name="serveractivity",
    description="Show overall server activity."
)
async def serveractivity(interaction):

    if not is_staff(interaction.user):

        return await interaction.response.send_message(
            "❌ Staff only.",
            ephemeral=True
        )

    rows = db.execute(
        """
        SELECT *
        FROM activity
        WHERE guild_id=?
        """,
        (
            interaction.guild.id,
        )
    ).fetchall()

    online = 0
    idle = 0
    dnd = 0

    for row in rows:

        if row["current_status"] == "online":
            online += 1

        elif row["current_status"] == "idle":
            idle += 1

        elif row["current_status"] == "dnd":
            dnd += 1

    embed = discord.Embed(
        title="📊 Modern City Server Activity",
        color=discord.Color.blurple()
    )

    embed.add_field(
        name="👥 Members",
        value=str(
            interaction.guild.member_count
        ),
        inline=True
    )

    embed.add_field(
        name="🟢 Online",
        value=str(online),
        inline=True
    )

    embed.add_field(
        name="💤 AFK / Idle",
        value=str(idle),
        inline=True
    )

    embed.add_field(
        name="🔴 DND",
        value=str(dnd),
        inline=True
    )

    embed.add_field(
        name="📡 Tracking",
        value="Presence based",
        inline=False
    )

    await interaction.response.send_message(
        embed=embed
    )


# =========================================================
# ACTIVITY RESET
# =========================================================

@bot.tree.command(
    name="activityreset",
    description="Reset member activity."
)
@app_commands.describe(
    member="Member"
)
async def activityreset(
    interaction,
    member: discord.Member
):

    if not is_staff(interaction.user):

        return await interaction.response.send_message(
            "❌ Staff only.",
            ephemeral=True
        )

    db.execute(
        """
        UPDATE activity
        SET
            active_seconds=0,
            idle_seconds=0,
            current_status='offline',
            last_change=?,
            idle_since=NULL
        WHERE guild_id=? AND user_id=?
        """,
        (
            iso_time(utc_now()),
            interaction.guild.id,
            member.id
        )
    )

    db.commit()

    await interaction.response.send_message(
        f"♻️ Activity reset for {member.mention}."
    )


# =========================================================
# ANNOUNCEMENT
# =========================================================

@bot.tree.command(
    name="announce",
    description="Send announcement with Citizen mention."
)
@app_commands.describe(
    channel="Announcement channel",
    title="Announcement title",
    message="Announcement message"
)
async def announce(
    interaction,
    channel: discord.TextChannel,
    title: str,
    message: str
):

    if not is_staff(interaction.user):

        return await interaction.response.send_message(
            "❌ Staff only.",
            ephemeral=True
        )

    citizen = interaction.guild.get_role(
        CITIZEN_ROLE_ID
    )

    if citizen is None:

        return await interaction.response.send_message(
            "❌ Citizen role not found.",
            ephemeral=True
        )

    embed = discord.Embed(
        title=f"📢 {title}",
        description=message,
        color=discord.Color.blurple(),
        timestamp=utc_now()
    )

    embed.set_footer(
        text=f"Posted by {interaction.user.display_name}"
    )

    allowed_mentions = discord.AllowedMentions(
        roles=[citizen],
        users=False,
        everyone=False,
        replied_user=False
    )

    await channel.send(
        content=citizen.mention,
        embed=embed,
        allowed_mentions=allowed_mentions
    )

    await interaction.response.send_message(
        f"✅ Announcement sent to {channel.mention}.",
        ephemeral=True
    )


# =========================================================
# PING
# =========================================================

@bot.tree.command(
    name="ping",
    description="Check bot latency."
)
async def ping(interaction):

    latency = round(
        bot.latency * 1000
    )

    await interaction.response.send_message(
        f"🏓 Pong! `{latency}ms`"
    )


# =========================================================
# BOT INFO
# =========================================================

@bot.tree.command(
    name="botinfo",
    description="Show bot information."
)
async def botinfo(interaction):

    embed = discord.Embed(
        title="🤖 Modern City Bot",
        description=(
            "Modern City RP security, "
            "moderation and management bot."
        ),
        color=discord.Color.blurple()
    )

    embed.add_field(
        name="🛡️ Security",
        value="Advanced Anti-Link",
        inline=True
    )

    embed.add_field(
        name="📊 Activity",
        value="Presence + AFK",
        inline=True
    )

    embed.add_field(
        name="📢 Announcements",
        value="Citizen Auto Mention",
        inline=True
    )

    embed.add_field(
        name="💾 Database",
        value="SQLite",
        inline=True
    )

    embed.add_field(
        name="🎙️ Recording",
        value="Disabled",
        inline=True
    )

    await interaction.response.send_message(
        embed=embed
    )


# =========================================================
# SERVER INFO
# =========================================================

@bot.tree.command(
    name="serverinfo",
    description="Show server information."
)
async def serverinfo(interaction):

    guild = interaction.guild

    embed = discord.Embed(
        title=f"🏙️ {guild.name}",
        color=discord.Color.blurple()
    )

    embed.add_field(
        name="👥 Members",
        value=str(guild.member_count),
        inline=True
    )

    embed.add_field(
        name="💬 Channels",
        value=str(len(guild.channels)),
        inline=True
    )

    embed.add_field(
        name="🎭 Roles",
        value=str(len(guild.roles)),
        inline=True
    )

    embed.add_field(
        name="📅 Created",
        value=discord.utils.format_dt(
            guild.created_at,
            "D"
        ),
        inline=False
    )

    await interaction.response.send_message(
        embed=embed
    )


# =========================================================
# START BOT
# =========================================================

if not TOKEN:
    raise RuntimeError(
        "BOT_TOKEN GitHub Secret is missing."
    )

init_database()

bot.run(TOKEN)
