"""@Bekcraftuzbot — BekCraft katalogi va buyurtmalar.

Ma'lumot bitta joyda — bekcraft.uz bazasida. Bot saytga BOT_API_KEY bilan
murojaat qiladi (site_api.py). Botda kiritilgan model darhol saytda ham chiqadi.
"""
import hashlib
import hmac
import logging
import os
import re
import time
import uuid

from fastapi import FastAPI, Header, Request
from fastapi.responses import PlainTextResponse
import uvicorn

from telegram import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    InputMediaPhoto,
    KeyboardButton,
    ReplyKeyboardMarkup,
    ReplyKeyboardRemove,
    Update,
)
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from site_api import SiteApi, SiteError

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("bekcraft")
# httpx so'rov manzillarini logga yozmasin.
logging.getLogger("httpx").setLevel(logging.WARNING)

BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]


def parse_admin_ids(raw):
    ids = set()
    for part in str(raw or "").split(","):
        part = part.strip()
        if part.isdigit():
            ids.add(int(part))
    return ids


ADMIN_IDS = parse_admin_ids(os.environ.get("ADMIN_IDS") or os.environ.get("ADMIN_ID"))
SITE_URL = os.environ.get("SITE_URL", "https://bekcraft.uz").rstrip("/")
BOT_API_KEY = os.environ.get("BOT_API_KEY", "").strip()
WEBHOOK_URL = os.environ.get("WEBHOOK_URL", "").rstrip("/")
PORT = int(os.environ.get("PORT", "10000"))
WEBHOOK_SECRET_PATTERN = re.compile(r"^[A-Za-z0-9_-]{1,256}$")


class WebhookSecretError(RuntimeError):
    """WEBHOOK_SECRET yo'q yoki Telegram qoidasiga mos emas."""


def require_webhook_secret(raw):
    if raw is None or not str(raw).strip():
        raise WebhookSecretError(
            "WEBHOOK_SECRET topilmadi. Bot himoyasiz ishga tushmaydi. "
            "1–256 belgidan iborat sir bering: faqat lotin harflari, raqamlar, _ va -."
        )
    secret = str(raw).strip()
    if WEBHOOK_SECRET_PATTERN.fullmatch(secret) is None:
        raise WebhookSecretError(
            "WEBHOOK_SECRET yaroqsiz. Bot himoyasiz ishga tushmaydi. "
            "Uzunlik 1–256 bo'lsin va faqat lotin harflari, raqamlar, _ yoki - ishlating."
        )
    return secret


def webhook_secret_matches(provided):
    if not isinstance(provided, str) or not provided:
        return False
    try:
        given = provided.encode("utf-8")
    except UnicodeError:
        return False
    expected_digest = hashlib.sha256(WEBHOOK_SECRET.encode("utf-8")).digest()
    given_digest = hashlib.sha256(given).digest()
    return hmac.compare_digest(expected_digest, given_digest)


WEBHOOK_SECRET = require_webhook_secret(os.environ.get("WEBHOOK_SECRET"))

site = SiteApi(SITE_URL, BOT_API_KEY)

MAX_PHOTOS = 10
CAPTION_LIMIT = 1024
SKIP_TEXT = "⏭ O'tkazib yuborish"
CONTACT_TEXT = (
    "📞 Biz bilan bog'lanish:\n\n"
    "+998938374177\n\n"
    "+998933364177"
)
PRIVATE_ORDER_TEXT = (
    "Buyurtma faqat bot bilan shaxsiy chatda qabul qilinadi.\n\n"
    "Iltimos, shu botning shaxsiy chatini oching va buyurtmani o'sha yerda bering. "
    "Guruhda ism va telefon so'ralmaydi."
)
ADMIN_ONLY_TEXT = "Bu bo'lim faqat administrator uchun."


def button(text, data):
    return InlineKeyboardButton(text, callback_data=data)


def is_admin(update):
    return bool(update.effective_user and update.effective_user.id in ADMIN_IDS)


def is_private_chat(update):
    chat = update.effective_chat
    return bool(chat and chat.type == "private")


def actor_of(update):
    user = update.effective_user
    name = getattr(user, "full_name", "") or getattr(user, "username", "") or "admin"
    return f"{name} ({user.id})"


# ---- Katalog keshi: sayt sekin uyg'onsa ham menyular tez ochilsin ----

_catalog_cache = {"at": 0.0, "data": None}
CATALOG_TTL = 60


async def get_catalog(fresh=False):
    if not fresh and _catalog_cache["data"] is not None and time.monotonic() - _catalog_cache["at"] < CATALOG_TTL:
        return _catalog_cache["data"]
    data = await site.catalog()
    _catalog_cache.update(at=time.monotonic(), data=data)
    return data


def forget_catalog():
    _catalog_cache.update(at=0.0, data=None)


def find_category(catalog, category_id):
    for category in catalog:
        if category.get("id") == category_id:
            return category
    return None


def category_id_by_name(catalog, name):
    for category in catalog:
        if category.get("name") == name:
            return category.get("id")
    return None


def short(text, limit):
    text = str(text or "")
    return text if len(text) <= limit else text[: limit - 1] + "…"


def parse_int(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


# ---- Mijoz qismi ----

def home_buttons():
    return [[button("📞 Biz bilan bog'lanish", "contact")]]


async def show_home(message):
    try:
        catalog = await get_catalog()
    except SiteError as error:
        await message.reply_text(error.message + "\n\n" + CONTACT_TEXT)
        return
    rows = []
    for category in catalog:
        if category.get("id") and any(p["model_count"] for p in category["products"]):
            rows.append([button(category["name"], f"c:{category['id']}")])
    rows += home_buttons()
    text = "Bo'limni tanlang:" if len(rows) > 1 else "Katalog hozircha bo'sh."
    await message.reply_text(text, reply_markup=InlineKeyboardMarkup(rows))


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    await update.message.reply_text(
        "Assalomu alaykum! 👋\n\n"
        "BekCraft katalogiga xush kelibsiz. "
        "Mahsulotni tanlang, rasmlari va narxini ko'ring, buyurtma bering.",
        reply_markup=ReplyKeyboardRemove(),
    )
    await show_home(update.message)


async def show_category(message, category_id):
    catalog = await get_catalog()
    category = find_category(catalog, category_id)
    products = [p for p in (category or {}).get("products", []) if p["model_count"]]
    if not products:
        await message.reply_text("Bu bo'limda hozircha mahsulot yo'q.",
                                 reply_markup=InlineKeyboardMarkup([[button("⬅️ Bo'limlar", "home")]]))
        return
    rows = [[button(f"{p['name']} ({p['model_count']})", f"p:{p['id']}")] for p in products]
    rows.append([button("⬅️ Bo'limlar", "home")])
    await message.reply_text(f"{category['name']}\n\nTurini tanlang:", reply_markup=InlineKeyboardMarkup(rows))


async def show_models(message, product_id):
    data = await site.models(product_id)
    catalog = await get_catalog()
    category_id = category_id_by_name(catalog, data["product"]["category"])
    back = f"c:{category_id}" if category_id else "home"
    models = [m for m in data["models"] if m["image_count"]]
    if not models:
        await message.reply_text("Bu turda hozircha model yo'q.",
                                 reply_markup=InlineKeyboardMarkup([[button("⬅️ Orqaga", back)]]))
        return
    rows = [[button(short(f"{m['name']} — {m['price_label']}", 60), f"m:{m['id']}")] for m in models]
    rows.append([button("⬅️ Orqaga", back)])
    await message.reply_text(f"{data['product']['name']}\n\nModelni tanlang:", reply_markup=InlineKeyboardMarkup(rows))


def model_caption(model):
    text = f"📌 {model['name']}\n💰 {model['price_label']}"
    if model.get("description"):
        text += "\n\n" + model["description"]
    return short(text, CAPTION_LIMIT)


async def send_album(message, images, caption="", numbered=False):
    """Rasmlarni albom qilib yuboradi. Telegram rasmni olib bo'lmasa — False."""
    media = []
    for index, image in enumerate(images[:MAX_PHOTOS]):
        if numbered:
            text = f"{index + 1}-rasm" + (" (asosiy)" if index == 0 else "")
        else:
            text = caption if index == 0 else None
        media.append(InputMediaPhoto(media=image["url"], caption=text))
    if not media:
        return False
    try:
        if len(media) == 1:
            await message.reply_photo(photo=media[0].media, caption=media[0].caption)
        else:
            await message.reply_media_group(media=media)
        return True
    except Exception:
        log.exception("Albom yuborilmadi")
        return False


async def show_model(message, model_id):
    data = await site.model(model_id)
    model = data["model"]
    sent = await send_album(message, data["images"], caption=model_caption(model))
    text = "Buyurtma berish uchun tugmani bosing:" if sent else model_caption(model)
    rows = [
        [button("📦 Buyurtma berish", f"o:{model['id']}")],
        [button("📞 Bog'lanish", "contact"), button("⬅️ Orqaga", f"p:{model['product_id']}")],
    ]
    await message.reply_text(text, reply_markup=InlineKeyboardMarkup(rows))


# ---- Buyurtma ----

def phone_keyboard():
    return ReplyKeyboardMarkup(
        [[KeyboardButton("📱 Raqamni yuborish", request_contact=True)]],
        resize_keyboard=True,
        one_time_keyboard=True,
    )


def valid_phone(text):
    digits = re.sub(r"\D", "", str(text or ""))
    return 9 <= len(digits) <= 15


async def start_order(query, context, model_id):
    try:
        data = await site.model(model_id)
    except SiteError as error:
        await query.message.reply_text(error.message)
        return
    context.user_data["order"] = {
        "model_id": data["model"]["id"],
        "model_name": data["model"]["name"],
        "submission_id": str(uuid.uuid4()),
    }
    context.user_data["order_step"] = "name"
    await query.message.reply_text(
        f"📦 {data['model']['name']} uchun buyurtma.\n\n1/3. Ismingizni yozing:"
    )


async def submit_order(update, context):
    order = context.user_data["order"]
    user = update.effective_user
    try:
        await site.order(
            name=order["customer_name"],
            phone=order["phone"],
            message=order.get("note", ""),
            model_id=order["model_id"],
            telegram=f"@{user.username}" if getattr(user, "username", None) else f"ID {user.id}",
            submission_id=order["submission_id"],
        )
    except SiteError as error:
        # Holat saqlanadi: mijoz izohni qayta yuborsa, o'sha buyurtma qayta jo'natiladi.
        await update.message.reply_text(
            error.message + "\n\nQayta yuborish uchun izohni yana yozing yoki quyidagi raqamga qo'ng'iroq qiling.\n\n"
            + CONTACT_TEXT
        )
        return
    context.user_data.pop("order", None)
    context.user_data.pop("order_step", None)
    await update.message.reply_text(
        "✅ Buyurtmangiz qabul qilindi!\n\nTez orada siz bilan bog'lanamiz.",
        reply_markup=ReplyKeyboardRemove(),
    )
    await show_home(update.message)


async def handle_order_text(update, context):
    order = context.user_data.get("order")
    step = context.user_data.get("order_step")
    if not order or not step:
        return False
    if not is_private_chat(update):
        await update.message.reply_text(PRIVATE_ORDER_TEXT)
        return True

    text = (update.message.text or "").strip()

    if step == "name":
        if not text or len(text) > 100:
            await update.message.reply_text("Ismingizni yozing (100 belgigacha):")
            return True
        order["customer_name"] = text
        context.user_data["order_step"] = "phone"
        await update.message.reply_text(
            "2/3. Telefon raqamingizni yuboring: pastdagi «📱 Raqamni yuborish» tugmasini bosing yoki raqamni yozing.",
            reply_markup=phone_keyboard(),
        )
        return True

    if step == "phone":
        if not valid_phone(text):
            await update.message.reply_text("Raqam noto'g'ri. Masalan: +998901234567", reply_markup=phone_keyboard())
            return True
        order["phone"] = text
        await ask_note(update, context)
        return True

    if step == "note":
        order["note"] = "" if text == SKIP_TEXT else text[:1500]
        await submit_order(update, context)
        return True

    return False


async def ask_note(update, context):
    context.user_data["order_step"] = "note"
    await update.message.reply_text(
        "3/3. Izoh yozing: manzil, o'lcham, soni yoki savolingiz. Kerak bo'lmasa «O'tkazib yuborish» ni bosing.",
        reply_markup=ReplyKeyboardMarkup([[SKIP_TEXT]], resize_keyboard=True, one_time_keyboard=True),
    )


async def contact_router(update, context):
    order = context.user_data.get("order")
    if not order or context.user_data.get("order_step") != "phone" or not is_private_chat(update):
        return
    order["phone"] = update.message.contact.phone_number
    await ask_note(update, context)


# ---- Admin qismi ----

def admin_state(context):
    return context.user_data.setdefault("admin", {})


def admin_menu():
    return InlineKeyboardMarkup([
        [button("➕ Model qo'shish", "a:add")],
        [button("📋 Modellar", "a:list")],
        [button("📦 Oxirgi buyurtmalar", "a:leads")],
    ])


async def admin_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update) or not is_private_chat(update):
        await update.message.reply_text(ADMIN_ONLY_TEXT)
        return
    context.user_data.clear()
    await update.message.reply_text("⚙️ BekCraft boshqaruvi\n\nBu yerdagi o'zgarish darhol saytda ham chiqadi.",
                                    reply_markup=admin_menu())


async def admin_categories(message, prefix, title):
    catalog = await get_catalog(fresh=True)
    rows = [[button(c["name"], f"{prefix}:{c['id']}")] for c in catalog if c.get("id")]
    rows.append([button("⬅️ Menyu", "a:menu")])
    await message.reply_text(title, reply_markup=InlineKeyboardMarkup(rows))


async def admin_products(message, category_id, prefix, back):
    catalog = await get_catalog(fresh=True)
    category = find_category(catalog, category_id)
    products = (category or {}).get("products", [])
    if not products:
        await message.reply_text(
            "Bu bo'limda tur yo'q. Yangi turni hozircha sayt admin panelidan qo'shing.",
            reply_markup=InlineKeyboardMarkup([[button("⬅️ Orqaga", back)]]),
        )
        return
    rows = [[button(f"{p['name']} ({p['model_count']})", f"{prefix}:{p['id']}")] for p in products]
    rows.append([button("⬅️ Orqaga", back)])
    await message.reply_text(f"{category['name']}\n\nTurni tanlang:", reply_markup=InlineKeyboardMarkup(rows))


async def admin_models(message, product_id):
    data = await site.models(product_id)
    catalog = await get_catalog()
    category_id = category_id_by_name(catalog, data["product"]["category"])
    rows = [[button(short(f"{m['name']} — {m['price_label']}", 60), f"am:{m['id']}")] for m in data["models"]]
    rows.append([button("➕ Shu turga model qo'shish", f"np:{product_id}")])
    rows.append([button("⬅️ Orqaga", f"ac:{category_id}" if category_id else "a:list")])
    text = f"{data['product']['name']}\n\n" + ("Modelni tanlang:" if data["models"] else "Hozircha model yo'q.")
    await message.reply_text(text, reply_markup=InlineKeyboardMarkup(rows))


async def admin_card(message, model_id):
    data = await site.model(model_id)
    model = data["model"]
    text = (
        f"📌 {model['name']}\n"
        f"💰 {model['price_label']}\n"
        f"🖼 Rasmlar: {len(data['images'])} ta\n\n"
        f"{model['description'] or '(tavsif yo‘q)'}"
    )
    rows = [
        [button("✏️ Nom", f"ae:{model['id']}:name"), button("✏️ Tavsif", f"ae:{model['id']}:description")],
        [button("💰 Narx", f"ae:{model['id']}:price_som"), button("🖼 Rasmlar", f"ai:{model['id']}")],
        [button("🗑 Modelni o'chirish", f"md:{model['id']}")],
        [button("⬅️ Orqaga", f"ap:{model['product_id']}")],
    ]
    await message.reply_text(short(text, 4000), reply_markup=InlineKeyboardMarkup(rows))


def images_keyboard(model_id, images):
    rows = []
    for index, image in enumerate(images):
        n = index + 1
        rows.append([
            button(f"{n} ⬆️", f"iu:{model_id}:{image['id']}"),
            button(f"{n} ⬇️", f"iw:{model_id}:{image['id']}"),
            button(f"{n} 🗑", f"ix:{model_id}:{image['id']}"),
        ])
    rows.append([button("👁 Rasmlarni ko'rish", f"iv:{model_id}"), button("➕ Rasm qo'shish", f"ia:{model_id}")])
    rows.append([button("⬅️ Modelga qaytish", f"am:{model_id}")])
    return InlineKeyboardMarkup(rows)


async def admin_images(message, model_id, show_album=True, note=""):
    data = await site.model(model_id)
    images = data["images"]
    if show_album:
        await send_album(message, images, numbered=True)
    text = (note + "\n\n" if note else "") + (
        f"🖼 {data['model']['name']} — {len(images)} ta rasm.\n"
        "1-rasm — asosiy, saytda birinchi chiqadi. ⬆️⬇️ — tartib, 🗑 — o'chirish."
    )
    await message.reply_text(text, reply_markup=images_keyboard(model_id, images))


async def admin_leads(message, update):
    leads = await site.leads(actor_of(update), limit=10)
    if not leads:
        await message.reply_text("Hozircha buyurtma yo'q.", reply_markup=admin_menu())
        return
    parts = []
    for lead in leads:
        item = lead.get("model_name") or lead.get("product_name") or "Umumiy murojaat"
        when = str(lead.get("created_at", ""))[:16].replace("T", " ")
        parts.append(
            f"🕒 {when} (UTC)\n📌 {item}\n👤 {lead['name']}\n📞 {lead['phone']}\n💬 {short(lead.get('message', ''), 300)}"
        )
    await message.reply_text(short("📦 Oxirgi buyurtmalar:\n\n" + "\n\n".join(parts), 4000), reply_markup=admin_menu())


def start_new_model(context, product_id, product_name):
    state = admin_state(context)
    state.clear()
    state.update(step="new_name", new={"product_id": product_id, "product_name": product_name, "photos": []})


EDIT_PROMPTS = {
    "name": "Yangi nomni yozing:",
    "description": "Yangi tavsifni yozing (o'chirish uchun «-» yozing):",
    "price_som": "Yangi narxni so'mda yozing, masalan 2500000 (narxni olib tashlash uchun «-» yozing):",
}


def clean_price(text):
    text = text.strip()
    if text == "-":
        return True, ""
    compact = re.sub(r"[\s.,]", "", text)
    if compact.isdigit() and len(compact) <= 12:
        return True, compact
    return False, ""


async def handle_admin_text(update, context):
    if not is_admin(update) or not is_private_chat(update):
        return False
    state = context.user_data.get("admin") or {}
    step = state.get("step")
    if not step:
        return False
    text = (update.message.text or "").strip()
    message = update.message

    if step == "new_name":
        if not text or len(text) > 120:
            await message.reply_text("Nom 1–120 belgi bo'lsin. Qayta yozing:")
            return True
        state["new"]["name"] = text
        state["step"] = "new_desc"
        await message.reply_text("2/4. Tavsifni yozing (kerak bo'lmasa «-»):")
        return True

    if step == "new_desc":
        if len(text) > 500:
            await message.reply_text("Tavsif 500 belgidan oshmasin. Qisqaroq yozing:")
            return True
        state["new"]["description"] = "" if text == "-" else text
        state["step"] = "new_price"
        await message.reply_text("3/4. Narxni so'mda yozing, masalan 2500000 (narx ko'rsatilmasin desangiz «-»):")
        return True

    if step == "new_price":
        ok, price = clean_price(text)
        if not ok:
            await message.reply_text("Narx faqat raqam bo'lsin, masalan 2500000. Yoki «-»:")
            return True
        state["new"]["price"] = price
        state["step"] = "new_photos"
        await message.reply_text(
            f"4/4. Rasmlarni yuboring (1–{MAX_PHOTOS} ta). Sifat yaxshi bo'lishi uchun «Файл» sifatida yuborsangiz ham bo'ladi.\n"
            "Tugatgach «✅ Rasmlar tayyor» ni bosing.",
            reply_markup=InlineKeyboardMarkup([[button("✅ Rasmlar tayyor", "nd")], [button("❌ Bekor qilish", "nx")]]),
        )
        return True

    if step in ("new_photos", "add_photos"):
        await message.reply_text("Rasm yuboring yoki «✅ Rasmlar tayyor» ni bosing.",
                                 reply_markup=InlineKeyboardMarkup([[button("✅ Rasmlar tayyor", "nd")],
                                                                    [button("❌ Bekor qilish", "nx")]]))
        return True

    if step == "edit":
        field = state["field"]
        model_id = state["model_id"]
        if field == "price_som":
            ok, value = clean_price(text)
            if not ok:
                await message.reply_text("Narx faqat raqam bo'lsin, masalan 2500000. Yoki «-»:")
                return True
        elif field == "description":
            value = "" if text == "-" else text
        else:
            value = text
        try:
            await site.update_model(actor_of(update), model_id, **{field: value})
        except SiteError as error:
            await message.reply_text(error.message + "\nQayta yozing:")
            return True
        state.clear()
        forget_catalog()
        await message.reply_text("✅ Saqlandi. Saytda ham yangilandi.")
        await admin_card(message, model_id)
        return True

    return False


def photo_file_id(message):
    if message.photo:
        return message.photo[-1].file_id
    document = message.document
    if document and str(document.mime_type or "").lower() in ("image/jpeg", "image/png", "image/webp"):
        return document.file_id
    return None


async def photo_router(update, context):
    if not is_admin(update) or not is_private_chat(update):
        return
    state = context.user_data.get("admin") or {}
    if state.get("step") not in ("new_photos", "add_photos"):
        return
    file_id = photo_file_id(update.message)
    if not file_id:
        await update.message.reply_text("Faqat JPG, PNG yoki WEBP rasm qabul qilinadi.")
        return
    photos = state.setdefault("photos", [])
    limit = state.get("limit", MAX_PHOTOS)
    if len(photos) >= limit:
        if state.get("warned") != update.message.media_group_id or not update.message.media_group_id:
            state["warned"] = update.message.media_group_id
            await update.message.reply_text(f"Ko'pi bilan {limit} ta rasm. Ortiqchasi olinmadi.")
        return
    photos.append(file_id)
    group = update.message.media_group_id
    # Albomdagi har rasmga alohida javob yozilmaydi.
    if group and state.get("last_group") == group:
        return
    state["last_group"] = group
    await update.message.reply_text(
        "📥 Rasm qabul qilindi. Yana yuboring yoki «✅ Rasmlar tayyor» ni bosing.",
        reply_markup=InlineKeyboardMarkup([[button("✅ Rasmlar tayyor", "nd")], [button("❌ Bekor qilish", "nx")]]),
    )


async def download_photos(bot, file_ids):
    out = []
    for file_id in file_ids:
        file = await bot.get_file(file_id)
        out.append(bytes(await file.download_as_bytearray()))
    return out


async def photos_done(query, context, update):
    state = context.user_data.get("admin") or {}
    photos = state.get("photos", [])
    if state.get("step") not in ("new_photos", "add_photos"):
        await query.message.reply_text("Bu amal eskirgan. /admin dan qayta boshlang.")
        return
    if not photos:
        await query.message.reply_text("Kamida 1 ta rasm yuboring.")
        return
    if state["step"] == "new_photos":
        new = state["new"]
        state["step"] = "new_confirm"
        price = f"{int(new['price']):,} so'm".replace(",", " ") if new["price"] else "Narx so'rov bo'yicha"
        await query.message.reply_text(
            "Tekshiring:\n\n"
            f"📂 Tur: {new['product_name']}\n"
            f"📌 Nom: {new['name']}\n"
            f"💰 Narx: {price}\n"
            f"📝 Tavsif: {new['description'] or '—'}\n"
            f"🖼 Rasmlar: {len(photos)} ta\n\n"
            "Saqlansa, model darhol saytda ham chiqadi.",
            reply_markup=InlineKeyboardMarkup([[button("✅ Saqlash", "ns"), button("❌ Bekor qilish", "nx")]]),
        )
        return
    model_id = state["model_id"]
    await query.message.reply_text("⏳ Rasmlar saqlanmoqda…")
    try:
        await site.add_images(actor_of(update), model_id, await download_photos(context.bot, photos))
    except SiteError as error:
        await query.message.reply_text(error.message)
        return
    state.clear()
    await admin_images(query.message, model_id, show_album=False, note="✅ Rasmlar qo'shildi.")


async def save_new_model(query, context, update):
    state = context.user_data.get("admin") or {}
    if state.get("step") != "new_confirm":
        await query.message.reply_text("Bu amal eskirgan. /admin dan qayta boshlang.")
        return
    new = state["new"]
    state["step"] = "saving"
    await query.message.reply_text("⏳ Saqlanmoqda… (rasmlar ko'p bo'lsa, bir daqiqagacha)")
    try:
        model_id = await site.create_model(
            actor_of(update),
            new["product_id"],
            name=new["name"],
            description=new["description"],
            price=new["price"],
            photos=await download_photos(context.bot, state.get("photos", [])),
        )
    except SiteError as error:
        state["step"] = "new_confirm"
        await query.message.reply_text(
            error.message,
            reply_markup=InlineKeyboardMarkup([[button("🔁 Qayta urinish", "ns"), button("❌ Bekor qilish", "nx")]]),
        )
        return
    state.clear()
    forget_catalog()
    await query.message.reply_text("✅ Model saqlandi va saytda chiqdi.")
    await admin_card(query.message, model_id)


async def admin_callback(query, context, update, data):
    message = query.message
    kind, _, rest = data.partition(":")
    args = rest.split(":") if rest else []
    state = admin_state(context)
    actor = actor_of(update)

    if data == "a:menu":
        state.clear()
        await message.reply_text("⚙️ BekCraft boshqaruvi", reply_markup=admin_menu())
    elif data == "a:add":
        state.clear()
        await admin_categories(message, "nc", "➕ Yangi model. Bo'limni tanlang:")
    elif data == "a:list":
        state.clear()
        await admin_categories(message, "ac", "📋 Bo'limni tanlang:")
    elif data == "a:leads":
        await admin_leads(message, update)
    elif kind == "nc":
        await admin_products(message, parse_int(args[0]), "np", "a:add")
    elif kind == "np":
        data_models = await site.models(parse_int(args[0]))
        start_new_model(context, data_models["product"]["id"], data_models["product"]["name"])
        await message.reply_text(f"➕ {data_models['product']['name']} — yangi model.\n\n1/4. Model nomini yozing:")
    elif kind == "nd":
        await photos_done(query, context, update)
    elif kind == "ns":
        await save_new_model(query, context, update)
    elif kind == "nx":
        state.clear()
        await message.reply_text("Bekor qilindi.", reply_markup=admin_menu())
    elif kind == "ac":
        await admin_products(message, parse_int(args[0]), "ap", "a:list")
    elif kind == "ap":
        state.clear()
        await admin_models(message, parse_int(args[0]))
    elif kind == "am":
        state.clear()
        await admin_card(message, parse_int(args[0]))
    elif kind == "ae":
        field = args[1] if len(args) > 1 else ""
        if field not in EDIT_PROMPTS:
            return
        state.clear()
        state.update(step="edit", model_id=parse_int(args[0]), field=field)
        await message.reply_text(EDIT_PROMPTS[field])
    elif kind == "ai":
        await admin_images(message, parse_int(args[0]))
    elif kind == "iv":
        await admin_images(message, parse_int(args[0]))
    elif kind in ("iu", "iw"):
        model_id, image_id = parse_int(args[0]), parse_int(args[1])
        direction = "up" if kind == "iu" else "down"
        try:
            await site.move_image(actor, model_id, image_id, direction)
            note = "✅ Tartib o'zgardi. Ko'rish uchun «👁 Rasmlarni ko'rish»."
        except SiteError as error:
            note = error.message
        await admin_images(message, model_id, show_album=False, note=note)
    elif kind == "ix":
        model_id, image_id = parse_int(args[0]), parse_int(args[1])
        await message.reply_text(
            "Shu rasm o'chirilsinmi? Saytdan ham o'chadi.",
            reply_markup=InlineKeyboardMarkup([[button("✅ Ha, o'chirish", f"iy:{model_id}:{image_id}"),
                                                button("❌ Yo'q", f"ai:{model_id}")]]),
        )
    elif kind == "iy":
        model_id, image_id = parse_int(args[0]), parse_int(args[1])
        try:
            await site.delete_image(actor, model_id, image_id)
            note = "✅ Rasm o'chirildi."
        except SiteError as error:
            note = error.message
        await admin_images(message, model_id, show_album=False, note=note)
    elif kind == "ia":
        model_id = parse_int(args[0])
        data_model = await site.model(model_id)
        free = MAX_PHOTOS - len(data_model["images"])
        if free <= 0:
            await message.reply_text(f"Modelda allaqachon {MAX_PHOTOS} ta rasm bor. Avval birini o'chiring.")
            return
        state.clear()
        state.update(step="add_photos", model_id=model_id, photos=[], limit=free)
        await message.reply_text(
            f"Rasmlarni yuboring ({free} tagacha). Tugatgach «✅ Rasmlar tayyor» ni bosing.",
            reply_markup=InlineKeyboardMarkup([[button("✅ Rasmlar tayyor", "nd")], [button("❌ Bekor qilish", "nx")]]),
        )
    elif kind == "md":
        model_id = parse_int(args[0])
        data_model = await site.model(model_id)
        await message.reply_text(
            f"«{data_model['model']['name']}» modeli barcha rasmlari bilan o'chirilsinmi?\n"
            "Saytdan ham o'chadi, qaytarib bo'lmaydi.",
            reply_markup=InlineKeyboardMarkup([
                [button("✅ Ha, o'chirish", f"my:{model_id}:{data_model['model']['product_id']}"),
                 button("❌ Yo'q", f"am:{model_id}")],
            ]),
        )
    elif kind == "my":
        model_id, product_id = parse_int(args[0]), parse_int(args[1] if len(args) > 1 else 0)
        try:
            await site.delete_model(actor, model_id)
        except SiteError as error:
            await message.reply_text(error.message)
            return
        forget_catalog()
        await message.reply_text("✅ Model o'chirildi.")
        if product_id:
            await admin_models(message, product_id)
        else:
            await message.reply_text("⚙️ BekCraft boshqaruvi", reply_markup=admin_menu())


ADMIN_KINDS = {"a", "nc", "np", "nd", "ns", "nx", "ac", "ap", "am", "ae", "ai", "iv",
               "iu", "iw", "ix", "iy", "ia", "md", "my"}


async def callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data or ""
    kind, _, rest = data.partition(":")

    try:
        if kind in ADMIN_KINDS:
            if not is_admin(update) or not is_private_chat(update):
                await query.message.reply_text(ADMIN_ONLY_TEXT)
                return
            await admin_callback(query, context, update, data)
            return
        if kind == "o":
            if not is_private_chat(update):
                await query.message.reply_text(PRIVATE_ORDER_TEXT)
                return
            await start_order(query, context, parse_int(rest))
        elif kind == "c":
            await show_category(query.message, parse_int(rest))
        elif kind == "p":
            await show_models(query.message, parse_int(rest))
        elif kind == "m":
            await show_model(query.message, parse_int(rest))
        elif data == "contact":
            await query.message.reply_text(CONTACT_TEXT)
        else:
            # "home" va eski menyulardagi tugmalar.
            await show_home(query.message)
    except SiteError as error:
        await query.message.reply_text(error.message)


async def text_router(update, context):
    if await handle_admin_text(update, context):
        return
    if await handle_order_text(update, context):
        return


bot = Application.builder().token(BOT_TOKEN).build()

bot.add_handler(CommandHandler("start", start))
bot.add_handler(CommandHandler("admin", admin_command))
bot.add_handler(CallbackQueryHandler(callback))
bot.add_handler(MessageHandler(filters.CONTACT, contact_router))
bot.add_handler(MessageHandler(filters.PHOTO | filters.Document.IMAGE, photo_router))
bot.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_router))


app = FastAPI()


@app.get("/", response_class=PlainTextResponse)
async def health():
    return "BekCraft bot is running"


@app.post("/telegram/webhook")
async def webhook(
    request: Request,
    x_telegram_bot_api_secret_token: str | None = Header(default=None),
):
    if not webhook_secret_matches(x_telegram_bot_api_secret_token):
        return PlainTextResponse("Forbidden", status_code=403)
    data = await request.json()
    update = Update.de_json(data, bot.bot)
    await bot.process_update(update)
    return {"ok": True}


@app.on_event("startup")
async def startup():
    if not BOT_API_KEY:
        log.warning("BOT_API_KEY berilmagan: sayt bot so'rovlarini rad etadi.")
    if not ADMIN_IDS:
        log.warning("ADMIN_IDS berilmagan: /admin hech kimga ochilmaydi.")
    await bot.initialize()

    if WEBHOOK_URL:
        await bot.bot.set_webhook(
            f"{WEBHOOK_URL}/telegram/webhook",
            secret_token=WEBHOOK_SECRET,
        )

    await bot.start()
    log.info("BekCraft bot started")


@app.on_event("shutdown")
async def shutdown():
    await bot.stop()
    await bot.shutdown()


if __name__ == "__main__":
    uvicorn.run("app:app", host="0.0.0.0", port=PORT)
