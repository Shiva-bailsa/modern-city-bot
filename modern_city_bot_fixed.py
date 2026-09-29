import os
import re
import sqlite3
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import discord
from discord import app_commands
from discord.ext import commands, tasks


# ============================================================
# MODERN CITY RP BOT
# COMPLETE SINGLE-FILE VERSION
# ============================================================

TOKEN = os.getenv("BOT_TOKEN")

# ============================================================
# SERVER CONFIG
# ============================================================

GUILD_ID = 1552902541061394432

CITIZEN_ROLE_ID = 1552903102204747856
MASTER_ROLE_ID = 1552903005500866650

ORG_PANEL_CHANNEL_ID = 1552903355339243520
APPLICATION_CATEGORY_ID = 1553784383989743616
LOG_CHANNEL_ID = 1553365117750485032

DB_FILE = "modern_city.db"

IST = ZoneInfo("Asia/Kolkata")


# ============================================================
# STAFF ROLES
# ============================================================

STAFF_ROLE_NAMES = {
    "Founder",
    "Owner",
    "Administrator",
    "Head Administrator",
    "Senior Administrator",
    "Moderator",
    "Senior Moderator",
}


# ============================================================
# ORGANIZATIONS
# ============================================================

ORG_ROLE_NAMES = [
    "🏛️ Government",
    "🪖 Military Unit",
    "🏥 ARZAMAS Hospital",
    "🏥 YUZHNEY Hospital",
    "🚓 Yuzhny Police Department",
    "🕵️ FBI",
    "🚓 Arzamas Police Department",
    "📰 News Network",
    "🏴 Caucasian OCG",
    "🏴 Orekhov OCG",
    "🏴 Kurgan OCG",
]


# ============================================================
# LINK PROTECTION
# ============================================================

URL_PATTERN = re.compile(
    r"""(?ix)
    (?:
        https?://[^\s<>()]+
        |
        www\.[^\s<>()]+
        |
        discord\.gg/[^\s<>()]+
        |
        discord(?:app)?\.com/invite/[^\s<>()]+
        |
        (?<![@\w.-])
        (?:[a-z0-9-]+\.)+
        (?:com|net|org|gg|io|in|co|xyz|me|dev|app|info|biz|site|online|store|tech|pro|live|tv|ly|link)
        (?:[/?#][^\s<>()]*)?
    )
    """
)


# ============================================================
# DISCORD INTENTS
# ============================================================

intents = discord.Intents.default()

intents.members = True
intents.presences = True
intents.message_content = True


# ============================================================
# TIME HELPERS
# ============================================================

def now_utc():
    return datetime.now(timezone.utc)


def now_ist():
    return datetime.now(IST)


def iso_now():
    return now_utc().isoformat()


def parse_dt(value):
    if not value:
        return None

    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def format_seconds(seconds):
    seconds = max(0, int(seconds or 0))

    days, remainder = divmod(seconds, 86400)
    hours, remainder = divmod(remainder, 3600)
    minutes, _ = divmod(remainder, 60)

    parts = []

    if days:
        parts.append(f"{days}d")

    if hours:
        parts.append(f"{hours}h")

    if minutes or not parts:
        parts.append(f"{minutes}m")

    return " ".join(parts)


# ============================================================
# DATABASE
# ============================================================

def db():
    return sqlite3.connect(DB_FILE)


def init_db():

    with db() as con:

        # ----------------------------
        # WARNINGS
        # ----------------------------

        con.execute("""
            CREATE TABLE IF NOT EXISTS warnings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                guild_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                moderator_id INTEGER NOT NULL,
                reason TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
        """)

        # ----------------------------
        # APPLICATIONS
        # ----------------------------

        con.execute("""
            CREATE TABLE IF NOT EXISTS applications (
                user_id INTEGER PRIMARY KEY,
                channel_id INTEGER NOT NULL,
                org_name TEXT NOT NULL,
                proof_received INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL
            )
        """)

        # ----------------------------
        # ACTIVITY
        # ----------------------------

        con.execute("""
            CREATE TABLE IF NOT EXISTS activity (
                user_id INTEGER PRIMARY KEY,
                online_seconds INTEGER NOT NULL DEFAULT 0,
                idle_seconds INTEGER NOT NULL DEFAULT 0,
                dnd_seconds INTEGER NOT NULL DEFAULT 0,
                session_count INTEGER NOT NULL DEFAULT 0,
                first_tracked TEXT,
                last_seen TEXT,
                current_status TEXT NOT NULL DEFAULT 'offline',
                status_started TEXT NOT NULL
            )
        """)

        # ----------------------------
        # DAILY ACTIVITY
        # ----------------------------

        con.execute("""
            CREATE TABLE IF NOT EXISTS daily_activity (
                user_id INTEGER NOT NULL,
                day TEXT NOT NULL,
                online_seconds INTEGER NOT NULL DEFAULT 0,
                idle_seconds INTEGER NOT NULL DEFAULT 0,
                dnd_seconds INTEGER NOT NULL DEFAULT 0,
                PRIMARY KEY (user_id, day)
            )
        """)


# ============================================================
# GENERAL HELPERS
# ============================================================

def is_staff(member):

    if member.guild_permissions.administrator:
        return True

    if any(role.id == MASTER_ROLE_ID for role in member.roles):
        return True

    return any(
        role.name in STAFF_ROLE_NAMES
        for role in member.roles
    )


def get_master_role(guild):
    return guild.get_role(MASTER_ROLE_ID)


def get_citizen_role(guild):
    return guild.get_role(CITIZEN_ROLE_ID)


def find_org_role(guild, org_name):

    return discord.utils.find(
        lambda role: role.name == org_name,
        guild.roles,
    )


async def send_log(
    guild,
    title,
    description,
    color=discord.Color.blurple(),
):

    channel = guild.get_channel(LOG_CHANNEL_ID)

    if not isinstance(channel, discord.TextChannel):
        return

    embed = discord.Embed(
        title=title,
        description=description,
        color=color,
        timestamp=now_utc(),
    )

    try:
        await channel.send(embed=embed)
    except discord.HTTPException:
        pass


# ============================================================
# ACTIVITY FUNCTIONS
# ============================================================

def ensure_activity_row(user_id, status="offline"):

    stamp = iso_now()

    with db() as con:

        row = con.execute(
            "SELECT user_id FROM activity WHERE user_id=?",
            (user_id,),
        ).fetchone()

        if row:
            return

        con.execute(
            """
            INSERT INTO activity (
                user_id,
                first_tracked,
                last_seen,
                current_status,
                status_started
            )
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                user_id,
                stamp,
                stamp,
                status,
                stamp,
            ),
        )


def get_activity_row(user_id):

    with db() as con:

        return con.execute(
            """
            SELECT
                user_id,
                online_seconds,
                idle_seconds,
                dnd_seconds,
                session_count,
                first_tracked,
                last_seen,
                current_status,
                status_started
            FROM activity
            WHERE user_id=?
            """,
            (user_id,),
        ).fetchone()


def get_status_column(status):

    if status == "online":
        return "online_seconds"

    if status == "idle":
        return "idle_seconds"

    if status == "dnd":
        return "dnd_seconds"

    return None


def add_activity(user_id, status, seconds):

    if seconds <= 0:
        return

    column = get_status_column(status)

    if not column:
        return

    day = now_ist().date().isoformat()

    with db() as con:

        con.execute(
            f"""
            UPDATE activity
            SET {column} = {column} + ?,
                last_seen = ?
            WHERE user_id=?
            """,
            (
                seconds,
                iso_now(),
                user_id,
            ),
        )

        con.execute(
            """
            INSERT INTO daily_activity (
                user_id,
                day,
                online_seconds,
                idle_seconds,
                dnd_seconds
            )
            VALUES (?, ?, ?, ?, ?)

            ON CONFLICT(user_id, day)
            DO UPDATE SET
                online_seconds =
                    online_seconds + excluded.online_seconds,

                idle_seconds =
                    idle_seconds + excluded.idle_seconds,

                dnd_seconds =
                    dnd_seconds + excluded.dnd_seconds
            """,
            (
                user_id,
                day,
                seconds if status == "online" else 0,
                seconds if status == "idle" else 0,
                seconds if status == "dnd" else 0,
            ),
        )


def change_activity_status(user_id, new_status):

    ensure_activity_row(
        user_id,
        new_status,
    )

    row = get_activity_row(user_id)

    if not row:
        return

    (
        user_id,
        online_seconds,
        idle_seconds,
        dnd_seconds,
        session_count,
        first_tracked,
        last_seen,
        old_status,
        status_started,
    ) = row

    started = parse_dt(status_started)

    if started and old_status in {
        "online",
        "idle",
        "dnd",
    }:

        elapsed = int(
            (now_utc() - started).total_seconds()
        )

        add_activity(
            user_id,
            old_status,
            elapsed,
        )

    sessions = session_count

    if (
        old_status == "offline"
        and new_status in {
            "online",
            "idle",
            "dnd",
        }
    ):
        sessions += 1

    stamp = iso_now()

    with db() as con:

        con.execute(
            """
            UPDATE activity
            SET
                current_status=?,
                status_started=?,
                session_count=?,
                last_seen=?
            WHERE user_id=?
            """,
            (
                new_status,
                stamp,
                sessions,
                stamp,
                user_id,
            ),
        )


# ============================================================
# BOT CLASS
# ============================================================

class ModernCityBot(commands.Bot):

    async def setup_hook(self):

        # Persistent buttons
        self.add_view(
            OrganizationPanelView()
        )

        self.add_view(
            ApplicationReviewView()
        )

        # Initialize database
        init_db()

        # Guild slash commands
        guild = discord.Object(
            id=GUILD_ID
        )

        try:

            synced = await self.tree.sync(
                guild=guild
            )

            print(
                f"Synced {len(synced)} slash commands."
            )

        except Exception as error:

            print(
                f"Slash command sync failed: {error}"
            )


bot = ModernCityBot(
    command_prefix="!",
    intents=intents,
    help_command=None,
)


# ============================================================
# SLASH COMMANDS
# ============================================================

@bot.tree.command(
    name="ping",
    description="Check the bot latency",
    guild=discord.Object(id=GUILD_ID),
)
async def ping(interaction: discord.Interaction):

    latency = round(bot.latency * 1000)

    await interaction.response.send_message(
        f"🏓 Pong! `{latency}ms`",
        ephemeral=True,
    )


@bot.tree.command(
    name="orgpanel",
    description="Create the Modern City organization panel",
    guild=discord.Object(id=GUILD_ID),
)
async def orgpanel(interaction: discord.Interaction):

    if not interaction.guild:
        await interaction.response.send_message(
            "❌ This command can only be used inside the server.",
            ephemeral=True,
        )
        return

    if not isinstance(interaction.user, discord.Member):
        await interaction.response.send_message(
            "❌ Member information unavailable.",
            ephemeral=True,
        )
        return

    if not is_staff(interaction.user):
        await interaction.response.send_message(
            "❌ Master/Staff only.",
            ephemeral=True,
        )
        return

    channel = interaction.guild.get_channel(
        ORG_PANEL_CHANNEL_ID
    )

    if not isinstance(channel, discord.TextChannel):
        await interaction.response.send_message(
            "❌ Organization panel channel is missing.",
            ephemeral=True,
        )
        return

    embed = discord.Embed(
        title="🏛️ Modern City Organization Center",
        description=(
            "Select the organization you want to apply for.\n\n"
            "**Rules**\n"
            "• Only one organization role at a time.\n"
            "• Proof is mandatory.\n"
            "• Master/Staff verifies applications.\n"
            "• Citizen role is retained.\n\n"
            "Tap an organization button to open your private application."
        ),
        color=discord.Color.dark_blue(),
    )

    try:
        await channel.send(
            embed=embed,
            view=OrganizationPanelView(),
        )

        await interaction.response.send_message(
            f"✅ Organization panel created in {channel.mention}.",
            ephemeral=True,
        )

    except discord.HTTPException as error:
        await interaction.response.send_message(
            f"❌ Could not create the panel: `{error}`",
            ephemeral=True,
        )


# ============================================================
# ORGANIZATION PANEL
# ============================================================

class OrganizationPanelView(discord.ui.View):

    def __init__(self):

        super().__init__(
            timeout=None
        )

        for index, org_name in enumerate(
            ORG_ROLE_NAMES
        ):

            button = discord.ui.Button(
                label=org_name,
                style=discord.ButtonStyle.secondary,
                custom_id=f"org_apply_{index}",
                row=index // 3,
            )

            button.callback = (
                self.make_callback(
                    org_name
                )
            )

            self.add_item(button)

    def make_callback(self, org_name):

        async def callback(interaction):

            await create_application(
                interaction,
                org_name,
            )

        return callback


# ============================================================
# CREATE APPLICATION
# ============================================================

async def create_application(
    interaction,
    org_name,
):

    guild = interaction.guild
    member = interaction.user

    if not guild:
        return

    if not isinstance(
        member,
        discord.Member,
    ):
        return

    # ----------------------------
    # CHECK EXISTING APPLICATION
    # ----------------------------

    with db() as con:

        existing = con.execute(
            """
            SELECT channel_id
            FROM applications
            WHERE user_id=?
            """,
            (member.id,),
        ).fetchone()

    if existing:

        existing_channel = guild.get_channel(
            existing[0]
        )

        if existing_channel:

            await interaction.response.send_message(
                f"You already have a pending application: "
                f"{existing_channel.mention}",
                ephemeral=True,
            )

            return

        with db() as con:

            con.execute(
                """
                DELETE FROM applications
                WHERE user_id=?
                """,
                (member.id,),
            )

    # ----------------------------
    # CATEGORY
    # ----------------------------

    category = guild.get_channel(
        APPLICATION_CATEGORY_ID
    )

    if not isinstance(
        category,
        discord.CategoryChannel,
    ):

        await interaction.response.send_message(
            "❌ Application category is missing.",
            ephemeral=True,
        )

        return

    # ----------------------------
    # MASTER ROLE
    # ----------------------------

    master_role = get_master_role(
        guild
    )

    if not master_role:

        await interaction.response.send_message(
            "❌ Master role is missing.",
            ephemeral=True,
        )

        return

    # ----------------------------
    # CHANNEL NAME
    # ----------------------------

    safe_name = re.sub(
        r"[^a-z0-9-]+",
        "-",
        member.display_name.lower(),
    ).strip("-")

    if not safe_name:
        safe_name = f"user-{member.id}"

    safe_name = safe_name[:35]

    # ----------------------------
    # PERMISSIONS
    # ----------------------------

    overwrites = {

        guild.default_role:
            discord.PermissionOverwrite(
                view_channel=False
            ),

        member:
            discord.PermissionOverwrite(
                view_channel=True,
                send_messages=True,
                read_message_history=True,
                attach_files=True,
            ),

        master_role:
            discord.PermissionOverwrite(
                view_channel=True,
                send_messages=True,
                read_message_history=True,
            ),
    }

    # ----------------------------
    # CREATE CHANNEL
    # ----------------------------

    try:

        channel = await guild.create_text_channel(
            name=f"apply-{safe_name}",
            category=category,
            overwrites=overwrites,
            reason="Modern City organization application",
        )

    except discord.Forbidden:

        await interaction.response.send_message(
            "❌ I cannot create the application channel. "
            "Check Manage Channels permission.",
            ephemeral=True,
        )

        return

    # ----------------------------
    # DATABASE
    # ----------------------------

    with db() as con:

        con.execute(
            """
            INSERT INTO applications (
                user_id,
                channel_id,
                org_name,
                proof_received,
                created_at
            )
            VALUES (?, ?, ?, 0, ?)
            """,
            (
                member.id,
                channel.id,
                org_name,
                iso_now(),
            ),
        )

    # ----------------------------
    # EMBED
    # ----------------------------

    embed = discord.Embed(
        title="🏛️ Organization Application",
        description=(
            f"**Applicant:** {member.mention}\n"
            f"**Organization:** {org_name}\n\n"

            "**Application Requirements**\n"
            "1. Explain why you want this organization.\n"
            "2. Explain your RP experience.\n"
            "3. Attach your proof in this channel.\n\n"

            "⚠️ **Proof is mandatory.**\n"
            "The application cannot be approved until proof is attached."
        ),
        color=discord.Color.blurple(),
    )

    # ----------------------------
    # SEND APPLICATION
    # ----------------------------

    try:

        await channel.send(
            content=master_role.mention,
            embed=embed,
            view=ApplicationReviewView(),
            allowed_mentions=discord.AllowedMentions(
                roles=True
            ),
        )

        await channel.send(
            f"{member.mention}, please submit your "
            "application details and attach your proof here.",
            allowed_mentions=discord.AllowedMentions(
                users=True
            ),
        )

        await interaction.response.send_message(
            f"✅ Application created: {channel.mention}",
            ephemeral=True,
        )

        await send_log(
            guild,
            "📥 Application Created",
            (
                f"{member.mention} applied for "
                f"**{org_name}**.\n"
                f"Application: {channel.mention}"
            ),
        )

    except discord.HTTPException:

        with db() as con:

            con.execute(
                """
                DELETE FROM applications
                WHERE user_id=?
                """,
                (member.id,),
            )

        try:
            await channel.delete(
                reason="Application setup failed"
            )
        except discord.HTTPException:
            pass

        await interaction.response.send_message(
            "❌ Application setup failed.",
            ephemeral=True,
        )


# ============================================================
# APPLICATION REVIEW BUTTONS
# ============================================================

class ApplicationReviewView(discord.ui.View):

    def __init__(self):

        super().__init__(
            timeout=None
        )

    async def check_staff(
        self,
        interaction,
    ):

        if not interaction.guild:
            return False

        if not isinstance(
            interaction.user,
            discord.Member,
        ):
            return False

        if not is_staff(
            interaction.user
        ):

            await interaction.response.send_message(
                "❌ Master/Staff only.",
                ephemeral=True,
            )

            return False

        return True

    # ========================================================
    # APPROVE
    # ========================================================

    @discord.ui.button(
        label="Approve",
        style=discord.ButtonStyle.success,
        custom_id="app_approve",
        row=0,
    )
    async def approve(
        self,
        interaction,
        button,
    ):

        if not await self.check_staff(
            interaction
        ):
            return

        guild = interaction.guild
        channel = interaction.channel

        if not isinstance(
            channel,
            discord.TextChannel,
        ):
            return

        with db() as con:

            row = con.execute(
                """
                SELECT
                    user_id,
                    org_name,
                    proof_received
                FROM applications
                WHERE channel_id=?
                """,
                (channel.id,),
            ).fetchone()

        if not row:

            await interaction.response.send_message(
                "❌ Application data not found.",
                ephemeral=True,
            )

            return

        (
            user_id,
            org_name,
            proof_received,
        ) = row

        # ----------------------------
        # PROOF REQUIRED
        # ----------------------------

        if not proof_received:

            await interaction.response.send_message(
                "❌ Proof is mandatory. "
                "Ask the applicant to attach proof first.",
                ephemeral=True,
            )

            return

        member = guild.get_member(
            user_id
        )

        if not member:

            await interaction.response.send_message(
                "❌ Applicant is no longer in the server.",
                ephemeral=True,
            )

            return

        target_role = find_org_role(
            guild,
            org_name,
        )

        if not target_role:

            await interaction.response.send_message(
                f"❌ Role not found:\n`{org_name}`\n\n"
                "Create the role with the exact name first.",
                ephemeral=True,
            )

            return

        bot_member = guild.me

        if not bot_member:

            await interaction.response.send_message(
                "❌ Bot member information is unavailable.",
                ephemeral=True,
            )

            return

        # ----------------------------
        # ROLE HIERARCHY
        # ----------------------------

        if target_role >= bot_member.top_role:

            await interaction.response.send_message(
                "❌ Bot role must be ABOVE the organization roles.",
                ephemeral=True,
            )

            return

        # ----------------------------
        # FIND OLD ORG ROLES
        # ----------------------------

        old_roles = [

            role

            for role in member.roles

            if (
                role.name in ORG_ROLE_NAMES
                and role.id != target_role.id
            )

        ]

        try:

            # Remove old organization role(s)
            if old_roles:

                await member.remove_roles(
                    *old_roles,
                    reason="Organization role switch",
                )

            # Add new organization role
            if target_role not in member.roles:

                await member.add_roles(
                    target_role,
                    reason="Organization application approved",
                )

            # Keep Citizen
            citizen = get_citizen_role(
                guild
            )

            if (
                citizen
                and citizen not in member.roles
            ):

                await member.add_roles(
                    citizen,
                    reason="Citizen role retained",
                )

        except discord.Forbidden:

            await interaction.response.send_message(
                "❌ Role action failed.\n"
                "Move the bot role above all organization roles "
                "and make sure Manage Roles is enabled.",
                ephemeral=True,
            )

            return

        # ----------------------------
        # SUCCESS
        # ----------------------------

        await interaction.response.send_message(
            f"✅ {member.mention} approved for "
            f"**{org_name}**.",
            ephemeral=True,
        )

        await send_log(
            guild,
            "✅ Organization Approved",
            (
                f"**Member:** {member.mention}\n"
                f"**Organization:** {org_name}\n"
                f"**Approved by:** {interaction.user.mention}"
            ),
            discord.Color.green(),
        )

        with db() as con:

            con.execute(
                """
                DELETE FROM applications
                WHERE user_id=?
                """,
                (user_id,),
            )

        try:

            await channel.delete(
                reason="Organization application approved"
            )

        except discord.HTTPException:
            pass

    # ========================================================
    # REJECT
    # ========================================================

    @discord.ui.button(
        label="Reject",
        style=discord.ButtonStyle.danger,
        custom_id="app_reject",
        row=0,
    )
    async def reject(
        self,
        interaction,
        button,
    ):

        if not await self.check_staff(
            interaction
        ):
            return

        guild = interaction.guild
        channel = interaction.channel

        if not isinstance(
            channel,
            discord.TextChannel,
        ):
            return

        with db() as con:

            row = con.execute(
                """
                SELECT user_id, org_name
                FROM applications
                WHERE channel_id=?
                """,
                (channel.id,),
            ).fetchone()

        if not row:

            await interaction.response.send_message(
                "❌ Application data not found.",
                ephemeral=True,
            )

            return

        user_id, org_name = row

        member = guild.get_member(
            user_id
        )

        await interaction.response.send_message(
            "❌ Application rejected.",
            ephemeral=True,
        )

        await send_log(
            guild,
            "❌ Organization Rejected",
            (
                f"**Member:** "
                f"{member.mention if member else user_id}\n"
                f"**Organization:** {org_name}\n"
                f"**Rejected by:** {interaction.user.mention}"
            ),
            discord.Color.red(),
        )

        with db() as con:

            con.execute(
                """
                DELETE FROM applications
                WHERE user_id=?
                """,
                (user_id,),
            )

        try:

            await channel.delete(
                reason="Organization application rejected"
            )

        except discord.HTTPException:
            pass

    # ========================================================
    # MORE PROOF
    # ========================================================

    @discord.ui.button(
        label="More Proof",
        style=discord.ButtonStyle.primary,
        custom_id="app_more_proof",
        row=0,
    )
    async def more_proof(
        self,
        interaction,
        button,
    ):

        if not await self.check_staff(
            interaction
        ):
            return

        await interaction.response.send_message(
            "📎 **Additional proof required.**\n"
            "Applicant, attach the requested proof in this channel."
        )

        await send_log(
            interaction.guild,
            "📎 More Proof Requested",
            (
                f"Requested by {interaction.user.mention}\n"
                f"Channel: {interaction.channel.mention}"
            ),
            discord.Color.orange(),
        )

    # ========================================================
    # CLOSE
    # ========================================================

    @discord.ui.button(
        label="Close",
        style=discord.ButtonStyle.secondary,
        custom_id="app_close",
        row=0,
    )
    async def close(
        self,
        interaction,
        button,
    ):

        if not await self.check_staff(
            interaction
        ):
            return

        guild = interaction.guild
        channel = interaction.channel

        if not isinstance(
            channel,
            discord.TextChannel,
        ):
            return

        with db() as con:

            row = con.execute(
                """
                SELECT user_id
                FROM applications
                WHERE channel_id=?
                """,
                (channel.id,),
            ).fetchone()

        if row:

            with db() as con:

                con.execute(
                    """
                    DELETE FROM applications
                    WHERE user_id=?
                    """,
                    (row[0],),
                )

        await interaction.response.send_message(
            "🔒 Application closed.",
            ephemeral=True,
        )

        await send_log(
            guild,
            "🔒 Application Closed",
            (
                f"Channel: {channel.mention}\n"
                f"Closed by: {interaction.user.mention}"
            ),
        )

        try:

            await channel.delete(
                reason="Application closed"
            )

        except discord.HTTPException:
            pass


# ============================================================
# ORGANIZATION PANEL AUTO-CHECK
# ============================================================

async def ensure_org_panel():

    guild = bot.get_guild(
        GUILD_ID
    )

    if not guild:
        return

    if not bot.user:
        return

    channel = guild.get_channel(
        ORG_PANEL_CHANNEL_ID
    )

    if not isinstance(
        channel,
        discord.TextChannel,
    ):
        return

    # Don't create duplicate panels
    try:

        async for message in channel.history(
            limit=50
        ):

            if (
                message.author.id == bot.user.id
                and message.embeds
                and message.embeds[0].title
                == "🏛️ Modern City Organization Center"
            ):

                return

    except discord.HTTPException:
        return

    embed = discord.Embed(
        title="🏛️ Modern City Organization Center",
        description=(
            "Select the organization you want to apply for.\n\n"

            "**Rules**\n"
            "• Only one organization role at a time.\n"
            "• Proof is mandatory.\n"
            "• Master/Staff verifies applications.\n"
            "• Citizen role is retained.\n\n"

            "Tap an organization button to open "
            "your private application."
        ),
        color=discord.Color.dark_blue(),
    )

    try:

        await channel.send(
            embed=embed,
            view=OrganizationPanelView(),
        )

    except discord.HTTPException:
        pass


@bot.event
async def on_ready():

    print(f"Logged in as {bot.user} (ID: {bot.user.id})")

    await ensure_org_panel()


bot.run(TOKEN)
