# BekCraft Admin Catalog Bot

Telefon orqali Telegram ichidan katalogni boshqarish:
- /admin
- mahsulot qo'shish: nom -> kategoriya -> tavsif -> rasm
- mahsulotlarni ko'rish
- yashirish/ko'rsatish
- o'chirish

Mijozlar narx ko'rmaydi; ular rasmlarni ko'radi va menejerlarga qo'ng'iroq qiladi.

Muhim: bu demo versiyada products.json lokal faylda. Render'da doimiy saqlash uchun keyingi bosqichda persistent database ulash kerak.

## Webhook himoyasi

`WEBHOOK_SECRET` majburiy. U yo'q yoki yaroqsiz bo'lsa, bot himoyasiz ishga tushmaydi.

Qoidasi: 1–256 belgi, faqat lotin harflari (`A-Z`, `a-z`), raqamlar, `_` va `-`. Bo'sh joy yoki boshqa belgi yaroqsiz. Qiymatni Gitga, logga yoki shu faylga yozmang.

Ishga tushganda `set_webhook` shu sirni `secret_token` sifatida Telegramga beradi. Kelgan so'rovda `X-Telegram-Bot-Api-Secret-Token` sarlavhasi shu sir bilan solishtiriladi. Sarlavha yo'q yoki mos kelmasa, yangilanish qayta ishlanmaydi va javob `403` bo'ladi.

Buyurtma faqat shaxsiy chatda qabul qilinadi. Guruhdagi buyurtma tugmasi va matn qadamlari ism, telefon yoki manzil yig'maydi.

### Renderda chiqarish tartibi

1. Sirni o'zingiz yarating. Masalan, kompyuterda: `python -c "import secrets; print(secrets.token_urlsafe(32).replace('-', 'A').replace('_', 'B')[:48])"`. Chiqqan qiymatni saqlang, repozitoriyga qo'ymang.
2. Render Dashboard → `bekcraftuzbot` → Environment. `WEBHOOK_SECRET` kalitini qo'shing va qiymatni shu yerga yozing. Saqlang.
3. Shundan keyin yangi kodni chiqaring (Deploy). Jarayon ochilganda bot Telegram webhookini shu sir bilan yangilaydi.
4. Agar kod avval chiqib, o'zgaruvchi hali yo'q bo'lsa, xizmat ataylab ishga tushmaydi. Avval o'zgaruvchini qo'ying, keyin qayta ishga tushiring yoki qayta deploy qiling.

Eski kod yangi sarlavhani tekshirmaydi. Shuning uchun sirni Telegramga yuborish faqat shu yangi kod ishga tushgach bo'ladi.
