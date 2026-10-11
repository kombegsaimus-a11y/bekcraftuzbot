import os
import subprocess
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import httpx

ROOT = Path(__file__).resolve().parent
FAKE_TOKEN = "123456789:" + ("A" * 35)
FAKE_SECRET = "unit_test_webhook_secret"
FAKE_DATABASE_URL = "postgresql://test:test@127.0.0.1:5432/bekcraft_unit"

os.environ["TELEGRAM_BOT_TOKEN"] = FAKE_TOKEN
os.environ["ADMIN_ID"] = "1"
os.environ["ADMIN_IDS"] = "1"
os.environ["DATABASE_URL"] = FAKE_DATABASE_URL
os.environ["WEBHOOK_SECRET"] = FAKE_SECRET
os.environ.pop("WEBHOOK_URL", None)

import app


def child_env(secret=None, include_secret=True):
    env = {
        "SYSTEMROOT": os.environ.get("SYSTEMROOT", r"C:\Windows"),
        "PATH": os.environ.get("PATH", ""),
        "TEMP": os.environ.get("TEMP", ""),
        "TMP": os.environ.get("TMP", ""),
        "PATHEXT": os.environ.get("PATHEXT", ""),
        "PYTHONUTF8": "1",
        "PYTHONDONTWRITEBYTECODE": "1",
        "TELEGRAM_BOT_TOKEN": FAKE_TOKEN,
        "ADMIN_ID": "1",
        "DATABASE_URL": FAKE_DATABASE_URL,
    }
    if include_secret:
        env["WEBHOOK_SECRET"] = FAKE_SECRET if secret is None else secret
    return env


class Chat:
    def __init__(self, chat_type):
        self.type = chat_type


class User:
    def __init__(self):
        self.id = 50
        self.username = "mijoz"


class Message:
    def __init__(self, text, chat_type):
        self.text = text
        self.chat = Chat(chat_type)
        self.replies = []

    async def reply_text(self, text, reply_markup=None):
        self.replies.append(text)


class Query:
    def __init__(self, data, message):
        self.data = data
        self.message = message

    async def answer(self):
        return None


class Update:
    def __init__(self, chat_type, text="", data=None):
        self.effective_user = User()
        self.effective_chat = Chat(chat_type)
        self.message = Message(text, chat_type)
        self.callback_query = Query(data, self.message) if data is not None else None


class Context:
    def __init__(self):
        self.user_data = {}
        self.sent = []

        class Bot:
            def __init__(self, outer):
                self.outer = outer

            async def send_message(self, chat_id, text):
                self.outer.sent.append((chat_id, text))

        self.bot = Bot(self)


class SecurityTests(unittest.IsolatedAsyncioTestCase):
    def webhook_doubles(self):
        process_update = AsyncMock()
        fake_bot = SimpleNamespace(process_update=process_update, bot=SimpleNamespace())
        return fake_bot, process_update

    async def post_webhook(self, header=None, body=b'{"update_id": 1}'):
        transport = httpx.ASGITransport(app=app.app)
        headers = {}
        if header is not None:
            headers["X-Telegram-Bot-Api-Secret-Token"] = header
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            return await client.post("/telegram/webhook", content=body, headers=headers)

    async def test_valid_webhook_secret_is_accepted(self):
        fake_bot, process_update = self.webhook_doubles()
        with patch.object(app, "bot", fake_bot), patch.object(app, "Update") as update_cls:
            update_cls.de_json.return_value = object()
            response = await self.post_webhook(header=FAKE_SECRET)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"ok": True})
        update_cls.de_json.assert_called_once()
        process_update.assert_awaited_once()

    async def test_missing_webhook_secret_is_rejected(self):
        fake_bot, process_update = self.webhook_doubles()
        with patch.object(app, "bot", fake_bot), patch.object(app, "Update") as update_cls:
            response = await self.post_webhook(header=None, body=b"not-json")
        self.assertEqual(response.status_code, 403)
        update_cls.de_json.assert_not_called()
        process_update.assert_not_awaited()

    async def test_wrong_webhook_secret_is_rejected(self):
        fake_bot, process_update = self.webhook_doubles()
        with patch.object(app, "bot", fake_bot), patch.object(app, "Update") as update_cls:
            response = await self.post_webhook(header=FAKE_SECRET + "x")
        self.assertEqual(response.status_code, 403)
        update_cls.de_json.assert_not_called()
        process_update.assert_not_awaited()

    async def test_startup_sends_secret_token_to_set_webhook(self):
        original = app.WEBHOOK_URL
        app.WEBHOOK_URL = "https://example.test"
        set_webhook = AsyncMock()
        fake_bot = SimpleNamespace(
            initialize=AsyncMock(),
            start=AsyncMock(),
            bot=SimpleNamespace(set_webhook=set_webhook),
        )
        try:
            with patch.object(app, "init_db", new=AsyncMock()), patch.object(app, "bot", fake_bot):
                await app.startup()
            set_webhook.assert_awaited_once_with(
                "https://example.test/telegram/webhook",
                secret_token=FAKE_SECRET,
            )
        finally:
            app.WEBHOOK_URL = original

    def test_missing_secret_refuses_to_import(self):
        completed = subprocess.run(
            [sys.executable, "-c", "import app"],
            cwd=ROOT,
            env=child_env(include_secret=False),
            capture_output=True,
            text=True,
            timeout=60,
        )
        output = completed.stdout + completed.stderr
        self.assertNotEqual(completed.returncode, 0)
        self.assertIn("WEBHOOK_SECRET", output)
        self.assertIn("himoyasiz", output)
        self.assertNotIn(FAKE_TOKEN, output)

    def test_invalid_secret_refuses_to_import_without_leaking_value(self):
        leaked = "LEAK_CHECK bad!"
        completed = subprocess.run(
            [sys.executable, "-c", "import app"],
            cwd=ROOT,
            env=child_env(secret=leaked),
            capture_output=True,
            text=True,
            timeout=60,
        )
        output = completed.stdout + completed.stderr
        self.assertNotEqual(completed.returncode, 0)
        self.assertIn("yaroqsiz", output)
        self.assertIn("himoyasiz", output)
        self.assertNotIn(leaked, output)
        self.assertNotIn(FAKE_TOKEN, output)

    async def test_group_order_button_does_not_start_or_save(self):
        update = Update("group", data="order:7")
        context = Context()
        with patch.object(app, "get_product", new=AsyncMock()) as get_product, patch.object(
            app, "db_query", new=AsyncMock()
        ) as db_query:
            await app.callback(update, context)
        get_product.assert_not_called()
        db_query.assert_not_called()
        self.assertNotIn("order", context.user_data)
        self.assertNotIn("order_step", context.user_data)
        self.assertTrue(any("shaxsiy chat" in text for text in update.message.replies))

    async def test_group_text_does_not_collect_or_save_existing_order(self):
        context = Context()
        context.user_data["order"] = {"product_id": 7, "product_name": "Stol"}
        context.user_data["order_step"] = "quantity"
        update = Update("supergroup", text="2")
        with patch.object(app, "db_query", new=AsyncMock()) as db_query:
            await app.text_router(update, context)
        db_query.assert_not_called()
        self.assertNotIn("quantity", context.user_data["order"])
        self.assertNotIn("customer_name", context.user_data["order"])
        self.assertEqual(context.user_data["order_step"], "quantity")
        self.assertTrue(any("shaxsiy chat" in text for text in update.message.replies))

    async def test_private_order_flow_is_saved(self):
        context = Context()
        product = {
            "id": 3,
            "name": "Stol",
            "category": "garden",
            "description": "",
            "telegram_file_id": None,
            "active": True,
        }
        with patch.object(app, "get_product", new=AsyncMock(return_value=product)), patch.object(
            app, "db_query", new=AsyncMock()
        ) as db_query:
            await app.callback(Update("private", data="order:3"), context)
            self.assertEqual(context.user_data["order_step"], "name")
            self.assertEqual(context.user_data["order"]["product_name"], "Stol")
            db_query.assert_not_called()

            group_update = Update("group", text="Guruhdagi ism")
            await app.text_router(group_update, context)
            self.assertEqual(context.user_data["order_step"], "name")
            self.assertNotIn("customer_name", context.user_data["order"])
            db_query.assert_not_called()

            await app.text_router(Update("private", text="Ali"), context)
            await app.text_router(Update("private", text="+998901112233"), context)
            await app.text_router(Update("private", text="Toshkent"), context)
            done = Update("private", text="2")
            await app.text_router(done, context)

        db_query.assert_awaited_once()
        sql, params = db_query.await_args.args
        self.assertIn("INSERT INTO orders", sql)
        self.assertEqual(params, (3, "Stol", "Ali", "+998901112233", "Toshkent", 2))
        self.assertNotIn("order", context.user_data)
        self.assertNotIn("order_step", context.user_data)
        self.assertTrue(any("qabul qilindi" in text for text in done.message.replies))
        self.assertEqual(len(context.sent), 1)


if __name__ == "__main__":
    unittest.main()
