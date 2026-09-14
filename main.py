from __future__ import annotations

import asyncio
from io import BytesIO
import json
import logging
import os
import sqlite3
from datetime import date, datetime, timedelta
from functools import wraps
from pathlib import Path
from typing import Any, Awaitable, Callable
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import httpx
from telegram import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
    ReplyKeyboardRemove,
    Update,
)
from telegram.constants import ChatMemberStatus, KeyboardButtonStyle
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)


BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
DB_PATH = DATA_DIR / "quran_bot.sqlite3"
CHANNEL = os.getenv("CHANNEL_USERNAME", "@Quranthebot")
BOT_TOKEN = os.getenv("BOT_TOKEN")
try:
    OWNER_ID = int(os.getenv("ADMIN_ID", "0"))
except ValueError:
    OWNER_ID = 0

RIYADH = ZoneInfo("Asia/Riyadh")
logger = logging.getLogger("quran-bot")
http_client: httpx.AsyncClient | None = None
health_server: asyncio.AbstractServer | None = None
reciter_cache: list[dict[str, Any]] = []
prayer_cache: dict[int, tuple[date, dict[str, str]]] = {}
friday_views: dict[tuple[int, int], str] = {}

PRAYER_NAMES_AR = {
    "Fajr": "الفجر",
    "Dhuhr": "الظهر",
    "Asr": "العصر",
    "Maghrib": "المغرب",
    "Isha": "العشاء",
}

ARABIC_WEEKDAYS = (
    "الاثنين",
    "الثلاثاء",
    "الأربعاء",
    "الخميس",
    "الجمعة",
    "السبت",
    "الأحد",
)

FRIDAY_PRAYERS = (
    "اللهم اغفر لي ذنبي كله، دقه وجله، أوله وآخره، سره وعلانيته.",
    "ربنا آتنا في الدنيا حسنة وفي الآخرة حسنة وقنا عذاب النار.",
    "اللهم إنك عفو تحب العفو فاعف عني.",
    "ربنا لا تزغ قلوبنا بعد إذ هديتنا وهب لنا من لدنك رحمة.",
    "اللهم صل وسلم وبارك على نبينا محمد، واغفر لنا وارحمنا.",
)

SURAHS = [
    "الفاتحة", "البقرة", "آل عمران", "النساء", "المائدة", "الأنعام",
    "الأعراف", "الأنفال", "التوبة", "يونس", "هود", "يوسف", "الرعد",
    "إبراهيم", "الحجر", "النحل", "الإسراء", "الكهف", "مريم", "طه",
    "الأنبياء", "الحج", "المؤمنون", "النور", "الفرقان", "الشعراء",
    "النمل", "القصص", "العنكبوت", "الروم", "لقمان", "السجدة", "الأحزاب",
    "سبأ", "فاطر", "يس", "الصافات", "ص", "الزمر", "غافر", "فصلت",
    "الشورى", "الزخرف", "الدخان", "الجاثية", "الأحقاف", "محمد", "الفتح",
    "الحجرات", "ق", "الذاريات", "الطور", "النجم", "القمر", "الرحمن",
    "الواقعة", "الحديد", "المجادلة", "الحشر", "الممتحنة", "الصف",
    "الجمعة", "المنافقون", "التغابن", "الطلاق", "التحريم", "الملك",
    "القلم", "الحاقة", "المعارج", "نوح", "الجن", "المزمل", "المدثر",
    "القيامة", "الإنسان", "المرسلات", "النبأ", "النازعات", "عبس",
    "التكوير", "الانفطار", "المطففين", "الانشقاق", "البروج", "الطارق",
    "الأعلى", "الغاشية", "الفجر", "البلد", "الشمس", "الليل", "الضحى",
    "الشرح", "التين", "العلق", "القدر", "البينة", "الزلزلة", "العاديات",
    "القارعة", "التكاثر", "العصر", "الهمزة", "الفيل", "قريش", "الماعون",
    "الكوثر", "الكافرون", "النصر", "المسد", "الإخلاص", "الفلق", "الناس",
]

ARABIC_ALPHABET = "ابتثجحخدذرزسشصضطظعغفقكلمنهوي"
ARABIC_NORMALIZATION = str.maketrans(
    {
        "أ": "ا",
        "إ": "ا",
        "آ": "ا",
        "ٱ": "ا",
        "ى": "ي",
    }
)


def arabic_sort_key(value: str) -> tuple[tuple[int, ...], str]:
    normalized = value.translate(ARABIC_NORMALIZATION).replace(" ", "")
    if normalized.startswith("ال"):
        normalized = normalized[2:]
    ranks = tuple(
        ARABIC_ALPHABET.index(letter)
        if letter in ARABIC_ALPHABET
        else len(ARABIC_ALPHABET)
        for letter in normalized
    )
    return ranks, normalized


SURAH_MENU = sorted(
    ((number, name) for number, name in enumerate(SURAHS, start=1)),
    key=lambda item: arabic_sort_key(item[1]),
)

POPULAR_RECITER_ALIASES = (
    "عبد الرحمن مسعد",
    "عبد الباسط عبد الصمد",
    "محمود خليل الحصري",
    "محمد صديق المنشاوي",
    "مشاري العفاسي",
    "عبد الرحمن السديس",
    "سعود الشريم",
    "ماهر المعيقلي",
    "ياسر الدوسري",
    "سعد الغامدي",
    "فارس عباد",
    "ناصر القطامي",
    "عبد الله عواد الجهني",
    "أحمد بن علي العجمي",
    "أبو بكر الشاطري",
    "صلاح بو خاطر",
    "علي جابر",
    "إدريس أبكر",
    "هاني الرفاعي",
    "محمد أيوب",
    "محمود علي البنا",
    "مصطفى إسماعيل",
    "خالد الجليل",
    "محمد اللحيدان",
    "بندر بليلة",
    "إسلام صبحي",
)

ABDULRAHMAN_MOSAD_AUDIO = {
    "moshaf_id": 210021,
    "reciter_id": 210021,
    "name": "عبد الرحمن مسعد",
    "rewaya": "حفص عن عاصم — مصدر خارجي",
    "server": "https://archive.org/download/010_20221110",
    "surah_list": "10,19,23,29,32,49,73,78,87,88,100,107",
}


def reciter_rank(name: str) -> int | None:
    normalized_name = name.translate(ARABIC_NORMALIZATION).replace(" ", "")
    for rank, alias in enumerate(POPULAR_RECITER_ALIASES):
        normalized_alias = alias.translate(ARABIC_NORMALIZATION).replace(" ", "")
        if normalized_alias in normalized_name:
            return rank
    return None


HADITHS = [
    ("إنما الأعمال بالنيات، وإنما لكل امرئ ما نوى.", "صحيح البخاري", "1"),
    ("من كان يؤمن بالله واليوم الآخر فليقل خيرًا أو ليصمت.", "صحيح البخاري", "6018"),
    ("المسلم من سلم المسلمون من لسانه ويده.", "صحيح البخاري", "10"),
    ("لا يؤمن أحدكم حتى يحب لأخيه ما يحب لنفسه.", "صحيح البخاري", "13"),
    ("من لا يرحم لا يُرحم.", "صحيح البخاري", "5997"),
    ("الكلمة الطيبة صدقة.", "صحيح البخاري", "2989"),
    ("يسروا ولا تعسروا، وبشروا ولا تنفروا.", "صحيح البخاري", "69"),
    ("الدين النصيحة.", "صحيح مسلم", "55"),
    ("الطهور شطر الإيمان.", "صحيح مسلم", "223"),
    ("من سلك طريقًا يلتمس فيه علمًا سهل الله له به طريقًا إلى الجنة.", "صحيح مسلم", "2699"),
    ("من صلى علي واحدة صلى الله عليه بها عشرًا.", "صحيح مسلم", "408"),
    ("خيركم من تعلم القرآن وعلمه.", "صحيح البخاري", "5027"),
    ("اقرؤوا القرآن فإنه يأتي يوم القيامة شفيعًا لأصحابه.", "صحيح مسلم", "804"),
    ("أحب الأعمال إلى الله أدومها وإن قل.", "صحيح البخاري", "6465"),
    ("اتق الله حيثما كنت، وأتبع السيئة الحسنة تمحها، وخالق الناس بخلق حسن.", "سنن الترمذي", "1987"),
    ("تبسمك في وجه أخيك لك صدقة.", "سنن الترمذي", "1956"),
    ("الراحمون يرحمهم الرحمن، ارحموا من في الأرض يرحمكم من في السماء.", "سنن الترمذي", "1924"),
    ("من غشنا فليس منا.", "صحيح مسلم", "101"),
    ("من يرد الله به خيرًا يفقهه في الدين.", "صحيح البخاري", "71"),
    ("المؤمن للمؤمن كالبنيان يشد بعضه بعضًا.", "صحيح البخاري", "481"),
    ("المؤمنون كرجل واحد، إن اشتكى رأسه تداعى له سائر الجسد بالحمى والسهر.", "صحيح مسلم", "2586"),
    ("لا ضرر ولا ضرار.", "سنن ابن ماجه", "2341"),
    ("اتقوا النار ولو بشق تمرة، فمن لم يجد فبكلمة طيبة.", "صحيح البخاري", "1413"),
    ("من كان يؤمن بالله واليوم الآخر فليكرم ضيفه.", "صحيح البخاري", "6018"),
    ("خير الناس أنفعهم للناس.", "المعجم الأوسط", "5787"),
    ("من سلك طريقًا يلتمس فيه علمًا سهل الله له به طريقًا إلى الجنة.", "صحيح مسلم", "2699"),
    ("الحياء لا يأتي إلا بخير.", "صحيح البخاري", "6117"),
    ("ليس الشديد بالصرعة، إنما الشديد الذي يملك نفسه عند الغضب.", "صحيح البخاري", "6114"),
    ("من لا يشكر الناس لا يشكر الله.", "سنن الترمذي", "1954"),
    ("أحب الناس إلى الله أنفعهم للناس.", "المعجم الأوسط", "6026"),
    ("من دل على خير فله مثل أجر فاعله.", "صحيح مسلم", "1893"),
    ("البر حسن الخلق، والإثم ما حاك في نفسك وكرهت أن يطلع عليه الناس.", "صحيح مسلم", "2553"),
    ("اتق الله حيثما كنت، وأتبع السيئة الحسنة تمحها، وخالق الناس بخلق حسن.", "سنن الترمذي", "1987"),
    ("لا يؤمن أحدكم حتى أكون أحب إليه من والده وولده والناس أجمعين.", "صحيح البخاري", "15"),
    ("من كان في حاجة أخيه كان الله في حاجته.", "صحيح البخاري", "2442"),
    ("والله في عون العبد ما كان العبد في عون أخيه.", "صحيح مسلم", "2699"),
    ("من تواضع لله رفعه الله.", "صحيح مسلم", "2588"),
    ("لا تحقرن من المعروف شيئًا ولو أن تلقى أخاك بوجه طلق.", "صحيح مسلم", "2626"),
    ("إن الله لا ينظر إلى صوركم وأموالكم، ولكن ينظر إلى قلوبكم وأعمالكم.", "صحيح مسلم", "2564"),
    ("يسروا ولا تعسروا، وبشروا ولا تنفروا.", "صحيح البخاري", "69"),
    ("اغتنم خمسًا قبل خمس: حياتك قبل موتك، وصحتك قبل سقمك، وفراغك قبل شغلك، وشبابك قبل هرمك، وغناك قبل فقرك.", "المستدرك على الصحيحين", "7846"),
]

HADITHS_PATH = BASE_DIR / "hadiths_ar.json"
hadith_cache: list[tuple[str, str, str]] = []


def load_hadiths() -> list[tuple[str, str, str]]:
    global hadith_cache
    if hadith_cache:
        return hadith_cache
    try:
        payload = json.loads(HADITHS_PATH.read_text(encoding="utf-8"))
        loaded = [
            (
                str(item["hadeeth"]).strip(),
                str(item["source"]).strip(),
                str(item.get("id", "")),
            )
            for item in payload
            if item.get("hadeeth") and item.get("source")
        ]
        if len(loaded) >= 250:
            hadith_cache = loaded
    except (OSError, ValueError, TypeError, KeyError) as error:
        logger.warning("Local hadith collection could not be loaded: %s", error)
    return hadith_cache or HADITHS


AZKAR = {
    "morning": [
        "أصبحنا وأصبح الملك لله، والحمد لله، لا إله إلا الله وحده لا شريك له.",
        "رضيت بالله ربًا، وبالإسلام دينًا، وبمحمد صلى الله عليه وسلم نبيًا. (3 مرات)",
        "اللهم بك أصبحنا وبك أمسينا وبك نحيا وبك نموت وإليك النشور.",
        "حسبي الله لا إله إلا هو عليه توكلت وهو رب العرش العظيم. (7 مرات)",
        "سبحان الله وبحمده. (100 مرة)",
    ],
    "evening": [
        "أمسينا وأمسى الملك لله، والحمد لله، لا إله إلا الله وحده لا شريك له.",
        "أعوذ بكلمات الله التامات من شر ما خلق. (3 مرات)",
        "اللهم إني أسألك العفو والعافية في الدنيا والآخرة.",
        "رضيت بالله ربًا، وبالإسلام دينًا، وبمحمد صلى الله عليه وسلم نبيًا. (3 مرات)",
        "لا إله إلا الله وحده لا شريك له، له الملك وله الحمد وهو على كل شيء قدير. (10 مرات)",
    ],
    "after_prayer": [
        "أستغفر الله. (3 مرات)",
        "اللهم أنت السلام ومنك السلام تباركت يا ذا الجلال والإكرام.",
        "سبحان الله، والحمد لله، والله أكبر. (33 مرة)",
        "لا إله إلا الله وحده لا شريك له، له الملك وله الحمد وهو على كل شيء قدير.",
        "آية الكرسي، وسورة الإخلاص، والفلق، والناس.",
    ],
}


def db() -> sqlite3.Connection:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(DB_PATH)
    connection.row_factory = sqlite3.Row
    return connection


def init_db() -> None:
    with db() as connection:
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                first_name TEXT NOT NULL,
                lat REAL,
                lng REAL,
                city TEXT,
                timezone TEXT,
                notifications_enabled INTEGER NOT NULL DEFAULT 1,
                azan_enabled INTEGER NOT NULL DEFAULT 0,
                joined_at TEXT NOT NULL,
                last_azan_key TEXT,
                entry_reported INTEGER NOT NULL DEFAULT 0
            );
            CREATE TABLE IF NOT EXISTS admins (
                user_id INTEGER PRIMARY KEY,
                added_by INTEGER NOT NULL,
                added_at TEXT NOT NULL,
                can_manage_admins INTEGER NOT NULL DEFAULT 0
            );
            CREATE TABLE IF NOT EXISTS broadcasts (
                broadcast_id INTEGER PRIMARY KEY AUTOINCREMENT,
                content TEXT NOT NULL,
                sent_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS broadcast_messages (
                broadcast_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                message_id INTEGER NOT NULL,
                PRIMARY KEY (broadcast_id, user_id)
            );
            """
        )
        admin_columns = {
            row["name"]
            for row in connection.execute("PRAGMA table_info(admins)").fetchall()
        }
        user_columns = {
            row["name"]
            for row in connection.execute("PRAGMA table_info(users)").fetchall()
        }
        if "timezone" not in user_columns:
            connection.execute("ALTER TABLE users ADD COLUMN timezone TEXT")
        if "entry_reported" not in user_columns:
            connection.execute(
                "ALTER TABLE users ADD COLUMN entry_reported INTEGER NOT NULL DEFAULT 0"
            )
        if "can_manage_admins" not in admin_columns:
            connection.execute(
                "ALTER TABLE admins ADD COLUMN can_manage_admins INTEGER NOT NULL DEFAULT 0"
            )
        if OWNER_ID:
            connection.execute(
                """
                INSERT OR IGNORE INTO admins
                    (user_id, added_by, added_at, can_manage_admins)
                VALUES (?, ?, ?, 1)
                """,
                (OWNER_ID, OWNER_ID, datetime.now(tz=RIYADH).isoformat()),
            )
            connection.execute(
                "UPDATE admins SET can_manage_admins = 1 WHERE user_id = ?",
                (OWNER_ID,),
            )


def remember_user(user_id: int, first_name: str) -> None:
    with db() as connection:
        connection.execute(
            """
            INSERT INTO users (user_id, first_name, joined_at)
            VALUES (?, ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET first_name=excluded.first_name
            """,
            (user_id, first_name, datetime.now(tz=RIYADH).isoformat()),
        )


def user_row(user_id: int) -> sqlite3.Row | None:
    with db() as connection:
        return connection.execute("SELECT * FROM users WHERE user_id = ?", (user_id,)).fetchone()


def claim_entry_report(user_id: int) -> bool:
    with db() as connection:
        cursor = connection.execute(
            """
            UPDATE users
            SET entry_reported = 1
            WHERE user_id = ? AND entry_reported = 0
            """,
            (user_id,),
        )
    return cursor.rowcount == 1


def user_count() -> int:
    with db() as connection:
        row = connection.execute("SELECT COUNT(*) AS total FROM users").fetchone()
    return int(row["total"]) if row else 0


def admin_ids() -> list[int]:
    with db() as connection:
        rows = connection.execute("SELECT user_id FROM admins").fetchall()
    return [int(row["user_id"]) for row in rows]


def is_admin(user_id: int) -> bool:
    with db() as connection:
        return connection.execute("SELECT 1 FROM admins WHERE user_id = ?", (user_id,)).fetchone() is not None


def can_manage_admins(user_id: int) -> bool:
    if user_id == OWNER_ID:
        return True
    with db() as connection:
        row = connection.execute(
            "SELECT can_manage_admins FROM admins WHERE user_id = ?", (user_id,)
        ).fetchone()
        return bool(row and row["can_manage_admins"])


def admin_display_name(user_id: int, fallback: str | None = None) -> str:
    if user_id == OWNER_ID:
        return "المالك"
    row = user_row(user_id)
    return (row["first_name"] if row else None) or fallback or str(user_id)


async def subscription_ok(user_id: int, context: ContextTypes.DEFAULT_TYPE) -> bool:
    try:
        member = await context.bot.get_chat_member(chat_id=CHANNEL, user_id=user_id)
        return member.status in {
            ChatMemberStatus.MEMBER,
            ChatMemberStatus.ADMINISTRATOR,
            ChatMemberStatus.OWNER,
        }
    except Exception as error:
        logger.warning("Could not check channel membership: %s", error)
        return False


async def notify_new_user_if_needed(
    context: ContextTypes.DEFAULT_TYPE, user: Any
) -> None:
    """Send one profile report to admins after the user passes subscription check."""
    if not claim_entry_report(user.id):
        return
    try:
        profile = await context.bot.get_chat(chat_id=user.id)
    except Exception:
        profile = None
    username = getattr(profile, "username", None) or getattr(user, "username", None)
    first_name = getattr(profile, "first_name", None) or getattr(user, "first_name", None) or "بدون اسم"
    last_name = getattr(profile, "last_name", None) or getattr(user, "last_name", None) or ""
    bio = getattr(profile, "bio", None) or "لا توجد نبذة ظاهرة"
    full_name = f"{first_name} {last_name}".strip()
    username_text = f"@{username}" if username else "بدون يوزر"
    report = (
        "👤 مستخدم جديد دخل البوت واشترك في القناة\n\n"
        f"الاسم: {full_name}\n"
        f"اليوزر: {username_text}\n"
        f"الآيدي: {user.id}\n"
        f"وصف الحساب: {bio}\n\n"
        f"📊 إجمالي دخول البوت: {user_count()}"
    )
    for admin_id in admin_ids():
        try:
            await context.bot.send_message(
                chat_id=admin_id,
                text=report,
                parse_mode=None,
                disable_web_page_preview=True,
            )
        except Exception:
            continue


SUBSCRIBE_BUTTON = "اشترك في القناة"
VERIFY_BUTTON = "تحقق من الاشتراك"
PRAYER_BUTTON = "مواقيت الصلاة وموقعي"
QURAN_BUTTON = "القرآن الكريم"
AZKAR_BUTTON = "الأذكار"
HADITH_BUTTON = "الأحاديث مع الدليل"
FRIDAY_BUTTON = "الجمعة"
SEASONS_BUTTON = "أيام للأجر"
SETTINGS_BUTTON = "الإعدادات والتنبيهات"
FEATURES_BUTTON = "مطور البوت"
ADMIN_BUTTON = "لوحة التحكم"


def subscription_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        [
            [KeyboardButton(SUBSCRIBE_BUTTON, style=KeyboardButtonStyle.DANGER)],
            [KeyboardButton(VERIFY_BUTTON, style=KeyboardButtonStyle.PRIMARY)],
        ],
        resize_keyboard=True,
        is_persistent=True,
        one_time_keyboard=False,
        input_field_placeholder="اختر من الأزرار",
    )


def main_reply_keyboard(*, include_admin: bool = False) -> ReplyKeyboardMarkup:
    rows = [
        [KeyboardButton(PRAYER_BUTTON, style=KeyboardButtonStyle.PRIMARY)],
        [KeyboardButton(QURAN_BUTTON, style=KeyboardButtonStyle.SUCCESS)],
        [KeyboardButton(AZKAR_BUTTON, style=KeyboardButtonStyle.DANGER)],
        [KeyboardButton(HADITH_BUTTON, style=KeyboardButtonStyle.PRIMARY)],
        [KeyboardButton(FRIDAY_BUTTON, style=KeyboardButtonStyle.SUCCESS)],
        [KeyboardButton(SEASONS_BUTTON, style=KeyboardButtonStyle.SUCCESS)],
        [KeyboardButton(SETTINGS_BUTTON, style=KeyboardButtonStyle.PRIMARY)],
        [KeyboardButton(FEATURES_BUTTON, style=KeyboardButtonStyle.DANGER)],
    ]
    if include_admin:
        rows.append([KeyboardButton(ADMIN_BUTTON, style=KeyboardButtonStyle.DANGER)])
    return ReplyKeyboardMarkup(
        rows,
        resize_keyboard=True,
        is_persistent=True,
        one_time_keyboard=False,
        input_field_placeholder="اختر قسمًا من القائمة",
    )


def subscription_text() -> str:
    return (
        "🔒 للوصول إلى البوت، اشترك أولًا في قناة القرآن الكريم.\n\n"
        f"🔗 رابط القناة: https://t.me/{CHANNEL.lstrip('@')}\n\n"
        f"بعد الاشتراك اضغط «{VERIFY_BUTTON}»."
    )


async def show_subscription_gate(update: Update) -> None:
    text = subscription_text()
    query = update.callback_query
    if query:
        try:
            await query.edit_message_text(text)
            await query.message.reply_text(
                "استخدم الأزرار بالأسفل:",
                reply_markup=subscription_keyboard(),
            )
        except Exception:
            await query.message.reply_text(text, reply_markup=subscription_keyboard())
    elif update.effective_message:
        await update.effective_message.reply_text(text, reply_markup=subscription_keyboard())


def guarded(handler: Callable[..., Awaitable[Any]]) -> Callable[..., Awaitable[Any]]:
    @wraps(handler)
    async def wrapped(update: Update, context: ContextTypes.DEFAULT_TYPE) -> Any:
        user = update.effective_user
        if not user:
            return None
        remember_user(user.id, user.first_name or "مستخدم")
        if not await subscription_ok(user.id, context):
            await show_subscription_gate(update)
            return None
        await notify_new_user_if_needed(context, user)
        return await handler(update, context)

    return wrapped


def home_button() -> InlineKeyboardButton:
    return InlineKeyboardButton("🏠 القائمة الرئيسية", callback_data="home")


async def render_screen(
    update: Update,
    text: str,
    reply_markup: InlineKeyboardMarkup | ReplyKeyboardMarkup | None = None,
) -> None:
    query = update.callback_query
    if query:
        await query.edit_message_text(text, reply_markup=reply_markup)
    elif update.effective_message:
        await update.effective_message.reply_text(text, reply_markup=reply_markup)


async def welcome_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    text = (
        f"✨ أهلًا يا {user.first_name}، في رفيقك الإيماني ﷺ\n\n"
        "تم التحقق من اشتراكك في القناة\n\n"
        "مميزات البوت:\n"
        "1. القرآن الكريم نصًا كاملًا وصوتًا.\n"
        "2. أكثر من 100 قارئ ورواية.\n"
        "3. الأحاديث النبوية (مصادر موثوقة).\n"
        "4. ألاذكــــار.\n"
        "5. أيـــام للـــاجـــر.\n"
        "6. مواقيت الصلاة حسب موقعك.\n\n"
        "DEV BOT- @dl_r7c\n\n"
        "اختر قسمًا من القائمة:"
    )
    markup = main_reply_keyboard(include_admin=is_admin(user.id))
    query = update.callback_query
    if query:
        await query.edit_message_text(text)
        await query.message.reply_text("اختر قسمًا من القائمة:", reply_markup=markup)
    else:
        await update.effective_message.reply_text(text, reply_markup=markup)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    if not user:
        return
    remember_user(user.id, user.first_name or "مستخدم")
    if not await subscription_ok(user.id, context):
        await show_subscription_gate(update)
        return
    await notify_new_user_if_needed(context, user)
    await welcome_text(update, context)


async def verify_subscription(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    user = query.from_user if query else update.effective_user
    if not user:
        return
    if query:
        await query.answer()
    if await subscription_ok(user.id, context):
        await notify_new_user_if_needed(context, user)
        await welcome_text(update, context)
    else:
        await show_subscription_gate(update)


def page_buttons(page: int, total: int, prefix: str, back: str = "home") -> list[list[InlineKeyboardButton]]:
    row: list[InlineKeyboardButton] = []
    if page > 0:
        row.append(InlineKeyboardButton("◀️ السابق", callback_data=f"{prefix}:{page - 1}"))
    if page < total - 1:
        row.append(InlineKeyboardButton("التالي ▶️", callback_data=f"{prefix}:{page + 1}"))
    rows = [row] if row else []
    rows.append([InlineKeyboardButton("🔙 رجوع", callback_data=back), home_button()])
    return rows


async def show_quran(update: Update, page: int) -> None:
    per_page = 18
    total_pages = (len(SURAH_MENU) + per_page - 1) // per_page
    page = max(0, min(page, total_pages - 1))
    start_index = page * per_page
    buttons = [
        InlineKeyboardButton(f"{number}. {name}", callback_data=f"surah:{number}")
        for number, name in SURAH_MENU[start_index : start_index + per_page]
    ]
    rows = [buttons[i : i + 3] for i in range(0, len(buttons), 3)]
    rows += page_buttons(page, total_pages, "quran", "home")
    text = f"📖 القرآن الكريم\nالصفحة {page + 1} من {total_pages}\n\nاختر السورة:"
    await render_screen(update, text, InlineKeyboardMarkup(rows))


async def fetch_json(url: str, **kwargs: Any) -> dict[str, Any]:
    global http_client
    if http_client is None:
        http_client = httpx.AsyncClient(timeout=20, follow_redirects=True)
    response = await http_client.get(url, **kwargs)
    response.raise_for_status()
    return response.json()


def split_text(text: str, limit: int = 3900) -> list[str]:
    chunks: list[str] = []
    while len(text) > limit:
        cut = text.rfind("\n", 0, limit)
        if cut < 500:
            cut = limit
        chunks.append(text[:cut])
        text = text[cut:].lstrip()
    if text:
        chunks.append(text)
    return chunks


async def show_surah(update: Update, context: ContextTypes.DEFAULT_TYPE, surah_number: int) -> None:
    query = update.callback_query
    await query.answer("جاري تحميل السورة...")
    try:
        payload = await fetch_json(f"https://api.alquran.cloud/v1/surah/{surah_number}/quran-uthmani")
        data = payload["data"]
        ayahs = data["ayahs"]
        text = f"📖 سورة {SURAHS[surah_number - 1]} ({surah_number})\n\n"
        text += "\n".join(f"{ayah['text']} ۝{ayah['numberInSurah']}" for ayah in ayahs)
        await query.edit_message_text(split_text(text)[0])
        for chunk in split_text(text)[1:]:
            await query.message.reply_text(chunk)
        await query.message.reply_text(
            "🎧 اختر القارئ والرواية لسماع السورة:",
            reply_markup=InlineKeyboardMarkup(
                await reciter_keyboard(surah_number, 0)
            ),
        )
    except Exception as error:
        logger.exception("Quran fetch failed: %s", error)
        await query.edit_message_text(
            "تعذر تحميل السورة الآن. حاول مرة أخرى بعد قليل.",
            reply_markup=InlineKeyboardMarkup([[home_button()]]),
        )


async def load_reciters() -> list[dict[str, Any]]:
    global reciter_cache
    if reciter_cache:
        return reciter_cache
    try:
        payload = await fetch_json("https://mp3quran.net/api/v3/reciters?language=ar")
        popular_result: list[dict[str, Any]] = []
        fallback_result: list[dict[str, Any]] = []
        for reciter in payload.get("reciters", []):
            name = reciter.get("name") or ""
            rank = reciter_rank(name)
            moshafs = [
                moshaf
                for moshaf in reciter.get("moshaf") or []
                if moshaf.get("server") and moshaf.get("surah_list")
            ]
            hafs_moshafs = [
                moshaf
                for moshaf in moshafs
                if moshaf.get("rewaya_id") == 1
                or "حفص عن عاصم" in (moshaf.get("name") or "")
            ]
            # Prefer the well-known Hafs recording, but keep a usable
            # recording for a famous reciter when the API labels it differently.
            selected_moshafs = hafs_moshafs or moshafs[:1]
            for moshaf in selected_moshafs:
                if not moshaf.get("server") or not moshaf.get("surah_list"):
                    continue
                item = {
                    "moshaf_id": moshaf["id"],
                    "reciter_id": reciter["id"],
                    "name": name,
                    "rewaya": moshaf.get("name") or "الرواية المتاحة",
                    "server": moshaf["server"],
                    "surah_list": moshaf["surah_list"],
                }
                fallback_result.append(item)
                if rank is not None:
                    popular_result.append(item)

        if not any(item["name"] == ABDULRAHMAN_MOSAD_AUDIO["name"] for item in popular_result):
            popular_result.append(ABDULRAHMAN_MOSAD_AUDIO.copy())

        result = popular_result or fallback_result
        result.sort(
            key=lambda item: (
                reciter_rank(item["name"]) if reciter_rank(item["name"]) is not None else 999,
                item["name"],
                0 if "حفص عن عاصم" in item["rewaya"] else 1,
                item["rewaya"],
            )
        )
        reciter_cache = result
    except Exception as error:
        logger.warning("Reciters fetch failed: %s", error)
        reciter_cache = [ABDULRAHMAN_MOSAD_AUDIO.copy()]
    return reciter_cache


async def reciter_keyboard(surah_number: int, page: int) -> list[list[InlineKeyboardButton]]:
    reciters = [
        item
        for item in await load_reciters()
        if str(surah_number) in item["surah_list"].split(",")
    ]
    per_page = 8
    total = max(1, (len(reciters) + per_page - 1) // per_page)
    page = max(0, min(page, total - 1))
    rows = []
    for item in reciters[page * per_page : (page + 1) * per_page]:
        label = f"{item['name']} — {item['rewaya']}"
        rows.append(
            [
                InlineKeyboardButton(
                    label,
                    callback_data=f"audio:{surah_number}:{item['moshaf_id']}",
                )
            ]
        )
    rows += page_buttons(page, total, f"reciters:{surah_number}", f"surah:{surah_number}")
    return rows


async def send_reciter_audio(update: Update, surah_number: int, moshaf_id: int) -> None:
    query = update.callback_query
    await query.answer("جاري تجهيز الصوت...")
    reciters = await load_reciters()
    reciter = next(
        (item for item in reciters if int(item["moshaf_id"]) == moshaf_id),
        None,
    )
    if not reciter:
        await query.answer("القارئ غير متاح حاليًا", show_alert=True)
        return
    url = f"{reciter['server'].rstrip('/')}/{surah_number:03d}.mp3"
    try:
        async with httpx.AsyncClient(timeout=60, follow_redirects=True) as client:
            response = await client.get(url)
            response.raise_for_status()
        audio = BytesIO(response.content)
        audio.name = f"{surah_number:03d}.mp3"
        await query.message.reply_audio(
            audio=audio,
            filename=audio.name,
            caption=(
                f"🎧 سورة {SURAHS[surah_number - 1]}\n"
                f"القارئ: {reciter['name']}\n"
                f"الرواية: {reciter['rewaya']}"
            ),
        )
    except Exception as error:
        logger.warning("Audio send failed: %s", error)
        await query.message.reply_text("تعذر إرسال المقطع الصوتي لهذا القارئ حاليًا.")


async def show_prayer(update: Update) -> None:
    await render_screen(
        update,
        "🕌 مواقيت الصلاة\n\nشارك موقعك للحصول على مواقيت الصلاة لمدينتك:",
        reply_markup=InlineKeyboardMarkup([[home_button()]]),
    )
    message = update.effective_message
    if update.callback_query:
        message = update.callback_query.message
    await message.reply_text(
        "📍 اضغط الزر لإرسال موقعك:",
        reply_markup=ReplyKeyboardMarkup(
            [[KeyboardButton("📍 مشاركة موقعي", request_location=True)]],
            resize_keyboard=True,
            one_time_keyboard=True,
        ),
    )


def timezone_for_name(name: str | None) -> ZoneInfo:
    try:
        return ZoneInfo(name or "Asia/Riyadh")
    except ZoneInfoNotFoundError:
        return RIYADH


def format_time_12(value: str) -> str:
    """Convert the API's 24-hour HH:MM value to Arabic 12-hour display."""
    raw = value.strip().split(" ")[0]
    try:
        hour, minute = (int(part) for part in raw.split(":", 1))
    except (TypeError, ValueError):
        return value
    suffix = "ص" if hour < 12 else "م"
    display_hour = hour % 12 or 12
    return f"{display_hour}:{minute:02d} {suffix}"


async def prayer_for_location(latitude: float, longitude: float) -> tuple[str, dict[str, str]]:
    payload = await fetch_json(
        "https://api.aladhan.com/v1/timings",
        params={
            "latitude": latitude,
            "longitude": longitude,
            "method": 4,
            "school": 0,
        },
    )
    data = payload["data"]
    timings = {
        key: data["timings"][key].split(" ")[0]
        for key in ("Fajr", "Dhuhr", "Asr", "Maghrib", "Isha")
    }
    timezone_name = data.get("meta", {}).get("timezone") or "Asia/Riyadh"
    return timezone_name, timings


async def reverse_geocode(latitude: float, longitude: float) -> str | None:
    try:
        payload = await fetch_json(
            "https://nominatim.openstreetmap.org/reverse",
            params={"lat": latitude, "lon": longitude, "format": "jsonv2", "zoom": 10},
            headers={"User-Agent": "QuranTelegramBot/1.0"},
        )
        address = payload.get("address", {})
        return (
            address.get("city")
            or address.get("town")
            or address.get("village")
            or address.get("state")
        )
    except Exception as error:
        logger.warning("Reverse geocoding failed: %s", error)
        return None


async def location_received(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    if not user or not await subscription_ok(user.id, context):
        await show_subscription_gate(update)
        return
    location = update.effective_message.location
    try:
        timezone_name, timings = await prayer_for_location(location.latitude, location.longitude)
        city = await reverse_geocode(location.latitude, location.longitude)
        city = city or timezone_name.split("/")[-1].replace("_", " ")
        with db() as connection:
            connection.execute(
                "UPDATE users SET lat=?, lng=?, city=?, timezone=? WHERE user_id=?",
                (location.latitude, location.longitude, city, timezone_name, user.id),
            )
        local_now = datetime.now(tz=timezone_for_name(timezone_name))
        prayer_cache[user.id] = (local_now.date(), timings)
        text = (
            f"🕌 مواقيت الصلاة اليوم\n📍 {city}\n\n"
            f"المنطقة الزمنية: {timezone_name}\n\n"
            f"الفجر: {format_time_12(timings['Fajr'])}\n"
            f"الظهر: {format_time_12(timings['Dhuhr'])}\n"
            f"العصر: {format_time_12(timings['Asr'])}\n"
            f"المغرب: {format_time_12(timings['Maghrib'])}\n"
            f"العشاء: {format_time_12(timings['Isha'])}\n\n"
            "يمكنك تفعيل تنبيهات الأذان من الإعدادات."
        )
        await update.effective_message.reply_text(text, reply_markup=ReplyKeyboardRemove())
        await update.effective_message.reply_text(
            "اختر ما تريد:",
            reply_markup=InlineKeyboardMarkup([[home_button()]]),
        )
    except Exception as error:
        logger.warning("Prayer lookup failed: %s", error)
        await update.effective_message.reply_text(
            "تعذر جلب المواقيت الآن. تأكد من تفعيل الموقع وحاول مرة أخرى.",
            reply_markup=ReplyKeyboardRemove(),
        )


async def show_azkar(update: Update) -> None:
    rows = [
        [InlineKeyboardButton("🌅 أذكار الصباح", callback_data="azkar:morning")],
        [InlineKeyboardButton("🌃 أذكار المساء", callback_data="azkar:evening")],
        [InlineKeyboardButton("🤲 أذكار بعد الصلاة", callback_data="azkar:after_prayer")],
        [InlineKeyboardButton("🔙 رجوع", callback_data="home"), home_button()],
    ]
    await render_screen(update, "🤲 اختر قسم الأذكار:", InlineKeyboardMarkup(rows))


async def show_azkar_category(update: Update, category: str) -> None:
    query = update.callback_query
    titles = {"morning": "🌅 أذكار الصباح", "evening": "🌃 أذكار المساء", "after_prayer": "🤲 أذكار بعد الصلاة"}
    text = f"{titles[category]}\n\n" + "\n\n".join(
        f"{index}. {item}" for index, item in enumerate(AZKAR[category], 1)
    )
    await query.edit_message_text(
        text,
        reply_markup=InlineKeyboardMarkup(
            [[InlineKeyboardButton("🔙 رجوع", callback_data="azkar"), home_button()]]
        ),
    )


def hadith_page_buttons(
    page: int, total: int
) -> list[list[InlineKeyboardButton]]:
    row: list[InlineKeyboardButton] = []
    if page > 0:
        row.append(InlineKeyboardButton("السابق", callback_data=f"hadith:{page - 1}"))
    if page < total - 1:
        row.append(InlineKeyboardButton("التالي", callback_data=f"hadith:{page + 1}"))
    rows = [row] if row else []
    rows.append(
        [
            InlineKeyboardButton("رجوع", callback_data="home"),
            InlineKeyboardButton("القائمة الرئيسية", callback_data="home"),
        ]
    )
    return rows


async def show_hadith(update: Update, page: int) -> None:
    hadiths = load_hadiths()
    page = max(0, min(page, len(hadiths) - 1))
    content, source, _number = hadiths[page]
    text = f"{content}\n\nالمصدر: {source}"
    rows = hadith_page_buttons(page, len(hadiths))
    await render_screen(update, text, InlineKeyboardMarkup(rows))


def format_countdown(delta: timedelta) -> tuple[str, int]:
    total_seconds = max(0, int(delta.total_seconds()))
    days, remainder = divmod(total_seconds, 24 * 60 * 60)
    hours, remainder = divmod(remainder, 60 * 60)
    minutes, seconds = divmod(remainder, 60)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}", days


def next_friday_start(now: datetime) -> datetime:
    days = (4 - now.weekday()) % 7
    return (now + timedelta(days=days)).replace(
        hour=0, minute=0, second=0, microsecond=0
    )


def friday_text(now: datetime) -> str:
    text = "الجمعة\n\nأدعية مأثورة:\n" + "\n".join(
        f"• {prayer}" for prayer in FRIDAY_PRAYERS
    )
    if now.weekday() == 4:
        return text + "\n\nاليوم هو يوم الجمعة، تقبّل الله طاعاتكم."

    target = next_friday_start(now)
    countdown, days = format_countdown(target - now)
    target_date = target.strftime("%Y-%m-%d")
    return (
        f"{text}\n\n"
        f"العدّاد التنازلي: {countdown}\n"
        f"الأيام المتبقية: {days}\n"
        f"أقرب جمعة قادمة: {ARABIC_WEEKDAYS[target.weekday()]} "
        f"{target_date} (ميلادي)"
    )


def friday_markup() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("تحديث العداد", callback_data="friday:refresh")],
            [InlineKeyboardButton("رجوع", callback_data="home"), home_button()],
        ]
    )


async def show_friday(update: Update) -> None:
    text = friday_text(datetime.now(tz=RIYADH))
    query = update.callback_query
    if query:
        await query.edit_message_text(text, reply_markup=friday_markup())
        message = query.message
    elif update.effective_message:
        message = await update.effective_message.reply_text(
            text, reply_markup=friday_markup()
        )
    else:
        return

    if message:
        friday_views[(message.chat_id, message.message_id)] = text


def next_fixed_date(month: int, day: int) -> date:
    today = date.today()
    candidate = date(today.year, month, day)
    return candidate if candidate >= today else date(today.year + 1, month, day)


async def show_seasons(update: Update) -> None:
    now = datetime.now(tz=RIYADH)
    ramadan = date(now.year, 2, 18)
    if ramadan < now.date():
        ramadan = date(now.year + 1, 2, 8)
    eid_fitr = ramadan + timedelta(days=30)
    arafah = date(now.year, 5, 26)
    if arafah < now.date():
        arafah = date(now.year + 1, 5, 15)
    laylat_al_qadr = ramadan + timedelta(days=26)

    def event_line(label: str, event_date: date) -> str:
        target = now.replace(
            year=event_date.year,
            month=event_date.month,
            day=event_date.day,
            hour=0,
            minute=0,
            second=0,
            microsecond=0,
        )
        countdown, days = format_countdown(target - now)
        return (
            f"• {label}\n"
            f"  العدّاد: {countdown} | الأيام المتبقية: {days}\n"
            f"  التاريخ الميلادي: {event_date.strftime('%Y-%m-%d')}"
        )

    text = (
        "🌙 أيام للأجر\n\n"
        f"{event_line('رمضان المتوقع', ramadan)}\n\n"
        f"{event_line('عيد الفطر المتوقع', eid_fitr)}\n\n"
        f"{event_line('يوم عرفة المتوقع', arafah)}\n\n"
        f"{event_line('ليلة القدر (متوقعة وليست مؤكدة)', laylat_al_qadr)}\n"
        "تنبيه: ليلة القدر متوقعة وليست مؤكدة، وتُحرّى في العشر الأواخر "
        "من رمضان حسب حديث النبي ﷺ.\n\n"
        "📿 تذكير بالصيام:\n"
        "• الاثنين والخميس\n• الأيام البيض 13 و14 و15\n"
        "• عاشوراء\n• الست من شوال\n• عشر ذي الحجة"
    )
    await render_screen(
        update,
        text,
        reply_markup=InlineKeyboardMarkup([[home_button()]]),
    )


async def show_settings(update: Update) -> None:
    user = update.effective_user
    if not user:
        return
    row = user_row(user.id)
    notifications = bool(row["notifications_enabled"]) if row else True
    azan = bool(row["azan_enabled"]) if row else False
    markup = InlineKeyboardMarkup(
        [
            [InlineKeyboardButton(f"🔔 كل التنبيهات: {'مفعّلة ✅' if notifications else 'متوقفة ❌'}", callback_data="settings:notifications")],
            [InlineKeyboardButton(f"🕌 تنبيه الأذان: {'مفعّل ✅' if azan else 'متوقف ❌'}", callback_data="settings:azan")],
            [InlineKeyboardButton("🔙 رجوع", callback_data="home"), home_button()],
        ]
    )
    await render_screen(update, "⚙️ الإعدادات والتنبيهات", markup)


async def toggle_setting(update: Update, field: str) -> None:
    query = update.callback_query
    column = "notifications_enabled" if field == "notifications" else "azan_enabled"
    with db() as connection:
        connection.execute(
            f"UPDATE users SET {column} = CASE {column} WHEN 1 THEN 0 ELSE 1 END WHERE user_id = ?",
            (query.from_user.id,),
        )
    await query.answer("تم تحديث الإعداد")
    await show_settings(update)


async def show_features(update: Update) -> None:
    await render_screen(
        update,
        "مطور البوت\n\n"
        "• أحاديث موثوقة.\n"
        "• الاذكــار.\n"
        "• حفظ القرآن الكريم كاملاً - 100+ قارئ.\n"
        "• مواقيت الصلاة حسب الموقع.\n"
        "• تنبيهات قابلة للتشغيل والإيقاف.\n"
        "\n"
        "مطور البوت - @dl_r7c\n"
        "Islamic Telegram Bot v1.0",
        reply_markup=InlineKeyboardMarkup([[home_button()]]),
    )


async def show_admin(update: Update) -> None:
    user = update.effective_user
    if not user or not is_admin(user.id):
        if update.callback_query:
            await update.callback_query.answer("هذا القسم للأدمن فقط", show_alert=True)
        elif update.effective_message:
            await update.effective_message.reply_text("هذا القسم للأدمن فقط.")
        return
    rows = []
    if can_manage_admins(user.id):
        rows.extend(
            [
                [InlineKeyboardButton("➕ إضافة مشرف", callback_data="admin:add")],
                [InlineKeyboardButton("➖ إزالة مشرف", callback_data="admin:remove")],
            ]
        )
    else:
        rows.append(
            [
                InlineKeyboardButton(
                    "🔒 إدارة المشرفين — صلاحية المالك فقط",
                    callback_data="admin:no_permission",
                )
            ]
        )
    if user.id == OWNER_ID:
        rows.append(
            [
                InlineKeyboardButton(
                    "🔐 منح/سحب صلاحية إدارة المشرفين",
                    callback_data="admin:permissions",
                )
            ]
        )
    rows.extend(
        [
            [InlineKeyboardButton("📢 بث رسالة للجميع", callback_data="admin:broadcast")],
            [InlineKeyboardButton("👁 الرسالة الأخيرة", callback_data="admin:latest")],
            [InlineKeyboardButton("🗑 مسح آخر رسالة", callback_data="admin:delete")],
            [InlineKeyboardButton("🔙 رجوع", callback_data="home")],
        ]
    )
    await render_screen(
        update,
        "👑 لوحة التحكم\n\n"
        "المالك وحده يستطيع منح صلاحية إدارة المشرفين أو سحبها.",
        reply_markup=InlineKeyboardMarkup(rows),
    )


async def show_permissions(update: Update) -> None:
    user = update.effective_user
    if not user or user.id != OWNER_ID:
        if update.callback_query:
            await update.callback_query.answer("هذه الصلاحية للمالك فقط", show_alert=True)
        return
    with db() as connection:
        admins = connection.execute(
            """
            SELECT admins.user_id, admins.can_manage_admins, users.first_name
            FROM admins
            LEFT JOIN users ON users.user_id = admins.user_id
            ORDER BY admins.user_id = ?, admins.added_at
            """,
            (OWNER_ID,),
        ).fetchall()
    rows = []
    for admin in admins:
        if admin["user_id"] == OWNER_ID:
            continue
        status = "ممنوحة ✅" if admin["can_manage_admins"] else "غير ممنوحة ❌"
        name = admin["first_name"] or str(admin["user_id"])
        rows.append(
            [
                InlineKeyboardButton(
                    f"{name} — {status}",
                    callback_data=f"permissions:toggle:{admin['user_id']}",
                )
            ]
        )
    if not rows:
        rows.append(
            [
                InlineKeyboardButton(
                    "لا يوجد مشرفون إضافيون حاليًا",
                    callback_data="admin:permissions",
                )
            ]
        )
    rows.extend(
        [
            [InlineKeyboardButton("🔙 لوحة التحكم", callback_data="admin")],
            [home_button()],
        ]
    )
    await render_screen(
        update,
        "🔐 صلاحيات إدارة المشرفين\n\n"
        "اضغط على اسم المشرف لمنحه أو سحب صلاحية إضافة وإزالة المشرفين.",
        reply_markup=InlineKeyboardMarkup(rows),
    )


async def toggle_admin_permission(update: Update, user_id: int) -> None:
    query = update.callback_query
    if query.from_user.id != OWNER_ID:
        await query.answer("هذه الصلاحية للمالك فقط", show_alert=True)
        return
    if user_id == OWNER_ID:
        await query.answer("صلاحية المالك ثابتة", show_alert=True)
        return
    with db() as connection:
        connection.execute(
            """
            UPDATE admins
            SET can_manage_admins = CASE can_manage_admins WHEN 1 THEN 0 ELSE 1 END
            WHERE user_id = ?
            """,
            (user_id,),
        )
    await query.answer("تم تحديث الصلاحية")
    await show_permissions(update)


async def admin_action(
    update: Update, context: ContextTypes.DEFAULT_TYPE, action: str
) -> None:
    query = update.callback_query
    if not is_admin(query.from_user.id):
        await query.answer("غير مصرح", show_alert=True)
        return
    if action in {"add", "remove"} and not can_manage_admins(query.from_user.id):
        await query.answer("لا تملك صلاحية إدارة المشرفين", show_alert=True)
        return
    if action == "permissions" and query.from_user.id != OWNER_ID:
        await query.answer("هذه الصلاحية للمالك فقط", show_alert=True)
        return
    if action == "no_permission":
        await query.answer("اطلب من المالك منحك صلاحية إدارة المشرفين", show_alert=True)
        return
    if action == "permissions":
        await show_permissions(update)
        return
    if action in {"add", "remove", "broadcast"}:
        context.user_data["admin_pending"] = action
        prompts = {
            "add": "أرسل رقم المستخدم (ID) لإضافته كمشرف:",
            "remove": "أرسل رقم المشرف (ID) لإزالته:",
            "broadcast": "أرسل نص الرسالة التي تريد بثها للجميع:",
        }
        await query.edit_message_text(prompts[action], reply_markup=InlineKeyboardMarkup([[home_button()]]))
        return
    if action == "latest":
        with db() as connection:
            row = connection.execute("SELECT * FROM broadcasts ORDER BY broadcast_id DESC LIMIT 1").fetchone()
        text = "لا توجد رسائل جماعية بعد."
        if row:
            text = f"📢 آخر رسالة جماعية ({row['sent_at']}):\n\n{row['content']}"
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup([[home_button()]]))
        return
    if action == "delete":
        with db() as connection:
            broadcast = connection.execute("SELECT * FROM broadcasts ORDER BY broadcast_id DESC LIMIT 1").fetchone()
            messages = (
                connection.execute(
                    "SELECT user_id, message_id FROM broadcast_messages WHERE broadcast_id = ?",
                    (broadcast["broadcast_id"],),
                ).fetchall()
                if broadcast
                else []
            )
            if broadcast:
                connection.execute("DELETE FROM broadcast_messages WHERE broadcast_id = ?", (broadcast["broadcast_id"],))
                connection.execute("DELETE FROM broadcasts WHERE broadcast_id = ?", (broadcast["broadcast_id"],))
        deleted = 0
        if broadcast:
            for item in messages:
                try:
                    await query.message.bot.delete_message(item["user_id"], item["message_id"])
                    deleted += 1
                except Exception:
                    pass
        await query.edit_message_text(f"🗑 تم حذف الرسالة من {deleted} محادثة.", reply_markup=InlineKeyboardMarkup([[home_button()]]))


async def handle_admin_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    if not user:
        return
    if not context.user_data.get("admin_pending"):
        await handle_reply_keyboard_text(update, context)
        return
    if not is_admin(user.id):
        return
    if not await subscription_ok(user.id, context):
        await show_subscription_gate(update)
        return
    action = context.user_data.pop("admin_pending")
    content = update.effective_message.text.strip()
    if action in {"add", "remove"}:
        if not can_manage_admins(user.id):
            await update.effective_message.reply_text(
                "🔒 لا تملك صلاحية إضافة أو إزالة المشرفين. اطلبها من المالك."
            )
            return
        try:
            target_id = int(content)
        except ValueError:
            await update.effective_message.reply_text("أرسل رقم ID صحيحًا.")
            return
        with db() as connection:
            if action == "add":
                connection.execute(
                    """
                    INSERT OR IGNORE INTO admins
                        (user_id, added_by, added_at, can_manage_admins)
                    VALUES (?, ?, ?, 0)
                    """,
                    (target_id, user.id, datetime.now(tz=RIYADH).isoformat()),
                )
            else:
                connection.execute(
                    "DELETE FROM admins WHERE user_id = ? AND user_id != ?",
                    (target_id, OWNER_ID),
                )
        if action == "add":
            try:
                await context.bot.send_message(target_id, "🎉 تم إضافتك مشرفًا في بوت أذكاري")
            except Exception:
                pass
        await update.effective_message.reply_text("✅ تم تحديث قائمة المشرفين.", reply_markup=InlineKeyboardMarkup([[home_button()]]))
        return
    if action == "broadcast":
        with db() as connection:
            cursor = connection.execute(
                "INSERT INTO broadcasts (content, sent_at) VALUES (?, ?)",
                (content, datetime.now(tz=RIYADH).isoformat()),
            )
            broadcast_id = cursor.lastrowid
            users = connection.execute("SELECT user_id FROM users").fetchall()
        sent = 0
        failed = 0
        for row in users:
            try:
                message = await context.bot.send_message(row["user_id"], content)
                with db() as connection:
                    connection.execute(
                        "INSERT INTO broadcast_messages (broadcast_id, user_id, message_id) VALUES (?, ?, ?)",
                        (broadcast_id, row["user_id"], message.message_id),
                    )
                sent += 1
            except Exception:
                failed += 1
            await asyncio.sleep(0.04)
        await update.effective_message.reply_text(
            f"📢 اكتمل البث.\n✅ نجح: {sent}\n❌ فشل: {failed}",
            reply_markup=InlineKeyboardMarkup([[home_button()]]),
        )


async def handle_reply_keyboard_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.effective_message
    user = update.effective_user
    if not message or not user:
        return
    text = message.text.strip()

    if text == SUBSCRIBE_BUTTON:
        await message.reply_text(
            f"🔗 افتح رابط القناة للاشتراك:\nhttps://t.me/{CHANNEL.lstrip('@')}",
            reply_markup=subscription_keyboard(),
        )
        return
    if text == VERIFY_BUTTON:
        await verify_subscription(update, context)
        return

    if not await subscription_ok(user.id, context):
        await show_subscription_gate(update)
        return
    remember_user(user.id, user.first_name or "مستخدم")

    menu_actions: dict[str, Callable[[], Awaitable[Any]]] = {
        PRAYER_BUTTON: lambda: show_prayer(update),
        QURAN_BUTTON: lambda: show_quran(update, 0),
        AZKAR_BUTTON: lambda: show_azkar(update),
        HADITH_BUTTON: lambda: show_hadith(update, 0),
        FRIDAY_BUTTON: lambda: show_friday(update),
        SEASONS_BUTTON: lambda: show_seasons(update),
        SETTINGS_BUTTON: lambda: show_settings(update),
        FEATURES_BUTTON: lambda: show_features(update),
        ADMIN_BUTTON: lambda: show_admin(update),
    }
    action = menu_actions.get(text)
    if action:
        await action()


async def callback_router(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    if query.data == "verify_sub":
        await verify_subscription(update, context)
        return
    if not await subscription_ok(query.from_user.id, context):
        await show_subscription_gate(update)
        return
    remember_user(query.from_user.id, query.from_user.first_name or "مستخدم")
    await notify_new_user_if_needed(context, query.from_user)
    parts = query.data.split(":")
    if query.data == "home":
        await welcome_text(update, context)
    elif query.data == "prayer":
        await show_prayer(update)
    elif parts[0] == "quran":
        await show_quran(update, int(parts[1]))
    elif parts[0] == "surah":
        await show_surah(update, context, int(parts[1]))
    elif parts[0] == "reciters":
        await query.edit_message_text(
            "🎧 اختر قارئًا:",
            reply_markup=InlineKeyboardMarkup(await reciter_keyboard(int(parts[1]), int(parts[2]))),
        )
    elif parts[0] == "audio":
        await send_reciter_audio(update, int(parts[1]), int(parts[2]))
    elif query.data == "azkar":
        await show_azkar(update)
    elif parts[0] == "azkar":
        await show_azkar_category(update, parts[1])
    elif parts[0] == "hadith":
        await show_hadith(update, int(parts[1]))
    elif query.data == "friday":
        await show_friday(update)
    elif parts[0] == "friday":
        await show_friday(update)
    elif query.data == "seasons":
        await show_seasons(update)
    elif query.data == "settings":
        await show_settings(update)
    elif parts[0] == "settings":
        await toggle_setting(update, parts[1])
    elif parts[0] == "permissions":
        await toggle_admin_permission(update, int(parts[2]))
    elif query.data == "features":
        await show_features(update)
    elif query.data == "admin":
        await show_admin(update)
    elif parts[0] == "admin":
        await admin_action(update, context, parts[1])


async def prayer_alert_job(context: ContextTypes.DEFAULT_TYPE) -> None:
    with db() as connection:
        users = connection.execute(
            "SELECT * FROM users WHERE azan_enabled = 1 AND notifications_enabled = 1 "
            "AND lat IS NOT NULL AND lng IS NOT NULL"
        ).fetchall()
    for user in users:
        try:
            now = datetime.now(tz=timezone_for_name(user["timezone"]))
            if now.second > 10:
                continue
            cached = prayer_cache.get(user["user_id"])
            if not cached or cached[0] != now.date():
                timezone_name, timings = await prayer_for_location(user["lat"], user["lng"])
                prayer_cache[user["user_id"]] = (now.date(), timings)
                if timezone_name != user["timezone"]:
                    with db() as connection:
                        connection.execute(
                            "UPDATE users SET timezone = ? WHERE user_id = ?",
                            (timezone_name, user["user_id"]),
                        )
            timings = prayer_cache[user["user_id"]][1]
            for label, time_value in timings.items():
                key = f"{now.date().isoformat()}:{label}:{time_value}"
                if time_value == now.strftime("%H:%M") and user["last_azan_key"] != key:
                    prayer_name = PRAYER_NAMES_AR.get(label, label)
                    await context.bot.send_message(
                        user["user_id"], f"🕌 حان الآن وقت صلاة {prayer_name}."
                    )
                    with db() as connection:
                        connection.execute("UPDATE users SET last_azan_key = ? WHERE user_id = ?", (key, user["user_id"]))
        except Exception as error:
            logger.warning("Prayer alert failed for %s: %s", user["user_id"], error)


async def friday_refresh_job(context: ContextTypes.DEFAULT_TYPE) -> None:
    if not friday_views:
        return
    text = friday_text(datetime.now(tz=RIYADH))
    for view, previous_text in list(friday_views.items()):
        if previous_text == text:
            continue
        chat_id, message_id = view
        try:
            await context.bot.edit_message_text(
                chat_id=chat_id,
                message_id=message_id,
                text=text,
                reply_markup=friday_markup(),
            )
            friday_views[view] = text
        except Exception as error:
            error_text = str(error).lower()
            if "not modified" in error_text:
                friday_views[view] = text
            elif "message to edit not found" in error_text or "chat not found" in error_text:
                friday_views.pop(view, None)


async def health_check(
    reader: asyncio.StreamReader,
    writer: asyncio.StreamWriter,
) -> None:
    try:
        await reader.read(1024)
        body = b'{"status":"ok","service":"quran-telegram-bot"}'
        response = (
            b"HTTP/1.1 200 OK\r\n"
            b"Content-Type: application/json\r\n"
            b"Content-Length: "
            + str(len(body)).encode()
            + b"\r\n"
            b"Connection: close\r\n\r\n"
            + body
        )
        writer.write(response)
        await writer.drain()
    finally:
        writer.close()
        await writer.wait_closed()


async def post_init(application: Application) -> None:
    global health_server
    init_db()
    port = int(os.getenv("PORT", "0") or "0")
    if port:
        health_server = await asyncio.start_server(
            health_check,
            host="0.0.0.0",
            port=port,
        )
        logger.info("Health server listening on port %s", port)
    application.job_queue.run_repeating(prayer_alert_job, interval=60, first=10)
    application.job_queue.run_repeating(friday_refresh_job, interval=5, first=5)


async def post_shutdown(application: Application) -> None:
    global health_server, http_client
    if health_server:
        health_server.close()
        await health_server.wait_closed()
        health_server = None
    if http_client:
        await http_client.aclose()
        http_client = None


def build_application() -> Application:
    if not BOT_TOKEN:
        raise RuntimeError("BOT_TOKEN secret is missing")
    application = (
        Application.builder()
        .token(BOT_TOKEN)
        .post_init(post_init)
        .post_shutdown(post_shutdown)
        .build()
    )
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CallbackQueryHandler(callback_router))
    application.add_handler(MessageHandler(filters.LOCATION, location_received))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_admin_text))
    return application


if __name__ == "__main__":
    logging.basicConfig(
        level=os.getenv("LOG_LEVEL", "INFO"),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    # HTTPX logs Telegram's token when it formats the request URL at INFO.
    # Keep transport logs quiet so secrets never reach workflow output.
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    init_db()
    app = build_application()
    logger.info("Quran Telegram Bot is starting")
    app.run_polling(allowed_updates=Update.ALL_TYPES, drop_pending_updates=False)
