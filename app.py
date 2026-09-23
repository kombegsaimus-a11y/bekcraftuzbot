import os, json, logging, asyncio
from pathlib import Path
from fastapi import FastAPI, Request
from fastapi.responses import PlainTextResponse
import uvicorn
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, ContextTypes, filters

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("bekcraft")

BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
ADMIN_ID = int(os.environ["ADMIN_ID"])
WEBHOOK_URL = os.environ.get("WEBHOOK_URL", "").rstrip("/")
PORT = int(os.environ.get("PORT", "10000"))

ROOT = Path(__file__).parent
DB_FILE = ROOT / "products.json"

def load_products():
    if not DB_FILE.exists():
        DB_FILE.write_text("[]", encoding="utf-8")
    return json.loads(DB_FILE.read_text(encoding="utf-8"))

def save_products(items):
    DB_FILE.write_text(json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8")

def is_admin(update):
    return update.effective_user and update.effective_user.id == ADMIN_ID

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
    ])

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Assalomu alaykum! 👋\n\nBekCraft rasmli katalogiga xush kelibsiz.\n"
        "Narxlar botda ko'rsatilmaydi. Narx va boshqa ma'lumotlarni menejerlar telefon orqali beradi.",
        reply_markup=public_menu()
    )

async def admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update):
        await update.message.reply_text("Bu bo'lim faqat administrator uchun.")
        return
    context.user_data.clear()
    await update.message.reply_text("🔐 BekCraft boshqaruv paneli", reply_markup=admin_menu())

async def admin_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    if not is_admin(update):
        return

    action = q.data
    products = load_products()

    if action == "admin:add":
        context.user_data["state"] = "add_name"
        await q.message.reply_text("1/4. Yangi mahsulot nomini yuboring:")
    elif action == "admin:list":
        if not products:
            await q.message.reply_text("Hozircha mahsulotlar yo'q.")
            return
        text = "📋 Mahsulotlar:\n\n" + "\n".join(
            f"{i+1}. {'🟢' if p.get('active', True) else '⚪'} {p['name']} [{p['category']}]"
            for i,p in enumerate(products)
        )
        await q.message.reply_text(text)
    elif action == "admin:toggle":
        if not products:
            await q.message.reply_text("Hozircha mahsulotlar yo'q.")
            return# BekCraft product contact buttons
        buttons = [[InlineKeyboardButton(
            f"{'🟢' if p.get('active', True) else '⚪'} {p['name']}",
            callback_data=f"toggle:{p['id']}")] for p in products]
        await q.message.reply_text("Qaysi mahsulotni yashirish/ko'rsatish?", reply_markup=InlineKeyboardMarkup(buttons))
    elif action == "admin:delete":
        if not products:
            await q.message.reply_text("Hozircha mahsulotlar yo'q.")
            return
        buttons = [[InlineKeyboardButton(p["name"], callback_data=f"delete:{p['id']}")] for p in products]
        await q.message.reply_text("Qaysi mahsulotni o'chirasiz?", reply_markup=InlineKeyboardMarkup(buttons))

async def public_category(update: Update, context: ContextTypes.DEFAULT_TYPE, category):
    products = [
        p for p in load_products()
        if p.get("category") == category and p.get("active", True)
    ]

    if not products:
        await update.callback_query.message.reply_text(
            "Hozircha bu bo'limda mahsulot yo'q."
        )
        return

    for p in products:
        caption = (
            f"📌 {p['name']}\n\n"
            f"{p.get('description', '')}\n\n"
            "💰 Narx: menejer orqali\n"
            "📞 Batafsil ma'lumot uchun tugmalardan foydalaning."
        )

        buttons = InlineKeyboardMarkup([
            [
                InlineKeyboardButton(
                    "📞 Narxni bilish",
                    callback_data="manager"
                )
            ],
            [
                InlineKeyboardButton(
                    "📦 Buyurtma berish",
                   callback_data="manager"
                )
            ]
        ])

        if p.get("telegram_file_id"):
            await update.callback_query.message.reply_photo(
                p["telegram_file_id"],
                caption=caption,
                reply_markup=buttons
            )
        else:
            await update.callback_query.message.reply_text(
                caption,
                reply_markup=buttons
            )

async def buttons(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    if q.data.startswith("admin:"):
        await admin_button(update, context); return
    if q.data.startswith("cat:"):
        await public_category(update, context, q.data.split(":")[1]); return
    if q.data.startswith("toggle:"):
        products = load_products()
        pid = q.data.split(":")[1]
        for p in products:
            if p["id"] == pid:
                p["active"] = not p.get("active", True)
                save_products(products)
                await q.message.reply_text(f"✅ {p['name']}: {'ko' if p['active'] else 'yashirildi'}.")
                return
    if q.data.startswith("delete:"):
        products = load_products()
        pid = q.data.split(":")[1]
        new = [p for p in products if p["id"] != pid]
        if len(new) != len(products):
            save_products(new)
            await q.message.reply_text("🗑 Mahsulot o'chirildi.")
        return
    if q.data == "manager":
        await q.message.reply_text(
            "📞 Menejerlar:\n+998938374177\n+998933364177"
        )

async def admin_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update):
        await update.message.reply_text(
            "Саволингиз қабул қилинди. Нарх ва бошқа маълумотлар учун менеджерларимизга қўнғироқ қилинг."
        )
        return

    state = context.user_data.get("state")
    if state == "add_name":
        context.user_data["new"] = {"id": str(update.message.message_id) + str(update.effective_user.id), "name": update.message.text}
        context.user_data["state"] = "add_category"
        await update.message.reply_text("2/4. Категорияни танланг:", reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🪑 Боғ мебели", callback_data="newcat:garden")],
            [InlineKeyboardButton("🏋️ Спорт", callback_data="newcat:sport")],
            [InlineKeyboardButton("🚧 Панжара/перила", callback_data="newcat:fences")]
        ]))
    elif state == "add_description":
        context.user_data["new"]["description"] = update.message.text
        context.user_data["state"] = "add_photo"
        await update.message.reply_text("4/4. Маҳсулот расмини юборинг.")
    else:
        await update.message.reply_text("Админ менюси:", reply_markup=admin_menu())

async def new_category(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    if not is_admin(update): return
    context.user_data["new"]["category"] = q.data.split(":")[1]
    context.user_data["state"] = "add_description"
    await q.message.reply_text("3/4. Маҳсулот ҳақида қисқача маълумот юборинг.")

async def admin_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update) or context.user_data.get("state") != "add_photo":
        return
    photo = update.message.photo[-1]
    context.user_data["new"]["telegram_file_id"] = photo.file_id
    context.user_data["new"]["active"] = True
    products = load_products()
    products.append(context.user_data["new"])
    save_products(products)
    context.user_data.clear()
    await update.message.reply_text("✅ Маҳсулот каталогга қўшилди!", reply_markup=admin_menu())

async def myid(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(f"Telegram ID: {update.effective_chat.id}")

bot = Application.builder().token(BOT_TOKEN).build()
bot.add_handler(CommandHandler("start", start))
bot.add_handler(CommandHandler("admin", admin))
bot.add_handler(CommandHandler("myid", myid))
bot.add_handler(CallbackQueryHandler(new_category, pattern=r"^newcat:"))
bot.add_handler(CallbackQueryHandler(buttons))
bot.add_handler(MessageHandler(filters.PHOTO, admin_photo))
bot.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, admin_text))

app = FastAPI()

@app.get("/", response_class=PlainTextResponse)
async def health():
    return "BekCraft admin catalog bot is running"

@app.post("/telegram/webhook")
async def webhook(request: Request):
    data = await request.json()
    await bot.process_update(Update.de_json(data, bot.bot))
    return {"ok": True}
@app.on_event("startup")
async def startup():
    await bot.initialize()
    await bot.bot.delete_webhook(drop_pending_updates=False)
    await bot.start()
    await bot.updater.start_polling()


@app.on_event("shutdown")
async def shutdown():
    await bot.updater.stop()
    await bot.stop()
    await bot.shutdown()


if __name__ == "__main__":
    uvicorn.run("app:app", host="0.0.0.0", port=PORT)
