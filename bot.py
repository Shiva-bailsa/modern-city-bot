import os
import re
import sqlite3
import time
import asyncio
from datetime import datetime, timezone, timedelta

import discord
from discord import app_commands
from discord.ext import commands, tasks


# ============================================================
# MODERN CITY RP BOT
# PART 1/3
# ============================================================

TOKEN = os.getenv("BOT_TOKEN")

# ---------------- SERVER ----------------

GUILD_ID = 1552902541061394432

# ---------------- ROLES ----------------

CITIZEN_ROLE_ID = 1552903102204747856
MASTER_ROLE_ID = 1552903005500866650

# ---------------- CHANNELS ----------------

ORG_PANEL_CHANNEL_ID = 1552903355339243520
APPLICATION_CATEGORY_ID = 1553784383989743616
LOG_CHANNEL_ID = 1553365117750485032

# ---------------- DATABASE ----------------

DB_FILE = "modern_city.db"


# ============================================================
# ORGANIZATIONS
# ============================================================

ORGANIZATIONS = {
    "Government": "🏛️ Government",
    "Military Unit": "🪖 Military Unit",
    "ARZAMAS Hospital": "🏥 ARZAMAS Hospital",
    "YUZHNEY Hospital": "🏥 YUZHNEY Hospital",
    "Yuzhny Police Department": "🚓 Yuzhny Police Department",
    "FBI": "🕵️ FBI",
    "Arzamas Police Department": "🚓 Arzamas Police Department",
    "News Network": "📰 News Network",

    "Caucasian OCG": "🏴 Caucasian OCG",
    "Orekhov OCG": "🏴 Orekhov OCG",
    "Kurgan OCG": "🏴 Kurgan OCG",
}

ORG_ROLE_NAMES = set(ORGANIZATIONS.values())


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
# DISCORD INTENTS
# ============================================================

intents = discord.Intents.default()

intents.guilds = True
intents.members = True
intents.presences = True
intents.message_content = True
intents.messages = True


bot = commands.Bot(
    command_prefix="!",
    intents=intents
)


# ============================================================
# DATABASE
# ============================================================

db = sqlite3.connect(
    DB_FILE,
    check_same_thread=False
)

db.row_factory = sqlite3.Row

db_lock = __import__("threading").Lock()


def db_execute(sql, params=(), fetch=False):
    with db_lock:

        cursor = db.cursor()

        cursor.execute(
            sql,
            params
        )

        rows = None

        if fetch:
            rows = cursor.fetchall()

        db.commit()

        return rows


def init_database():

    # --------------------------------------------------------
    # ORGANIZATION APPLICATIONS
    # --------------------------------------------------------

    db_execute("""
        CREATE TABLE IF NOT EXISTS applications (

            channel_id INTEGER PRIMARY KEY,

            user_id INTEGER NOT NULL,

            organization TEXT NOT NULL,

            created_at INTEGER NOT NULL,

            status TEXT NOT NULL DEFAULT 'pending',

            proof_received INTEGER NOT NULL DEFAULT 0,

            reviewer_id INTEGER,

            reason TEXT,

            additional_info TEXT
        )
    """)


    # --------------------------------------------------------
    # ACTIVITY
    # --------------------------------------------------------

    db_execute("""
        CREATE TABLE IF NOT EXISTS activity (

            user_id INTEGER PRIMARY KEY,

            online_seconds INTEGER NOT NULL DEFAULT 0,

            idle_seconds INTEGER NOT NULL DEFAULT 0,

            dnd_seconds INTEGER NOT NULL DEFAULT 0,

            session_count INTEGER NOT NULL DEFAULT 0,

            first_tracked INTEGER NOT NULL,

            last_seen INTEGER NOT NULL,

            current_status TEXT NOT NULL DEFAULT 'offline',

            status_started INTEGER NOT NULL
        )
    """)


    # --------------------------------------------------------
    # DAILY ACTIVITY
    # --------------------------------------------------------

    db_execute("""
        CREATE TABLE IF NOT EXISTS activity_daily (

            user_id INTEGER NOT NULL,

            day TEXT NOT NULL,

            online_seconds INTEGER NOT NULL DEFAULT 0,

            idle_seconds INTEGER NOT NULL DEFAULT 0,

            dnd_seconds INTEGER NOT NULL DEFAULT 0,

            PRIMARY KEY(user_id, day)
        )
    """)


    # --------------------------------------------------------
    # SETTINGS
    # --------------------------------------------------------

    db_execute("""
        CREATE TABLE IF NOT EXISTS settings (

            key TEXT PRIMARY KEY,

            value TEXT
        )
    """)


# ============================================================
# BASIC HELPERS
# ============================================================

def now_ts():

    return int(
        time.time()
    )


def utc_now():

    return datetime.now(
        timezone.utc
    )


def format_duration(seconds):

    seconds = max(
        0,
        int(seconds)
    )

    days, seconds = divmod(
        seconds,
        86400
    )

    hours, seconds = divmod(
        seconds,
        3600
    )

    minutes, seconds = divmod(
        seconds,
        60
    )

    parts = []

    if days:
        parts.append(
            f"{days}d"
        )

    if hours:
        parts.append(
            f"{hours}h"
        )

    if minutes:
        parts.append(
            f"{minutes}m"
        )

    if not parts:

        parts.append(
            f"{seconds}s"
        )

    return " ".join(parts)


def timestamp_text(timestamp):

    if not timestamp:

        return "Unknown"

    return datetime.fromtimestamp(
        timestamp,
        timezone.utc
    ).strftime(
        "%d %b %Y, %H:%M UTC"
    )


def get_guild():

    return bot.get_guild(
        GUILD_ID
    )


def get_role(guild, role_id):

    if not guild:

        return None

    return guild.get_role(
        role_id
    )


def find_role(guild, role_name):

    if not guild:

        return None

    return discord.utils.get(
        guild.roles,
        name=role_name
    )


def get_master_role(guild):

    return get_role(
        guild,
        MASTER_ROLE_ID
    )


def is_master(member):

    if member.guild_permissions.administrator:

        return True

    return any(
        role.id == MASTER_ROLE_ID
        for role in member.roles
    )


def is_staff(member):

    if member.guild_permissions.administrator:

        return True

    if any(
        role.id == MASTER_ROLE_ID
        for role in member.roles
    ):

        return True

    return any(
        role.name in STAFF_ROLE_NAMES
        for role in member.roles
    )


def get_organization_role(
    guild,
    organization
):

    role_name = ORGANIZATIONS.get(
        organization
    )

    if not role_name:

        return None

    return find_role(
        guild,
        role_name
    )


def get_member_org_roles(member):

    return [
        role
        for role in member.roles
        if role.name in ORG_ROLE_NAMES
    ]


def clean_channel_name(name):

    name = name.lower()

    name = re.sub(
        r"[^a-z0-9-]+",
        "-",
        name
    )

    name = re.sub(
        r"-+",
        "-",
        name
    )

    name = name.strip("-")

    return (
        name[:70]
        or "application"
    )


# ============================================================
# LOG SYSTEM
# ============================================================

async def send_log(
    title,
    description,
    color=discord.Color.blurple(),
    fields=None
):

    channel = bot.get_channel(
        LOG_CHANNEL_ID
    )

    if not channel:

        return

    embed = discord.Embed(

        title=title,

        description=description,

        color=color,

        timestamp=utc_now()
    )

    if fields:

        for name, value, inline in fields:

            embed.add_field(
                name=name,
                value=value,
                inline=inline
            )

    try:

        await channel.send(
            embed=embed
        )

    except discord.HTTPException:

        pass


async def safe_ephemeral(
    interaction,
    content=None,
    embed=None
):

    try:

        if interaction.response.is_done():

            await interaction.followup.send(
                content=content,
                embed=embed,
                ephemeral=True
            )

        else:

            await interaction.response.send_message(
                content=content,
                embed=embed,
                ephemeral=True
            )

    except discord.HTTPException:

        pass


# ============================================================
# ACTIVITY STATUS
# ============================================================

def normalize_status(status):

    if status == discord.Status.online:

        return "online"

    if status == discord.Status.idle:

        return "idle"

    if status == discord.Status.dnd:

        return "dnd"

    return "offline"


def ensure_activity_member(member):

    timestamp = now_ts()

    status = normalize_status(
        member.status
    )

    existing = db_execute(
        """
        SELECT user_id
        FROM activity
        WHERE user_id=?
        """,
        (member.id,),
        fetch=True
    )

    if existing:

        return

    db_execute(
        """
        INSERT INTO activity
        (
            user_id,
            online_seconds,
            idle_seconds,
            dnd_seconds,
            session_count,
            first_tracked,
            last_seen,
            current_status,
            status_started
        )

        VALUES
        (
            ?,
            0,
            0,
            0,
            0,
            ?,
            ?,
            ?,
            ?
        )
        """,
        (
            member.id,
            timestamp,
            timestamp,
            status,
            timestamp
        )
    )


def add_activity_seconds(
    user_id,
    status,
    seconds
):

    if seconds <= 0:

        return

    if status not in {
        "online",
        "idle",
        "dnd"
    }:

        return

    column = f"{status}_seconds"

    db_execute(
        f"""
        UPDATE activity

        SET
            {column} = {column} + ?,
            last_seen = ?

        WHERE user_id=?
        """,
        (
            seconds,
            now_ts(),
            user_id
        )
    )

    today = datetime.now(
        timezone.utc
    ).strftime(
        "%Y-%m-%d"
    )

    db_execute(
        f"""
        INSERT INTO activity_daily
        (
            user_id,
            day,
            {column}
        )

        VALUES
        (
            ?,
            ?,
            ?
        )

        ON CONFLICT(user_id, day)

        DO UPDATE SET
            {column} =
            {column} + excluded.{column}
        """,
        (
            user_id,
            today,
            seconds
        )
    )


async def process_presence(
    member,
    before_status,
    after_status
):

    old_status = normalize_status(
        before_status
    )

    new_status = normalize_status(
        after_status
    )

    if old_status == new_status:

        return

    ensure_activity_member(
        member
    )

    row = db_execute(
        """
        SELECT
            current_status,
            status_started

        FROM activity

        WHERE user_id=?
        """,
        (member.id,),
        fetch=True
    )

    if row:

        current_status = row[0][
            "current_status"
        ]

        started = row[0][
            "status_started"
        ]

        elapsed = max(
            0,
            now_ts() - started
        )

        add_activity_seconds(
            member.id,
            current_status,
            elapsed
        )

    if (
        old_status == "offline"
        and new_status
        in {
            "online",
            "idle",
            "dnd"
        }
    ):

        db_execute(
            """
            UPDATE activity

            SET session_count =
                session_count + 1

            WHERE user_id=?
            """,
            (member.id,)
        )

    db_execute(
        """
        UPDATE activity

        SET
            current_status=?,
            status_started=?,
            last_seen=?

        WHERE user_id=?
        """,
        (
            new_status,
            now_ts(),
            now_ts(),
            member.id
        )
    )


async def flush_activity():

    guild = get_guild()

    if not guild:

        return

    current_time = now_ts()

    for member in guild.members:

        row = db_execute(
            """
            SELECT
                current_status,
                status_started

            FROM activity

            WHERE user_id=?
            """,
            (member.id,),
            fetch=True
        )

        if not row:

            continue

        status = row[0][
            "current_status"
        ]

        started = row[0][
            "status_started"
        ]

        elapsed = max(
            0,
            current_time - started
        )

        if status in {
            "online",
            "idle",
            "dnd"
        }:

            add_activity_seconds(
                member.id,
                status,
                elapsed
            )

        db_execute(
            """
            UPDATE activity

            SET status_started=?

            WHERE user_id=?
            """,
            (
                current_time,
                member.id
            )
        )


@tasks.loop(minutes=1)
async def activity_flush():

    await flush_activity()


# ============================================================
# ACTIVITY DATA HELPER
# ============================================================

def get_activity_data(user_id):

    rows = db_execute(
        """
        SELECT

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
        fetch=True
    )

    if not rows:

        return None

    data = dict(
        rows[0]
    )

    current_status = data[
        "current_status"
    ]

    if current_status in {
        "online",
        "idle",
        "dnd"
    }:

        current_seconds = max(
            0,
            now_ts() -
            data["status_started"]
        )

        data[
            f"{current_status}_seconds"
        ] += current_seconds

    data["total_seconds"] = (
        data["online_seconds"]
        +
        data["idle_seconds"]
        +
        data["dnd_seconds"]
    )

    return data


# ============================================================
# INITIAL DATABASE
# ============================================================

init_database()


# ============================================================
# END OF PART 1
# ============================================================
# ============================================================
# PART 2
# ORGANIZATION APPLICATION + VERIFICATION SYSTEM
# ============================================================


# ============================================================
# ORGANIZATION PANEL
# ============================================================

class OrganizationPanelView(discord.ui.View):

    def __init__(self):

        super().__init__(
            timeout=None
        )


    async def create_application(
        self,
        interaction,
        organization
    ):

        guild = interaction.guild

        if not guild:

            return


        member = interaction.user


        # ----------------------------------------------------
        # CHECK EXISTING SAME ROLE
        # ----------------------------------------------------

        org_role = get_organization_role(
            guild,
            organization
        )

        if org_role and org_role in member.roles:

            await safe_ephemeral(
                interaction,
                f"❌ You already have the **{org_role.name}** role."
            )

            return


        # ----------------------------------------------------
        # CHECK PENDING APPLICATION
        # ----------------------------------------------------

        pending = db_execute(
            """
            SELECT channel_id
            FROM applications
            WHERE user_id=?
            AND status='pending'
            """,
            (member.id,),
            fetch=True
        )

        if pending:

            channel_id = pending[0][
                "channel_id"
            ]

            existing_channel = guild.get_channel(
                channel_id
            )

            if existing_channel:

                await safe_ephemeral(
                    interaction,
                    f"⚠️ You already have an active application: {existing_channel.mention}"
                )

                return

            else:

                db_execute(
                    """
                    UPDATE applications
                    SET status='closed'
                    WHERE channel_id=?
                    """,
                    (channel_id,)
                )


        # ----------------------------------------------------
        # CATEGORY
        # ----------------------------------------------------

        category = guild.get_channel(
            APPLICATION_CATEGORY_ID
        )

        if not isinstance(
            category,
            discord.CategoryChannel
        ):

            await safe_ephemeral(
                interaction,
                "❌ Application category was not found."
            )

            return


        # ----------------------------------------------------
        # MASTER ROLE
        # ----------------------------------------------------

        master_role = get_master_role(
            guild
        )


        # ----------------------------------------------------
        # CHANNEL NAME
        # ----------------------------------------------------

        channel_name = clean_channel_name(
            f"apply-{organization}-{member.display_name}"
        )


        # ----------------------------------------------------
        # PERMISSIONS
        # ----------------------------------------------------

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
                    embed_links=True
                )
        }


        if master_role:

            overwrites[
                master_role
            ] = discord.PermissionOverwrite(

                view_channel=True,
                send_messages=True,
                read_message_history=True,
                attach_files=True,
                embed_links=True
            )


        # ----------------------------------------------------
        # CREATE APPLICATION CHANNEL
        # ----------------------------------------------------

        try:

            channel = await guild.create_text_channel(

                name=channel_name,

                category=category,

                overwrites=overwrites,

                reason=(
                    f"Organization application: "
                    f"{organization} by {member}"
                )
            )

        except discord.Forbidden:

            await safe_ephemeral(
                interaction,
                "❌ Bot does not have permission to create application channels."
            )

            return

        except discord.HTTPException:

            await safe_ephemeral(
                interaction,
                "❌ Failed to create the application channel."
            )

            return


        # ----------------------------------------------------
        # SAVE APPLICATION
        # ----------------------------------------------------

        db_execute(
            """
            INSERT INTO applications
            (
                channel_id,
                user_id,
                organization,
                created_at,
                status,
                proof_received
            )

            VALUES
            (
                ?,
                ?,
                ?,
                ?,
                'pending',
                0
            )
            """,
            (
                channel.id,
                member.id,
                organization,
                now_ts()
            )
        )


        # ----------------------------------------------------
        # EMBED
        # ----------------------------------------------------

        embed = discord.Embed(

            title="📋 Organization Application",

            description=(
                f"Welcome {member.mention}.\n\n"
                f"Your application for "
                f"**{ORGANIZATIONS[organization]}** "
                f"has been created.\n\n"
                "### 📌 Application Requirements\n"
                "• Explain why you want to join.\n"
                "• Provide relevant information about yourself.\n"
                "• **Proof is mandatory.**\n"
                "• Upload your proof directly in this channel.\n\n"
                "### 🔐 Verification\n"
                "A Master/Admin will review your application.\n"
                "Do not delete your proof after sending it.\n\n"
                "Please wait for the verification team."
            ),

            color=discord.Color.blurple(),

            timestamp=utc_now()
        )


        embed.add_field(

            name="👤 Applicant",

            value=member.mention,

            inline=True
        )


        embed.add_field(

            name="🏢 Organization",

            value=ORGANIZATIONS[organization],

            inline=True
        )


        embed.add_field(

            name="📎 Proof",

            value="❌ Not received",

            inline=True
        )


        embed.set_footer(
            text="Modern City RP • Organization Verification"
        )


        review_view = ApplicationReviewView()


        mention_content = member.mention

        if master_role:

            mention_content += (
                f" {master_role.mention}"
            )


        try:

            await channel.send(

                content=mention_content,

                embed=embed,

                view=review_view,

                allowed_mentions=discord.AllowedMentions(
                    users=True,
                    roles=True
                )
            )

        except discord.HTTPException:

            pass


        # ----------------------------------------------------
        # USER RESPONSE
        # ----------------------------------------------------

        await safe_ephemeral(

            interaction,

            f"✅ Your application has been created: {channel.mention}"
        )


        # ----------------------------------------------------
        # LOG
        # ----------------------------------------------------

        await send_log(

            "📋 New Organization Application",

            f"{member.mention} created an application.",

            discord.Color.blurple(),

            fields=[

                (
                    "Applicant",
                    f"{member.mention}\n`{member.id}`",
                    False
                ),

                (
                    "Organization",
                    ORGANIZATIONS[organization],
                    True
                ),

                (
                    "Application",
                    channel.mention,
                    True
                )
            ]
        )


    # ========================================================
    # BUTTONS
    # ========================================================

    @discord.ui.button(
        label="Government",
        emoji="🏛️",
        style=discord.ButtonStyle.primary,
        custom_id="org_government"
    )
    async def government(
        self,
        interaction,
        button
    ):

        await self.create_application(
            interaction,
            "Government"
        )


    @discord.ui.button(
        label="Military Unit",
        emoji="🪖",
        style=discord.ButtonStyle.primary,
        custom_id="org_military"
    )
    async def military(
        self,
        interaction,
        button
    ):

        await self.create_application(
            interaction,
            "Military Unit"
        )


    @discord.ui.button(
        label="ARZAMAS Hospital",
        emoji="🏥",
        style=discord.ButtonStyle.success,
        custom_id="org_arzamas_hospital"
    )
    async def arzamas_hospital(
        self,
        interaction,
        button
    ):

        await self.create_application(
            interaction,
            "ARZAMAS Hospital"
        )


    @discord.ui.button(
        label="YUZHNEY Hospital",
        emoji="🏥",
        style=discord.ButtonStyle.success,
        custom_id="org_yuzhney_hospital"
    )
    async def yuzhney_hospital(
        self,
        interaction,
        button
    ):

        await self.create_application(
            interaction,
            "YUZHNEY Hospital"
        )


    @discord.ui.button(
        label="Yuzhny Police",
        emoji="🚓",
        style=discord.ButtonStyle.danger,
        custom_id="org_yuzhny_police"
    )
    async def yuzhny_police(
        self,
        interaction,
        button
    ):

        await self.create_application(
            interaction,
            "Yuzhny Police Department"
        )


    @discord.ui.button(
        label="FBI",
        emoji="🕵️",
        style=discord.ButtonStyle.secondary,
        custom_id="org_fbi"
    )
    async def fbi(
        self,
        interaction,
        button
    ):

        await self.create_application(
            interaction,
            "FBI"
        )


    @discord.ui.button(
        label="Arzamas Police",
        emoji="🚓",
        style=discord.ButtonStyle.danger,
        custom_id="org_arzamas_police"
    )
    async def arzamas_police(
        self,
        interaction,
        button
    ):

        await self.create_application(
            interaction,
            "Arzamas Police Department"
        )


    @discord.ui.button(
        label="News Network",
        emoji="📰",
        style=discord.ButtonStyle.secondary,
        custom_id="org_news"
    )
    async def news(
        self,
        interaction,
        button
    ):

        await self.create_application(
            interaction,
            "News Network"
        )


    @discord.ui.button(
        label="Caucasian OCG",
        emoji="🏴",
        style=discord.ButtonStyle.danger,
        custom_id="org_caucasian"
    )
    async def caucasian(
        self,
        interaction,
        button
    ):

        await self.create_application(
            interaction,
            "Caucasian OCG"
        )


    @discord.ui.button(
        label="Orekhov OCG",
        emoji="🏴",
        style=discord.ButtonStyle.danger,
        custom_id="org_orekhov"
    )
    async def orekhov(
        self,
        interaction,
        button
    ):

        await self.create_application(
            interaction,
            "Orekhov OCG"
        )


    @discord.ui.button(
        label="Kurgan OCG",
        emoji="🏴",
        style=discord.ButtonStyle.danger,
        custom_id="org_kurgan"
    )
    async def kurgan(
        self,
        interaction,
        button
    ):

        await self.create_application(
            interaction,
            "Kurgan OCG"
        )


# ============================================================
# APPLICATION REVIEW VIEW
# ============================================================

class ApplicationReviewView(
    discord.ui.View
):

    def __init__(self):

        super().__init__(
            timeout=None
        )


    # ========================================================
    # GET APPLICATION
    # ========================================================

    def get_application(
        self,
        channel_id
    ):

        rows = db_execute(

            """
            SELECT *

            FROM applications

            WHERE channel_id=?
            """,

            (channel_id,),

            fetch=True
        )

        if not rows:

            return None

        return rows[0]


    # ========================================================
    # APPROVE
    # ========================================================

    @discord.ui.button(
        label="Approve",
        emoji="✅",
        style=discord.ButtonStyle.success,
        custom_id="application_approve"
    )
    async def approve(
        self,
        interaction,
        button
    ):

        if not is_master(
            interaction.user
        ):

            await safe_ephemeral(
                interaction,
                "❌ Only Master/Admin can approve applications."
            )

            return


        application = self.get_application(
            interaction.channel.id
        )

        if not application:

            await safe_ephemeral(
                interaction,
                "❌ Application data was not found."
            )

            return


        if application["status"] != "pending":

            await safe_ephemeral(
                interaction,
                "⚠️ This application is already closed."
            )

            return


        guild = interaction.guild

        applicant = guild.get_member(
            application["user_id"]
        )

        if not applicant:

            await safe_ephemeral(
                interaction,
                "❌ Applicant is no longer in the server."
            )

            return


        organization = application[
            "organization"
        ]

        new_role = get_organization_role(
            guild,
            organization
        )

        if not new_role:

            await safe_ephemeral(

                interaction,

                f"❌ The role **{ORGANIZATIONS[organization]}** "
                "was not found in the server.\n\n"
                "Create the role with the exact name first."
            )

            return


        # ----------------------------------------------------
        # BOT ROLE HIERARCHY CHECK
        # ----------------------------------------------------

        if new_role >= guild.me.top_role:

            await safe_ephemeral(

                interaction,

                "❌ I cannot manage this role because "
                "my bot role is not above it."
            )

            return


        # ----------------------------------------------------
        # REMOVE OLD ORGANIZATION ROLES
        # ----------------------------------------------------

        old_roles = get_member_org_roles(
            applicant
        )

        removed_names = []

        for old_role in old_roles:

            if old_role == new_role:

                continue

            try:

                await applicant.remove_roles(
                    old_role,
                    reason=(
                        "Organization switch "
                        "approved by Master"
                    )
                )

                removed_names.append(
                    old_role.name
                )

            except discord.Forbidden:

                await safe_ephemeral(

                    interaction,

                    f"❌ I cannot remove `{old_role.name}`. "
                    "Check role hierarchy."
                )

                return


        # ----------------------------------------------------
        # ADD NEW ROLE
        # ----------------------------------------------------

        try:

            await applicant.add_roles(

                new_role,

                reason=(
                    f"Organization application approved "
                    f"by {interaction.user}"
                )
            )

        except discord.Forbidden:

            await safe_ephemeral(

                interaction,

                "❌ I cannot add the organization role. "
                "Check role hierarchy."
            )

            return


        # ----------------------------------------------------
        # ENSURE CITIZEN ROLE
        # ----------------------------------------------------

        citizen_role = get_role(
            guild,
            CITIZEN_ROLE_ID
        )

        if citizen_role:

            try:

                if citizen_role not in applicant.roles:

                    await applicant.add_roles(
                        citizen_role,
                        reason="Citizen role retention"
                    )

            except discord.Forbidden:

                pass


        # ----------------------------------------------------
        # DATABASE
        # ----------------------------------------------------

        db_execute(

            """
            UPDATE applications

            SET
                status='approved',
                reviewer_id=?

            WHERE channel_id=?
            """,

            (
                interaction.user.id,
                interaction.channel.id
            )
        )


        # ----------------------------------------------------
        # SUCCESS MESSAGE
        # ----------------------------------------------------

        await safe_ephemeral(

            interaction,

            f"✅ Application approved.\n"
            f"{applicant.mention} received "
            f"**{new_role.name}**."
        )


        # --------------------------------------------------------
    # LOG
    # --------------------------------------------------------

    await send_log(

        "📎 Application Proof Received",

        f"{message.author.mention} uploaded proof.",

        discord.Color.blue(),

        fields=[

            (
                "Organization",
                ORGANIZATIONS.get(
                    application["organization"],
                    application["organization"]
                ),
                True
            ),

            (
                "Application",
                message.channel.mention,
                True
            ),

            (
                "Files",
                file_text[:1000],
                False
            )
        ]
    )


# ============================================================
# ORGANIZATION PANEL EMBED
# ============================================================

def organization_panel_embed():

    embed = discord.Embed(

        title="🏢 MODERN CITY RP",
        description=(
            "**Organization Recruitment Center**\n\n"
            "Choose the organization you want to apply for.\n\n"
            "📋 **Application Process**\n"
            "1️⃣ Select an organization\n"
            "2️⃣ Private application channel opens\n"
            "3️⃣ Submit your information\n"
            "4️⃣ Upload mandatory proof\n"
            "5️⃣ Master/Admin reviews your application\n"
            "6️⃣ Approved applications receive the organization role\n\n"
            "⚠️ **Important:**\n"
            "You can have only **one organization role at a time**.\n"
            "When a new organization is approved, your previous "
            "organization role will be removed automatically."
        ),

        color=discord.Color.blurple()
    )


    embed.add_field(

        name="🏛️ Government",
        value="Government Administration",
        inline=True
    )

    embed.add_field(

        name="🪖 Military Unit",
        value="Military Organization",
        inline=True
    )

    embed.add_field(

        name="🏥 Hospitals",
        value="ARZAMAS • YUZHNEY",
        inline=True
    )

    embed.add_field(

        name="🚓 Police",
        value="Yuzhny PD • Arzamas PD",
        inline=True
    )

    embed.add_field(

        name="🕵️ FBI",
        value="Federal Investigation",
        inline=True
    )

    embed.add_field(

        name="📰 News Network",
        value="Media Organization",
        inline=True
    )

    embed.add_field(

        name="🏴 OCG",
        value="Caucasian • Orekhov • Kurgan",
        inline=False
    )


    embed.set_footer(

        text=(
            "Modern City RP • Organization Verification System"
        )
    )


    return embed


# ============================================================
# SEND / REFRESH ORGANIZATION PANEL
# ============================================================

async def send_organization_panel():

    channel = bot.get_channel(
        ORG_PANEL_CHANNEL_ID
    )

    if not channel:

        return


    embed = organization_panel_embed()


    try:

        await channel.send(

            embed=embed,

            view=OrganizationPanelView()
        )

    except discord.HTTPException:

        pass


# ============================================================
# APPLICATION VIEW RESTORE
# ============================================================

async def restore_pending_application_views():

    rows = db_execute(

        """
        SELECT channel_id

        FROM applications

        WHERE status='pending'
        """,

        fetch=True
    )


    for row in rows:

        channel_id = row[
            "channel_id"
        ]

        channel = bot.get_channel(
            channel_id
        )

        if not channel:

            continue


        try:

            bot.add_view(
                ApplicationReviewView(),
                message_id=None
            )

        except Exception:

            pass


# ============================================================
# END OF PART 2
# ============================================================
# ============================================================
# PART 3
# MODERATION + ANTI-LINK + ACTIVITY COMMANDS + STARTUP
# ============================================================


# ============================================================
# ANTI-LINK SYSTEM
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


async def apply_link_timeout(member):

    try:

        until = discord.utils.utcnow() + timedelta(
            minutes=10
        )

        await member.timeout(
            until,
            reason="Automatic anti-link protection"
        )

        return True

    except (
        discord.Forbidden,
        discord.HTTPException
    ):

        return False


async def handle_anti_link(message):

    if not message.guild:

        return False

    if message.author.bot:

        return False

    member = message.author

    if not isinstance(
        member,
        discord.Member
    ):

        return False

    # Master/Admin bypass
    if is_master(member):

        return False

    content = message.content or ""

    if not content.strip():

        return False

    if not URL_PATTERN.search(content):

        return False

    # Delete immediately
    try:

        await message.delete(
            reason="Automatic anti-link protection"
        )

    except discord.HTTPException:

        pass

    # Timeout for 10 minutes
    timeout_success = await apply_link_timeout(
        member
    )

    # Warning message
    try:

        if timeout_success:

            text = (
                f"🚫 {member.mention} **link detected and removed.**\n"
                "You have been timed out for **10 minutes**."
            )

        else:

            text = (
                f"🚫 {member.mention} **link detected and removed.**\n"
                "I could not apply the 10-minute timeout. "
                "Check the bot's role hierarchy."
            )

        warning = await message.channel.send(
            text,
            allowed_mentions=discord.AllowedMentions(
                users=True
            )
        )

        await asyncio.sleep(5)

        try:

            await warning.delete()

        except discord.HTTPException:

            pass

    except discord.HTTPException:

        pass

    # Log
    await send_log(

        "🛡️ Anti-Link Protection",

        f"{member.mention} sent a blocked link.",

        discord.Color.red(),

        fields=[

            (
                "User",
                f"{member.mention}\n`{member.id}`",
                True
            ),

            (
                "Channel",
                message.channel.mention,
                True
            ),

            (
                "Timeout",
                "10 minutes"
                if timeout_success
                else "Failed",
                True
            ),

            (
                "Action",
                "Message deleted",
                True
            )
        ]
    )

    return True


# ============================================================
# MESSAGE EVENT
# ============================================================

@bot.event
async def on_message(message):

    if message.author.bot:

        return

    # Anti-link first
    blocked = await handle_anti_link(
        message
    )

    if blocked:

        return

    # Application proof
    await handle_application_proof(
        message
    )

    # IMPORTANT:
    # Keep slash/prefix command processing alive.
    await bot.process_commands(
        message
    )


# ============================================================
# PRESENCE TRACKING
# ============================================================

@bot.event
async def on_presence_update(
    before,
    after
):

    try:

        await process_presence(
            after,
            before.status,
            after.status
        )

    except Exception:

        pass


# ============================================================
# PING
# ============================================================

@bot.tree.command(
    name="ping",
    description="Check bot latency"
)
async def ping(
    interaction: discord.Interaction
):

    latency = round(
        bot.latency * 1000
    )

    await interaction.response.send_message(

        f"🏓 **Pong!**\n"
        f"Latency: `{latency}ms`"
    )


# ============================================================
# BOT INFO
# ============================================================

@bot.tree.command(
    name="botinfo",
    description="Show bot information"
)
async def botinfo(
    interaction: discord.Interaction
):

    embed = discord.Embed(

        title="🤖 Modern City RP Bot",

        description=(
            "Modern City RP management and verification bot."
        ),

        color=discord.Color.blurple()
    )

    embed.add_field(
        name="⚙️ Features",
        value=(
            "• Organization verification\n"
            "• Anti-link protection\n"
            "• Moderation\n"
            "• Member activity\n"
            "• Staff tools\n"
            "• Server utilities"
        ),
        inline=False
    )

    embed.add_field(
        name="📦 Library",
        value="discord.py",
        inline=True
    )

    embed.add_field(
        name="🗄️ Database",
        value="SQLite",
        inline=True
    )

    embed.set_footer(
        text="Modern City RP"
    )

    await interaction.response.send_message(
        embed=embed
    )


# ============================================================
# SERVER INFO
# ============================================================

@bot.tree.command(
    name="serverinfo",
    description="Show server information"
)
async def serverinfo(
    interaction: discord.Interaction
):

    guild = interaction.guild

    if not guild:

        return

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
        name="🆔 Server ID",
        value=f"`{guild.id}`",
        inline=False
    )

    await interaction.response.send_message(
        embed=embed
    )


# ============================================================
# STAFF CHECK
# ============================================================

def staff_only():

    async def predicate(
        interaction: discord.Interaction
    ):

        if not interaction.guild:

            return False

        return is_staff(
            interaction.user
        )

    return app_commands.check(
        predicate
    )


# ============================================================
# ANNOUNCE
# ============================================================

@bot.tree.command(
    name="announce",
    description="Send a staff announcement"
)
@staff_only()
@app_commands.describe(
    channel="Channel where the announcement will be sent",
    title="Announcement title",
    message="Announcement message"
)
async def announce(
    interaction: discord.Interaction,
    channel: discord.TextChannel,
    title: str,
    message: str
):

    citizen_role = get_role(
        interaction.guild,
        CITIZEN_ROLE_ID
    )

    if not citizen_role:

        await interaction.response.send_message(
            "❌ Citizen role was not found.",
            ephemeral=True
        )

        return

    embed = discord.Embed(

        title=title,

        description=message,

        color=discord.Color.blurple(),

        timestamp=utc_now()
    )

    embed.set_footer(
        text=f"Announcement by {interaction.user}"
    )

    try:

        await channel.send(

            content=citizen_role.mention,

            embed=embed,

            allowed_mentions=discord.AllowedMentions(
                roles=True
            )
        )

    except discord.Forbidden:

        await interaction.response.send_message(
            "❌ I cannot send messages in that channel.",
            ephemeral=True
        )

        return

    except discord.HTTPException:

        await interaction.response.send_message(
            "❌ Failed to send announcement.",
            ephemeral=True
        )

        return

    await interaction.response.send_message(

        f"✅ Announcement sent to {channel.mention}.",

        ephemeral=True
    )

    await send_log(

        "📢 Announcement Sent",

        f"{interaction.user.mention} sent an announcement.",

        discord.Color.blurple(),

        fields=[

            (
                "Channel",
                channel.mention,
                True
            ),

            (
                "Title",
                title[:100],
                True
            )
        ]
    )


# ============================================================
# WARNINGS DATABASE
# ============================================================

db_execute("""
    CREATE TABLE IF NOT EXISTS warnings (

        id INTEGER PRIMARY KEY AUTOINCREMENT,

        guild_id INTEGER NOT NULL,

        user_id INTEGER NOT NULL,

        moderator_id INTEGER NOT NULL,

        reason TEXT NOT NULL,

        created_at INTEGER NOT NULL
    )
""")


# ============================================================
# WARN
# ============================================================

@bot.tree.command(
    name="warn",
    description="Warn a member"
)
@staff_only()
@app_commands.describe(
    member="Member to warn",
    reason="Reason for warning"
)
async def warn(
    interaction: discord.Interaction,
    member: discord.Member,
    reason: str
):

    if member.bot:

        await interaction.response.send_message(
            "❌ Bots cannot be warned.",
            ephemeral=True
        )

        return

    db_execute(

        """
        INSERT INTO warnings
        (
            guild_id,
            user_id,
            moderator_id,
            reason,
            created_at
        )

        VALUES
        (
            ?,
            ?,
            ?,
            ?,
            ?
        )
        """,

        (
            interaction.guild.id,
            member.id,
            interaction.user.id,
            reason,
            now_ts()
        )
    )

    rows = db_execute(

        """
        SELECT COUNT(*) AS total

        FROM warnings

        WHERE guild_id=?
        AND user_id=?
        """,

        (
            interaction.guild.id,
            member.id
        ),

        fetch=True
    )

    total = rows[0]["total"]

    await interaction.response.send_message(

        f"⚠️ {member.mention} has been warned.\n"
        f"Reason: **{reason}**\n"
        f"Total warnings: `{total}`"
    )

    await send_log(

        "⚠️ Member Warned",

        f"{member.mention} received a warning.",

        discord.Color.orange(),

        fields=[

            (
                "Member",
                f"{member.mention}\n`{member.id}`",
                True
            ),

            (
                "Moderator",
                f"{interaction.user.mention}\n`{interaction.user.id}`",
                True
            ),

            (
                "Reason",
                reason,
                False
            ),

            (
                "Total Warnings",
                str(total),
                True
            )
        ]
    )


# ============================================================
# WARNINGS
# ============================================================

@bot.tree.command(
    name="warnings",
    description="View member warnings"
)
@staff_only()
@app_commands.describe(
    member="Member whose warnings you want to view"
)
async def warnings(
    interaction: discord.Interaction,
    member: discord.Member
):

    rows = db_execute(

        """
        SELECT *

        FROM warnings

        WHERE guild_id=?
        AND user_id=?

        ORDER BY created_at DESC
        """,

        (
            interaction.guild.id,
            member.id
        ),

        fetch=True
    )

    if not rows:

        await interaction.response.send_message(

            f"✅ {member.mention} has no warnings.",

            ephemeral=True
        )

        return


    lines = []

    for row in rows[:20]:

        lines.append(

            f"**#{row['id']}** • "
            f"<@{row['moderator_id']}> • "
            f"{timestamp_text(row['created_at'])}\n"
            f"└ {row['reason']}"
        )


    embed = discord.Embed(

        title=f"⚠️ Warnings • {member}",

        description="\n\n".join(lines),

        color=discord.Color.orange()
    )

    embed.set_footer(
        text=f"Total warnings: {len(rows)}"
    )

    await interaction.response.send_message(
        embed=embed,
        ephemeral=True
    )


# ============================================================
# CLEAR WARNINGS
# ============================================================

@bot.tree.command(
    name="clearwarnings",
    description="Clear all warnings for a member"
)
@staff_only()
@app_commands.describe(
    member="Member whose warnings should be cleared"
)
async def clearwarnings(
    interaction: discord.Interaction,
    member: discord.Member
):

    db_execute(

        """
        DELETE FROM warnings

        WHERE guild_id=?
        AND user_id=?
        """,

        (
            interaction.guild.id,
            member.id
        )
    )

    await interaction.response.send_message(

        f"🧹 Cleared all warnings for {member.mention}.",

        ephemeral=True
    )

    await send_log(

        "🧹 Warnings Cleared",

        f"All warnings for {member.mention} were cleared.",

        discord.Color.green(),

        fields=[

            (
                "Member",
                f"{member.mention}\n`{member.id}`",
                True
            ),

            (
                "Moderator",
                f"{interaction.user.mention}\n`{interaction.user.id}`",
                True
            )
        ]
    )


# ============================================================
# KICK
# ============================================================

@bot.tree.command(
    name="kick",
    description="Kick a member"
)
@staff_only()
@app_commands.describe(
    member="Member to kick",
    reason="Reason"
)
async def kick(
    interaction: discord.Interaction,
    member: discord.Member,
    reason: str = "No reason provided"
):

    if member == interaction.user:

        await interaction.response.send_message(
            "❌ You cannot kick yourself.",
            ephemeral=True
        )

        return

    try:

        await member.kick(
            reason=reason
        )

    except discord.Forbidden:

        await interaction.response.send_message(
            "❌ I cannot kick this member.",
            ephemeral=True
        )

        return

    await interaction.response.send_message(

        f"👢 {member.mention} was kicked.\n"
        f"Reason: **{reason}**"
    )

    await send_log(

        "👢 Member Kicked",

        f"{member} was kicked.",

        discord.Color.red(),

        fields=[

            (
                "Member",
                f"{member}\n`{member.id}`",
                True
            ),

            (
                "Moderator",
                f"{interaction.user.mention}\n`{interaction.user.id}`",
                True
            ),

            (
                "Reason",
                reason,
                False
            )
        ]
    )


# ============================================================
# BAN
# ============================================================

@bot.tree.command(
    name="ban",
    description="Ban a member"
)
@staff_only()
@app_commands.describe(
    member="Member to ban",
    reason="Reason"
)
async def ban(
    interaction: discord.Interaction,
    member: discord.Member,
    reason: str = "No reason provided"
):

    if member == interaction.user:

        await interaction.response.send_message(
            "❌ You cannot ban yourself.",
            ephemeral=True
        )

        return

    try:

        await member.ban(
            reason=reason,
            delete_message_days=1
        )

    except discord.Forbidden:

        await interaction.response.send_message(
            "❌ I cannot ban this member.",
            ephemeral=True
        )

        return

    await interaction.response.send_message(

        f"🔨 {member.mention} was banned.\n"
        f"Reason: **{reason}**"
    )

    await send_log(

        "🔨 Member Banned",

        f"{member} was banned.",

        discord.Color.red(),

        fields=[

            (
                "Member",
                f"{member}\n`{member.id}`",
                True
            ),

            (
                "Moderator",
                f"{interaction.user.mention}\n`{interaction.user.id}`",
                True
            ),

            (
                "Reason",
                reason,
                False
            )
        ]
    )


# ============================================================
# TIMEOUT
# ============================================================

@bot.tree.command(
    name="timeout",
    description="Timeout a member"
)
@staff_only()
@app_commands.describe(
    member="Member to timeout",
    minutes="Timeout duration in minutes",
    reason="Reason"
)
async def timeout_member(
    interaction: discord.Interaction,
    member: discord.Member,
    minutes: int,
    reason: str = "No reason provided"
):

    if minutes < 1:

        await interaction.response.send_message(
            "❌ Minimum timeout is 1 minute.",
            ephemeral=True
        )

        return

    if minutes > 40320:

        await interaction.response.send_message(
            "❌ Maximum timeout is 28 days.",
            ephemeral=True
        )

        return

    try:

        await member.timeout(

            discord.utils.utcnow()
            + timedelta(minutes=minutes),

            reason=reason
        )

    except discord.Forbidden:

        await interaction.response.send_message(
            "❌ I cannot timeout this member.",
            ephemeral=True
        )

        return

    await interaction.response.send_message(

        f"⏱️ {member.mention} timed out for "
        f"**{minutes} minutes**.\n"
        f"Reason: **{reason}**"
    )


# ============================================================
# CLEAR MESSAGES
# ============================================================

@bot.tree.command(
    name="clear",
    description="Delete messages"
)
@staff_only()
@app_commands.describe(
    amount="Number of messages to delete"
)
async def clear(
    interaction: discord.Interaction,
    amount: int
):

    if amount < 1 or amount > 100:

        await interaction.response.send_message(
            "❌ Amount must be between 1 and 100.",
            ephemeral=True
        )

        return

    await interaction.response.defer(
        ephemeral=True
    )

    deleted = await interaction.channel.purge(
        limit=amount
    )

    await interaction.followup.send(

        f"🧹 Deleted `{len(deleted)}` messages.",

        ephemeral=True
    )


# ============================================================
# ACTIVITY EMBED
# ============================================================

def activity_status_emoji(status):

    return {

        "online": "🟢",

        "idle": "🌙",

        "dnd": "🔴",

        "offline": "⚫"

    }.get(
        status,
        "⚫"
    )


def activity_embed(
    member,
    data
):

    status = data[
        "current_status"
    ]

    embed = discord.Embed(

        title=f"📊 Activity • {member.display_name}",

        color=discord.Color.blurple()
    )

    embed.add_field(

        name="Status",

        value=(
            f"{activity_status_emoji(status)} "
            f"`{status.upper()}`"
        ),

        inline=True
    )

    embed.add_field(

        name="Sessions",

        value=str(
            data["session_count"]
        ),

        inline=True
    )

    embed.add_field(

        name="Total Tracked",

        value=format_duration(
            data["total_seconds"]
        ),

        inline=True
    )

    embed.add_field(

        name="🟢 Online",

        value=format_duration(
            data["online_seconds"]
        ),

        inline=True
    )

    embed.add_field(

        name="🌙 Idle",

        value=format_duration(
            data["idle_seconds"]
        ),

        inline=True
    )

    embed.add_field(

        name="🔴 DND",

        value=format_duration(
            data["dnd_seconds"]
        ),

        inline=True
    )

    embed.add_field(

        name="First Tracked",

        value=timestamp_text(
            data["first_tracked"]
        ),

        inline=False
    )

    embed.add_field(

        name="Last Seen",

        value=timestamp_text(
            data["last_seen"]
        ),

        inline=False
    )

    embed.set_thumbnail(
        url=member.display_avatar.url
    )

    return embed


# ============================================================
# /ACTIVITY
# ============================================================

@bot.tree.command(
    name="activity",
    description="View member activity"
)
@app_commands.describe(
    member="Member to check"
)
async def activity(
    interaction: discord.Interaction,
    member: discord.Member = None
):

    target = member or interaction.user

    data = get_activity_data(
        target.id
    )

    if not data:

        ensure_activity_member(
            target
        )

        data = get_activity_data(
            target.id
        )

    await interaction.response.send_message(

        embed=activity_embed(
            target,
            data
        ),

        ephemeral=(
            member is not None
            and not is_staff(interaction.user)
        )
    )


# ============================================================
# /ACTIVITYDATA
# ============================================================

@bot.tree.command(
    name="activitydata",
    description="View raw activity data"
)
@staff_only()
@app_commands.describe(
    member="Member"
)
async def activitydata(
    interaction: discord.Interaction,
    member: discord.Member
):

    data = get_activity_data(
        member.id
    )

    if not data:

        await interaction.response.send_message(
            "❌ No activity data found.",
            ephemeral=True
        )

        return

    current_session = max(
        0,
        now_ts() -
        data["status_started"]
    )

    embed = discord.Embed(

        title=f"🧾 Raw Activity Data • {member}",

        color=discord.Color.dark_blue()
    )

    embed.add_field(
        name="User ID",
        value=f"`{member.id}`",
        inline=False
    )

    embed.add_field(
        name="Current Status",
        value=data["current_status"],
        inline=True
    )

    embed.add_field(
        name="Current Session",
        value=format_duration(
            current_session
        ),
        inline=True
    )

    embed.add_field(
        name="Sessions",
        value=str(
            data["session_count"]
        ),
        inline=True
    )

    embed.add_field(
        name="Online",
        value=format_duration(
            data["online_seconds"]
        ),
        inline=True
    )

    embed.add_field(
        name="Idle",
        value=format_duration(
            data["idle_seconds"]
        ),
        inline=True
    )

    embed.add_field(
        name="DND",
        value=format_duration(
            data["dnd_seconds"]
        ),
        inline=True
    )

    embed.add_field(
        name="Total",
        value=format_duration(
            data["total_seconds"]
        ),
        inline=True
    )

    embed.add_field(
        name="First Tracked",
        value=timestamp_text(
            data["first_tracked"]
        ),
        inline=False
    )

    embed.add_field(
        name="Last Seen",
        value=timestamp_text(
            data["last_seen"]
        ),
        inline=False
    )

    await interaction.response.send_message(
        embed=embed,
        ephemeral=True
    )


# ============================================================
# /ACTIVITYBOARD
# ============================================================

@bot.tree.command(
    name="activityboard",
    description="Show top activity members"
)
async def activityboard(
    interaction: discord.Interaction
):

    rows = db_execute(

        """
        SELECT *

        FROM activity

        ORDER BY
            (
                online_seconds
                +
                idle_seconds
                +
                dnd_seconds
            ) DESC

        LIMIT 10
        """,

        fetch=True
    )

    if not rows:

        await interaction.response.send_message(
            "📊 No activity data available yet."
        )

        return

    lines = []

    for index, row in enumerate(
        rows,
        start=1
    ):

        member = interaction.guild.get_member(
            row["user_id"]
        )

        if not member:

            continue

        total = (
            row["online_seconds"]
            +
            row["idle_seconds"]
            +
            row["dnd_seconds"]
        )

        lines.append(

            f"**{index}.** {member.mention} "
            f"• `{format_duration(total)}`"
        )


    embed = discord.Embed(

        title="🏆 Activity Board",

        description="\n".join(lines)
        if lines
        else "No members found.",

        color=discord.Color.gold()
    )

    await interaction.response.send_message(
        embed=embed
    )


# ============================================================
# /SERVERACTIVITY
# ============================================================

@bot.tree.command(
    name="serveractivity",
    description="Show server activity"
)
async def serveractivity(
    interaction: discord.Interaction
):

    rows = db_execute(

        """
        SELECT current_status, COUNT(*) AS total

        FROM activity

        GROUP BY current_status
        """,

        fetch=True
    )

    counts = {
        "online": 0,
        "idle": 0,
        "dnd": 0,
        "offline": 0
    }

    for row in rows:

        counts[
            row["current_status"]
        ] = row["total"]


    total_tracked = sum(
        counts.values()
    )

    embed = discord.Embed(

        title="📊 Server Activity",

        color=discord.Color.blurple()
    )

    embed.add_field(
        name="🟢 Online",
        value=str(counts["online"]),
        inline=True
    )

    embed.add_field(
        name="🌙 Idle",
        value=str(counts["idle"]),
        inline=True
    )

    embed.add_field(
        name="🔴 DND",
        value=str(counts["dnd"]),
        inline=True
    )

    embed.add_field(
        name="⚫ Offline",
        value=str(counts["offline"]),
        inline=True
    )

    embed.add_field(
        name="👥 Total Tracked",
        value=str(total_tracked),
        inline=True
    )

    await interaction.response.send_message(
        embed=embed
    )


# ============================================================
# /ACTIVITYTODAY
# ============================================================

@bot.tree.command(
    name="activitytoday",
    description="Show today's activity"
)
async def activitytoday(
    interaction: discord.Interaction
):

    today = datetime.now(
        timezone.utc
    ).strftime(
        "%Y-%m-%d"
    )

    rows = db_execute(

        """
        SELECT
            user_id,
            online_seconds,
            idle_seconds,
            dnd_seconds

        FROM activity_daily

        WHERE day=?

        ORDER BY
            (
                online_seconds
                +
                idle_seconds
                +
                dnd_seconds
            ) DESC

        LIMIT 10
        """,

        (
            today,
        ),

        fetch=True
    )

    if not rows:

        await interaction.response.send_message(
            "📊 No activity recorded today."
        )

        return


    lines = []

    for index, row in enumerate(
        rows,
        start=1
    ):

        member = interaction.guild.get_member(
            row["user_id"]
        )

        if not member:

            continue

        total = (
            row["online_seconds"]
            +
            row["idle_seconds"]
            +
            row["dnd_seconds"]
        )

        lines.append(

            f"**{index}.** {member.mention} "
            f"• `{format_duration(total)}`"
        )


    embed = discord.Embed(

        title="📅 Today's Activity",

        description="\n".join(lines)
        if lines
        else "No members found.",

        color=discord.Color.green()
    )

    await interaction.response.send_message(
        embed=embed
    )


# ============================================================
# /ACTIVITYWEEK
# ============================================================

@bot.tree.command(
    name="activityweek",
    description="Show activity for the last 7 days"
)
async def activityweek(
    interaction: discord.Interaction
):

    rows = db_execute(

        """
        SELECT
            user_id,
            SUM(online_seconds) AS online,
            SUM(idle_seconds) AS idle,
            SUM(dnd_seconds) AS dnd

        FROM activity_daily

        GROUP BY user_id

        ORDER BY
            (
                SUM(online_seconds)
                +
                SUM(idle_seconds)
                +
                SUM(dnd_seconds)
            ) DESC

        LIMIT 10
        """,

        fetch=True
    )

    if not rows:

        await interaction.response.send_message(
            "📊 No weekly activity data yet."
        )

        return


    lines = []

    for index, row in enumerate(
        rows,
        start=1
    ):

        member = interaction.guild.get_member(
            row["user_id"]
        )

        if not member:

            continue

        total = (
            row["online"]
            +
            row["idle"]
            +
            row["dnd"]
        )

        lines.append(

            f"**{index}.** {member.mention} "
            f"• `{format_duration(total)}`"
        )


    embed = discord.Embed(

        title="📆 Weekly Activity",

        description="\n".join(lines)
        if lines
        else "No members found.",

        color=discord.Color.blue()
    )

    await interaction.response.send_message(
        embed=embed
    )


# ============================================================
# /AFKLIST
# ============================================================

@bot.tree.command(
    name="afklist",
    description="Show currently idle members"
)
async def afklist(
    interaction: discord.Interaction
):

    rows = db_execute(

        """
        SELECT
            user_id,
            status_started

        FROM activity

        WHERE current_status='idle'

        ORDER BY status_started ASC
        """,

        fetch=True
    )

    if not rows:

        await interaction.response.send_message(
            "🌙 No members are currently idle."
        )

        return


    lines = []

    for row in rows:

        member = interaction.guild.get_member(
            row["user_id"]
        )

        if not member:

            continue

        duration = max(
            0,
            now_ts() -
            row["status_started"]
        )

        lines.append(

            f"🌙 {member.mention} "
            f"• `{format_duration(duration)}`"
        )


    embed = discord.Embed(

        title="🌙 Currently Idle",

        description="\n".join(lines)
        if lines
        else "No members found.",

        color=discord.Color.orange()
    )

    await interaction.response.send_message(
        embed=embed
    )


# ============================================================
# /ACTIVITYRESET
# ============================================================

@bot.tree.command(
    name="activityreset",
    description="Reset member activity"
)
@staff_only()
@app_commands.describe(
    member="Member whose activity should be reset"
)
async def activityreset(
    interaction: discord.Interaction,
    member: discord.Member
):

    timestamp = now_ts()

    db_execute(

        """
        UPDATE activity

        SET
            online_seconds=0,
            idle_seconds=0,
            dnd_seconds=0,
            session_count=0,
            first_tracked=?,
            last_seen=?,
            status_started=?

        WHERE user_id=?
        """,

        (
            timestamp,
            timestamp,
            timestamp,
            member.id
        )
    )

    db_execute(

        """
        DELETE FROM activity_daily

        WHERE user_id=?
        """,

        (
            member.id,
        )
    )

    await interaction.response.send_message(

        f"♻️ Activity data reset for {member.mention}.",

        ephemeral=True
    )

    await send_log(

        "♻️ Activity Reset",

        f"Activity data reset for {member.mention}.",

        discord.Color.orange(),

        fields=[

            (
                "Member",
                f"{member.mention}\n`{member.id}`",
                True
            ),

            (
                "Staff",
                f"{interaction.user.mention}\n`{interaction.user.id}`",
                True
            )
        ]
    )


# ============================================================
# ORG PANEL COMMAND
# ============================================================

@bot.tree.command(
    name="orgpanel",
    description="Send the organization panel"
)
@staff_only()
async def orgpanel(
    interaction: discord.Interaction
):

    channel = bot.get_channel(
        ORG_PANEL_CHANNEL_ID
    )

    if not channel:

        await interaction.response.send_message(
            "❌ Organization panel channel not found.",
            ephemeral=True
        )

        return

    await channel.send(

        embed=organization_panel_embed(),

        view=OrganizationPanelView()
    )

    await interaction.response.send_message(

        f"✅ Organization panel sent to {channel.mention}.",

        ephemeral=True
    )


# ============================================================
# READY EVENT
# ============================================================

@bot.event
async def on_ready():

    print(
        f"Logged in as {bot.user} "
        f"({bot.user.id})"
    )

    guild = bot.get_guild(
        GUILD_ID
    )

    if guild:

        # ----------------------------------------------
        # INITIALIZE ACTIVITY DATA
        # ----------------------------------------------

        for member in guild.members:

            try:

                ensure_activity_member(
                    member
                )

            except Exception:

                pass


    # ----------------------------------------------
    # REGISTER PERSISTENT ORGANIZATION PANEL
    # ----------------------------------------------

    try:

        bot.add_view(
            OrganizationPanelView()
        )

    except Exception:

        pass


    # ----------------------------------------------
    # REGISTER APPLICATION REVIEW VIEW
    # ----------------------------------------------

    try:

        bot.add_view(
            ApplicationReviewView()
        )

    except Exception:

        pass


    # ----------------------------------------------
    # ACTIVITY LOOP
    # ----------------------------------------------

    if not activity_flush.is_running():

        activity_flush.start()


    # ----------------------------------------------
    # SYNC COMMANDS
    # ----------------------------------------------

    try:

        guild_object = discord.Object(
            id=GUILD_ID
        )

        synced = await bot.tree.sync(
            guild=guild_object
        )

        print(
            f"Synced {len(synced)} slash commands."
        )

    except Exception as error:

        print(
            f"Command sync error: {error}"
        )


    print(
        "Modern City RP Bot is ONLINE."
    )


# ============================================================
# COMMAND ERROR HANDLER
# ============================================================

@bot.tree.error
async def on_app_command_error(
    interaction,
    error
):

    if isinstance(
        error,
        app_commands.CheckFailure
    ):

        await safe_ephemeral(

            interaction,

            "❌ You do not have permission to use this command."
        )

        return


    print(
        f"Command error: {error}"
    )

    await safe_ephemeral(

        interaction,

        "❌ An unexpected error occurred while executing this command."
    )


# ============================================================
# START BOT
# ============================================================

if not TOKEN:

    raise RuntimeError(
        "BOT_TOKEN environment variable is missing."
    )


bot.run(
    TOKEN
)
