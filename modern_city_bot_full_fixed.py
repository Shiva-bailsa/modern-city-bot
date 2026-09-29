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
# ADDITIONAL SLASH COMMANDS
# ============================================================

@bot.tree.command(
    name="botinfo",
    description="Show bot information",
    guild=discord.Object(id=GUILD_ID),
)
async def botinfo(interaction: discord.Interaction):
    embed = discord.Embed(
        title="🤖 Modern City Bot",
        description="Modern City RP management bot.",
        color=discord.Color.blurple(),
    )
    embed.add_field(name="Latency", value=f"`{round(bot.latency * 1000)}ms`")
    embed.add_field(name="Guilds", value=f"`{len(bot.guilds)}`")
    await interaction.response.send_message(embed=embed, ephemeral=True)


@bot.tree.command(
    name="serverinfo",
    description="Show server information",
    guild=discord.Object(id=GUILD_ID),
)
async def serverinfo(interaction: discord.Interaction):
    guild = interaction.guild
    embed = discord.Embed(
        title=f"🏙️ {guild.name}",
        color=discord.Color.blurple(),
    )
    embed.add_field(name="Members", value=str(guild.member_count), inline=True)
    embed.add_field(name="Channels", value=str(len(guild.channels)), inline=True)
    embed.add_field(name="Roles", value=str(len(guild.roles)), inline=True)
    embed.add_field(
        name="Created",
        value=discord.utils.format_dt(guild.created_at, "F"),
        inline=False,
    )
    await interaction.response.send_message(embed=embed, ephemeral=True)


@bot.tree.command(
    name="warn",
    description="Warn a member",
    guild=discord.Object(id=GUILD_ID),
)
@app_commands.describe(
    member="Member to warn",
    reason="Reason for the warning",
)
async def warn(
    interaction: discord.Interaction,
    member: discord.Member,
    reason: str,
):
    if not isinstance(interaction.user, discord.Member) or not is_staff(interaction.user):
        await interaction.response.send_message(
            "❌ Master/Staff only.",
            ephemeral=True,
        )
        return

    if member.bot:
        await interaction.response.send_message(
            "❌ You cannot warn a bot.",
            ephemeral=True,
        )
        return

    with db() as con:
        con.execute(
            """
            INSERT INTO warnings
            (guild_id, user_id, moderator_id, reason, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                interaction.guild.id,
                member.id,
                interaction.user.id,
                reason[:500],
                iso_now(),
            ),
        )
        count = con.execute(
            """
            SELECT COUNT(*) FROM warnings
            WHERE guild_id=? AND user_id=?
            """,
            (interaction.guild.id, member.id),
        ).fetchone()[0]

    final_action = count >= 3

    if final_action:
        citizen = get_citizen_role(interaction.guild)
        me = interaction.guild.me

        for role in list(member.roles):
            if role == interaction.guild.default_role:
                continue
            if role.managed:
                continue
            if citizen and role.id == citizen.id:
                continue
            if me and role >= me.top_role:
                continue

            try:
                await member.remove_roles(
                    role,
                    reason="Third warning - remove roles",
                )
            except discord.HTTPException:
                pass

    message = (
        f"⚠️ {member.mention} received warning **#{count}**.\n"
        f"**Reason:** {reason}"
    )

    if final_action:
        message += (
            "\n🚨 **3 warnings reached:** all removable roles "
            "were removed. Citizen role was kept."
        )

    await interaction.response.send_message(message)

    await send_log(
        interaction.guild,
        "⚠️ Warning Issued",
        (
            f"**Member:** {member.mention}\n"
            f"**Moderator:** {interaction.user.mention}\n"
            f"**Warning:** `#{count}`\n"
            f"**Reason:** {reason}"
        ),
        discord.Color.orange(),
    )


@bot.tree.command(
    name="warnings",
    description="View a member's warnings",
    guild=discord.Object(id=GUILD_ID),
)
@app_commands.describe(member="Member to check")
async def warnings(
    interaction: discord.Interaction,
    member: discord.Member,
):
    if not isinstance(interaction.user, discord.Member) or not is_staff(interaction.user):
        await interaction.response.send_message(
            "❌ Master/Staff only.",
            ephemeral=True,
        )
        return

    with db() as con:
        rows = con.execute(
            """
            SELECT id, reason, moderator_id, created_at
            FROM warnings
            WHERE guild_id=? AND user_id=?
            ORDER BY id DESC
            """,
            (interaction.guild.id, member.id),
        ).fetchall()

    if not rows:
        await interaction.response.send_message(
            f"✅ {member.mention} has no warnings.",
            ephemeral=True,
        )
        return

    lines = []
    for row in rows:
        lines.append(
            f"**#{row[0]}** • {row[1]}\n"
            f"Moderator: <@{row[2]}> • `{row[3][:19]}`"
        )

    embed = discord.Embed(
        title=f"⚠️ Warnings • {member.display_name}",
        description="\n\n".join(lines[:20]),
        color=discord.Color.orange(),
    )

    await interaction.response.send_message(
        embed=embed,
        ephemeral=True,
    )


@bot.tree.command(
    name="clearwarnings",
    description="Clear all warnings for a member",
    guild=discord.Object(id=GUILD_ID),
)
@app_commands.describe(member="Member whose warnings should be cleared")
async def clearwarnings(
    interaction: discord.Interaction,
    member: discord.Member,
):
    if not isinstance(interaction.user, discord.Member) or not is_staff(interaction.user):
        await interaction.response.send_message(
            "❌ Master/Staff only.",
            ephemeral=True,
        )
        return

    with db() as con:
        deleted = con.execute(
            """
            DELETE FROM warnings
            WHERE guild_id=? AND user_id=?
            """,
            (interaction.guild.id, member.id),
        ).rowcount

    await interaction.response.send_message(
        f"🧹 Cleared **{deleted}** warning(s) from {member.mention}.",
        ephemeral=True,
    )

    await send_log(
        interaction.guild,
        "🧹 Warnings Cleared",
        f"**Member:** {member.mention}\n**By:** {interaction.user.mention}",
    )


@bot.tree.command(
    name="userinfo",
    description="Show member information",
    guild=discord.Object(id=GUILD_ID),
)
@app_commands.describe(member="Member to inspect")
async def userinfo(
    interaction: discord.Interaction,
    member: discord.Member,
):
    roles = [
        role.mention
        for role in reversed(member.roles[1:])
    ]

    embed = discord.Embed(
        title=f"👤 User Info • {member.display_name}",
        color=discord.Color.blurple(),
    )
    embed.add_field(
        name="User",
        value=f"{member.mention}\n`{member.id}`",
        inline=False,
    )
    embed.add_field(
        name="Joined",
        value=discord.utils.format_dt(member.joined_at, "F")
        if member.joined_at else "Unknown",
        inline=False,
    )
    embed.add_field(
        name="Created",
        value=discord.utils.format_dt(member.created_at, "F"),
        inline=False,
    )
    embed.add_field(
        name="Roles",
        value=", ".join(roles[:20]) if roles else "No roles",
        inline=False,
    )

    await interaction.response.send_message(
        embed=embed,
        ephemeral=True,
    )


# ============================================================
# ANTI-LINK PROTECTION
# ============================================================

async def handle_anti_link(message: discord.Message):
    if message.author.bot or not message.guild:
        return

    if not message.content or not URL_PATTERN.search(message.content):
        return

    if isinstance(message.author, discord.Member) and is_staff(message.author):
        return

    try:
        await message.delete()
    except discord.HTTPException:
        return

    try:
        await message.channel.send(
            f"🚫 {message.author.mention}, links are not allowed here.",
            delete_after=5,
        )
    except discord.HTTPException:
        pass

    await send_log(
        message.guild,
        "🔗 Link Blocked",
        (
            f"**Member:** {message.author.mention}\n"
            f"**Channel:** {message.channel.mention}\n"
            f"**Action:** Message deleted"
        ),
        discord.Color.red(),
    )


@bot.event
async def on_message(message: discord.Message):
    await handle_anti_link(message)
    await bot.process_commands(message)


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

# ============================================================
# PRESENCE TRACKING
# ============================================================

@bot.event
async def on_presence_update(
    before: discord.Member,
    after: discord.Member,
):
    if after.bot:
        return

    def presence_status(member):
        if member.status == discord.Status.online:
            return "online"
        if member.status == discord.Status.idle:
            return "idle"
        if member.status == discord.Status.dnd:
            return "dnd"
        return "offline"

    old_status = presence_status(before)
    new_status = presence_status(after)

    if old_status != new_status:
        change_activity_status(after.id, new_status)
    else:
        ensure_activity_row(after.id, new_status)


# ============================================================
# ACTIVITY COMMAND HELPERS
# ============================================================

def get_live_activity_totals(user_id):
    row = get_activity_row(user_id)
    if not row:
        ensure_activity_row(user_id, "offline")
        row = get_activity_row(user_id)

    if not row:
        return {
            "online": 0,
            "idle": 0,
            "dnd": 0,
            "sessions": 0,
            "status": "offline",
            "first_tracked": None,
            "last_seen": None,
        }

    (
        _user_id,
        online_seconds,
        idle_seconds,
        dnd_seconds,
        session_count,
        first_tracked,
        last_seen,
        current_status,
        status_started,
    ) = row

    extra = 0
    started = parse_dt(status_started)

    if started and current_status in {"online", "idle", "dnd"}:
        extra = max(0, int((now_utc() - started).total_seconds()))

    if current_status == "online":
        online_seconds += extra
    elif current_status == "idle":
        idle_seconds += extra
    elif current_status == "dnd":
        dnd_seconds += extra

    return {
        "online": online_seconds,
        "idle": idle_seconds,
        "dnd": dnd_seconds,
        "sessions": session_count,
        "status": current_status,
        "first_tracked": first_tracked,
        "last_seen": last_seen,
    }


def get_live_daily_activity(user_id):
    day = now_ist().date().isoformat()

    with db() as con:
        row = con.execute(
            """
            SELECT online_seconds, idle_seconds, dnd_seconds
            FROM daily_activity
            WHERE user_id=? AND day=?
            """,
            (user_id, day),
        ).fetchone()

    online = int(row[0]) if row else 0
    idle = int(row[1]) if row else 0
    dnd = int(row[2]) if row else 0

    activity = get_activity_row(user_id)
    if activity:
        current_status = activity[7]
        started = parse_dt(activity[8])

        if started and current_status in {"online", "idle", "dnd"}:
            extra = max(0, int((now_utc() - started).total_seconds()))

            if current_status == "online":
                online += extra
            elif current_status == "idle":
                idle += extra
            elif current_status == "dnd":
                dnd += extra

    return online, idle, dnd


def activity_embed(member, data, title=None):
    status = data["status"]

    status_text = {
        "online": "🟢 Online",
        "idle": "🌙 Idle",
        "dnd": "⛔ Do Not Disturb",
        "offline": "⚫ Offline",
    }.get(status, status.title())

    embed = discord.Embed(
        title=title or f"📊 Activity • {member.display_name}",
        color=discord.Color.blurple(),
    )

    embed.set_thumbnail(url=member.display_avatar.url)

    embed.add_field(
        name="🟢 Online Time",
        value=f"`{format_seconds(data['online'])}`",
        inline=True,
    )
    embed.add_field(
        name="🌙 Idle Time",
        value=f"`{format_seconds(data['idle'])}`",
        inline=True,
    )
    embed.add_field(
        name="⛔ DND Time",
        value=f"`{format_seconds(data['dnd'])}`",
        inline=True,
    )
    embed.add_field(
        name="📅 Sessions",
        value=f"`{data['sessions']}`",
        inline=True,
    )
    embed.add_field(
        name="📡 Current Status",
        value=status_text,
        inline=True,
    )
    embed.add_field(
        name="🕐 First Tracked",
        value=f"`{data['first_tracked'] or 'N/A'}`",
        inline=False,
    )
    embed.add_field(
        name="👀 Last Seen",
        value=f"`{data['last_seen'] or 'N/A'}`",
        inline=False,
    )

    return embed


# ============================================================
# ACTIVITY COMMANDS
# ============================================================

@bot.tree.command(
    name="clear",
    description="Delete multiple messages from the current channel",
    guild=discord.Object(id=GUILD_ID),
)
@app_commands.describe(amount="Number of messages to delete (1-100)")
async def clear_messages(
    interaction: discord.Interaction,
    amount: app_commands.Range[int, 1, 100],
):
    if not isinstance(interaction.user, discord.Member) or not is_staff(interaction.user):
        await interaction.response.send_message(
            "❌ You do not have permission to use this command.",
            ephemeral=True,
        )
        return

    channel = interaction.channel
    if not isinstance(channel, discord.TextChannel):
        await interaction.response.send_message(
            "❌ This command can only be used in a text channel.",
            ephemeral=True,
        )
        return

    me = interaction.guild.me if interaction.guild else None
    if me is None or not channel.permissions_for(me).manage_messages:
        await interaction.response.send_message(
            "❌ I need the **Manage Messages** permission in this channel.",
            ephemeral=True,
        )
        return

    await interaction.response.defer(ephemeral=True)

    try:
        deleted = await channel.purge(limit=int(amount))
    except discord.Forbidden:
        await interaction.followup.send(
            "❌ I don't have permission to delete messages here.",
            ephemeral=True,
        )
        return
    except discord.HTTPException as error:
        await interaction.followup.send(
            f"❌ Discord rejected the delete request: `{error}`",
            ephemeral=True,
        )
        return

    await interaction.followup.send(
        f"🧹 Deleted **{len(deleted)}** message(s) in {channel.mention}.",
        ephemeral=True,
    )

    await send_log(
        "Messages Deleted",
        f"{interaction.user.mention} deleted **{len(deleted)}** message(s) in {channel.mention}.",
        discord.Color.orange(),
    )


@bot.tree.command(
    name="activity",
    description="View activity statistics for a member",
    guild=discord.Object(id=GUILD_ID),
)
@app_commands.describe(member="Member whose activity you want to view")
async def activity(
    interaction: discord.Interaction,
    member: discord.Member = None,
):
    target = member or interaction.user

    if not isinstance(target, discord.Member):
        await interaction.response.send_message(
            "❌ Member information unavailable.",
            ephemeral=True,
        )
        return

    data = get_live_activity_totals(target.id)

    await interaction.response.send_message(
        embed=activity_embed(target, data),
        ephemeral=True,
    )


@bot.tree.command(
    name="dailyactivity",
    description="View today's activity for a member",
    guild=discord.Object(id=GUILD_ID),
)
@app_commands.describe(member="Member whose daily activity you want to view")
async def dailyactivity(
    interaction: discord.Interaction,
    member: discord.Member = None,
):
    target = member or interaction.user

    if not isinstance(target, discord.Member):
        await interaction.response.send_message(
            "❌ Member information unavailable.",
            ephemeral=True,
        )
        return

    online, idle, dnd = get_live_daily_activity(target.id)
    total = online + idle + dnd

    embed = discord.Embed(
        title=f"📅 Daily Activity • {target.display_name}",
        description=f"**Date:** `{now_ist().date().isoformat()}`",
        color=discord.Color.blurple(),
    )
    embed.set_thumbnail(url=target.display_avatar.url)

    embed.add_field(
        name="🟢 Online",
        value=f"`{format_seconds(online)}`",
        inline=True,
    )
    embed.add_field(
        name="🌙 Idle",
        value=f"`{format_seconds(idle)}`",
        inline=True,
    )
    embed.add_field(
        name="⛔ DND",
        value=f"`{format_seconds(dnd)}`",
        inline=True,
    )
    embed.add_field(
        name="⏱️ Total Tracked",
        value=f"`{format_seconds(total)}`",
        inline=False,
    )

    await interaction.response.send_message(
        embed=embed,
        ephemeral=True,
    )


@bot.tree.command(
    name="activityboard",
    description="Show the activity leaderboard",
    guild=discord.Object(id=GUILD_ID),
)
async def activityboard(interaction: discord.Interaction):
    with db() as con:
        rows = con.execute(
            """
            SELECT user_id
            FROM activity
            ORDER BY
                (online_seconds + idle_seconds + dnd_seconds) DESC
            LIMIT 25
            """
        ).fetchall()

    entries = []

    for index, (user_id,) in enumerate(rows, start=1):
        member = interaction.guild.get_member(user_id)

        if not member:
            continue

        data = get_live_activity_totals(user_id)
        total = data["online"] + data["idle"] + data["dnd"]

        entries.append(
            f"**{index}.** {member.mention} • `{format_seconds(total)}`"
        )

    if not entries:
        description = "No activity has been recorded yet."
    else:
        description = "\n".join(entries)

    embed = discord.Embed(
        title="🏆 Modern City Activity Leaderboard",
        description=description,
        color=discord.Color.gold(),
    )

    await interaction.response.send_message(embed=embed)


@bot.tree.command(
    name="sessions",
    description="View the number of activity sessions",
    guild=discord.Object(id=GUILD_ID),
)
@app_commands.describe(member="Member whose sessions you want to view")
async def sessions(
    interaction: discord.Interaction,
    member: discord.Member = None,
):
    target = member or interaction.user
    data = get_live_activity_totals(target.id)

    await interaction.response.send_message(
        f"📅 **{target.display_name}** has completed "
        f"`{data['sessions']}` tracked session(s).",
        ephemeral=True,
    )


@bot.tree.command(
    name="resetactivity",
    description="Reset a member's activity statistics",
    guild=discord.Object(id=GUILD_ID),
)
@app_commands.describe(member="Member whose activity should be reset")
async def resetactivity(
    interaction: discord.Interaction,
    member: discord.Member,
):
    if not isinstance(interaction.user, discord.Member) or not is_staff(interaction.user):
        await interaction.response.send_message(
            "❌ Master/Staff only.",
            ephemeral=True,
        )
        return

    stamp = iso_now()

    with db() as con:
        con.execute(
            "DELETE FROM activity WHERE user_id=?",
            (member.id,),
        )
        con.execute(
            "DELETE FROM daily_activity WHERE user_id=?",
            (member.id,),
        )

    ensure_activity_row(member.id, "offline")

    await send_log(
        interaction.guild,
        "📊 Activity Reset",
        (
            f"**Member:** {member.mention}\n"
            f"**Reset by:** {interaction.user.mention}\n"
            f"**Time:** {stamp}"
        ),
        discord.Color.orange(),
    )

    await interaction.response.send_message(
        f"✅ Activity statistics for {member.mention} have been reset.",
        ephemeral=True,
    )

async def on_ready():

    print(f"Logged in as {bot.user} (ID: {bot.user.id})")

    await ensure_org_panel()


bot.run(TOKEN)
