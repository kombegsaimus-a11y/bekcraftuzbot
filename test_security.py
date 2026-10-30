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

os.environ["TELEGRAM_BOT_TOKEN"] = FAKE_TOKEN
os.environ["ADMIN_ID"] = "1"
os.environ["ADMIN_IDS"] = "1"
os.environ["BOT_API_KEY"] = "unit-test-bot-key-" + ("x" * 20)
os.environ["SITE_URL"] = "https://site.test"
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
            with patch.object(app, "bot", fake_bot):
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
        update = Update("group", data="o:7")
        context = Context()
        with patch.object(app.site, "model", new=AsyncMock()) as model, patch.object(
            app.site, "order", new=AsyncMock()
        ) as order:
            await app.callback(update, context)
        model.assert_not_called()
        order.assert_not_called()
        self.assertNotIn("order", context.user_data)
        self.assertNotIn("order_step", context.user_data)
        self.assertTrue(any("shaxsiy chat" in text for text in update.message.replies))

    async def test_group_text_does_not_collect_or_save_existing_order(self):
        context = Context()
        context.user_data["order"] = {"model_id": 7, "model_name": "Stol", "submission_id": "x"}
        context.user_data["order_step"] = "note"
        update = Update("supergroup", text="Manzil")
        with patch.object(app.site, "order", new=AsyncMock()) as order:
            await app.text_router(update, context)
        order.assert_not_called()
        self.assertNotIn("note", context.user_data["order"])
        self.assertEqual(context.user_data["order_step"], "note")
        self.assertTrue(any("shaxsiy chat" in text for text in update.message.replies))

    async def test_private_order_flow_goes_to_site(self):
        context = Context()
        model = {"model": {"id": 3, "product_id": 1, "name": "Stol", "description": "", "price_label": "1 so‘m"},
                 "images": []}
        with patch.object(app.site, "model", new=AsyncMock(return_value=model)), patch.object(
            app.site, "order", new=AsyncMock(return_value={"ok": True})
        ) as order, patch.object(app, "show_home", new=AsyncMock()):
            await app.callback(Update("private", data="o:3"), context)
            self.assertEqual(context.user_data["order_step"], "name")
            self.assertEqual(context.user_data["order"]["model_name"], "Stol")

            await app.text_router(Update("group", text="Guruhdagi ism"), context)
            self.assertEqual(context.user_data["order_step"], "name")

            await app.text_router(Update("private", text="Ali"), context)
            bad_phone = Update("private", text="12")
            await app.text_router(bad_phone, context)
            self.assertEqual(context.user_data["order_step"], "phone")
            await app.text_router(Update("private", text="+998901112233"), context)
            done = Update("private", text="Jumabozor, 2 dona")
            await app.text_router(done, context)

        order.assert_awaited_once()
        kwargs = order.await_args.kwargs
        self.assertEqual(kwargs["name"], "Ali")
        self.assertEqual(kwargs["phone"], "+998901112233")
        self.assertEqual(kwargs["message"], "Jumabozor, 2 dona")
        self.assertEqual(kwargs["model_id"], 3)
        self.assertEqual(kwargs["telegram"], "@mijoz")
        self.assertTrue(kwargs["submission_id"])
        self.assertNotIn("order", context.user_data)
        self.assertTrue(any("qabul qilindi" in text for text in done.message.replies))

    async def test_failed_order_keeps_state_for_retry(self):
        context = Context()
        context.user_data["order"] = {"model_id": 3, "model_name": "Stol", "submission_id": "same-id",
                                      "customer_name": "Ali", "phone": "+998901112233"}
        context.user_data["order_step"] = "note"
        with patch.object(app.site, "order", new=AsyncMock(side_effect=app.SiteError("Sayt bilan aloqa bo'lmadi."))):
            update = Update("private", text=app.SKIP_TEXT)
            await app.text_router(update, context)
        self.assertEqual(context.user_data["order_step"], "note")
        self.assertEqual(context.user_data["order"]["submission_id"], "same-id")
        self.assertTrue(any("aloqa" in text for text in update.message.replies))

    async def test_admin_buttons_are_refused_for_customers(self):
        update = Update("private", data="my:5:1")
        context = Context()
        with patch.object(app.site, "delete_model", new=AsyncMock()) as delete_model:
            await app.callback(update, context)
        delete_model.assert_not_called()
        self.assertTrue(any("administrator" in text for text in update.message.replies))

    async def test_admin_delete_model_sends_actor(self):
        update = Update("private", data="my:5:0")
        update.effective_user.id = 1  # ADMIN_IDS = 1
        context = Context()
        with patch.object(app.site, "delete_model", new=AsyncMock(return_value={"ok": True})) as delete_model:
            await app.callback(update, context)
        delete_model.assert_awaited_once()
        actor, model_id = delete_model.await_args.args
        self.assertEqual(model_id, 5)
        self.assertIn("(1)", actor)
        self.assertTrue(any("o'chirildi" in text for text in update.message.replies))


class SiteApiTests(unittest.IsolatedAsyncioTestCase):
    async def test_sends_key_and_actor_and_reads_errors(self):
        seen = []

        def handler(request):
            seen.append(request)
            if request.url.path.endswith("/models/9"):
                return httpx.Response(404, json={"ok": False, "error": "model_not_found", "message": "Model topilmadi."})
            return httpx.Response(200, json={"ok": True})

        api = app.SiteApi("https://site.test", "k" * 40, transport=httpx.MockTransport(handler))
        await api.update_model("Usta (1)", 5, price_som="100")
        self.assertEqual(seen[0].url.path, "/api/bot/models/5")
        self.assertEqual(seen[0].headers["Authorization"], "Bearer " + "k" * 40)
        self.assertEqual(seen[0].headers["X-Bot-Actor"], "Usta (1)")
        with self.assertRaises(app.SiteError) as caught:
            await api.model(9)
        self.assertEqual(caught.exception.message, "Model topilmadi.")
        self.assertEqual(caught.exception.status, 404)

    async def test_non_ascii_actor_is_encoded(self):
        seen = []

        def handler(request):
            seen.append(request)
            return httpx.Response(200, json={"ok": True})

        api = app.SiteApi("https://site.test", "k" * 40, transport=httpx.MockTransport(handler))
        await api.update_model("Машраб Oʻg‘il (1)", 5, price_som="100")
        header = seen[0].headers["X-Bot-Actor"]
        header.encode("ascii")
        from urllib.parse import unquote
        self.assertEqual(unquote(header), "Машраб Oʻg‘il (1)")

    async def test_network_error_is_friendly(self):
        def handler(request):
            raise httpx.ConnectError("down")

        api = app.SiteApi("https://site.test", "k" * 40, transport=httpx.MockTransport(handler))
        with self.assertRaises(app.SiteError) as caught:
            await api.catalog()
        self.assertIn("aloqa", caught.exception.message)

    def test_relative_image_urls_get_site_prefix(self):
        api = app.SiteApi("https://bekcraft.uz/", "k")
        self.assertEqual(api.absolute("/uploads/a.jpg"), "https://bekcraft.uz/uploads/a.jpg")
        self.assertEqual(api.absolute("https://ik.imagekit.io/x.jpg"), "https://ik.imagekit.io/x.jpg")


if __name__ == "__main__":
    unittest.main()
