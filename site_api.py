"""bekcraft.uz bot API mijozi.

Bot o'z bazasiga ega emas: katalog, rasmlar va buyurtmalar saytda saqlanadi.
Har so'rov `Authorization: Bearer BOT_API_KEY` bilan yuboriladi.
"""
from urllib.parse import quote

import httpx

# Sayt Render bepul tarifida uxlab qolgan bo'lsa, birinchi javob 30–50 soniya kechikadi.
TIMEOUT = httpx.Timeout(90.0, connect=30.0)


class SiteError(Exception):
    """Sayt rad etdi yoki javob bermadi. `message` foydalanuvchiga ko'rsatiladi."""

    def __init__(self, message, status=0, code=""):
        super().__init__(message)
        self.message = message
        self.status = status
        self.code = code


class SiteApi:
    def __init__(self, base_url, api_key, transport=None):
        self.base_url = str(base_url or "").rstrip("/")
        self.api_key = str(api_key or "")
        self.transport = transport

    def absolute(self, url):
        url = str(url or "")
        if url.startswith("/"):
            return self.base_url + url
        return url

    async def _request(self, method, path, actor=None, json=None, data=None, files=None, params=None):
        headers = {"Authorization": f"Bearer {self.api_key}"}
        if actor:
            # HTTP sarlavhada faqat ASCII bo'ladi: kirill/o'zbekcha ism URL-kodlanadi, sayt qayta ochadi.
            headers["X-Bot-Actor"] = quote(str(actor), safe=" ()")
        try:
            async with httpx.AsyncClient(
                base_url=self.base_url + "/api/bot",
                timeout=TIMEOUT,
                transport=self.transport,
            ) as client:
                response = await client.request(
                    method, path, headers=headers, json=json, data=data, files=files, params=params
                )
        except httpx.HTTPError:
            raise SiteError("Sayt bilan aloqa bo'lmadi. Birozdan keyin qayta urinib ko'ring.")
        try:
            body = response.json()
        except ValueError:
            body = {}
        if response.status_code >= 400 or not body.get("ok"):
            message = body.get("message") or "Saytda xato yuz berdi. Keyinroq qayta urinib ko'ring."
            raise SiteError(message, response.status_code, body.get("error", ""))
        return body

    # ---- Mijoz ----

    async def catalog(self):
        return (await self._request("GET", "/catalog"))["categories"]

    async def models(self, product_id):
        return await self._request("GET", f"/products/{int(product_id)}/models")

    async def model(self, model_id):
        body = await self._request("GET", f"/models/{int(model_id)}")
        for image in body["images"]:
            image["url"] = self.absolute(image["url"])
        return body

    async def order(self, *, name, phone, message, model_id, telegram, submission_id):
        return await self._request("POST", "/orders", json={
            "name": name,
            "phone": phone,
            "message": message,
            "model_id": model_id,
            "telegram": telegram,
            "submission_id": submission_id,
        })

    # ---- Admin ----

    async def leads(self, actor, limit=10):
        return (await self._request("GET", "/leads", actor=actor, params={"limit": limit}))["leads"]

    async def create_model(self, actor, product_id, *, name, description, price, photos):
        files = [("images", (f"rasm{i + 1}.jpg", data, "image/jpeg")) for i, data in enumerate(photos)]
        body = await self._request(
            "POST",
            f"/products/{int(product_id)}/models",
            actor=actor,
            data={"name": name, "description": description, "price_som": price},
            files=files,
        )
        return body["model_id"]

    async def update_model(self, actor, model_id, **fields):
        return await self._request("PATCH", f"/models/{int(model_id)}", actor=actor, json=fields)

    async def delete_model(self, actor, model_id):
        return await self._request("DELETE", f"/models/{int(model_id)}", actor=actor)

    async def add_images(self, actor, model_id, photos):
        files = [("images", (f"rasm{i + 1}.jpg", data, "image/jpeg")) for i, data in enumerate(photos)]
        return await self._request("POST", f"/models/{int(model_id)}/images", actor=actor, files=files)

    async def move_image(self, actor, model_id, image_id, direction):
        return await self._request(
            "POST",
            f"/models/{int(model_id)}/images/{int(image_id)}/move",
            actor=actor,
            json={"direction": direction},
        )

    async def delete_image(self, actor, model_id, image_id):
        return await self._request("DELETE", f"/models/{int(model_id)}/images/{int(image_id)}", actor=actor)
