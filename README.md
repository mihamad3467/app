# Quran the Bot

هذه حزمة مستقلة لتشغيل بوت تيليجرام على VPS أو أي استضافة تدعم Python 3.11.

## المتطلبات

- Python 3.11 أو أحدث
- اتصال إنترنت مستمر
- Bot Token من BotFather
- Telegram numeric user ID للمالك
- البوت يجب أن يكون مشرفًا في القناة `@Quranthebot` حتى يعمل التحقق الإجباري من الاشتراك

## تشغيل سريع على Linux

```bash
unzip quran-telegram-bot.zip
cd quran-telegram-bot

python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt

cp .env.example .env
nano .env

chmod +x run.sh
./run.sh
```

عدّل القيم داخل `.env` قبل التشغيل:

```dotenv
BOT_TOKEN=ضع_توكن_البوت_هنا
ADMIN_ID=ضع_رقم_حساب_المالك_هنا
CHANNEL_USERNAME=@Quranthebot
LOG_LEVEL=INFO
PORT=0
```

لا تضع علامات اقتباس حول القيم، ولا ترسل ملف `.env` لأي شخص.

## تشغيل دائم باستخدام systemd

بعد رفع المجلد إلى `/opt/quran-telegram-bot`:

```bash
sudo cp systemd/quran-telegram-bot.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now quran-telegram-bot
sudo systemctl status quran-telegram-bot
```

لمشاهدة السجل:

```bash
sudo journalctl -u quran-telegram-bot -f
```

إذا كان مزود الاستضافة يطلب منفذ HTTP للصحة، غيّر `PORT` في `.env` إلى المنفذ المطلوب. إذا كان المطلوب تشغيل Telegram فقط، اتركه `0`.

## التخزين

يتم إنشاء قاعدة البيانات SQLite تلقائيًا داخل:

```text
data/quran_bot.sqlite3
```

احتفظ بنسخة احتياطية من مجلد `data` عند نقل الاستضافة أو إعادة تثبيت الخادم.

## ملاحظات مهمة

- لا تشغّل نسختين من البوت باستخدام نفس `BOT_TOKEN` في الوقت نفسه.
- يجب أن يكون `ADMIN_ID` رقم Telegram وليس اسم المستخدم.
- أضف البوت كمشرف في `@Quranthebot` مع صلاحية قراءة الأعضاء للتحقق من الاشتراك.
- في حال ظهور `Conflict: terminated by other getUpdates request`، أوقف أي نسخة أخرى تعمل بالتوكن نفسه.