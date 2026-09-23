import os
import json
import logging
from pathlib import Path

import psycopg
from fastapi import FastAPI, Request
from fastapi.responses import PlainTextResponse
import uvicorn

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters,
)

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("bekcraft")

BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
ADMIN_ID = int(os.environ["ADMIN_ID"])
ADMIN_IDS = {
    int(x.strip())
    for x in os.environ.get("ADMIN_IDS", str(ADMIN_ID)).split(",")
    if x.strip()
}
DATABASE_URL = os.environ["DATABASE_URL"]
WEBHOOK_URL = os.environ.get("WEBHOOK_URL", "").rstrip("/")
PORT = int(os.environ.get("PORT", "10000"))

ROOT = Path(__file__).parent
LEGACY_JSON = ROOT / "products.json"

CATEGORY_NAMES = {
    "garden": "🪑 Bog' mebellari",
    "sport": "🏋️ Sport anjomlari",
    "fences": "🚧 Panjara va perila",
}


async def db_query(query, params=None, fetch=False, fetchone=False):
    async with await psycopg.AsyncConnection.connect(DATABASE_URL) as conn:
        async with conn.cursor() as cur:
            await cur.execute(query, params or ())
            if fetchone:
                return await cur.fetchone()
            if fetch:
                return await cur.fetchall()
            return None


async def init_db():
    async with await psycopg.AsyncConnection.connect(DATABASE_URL) as conn:
        async with conn.cursor() as cur:
            await cur.execute("""
                CREATE TABLE IF NOT EXISTS products (
                    id BIGSERIAL PRIMARY KEY,
                    name TEXT NOT NULL,
                    category TEXT NOT NULL,
                    description TEXT NOT NULL DEFAULT '',
                    telegram_file_id TEXT,
                    active BOOLEAN NOT NULL DEFAULT TRUE,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                )
            """)
            await cur.execute("""
                CREATE TABLE IF NOT EXISTS orders (
                    id BIGSERIAL PRIMARY KEY,
                    product_id BIGINT REFERENCES products(id) ON DELETE SET NULL,
                    product_name TEXT NOT NULL,
                    customer_name TEXT NOT NULL,
                    phone TEXT NOT NULL,
                    address TEXT NOT NULL,
                    quantity INTEGER NOT NULL DEFAULT 1 CHECK (quantity > 0),
                    status TEXT NOT NULL DEFAULT 'new',
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                )
            """)
        await conn.commit()
    await migrate_legacy_products()


async def migrate_legacy_products():
    if not LEGACY_JSON.exists():
        return
    try:
        items = json.loads(LEGACY_JSON.read_text(encoding="utf-8"))
    except Exception:
        return
    if not items:
        return
    row = await db_query("SELECT COUNT(*) FROM products", fetchone=True)
    if row and row[0] > 0:
        return

    async with await psycopg.AsyncConnection.connect(DATABASE_URL) as conn:
        async with conn.cursor() as cur:
            for item in items:
                await cur.execute(
                    """
                    INSERT INTO products
                    (name, category, description, telegram_file_id, active)
                    VALUES (%s, %s, %s, %s, %s)
                    """,
                    (
                        item.get("name", "Без названия"),
                        item.get("category", "garden"),
                        item.get("description", ""),
                        item.get("telegram_file_id"),
                        item.get("active", True),
                    ),
                )
        await conn.commit()


async def get_product(product_id):
    row = await db_query(
        """
        SELECT id, name, category, description, telegram_file_id, active
        FROM products WHERE id = %s
        """,
        (product_id,),
        fetchone=True,
    )
    if not row:
        return None
    return {
        "id": row[0],
        "name": row[1],
        "category": row[2],
        "description": row[3],
        "telegram_file_id": row[4],
        "active": row[5],
    }


async def get_products(category=None, active_only=True):
    query = """
        SELECT id, name, category, description, telegram_file_id, active
        FROM products
    """
    params = []
    conditions = []

    if category:
        conditions.append("category = %s")
        params.append(category)
    if active_only:
        conditions.append("active = TRUE")
    if conditions:
        query += " WHERE " + " AND ".join(conditions)
    query += " ORDER BY id DESC"

    rows = await db_query(query, params, fetch=True)
    return [
        {
            "id": row[0],
            "name": row[1],
            "category": row[2],
            "description": row[3],
            "telegram_file_id": row[4],
            "active": row[5],
        }
        for row in rows
    ]


def is_admin(update):
    return bool(
        update.effective_user
        and update.effective_user.id in ADMIN_IDS
    )


def public_menu():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🪑 Bog' mebellari", callback_data="cat:garden")],
        [InlineKeyboardButton("🏋️ Sport anjomlari", callback_data="cat:sport")],
        [InlineKeyboardButton("🚧 Panjara va perila", callback_data="cat:fences")],
        [InlineKeyboardButton("📞 Menejer bilan bog'lanish", callback_data="manager")],
    ])


def admin_menu():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("➕ Mahsulot qo'shish", callback_data="admin:add")],
        [InlineKeyboardButton("📋 Mahsulotlar", callback_data="admin:list")],
        [InlineKeyboardButton("👁 Ko'rsatish/yashirish", callback_data="admin:toggle")],
        [InlineKeyboardButton("🗑 O'chirish", callback_data="admin:delete")],
        [InlineKeyboardButton("📦 Buyurtmalar", callback_data="admin:orders")],
    ])


def category_menu():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🪑 Bog' mebellari", callback_data="addcat:garden")],
        [InlineKeyboardButton("🏋️ Sport anjomlari", callback_data="addcat:sport")],
        [InlineKeyboardButton("🚧 Panjara va perila", callback_data="addcat:fences")],
    ])


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    await update.message.reply_text(
        "Assalomu alaykum! 👋\n\n"
        "BekCraft rasmli katalogiga xush kelibsiz.\n\n"
        "Narxlar botda ko'rsatilmaydi. "
        "Narx va boshqa ma'lumotlarni menejerlar telefon orqali beradi.",
        reply_markup=public_menu(),
    )


async def admin_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update):
        await update.message.reply_text("Bu bo'lim faqat administrator uchun.")
        return
    context.user_data.clear()
    await update.message.reply_text(
        "⚙️ BekCraft boshqaruv paneli",
        reply_markup=admin_menu(),
    )


async def show_category(query, category):
    products = await get_products(category=category, active_only=True)
    if not products:
        await query.message.reply_text(
            f"{CATEGORY_NAMES[category]}\n\nHozircha mahsulotlar mavjud emas.",
            reply_markup=public_menu(),
        )
        return

    await query.message.reply_text(CATEGORY_NAMES[category])

    for product in products:
        text = (
            f"📌 {product['name']}\n\n"
            f"{product['description']}\n\n"
            "💰 Narx: menejer orqali"
        )
        buttons = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("📞 Narxni bilish", callback_data="manager"),
                InlineKeyboardButton(
                    "📦 Buyurtma berish",
                    callback_data=f"order:{product['id']}",
                ),
            ]
        ])

        if product["telegram_file_id"]:
            await query.message.reply_photo(
                photo=product["telegram_file_id"],
                caption=text,
                reply_markup=buttons,
            )
        else:
            await query.message.reply_text(text, reply_markup=buttons)


async def send_manager(query):
    await query.message.reply_text(
        "📞 Menejer bilan bog'lanish:\n\n"
      "+998938374177\n\n"
"+998933364177"
    )


async def start_order(query, context, product_id):
    product = await get_product(product_id)
    if not product or not product["active"]:
        await query.message.reply_text("Kechirasiz, bu mahsulot hozir mavjud emas.")
        return

    context.user_data["order"] = {
        "product_id": product["id"],
        "product_name": product["name"],
    }
    context.user_data["order_step"] = "name"

    await query.message.reply_text(
        f"📦 {product['name']} uchun buyurtma.\n\n"
        "1/4. Ismingizni yozing:"
    )


async def handle_order_text(update, context):
    order = context.user_data.get("order")
    step = context.user_data.get("order_step")
    if not order or not step:
        return False

    text = update.message.text.strip()

    if step == "name":
        order["customer_name"] = text
        context.user_data["order_step"] = "phone"
        await update.message.reply_text("2/4. Telefon raqamingizni yozing:")
        return True

    if step == "phone":
        order["phone"] = text
        context.user_data["order_step"] = "address"
        await update.message.reply_text("3/4. Yetkazib berish manzilingizni yozing:")
        return True

    if step == "address":
        order["address"] = text
        context.user_data["order_step"] = "quantity"
        await update.message.reply_text("4/4. Nechta dona kerak? Masalan: 2")
        return True

    if step == "quantity":
        try:
            quantity = int(text)
            if quantity < 1 or quantity > 1000:
                raise ValueError
        except ValueError:
            await update.message.reply_text(
                "Iltimos, 1 dan 1000 gacha bo'lgan butun son yozing."
            )
            return True

        order["quantity"] = quantity

        await db_query(
            """
            INSERT INTO orders
            (product_id, product_name, customer_name, phone, address, quantity)
            VALUES (%s, %s, %s, %s, %s, %s)
            """,
            (
                order["product_id"],
                order["product_name"],
                order["customer_name"],
                order["phone"],
                order["address"],
                order["quantity"],
            ),
        )

        customer = update.effective_user
        username = f"@{customer.username}" if customer.username else "yo'q"

        admin_text = (
            "🔔 YANGI BUYURTMA\n\n"
            f"📌 Mahsulot: {order['product_name']}\n"
            f"🔢 Miqdor: {order['quantity']} dona\n"
            f"👤 Mijoz: {order['customer_name']}\n"
            f"📞 Telefon: {order['phone']}\n"
            f"📍 Manzil: {order['address']}\n"
            f"💬 Telegram: {username}\n"
            f"🆔 Telegram ID: {customer.id}"
        )

        for admin_id in ADMIN_IDS:
            try:
                await context.bot.send_message(chat_id=admin_id, text=admin_text)
            except Exception:
                log.exception("Admin notification failed")

        context.user_data.pop("order", None)
        context.user_data.pop("order_step", None)

        await update.message.reply_text(
            "✅ Buyurtmangiz qabul qilindi!\n\n"
            "Menejerimiz tez orada siz bilan bog'lanadi.",
            reply_markup=public_menu(),
        )
        return True

    return False


async def handle_admin_text(update, context):
    if not is_admin(update):
        return False

    step = context.user_data.get("admin_step")
    if not step:
        return False

    text = update.message.text.strip()

    if step == "name":
        context.user_data["new_product"] = {"name": text}
        context.user_data["admin_step"] = "category"
        await update.message.reply_text(
            "2/4. Mahsulot kategoriyasini tanlang:",
            reply_markup=category_menu(),
        )
        return True

    if step == "description":
        context.user_data["new_product"]["description"] = text
        context.user_data["admin_step"] = "photo"
        await update.message.reply_text("4/4. Mahsulot rasmini yuboring:")
        return True

    return False


async def handle_photo(update, context):
    if not is_admin(update):
        return False
    if context.user_data.get("admin_step") != "photo":
        return False

    new_product = context.user_data.get("new_product")
    if not new_product:
        return False

    photo = update.message.photo[-1]
    new_product["telegram_file_id"] = photo.file_id

    await db_query(
        """
        INSERT INTO products
        (name, category, description, telegram_file_id, active)
        VALUES (%s, %s, %s, %s, TRUE)
        """,
        (
            new_product["name"],
            new_product["category"],
            new_product["description"],
            new_product["telegram_file_id"],
        ),
    )

    context.user_data.pop("new_product", None)
    context.user_data.pop("admin_step", None)

    await update.message.reply_text(
        "✅ Mahsulot muvaffaqiyatli qo'shildi.",
        reply_markup=admin_menu(),
    )
    return True


async def callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data

    if data == "manager":
        await send_manager(query)
        return

    if data.startswith("cat:"):
        category = data.split(":", 1)[1]
        await show_category(query, category)
        return

    if data.startswith("order:"):
        product_id = int(data.split(":", 1)[1])
        await start_order(query, context, product_id)
        return

    if not is_admin(update):
        return

    if data == "admin:add":
        context.user_data.clear()
        context.user_data["admin_step"] = "name"
        await query.message.reply_text("1/4. Mahsulot nomini yozing:")
        return

    if data.startswith("addcat:"):
        category = data.split(":", 1)[1]
        if category not in CATEGORY_NAMES:
            return
        context.user_data["new_product"]["category"] = category
        context.user_data["admin_step"] = "description"
        await query.message.reply_text("3/4. Mahsulot tavsifini yozing:")
        return

    if data == "admin:list":
        products = await get_products(active_only=False)
        if not products:
            await query.message.reply_text(
                "📋 Mahsulotlar hali yo'q.",
                reply_markup=admin_menu(),
            )
            return

        lines = ["📋 Barcha mahsulotlar:\n"]
        for p in products:
            status = "🟢" if p["active"] else "🔴"
            lines.append(
                f"{status} ID {p['id']} — {p['name']} "
                f"({CATEGORY_NAMES.get(p['category'], p['category'])})"
            )

        await query.message.reply_text(
            "\n".join(lines),
            reply_markup=admin_menu(),
        )
        return

    if data == "admin:toggle":
        products = await get_products(active_only=False)
        if not products:
            await query.message.reply_text(
                "Mahsulotlar yo'q.",
                reply_markup=admin_menu(),
            )
            return

        buttons = []
        for p in products:
            status = "🟢" if p["active"] else "🔴"
            buttons.append([
                InlineKeyboardButton(
                    f"{status} {p['name']}",
                    callback_data=f"toggle:{p['id']}",
                )
            ])

        buttons.append([
            InlineKeyboardButton("⬅️ Admin menyu", callback_data="admin:back")
        ])

        await query.message.reply_text(
            "Qaysi mahsulot holatini o'zgartiramiz?",
            reply_markup=InlineKeyboardMarkup(buttons),
        )
        return

    if data.startswith("toggle:"):
        product_id = int(data.split(":", 1)[1])
        await db_query(
            "UPDATE products SET active = NOT active WHERE id = %s",
            (product_id,),
        )
        await query.message.reply_text(
            "✅ Mahsulot holati o'zgartirildi.",
            reply_markup=admin_menu(),
        )
        return

    if data == "admin:delete":
        products = await get_products(active_only=False)
        if not products:
            await query.message.reply_text(
                "Mahsulotlar yo'q.",
                reply_markup=admin_menu(),
            )
            return

        buttons = []
        for p in products:
            buttons.append([
                InlineKeyboardButton(
                    f"🗑 {p['name']}",
                    callback_data=f"delete:{p['id']}",
                )
            ])

        buttons.append([
            InlineKeyboardButton("⬅️ Admin menyu", callback_data="admin:back")
        ])

        await query.message.reply_text(
            "Qaysi mahsulotni o'chiramiz?",
            reply_markup=InlineKeyboardMarkup(buttons),
        )
        return

    if data.startswith("delete:"):
        product_id = int(data.split(":", 1)[1])
        await db_query("DELETE FROM products WHERE id = %s", (product_id,))
        await query.message.reply_text(
            "🗑 Mahsulot o'chirildi.",
            reply_markup=admin_menu(),
        )
        return

    if data == "admin:orders":
        rows = await db_query(
            """
            SELECT id, product_name, customer_name, phone, address, quantity, status
            FROM orders
            ORDER BY id DESC
            LIMIT 10
            """,
            fetch=True,
        )

        if not rows:
            await query.message.reply_text(
                "📦 Hali buyurtmalar yo'q.",
                reply_markup=admin_menu(),
            )
            return

        lines = ["📦 Oxirgi 10 ta buyurtma:\n"]
        for row in rows:
            lines.append(
                f"#{row[0]} — {row[1]} — {row[5]} dona\n"
                f"👤 {row[2]}\n"
                f"📞 {row[3]}\n"
                f"📍 {row[4]}\n"
                f"Status: {row[6]}\n"
            )

        await query.message.reply_text(
            "\n".join(lines),
            reply_markup=admin_menu(),
        )
        return

    if data == "admin:back":
        await query.message.reply_text(
            "⚙️ BekCraft boshqaruv paneli",
            reply_markup=admin_menu(),
        )


async def text_router(update, context):
    if await handle_admin_text(update, context):
        return
    if await handle_order_text(update, context):
        return


async def photo_router(update, context):
    await handle_photo(update, context)


bot = Application.builder().token(BOT_TOKEN).build()

bot.add_handler(CommandHandler("start", start))
bot.add_handler(CommandHandler("admin", admin_command))
bot.add_handler(CallbackQueryHandler(callback))
bot.add_handler(MessageHandler(filters.PHOTO, photo_router))
bot.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_router))


app = FastAPI()


@app.get("/", response_class=PlainTextResponse)
async def health():
    return "BekCraft bot is running"


@app.post("/telegram/webhook")
async def webhook(request: Request):
    data = await request.json()
    update = Update.de_json(data, bot.bot)
    await bot.process_update(update)
    return {"ok": True}


@app.on_event("startup")
async def startup():
    await init_db()
    await bot.initialize()

    if WEBHOOK_URL:
        await bot.bot.set_webhook(f"{WEBHOOK_URL}/telegram/webhook")

    await bot.start()
    log.info("BekCraft bot started")


@app.on_event("shutdown")
async def shutdown():
    await bot.stop()
    await bot.shutdown()


if __name__ == "__main__":
    uvicorn.run("app:app", host="0.0.0.0", port=PORT)
