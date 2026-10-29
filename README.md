# BekCraft bot (@Bekcraftuzbot)

Bot va sayt bitta katalogdan foydalanadi. Ma'lumot faqat bekcraft.uz bazasida saqlanadi; bot saytga `BOT_API_KEY` bilan murojaat qiladi (`site_api.py`). Botda kiritilgan narsa darhol saytda chiqadi. Sayt admin paneli zaxira sifatida ishlayveradi.

## Mijoz uchun
- Bo'lim → tur → model; rasmlar albom bo'lib chiqadi; narx (kiritilmagan bo'lsa — «Narx so'rov bo'yicha»).
- Buyurtma: ism → telefon («📱 Raqamni yuborish» tugmasi) → izoh (ixtiyoriy). Buyurtma saytdagi «Murojaatlar»ga tushadi va saytning odatiy Telegram xabari yuboriladi.
- Buyurtma faqat shaxsiy chatda qabul qilinadi; guruhda ism va telefon so'ralmaydi.

## Admin uchun (/admin)
Faqat `ADMIN_IDS` dagi Telegram ID lar. Har amal saytdagi «Tarix»ga `bot: Ism (ID)` deb yoziladi.
- ➕ Model qo'shish: bo'lim → tur → nom → tavsif → narx → 1–10 rasm → tekshirish → saqlash.
- 📋 Modellar: nom, tavsif, narxni o'zgartirish; rasmlarni ⬆️⬇️ surish, qo'shish, o'chirish (oxirgi rasm o'chmaydi); modelni o'chirish (tasdiq bilan).
- 📦 Oxirgi buyurtmalar.

Yangi bo'lim/tur, bosh sahifa rasmlari — hozircha sayt admin panelida (2-bosqich).

## Render → bekcraftuzbot → Environment
| Kalit | Nima |
|---|---|
| `TELEGRAM_BOT_TOKEN` | bot tokeni |
| `ADMIN_IDS` | Telegram ID lar vergul bilan (ID ni @userinfobot → Start dan oling; chatga yozmang) |
| `BOT_API_KEY` | saytdagi `BOT_API_KEY` bilan **bir xil** (kamida 32 belgi) |
| `SITE_URL` | `https://bekcraft.uz` (bo'lmasa shu olinadi) |
| `WEBHOOK_URL`, `WEBHOOK_SECRET` | avvalgidek |

`DATABASE_URL` endi ishlatilmaydi. Eski bot bazasi (Neon: bekcraft-telegram-бот) tegilmagan.

## Webhook himoyasi

`WEBHOOK_SECRET` majburiy. U yo'q yoki yaroqsiz bo'lsa, bot himoyasiz ishga tushmaydi.

Qoidasi: 1–256 belgi, faqat lotin harflari (`A-Z`, `a-z`), raqamlar, `_` va `-`. Qiymatni Gitga, logga yoki shu faylga yozmang.

Ishga tushganda `set_webhook` shu sirni `secret_token` sifatida Telegramga beradi. Kelgan so'rovda `X-Telegram-Bot-Api-Secret-Token` sarlavhasi shu sir bilan solishtiriladi; mos kelmasa — `403`.

## Bilish kerak
- Render bepul tarifi: bot 15 daqiqa ishlatilmasa uxlaydi, birinchi javob 30–50 soniya kechikadi. Bot uxlab qolsa, yarim to'ldirilgan amal (masalan, yangi model) yo'qoladi — /admin dan qayta boshlanadi.

## Test
`python -m unittest test_security -v`
