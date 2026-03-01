import asyncio
import json
import logging
import sqlite3
import sys
from datetime import datetime
from pathlib import Path
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import CommandStart, Command
from aiogram.types import (
    WebAppInfo, InlineKeyboardMarkup, InlineKeyboardButton,
    ReplyKeyboardMarkup, KeyboardButton, FSInputFile,
    BufferedInputFile
)
from aiocryptopay import AioCryptoPay, Networks

# ============================================================
#  НАСТРОЙКИ
# ============================================================
BOT_TOKEN       = "8767584053:AAEyJzBMZNCP8rify-6RCTBqzY9gogsDDMs"
CRYPTO_TOKEN    = "539055:AAigv2YSu3J9u8FT2aZrORrOj9wRHVaVocI"
WEB_APP_URL     = "https://istogen.github.io/Godlike/"
SUPPORT_CONTACT = "godlike_supp"
ADMIN_IDS       = []   # ← вставь свой Telegram ID, например [123456789]
USDT_RATE_RUB   = 105.0

# Путь к приветственной картинке (лежит рядом с ботом)
WELCOME_IMG = Path(__file__).parent / "welcome.jpg"

# ============================================================
#  ИНИЦИАЛИЗАЦИЯ
# ============================================================
bot    = Bot(token=BOT_TOKEN)
dp     = Dispatcher()
crypto = AioCryptoPay(token=CRYPTO_TOKEN, network=Networks.MAIN_NET)

# ============================================================
#  БАЗА ДАННЫХ
# ============================================================
def init_db():
    conn = sqlite3.connect("godlike.db")
    c = conn.cursor()
    c.execute("""CREATE TABLE IF NOT EXISTS users (
        user_id INTEGER PRIMARY KEY, username TEXT, full_name TEXT,
        ref_by INTEGER, joined_at TEXT, last_seen TEXT
    )""")
    c.execute("""CREATE TABLE IF NOT EXISTS invoices (
        invoice_id INTEGER PRIMARY KEY, user_id INTEGER, product TEXT,
        amount_usdt REAL, price_rub REAL, status TEXT DEFAULT 'pending',
        created_at TEXT, paid_at TEXT
    )""")
    c.execute("""CREATE TABLE IF NOT EXISTS referrals (
        ref_id INTEGER PRIMARY KEY AUTOINCREMENT,
        inviter_id INTEGER, invited_id INTEGER, created_at TEXT
    )""")
    c.execute("""CREATE TABLE IF NOT EXISTS feedback (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER, username TEXT, text TEXT,
        rating INTEGER, created_at TEXT
    )""")
    conn.commit(); conn.close()

def get_conn():
    conn = sqlite3.connect("godlike.db")
    conn.row_factory = sqlite3.Row
    return conn

def upsert_user(user: types.User, ref_by: int = None):
    now = datetime.now().isoformat()
    with get_conn() as conn:
        existing = conn.execute("SELECT user_id FROM users WHERE user_id=?", (user.id,)).fetchone()
        if existing:
            conn.execute("UPDATE users SET username=?, full_name=?, last_seen=? WHERE user_id=?",
                         (user.username, user.full_name, now, user.id))
        else:
            conn.execute("INSERT INTO users (user_id,username,full_name,ref_by,joined_at,last_seen) VALUES (?,?,?,?,?,?)",
                         (user.id, user.username, user.full_name, ref_by, now, now))
            if ref_by and ref_by != user.id:
                conn.execute("INSERT INTO referrals (inviter_id,invited_id,created_at) VALUES (?,?,?)",
                             (ref_by, user.id, now))
        conn.commit()

def get_user_stats(user_id: int) -> dict:
    with get_conn() as conn:
        row  = conn.execute("SELECT COUNT(*), COALESCE(SUM(amount_usdt),0) FROM invoices WHERE user_id=? AND status='paid'", (user_id,)).fetchone()
        refs = conn.execute("SELECT COUNT(*) FROM referrals WHERE inviter_id=?", (user_id,)).fetchone()
    return {"count": row[0], "spent": round(row[1], 2), "refs": refs[0]}

def save_invoice(invoice_id, user_id, product, amount_usdt, price_rub):
    now = datetime.now().isoformat()
    with get_conn() as conn:
        conn.execute("INSERT OR REPLACE INTO invoices (invoice_id,user_id,product,amount_usdt,price_rub,status,created_at) VALUES (?,?,?,?,?,?,?)",
                     (invoice_id, user_id, product, amount_usdt, price_rub, "pending", now))
        conn.commit()

def mark_paid(invoice_id):
    with get_conn() as conn:
        conn.execute("UPDATE invoices SET status='paid', paid_at=? WHERE invoice_id=?",
                     (datetime.now().isoformat(), invoice_id))
        conn.commit()

def get_invoice(invoice_id):
    with get_conn() as conn:
        return conn.execute("SELECT * FROM invoices WHERE invoice_id=?", (invoice_id,)).fetchone()

def get_global_stats():
    with get_conn() as conn:
        users   = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
        orders  = conn.execute("SELECT COUNT(*) FROM invoices WHERE status='paid'").fetchone()[0]
        revenue = conn.execute("SELECT COALESCE(SUM(amount_usdt),0) FROM invoices WHERE status='paid'").fetchone()[0]
        today   = datetime.now().strftime("%Y-%m-%d")
        today_o = conn.execute("SELECT COUNT(*) FROM invoices WHERE status='paid' AND paid_at LIKE ?", (f"{today}%",)).fetchone()[0]
        reviews = conn.execute("SELECT COUNT(*) FROM feedback").fetchone()[0]
    return {"users": users, "orders": orders, "revenue": round(revenue, 2), "today": today_o, "reviews": reviews}

def get_recent_orders(limit=10):
    with get_conn() as conn:
        return conn.execute("""SELECT i.invoice_id, i.product, i.amount_usdt, i.paid_at, u.username, u.full_name
               FROM invoices i LEFT JOIN users u ON i.user_id=u.user_id
               WHERE i.status='paid' ORDER BY i.paid_at DESC LIMIT ?""", (limit,)).fetchall()

def get_all_user_ids():
    with get_conn() as conn:
        return [r[0] for r in conn.execute("SELECT user_id FROM users").fetchall()]

def save_feedback(user_id, username, text, rating):
    with get_conn() as conn:
        conn.execute("INSERT INTO feedback (user_id,username,text,rating,created_at) VALUES (?,?,?,?,?)",
                     (user_id, username, text, rating, datetime.now().isoformat()))
        conn.commit()

def get_recent_feedback(limit=10):
    with get_conn() as conn:
        return conn.execute("SELECT * FROM feedback ORDER BY created_at DESC LIMIT ?", (limit,)).fetchall()

# ============================================================
#  КЛАВИАТУРЫ
# ============================================================
def main_kb():
    return ReplyKeyboardMarkup(keyboard=[
        [KeyboardButton(text="🛒 ОТКРЫТЬ МАГАЗИН", web_app=WebAppInfo(url=WEB_APP_URL))],
        [KeyboardButton(text="👤 ПРОФИЛЬ"), KeyboardButton(text="📦 МОИ ПОКУПКИ")],
        [KeyboardButton(text="👥 РЕФЕРАЛЬНАЯ ПРОГРАММА"), KeyboardButton(text="⭐ ОСТАВИТЬ ОТЗЫВ")],
        [KeyboardButton(text="🆘 ПОДДЕРЖКА")]
    ], resize_keyboard=True)

def rating_kb():
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="⭐", callback_data="rate:1"),
        InlineKeyboardButton(text="⭐⭐", callback_data="rate:2"),
        InlineKeyboardButton(text="⭐⭐⭐", callback_data="rate:3"),
        InlineKeyboardButton(text="⭐⭐⭐⭐", callback_data="rate:4"),
        InlineKeyboardButton(text="⭐⭐⭐⭐⭐", callback_data="rate:5"),
    ]])

# ============================================================
#  ХЕНДЛЕРЫ
# ============================================================
@dp.message(CommandStart())
async def cmd_start(m: types.Message):
    args = m.text.split()
    ref_by = None
    if len(args) > 1 and args[1].startswith("ref_"):
        try: ref_by = int(args[1][4:])
        except ValueError: pass

    upsert_user(m.from_user, ref_by=ref_by)

    caption = (
        f"🔥 <b>Привет, {m.from_user.first_name}!</b>\n\n"
        f"Добро пожаловать в <b>GODLIKE SHOP</b> — магазин №1 по Standoff 2.\n"
        f"Работаем с 2023 года • Более 1000 довольных клиентов\n\n"
        f"<b>Что мы предлагаем:</b>\n"
        f"📱 Читы для Android, iOS, PC и эмуляторов\n"
        f"🪙 Покупка и продажа игровой голды\n"
        f"💳 Оплата картой РФ или USDT\n"
        f"🛡 Гарантия Anti-ban на весь срок\n\n"
        f"Жми кнопку ниже и открывай магазин 👇"
    )

    if WELCOME_IMG.exists():
        await m.answer_photo(
            FSInputFile(WELCOME_IMG),
            caption=caption,
            reply_markup=main_kb(),
            parse_mode="HTML"
        )
    else:
        await m.answer(caption, reply_markup=main_kb(), parse_mode="HTML")


@dp.message(F.text == "👤 ПРОФИЛЬ")
async def cmd_profile(m: types.Message):
    upsert_user(m.from_user)
    st = get_user_stats(m.from_user.id)
    u  = m.from_user

    if st["count"] == 0:   badge = "🆕 Новичок"
    elif st["count"] < 3:  badge = "🥉 Покупатель"
    elif st["count"] < 7:  badge = "🥈 Постоянный"
    else:                   badge = "🥇 VIP"

    # Дни с регистрации
    with get_conn() as conn:
        row = conn.execute("SELECT joined_at FROM users WHERE user_id=?", (u.id,)).fetchone()
    days = 0
    if row and row["joined_at"]:
        try:
            joined = datetime.fromisoformat(row["joined_at"])
            days   = (datetime.now() - joined).days
        except Exception:
            pass

    await m.answer(
        f"👤 <b>Профиль</b>\n\n"
        f"🆔 ID: <code>{u.id}</code>\n"
        f"📛 Имя: {u.full_name}\n"
        f"🔗 @{u.username or 'не указан'}\n"
        f"📅 В магазине: <b>{days} дн.</b>\n\n"
        f"🏅 Статус: {badge}\n"
        f"🛍 Покупок: <b>{st['count']}</b>\n"
        f"💵 Потрачено: <b>{st['spent']} USDT</b>\n"
        f"👥 Рефералов: <b>{st['refs']}</b>\n\n"
        f"<i>Промокод GODLIKE даёт скидку 10% 🎁</i>",
        parse_mode="HTML"
    )


@dp.message(F.text == "📦 МОИ ПОКУПКИ")
async def cmd_purchases(m: types.Message):
    upsert_user(m.from_user)
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT product, amount_usdt, paid_at FROM invoices WHERE user_id=? AND status='paid' ORDER BY paid_at DESC LIMIT 10",
            (m.from_user.id,)
        ).fetchall()
    if not rows:
        await m.answer("📦 <b>Ваши покупки</b>\n\nПока покупок нет — откройте магазин! 🛒",
                       parse_mode="HTML")
        return
    text = "📦 <b>Последние покупки:</b>\n\n"
    for i, r in enumerate(rows, 1):
        date = r["paid_at"][:10] if r["paid_at"] else "—"
        text += f"{i}. <b>{r['product']}</b>\n   💵 {r['amount_usdt']} USDT · 📅 {date}\n\n"
    await m.answer(text, parse_mode="HTML")


@dp.message(F.text == "👥 РЕФЕРАЛЬНАЯ ПРОГРАММА")
async def cmd_referral(m: types.Message):
    upsert_user(m.from_user)
    st     = get_user_stats(m.from_user.id)
    bot_me = await bot.get_me()
    url    = f"https://t.me/{bot_me.username}?start=ref_{m.from_user.id}"
    await m.answer(
        f"👥 <b>Реферальная программа</b>\n\n"
        f"Приглашай друзей и получай бонусы!\n\n"
        f"🔗 Твоя ссылка:\n<code>{url}</code>\n\n"
        f"👫 Приглашено: <b>{st['refs']}</b>\n\n"
        f"<i>За каждого купившего друга напиши в поддержку — выдадим бонус 🎁</i>",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text="📤 Поделиться",
                url=f"https://t.me/share/url?url={url}&text=Крутой+магазин+по+Standoff+2!")
        ]])
    )


# ── СИСТЕМА ОТЗЫВОВ ──────────────────────────────────────────
pending_feedback: dict = {}   # user_id -> rating (ждём текст отзыва)

@dp.message(F.text == "⭐ ОСТАВИТЬ ОТЗЫВ")
async def cmd_feedback(m: types.Message):
    upsert_user(m.from_user)
    # Проверяем — есть ли хоть одна покупка
    st = get_user_stats(m.from_user.id)
    if st["count"] == 0:
        await m.answer(
            "⭐ <b>Оставить отзыв</b>\n\n"
            "Отзывы могут оставлять только покупатели.\n"
            "Сначала сделайте заказ в магазине! 🛒",
            parse_mode="HTML"
        )
        return
    await m.answer(
        "⭐ <b>Оценка</b>\n\nВыбери оценку от 1 до 5:",
        reply_markup=rating_kb(),
        parse_mode="HTML"
    )

@dp.callback_query(F.data.startswith("rate:"))
async def rate_callback(cb: types.CallbackQuery):
    rating = int(cb.data.split(":")[1])
    pending_feedback[cb.from_user.id] = rating
    stars = "⭐" * rating
    await cb.message.edit_text(
        f"Оценка: {stars}\n\n✍️ Теперь напиши свой отзыв текстом:",
        parse_mode="HTML"
    )
    await cb.answer()


@dp.message(F.text == "🆘 ПОДДЕРЖКА")
async def cmd_support(m: types.Message):
    upsert_user(m.from_user)
    await m.answer(
        "📬 Напиши нашему оператору — ответим быстро.",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text="✍️ Открыть поддержку", url=f"https://t.me/{SUPPORT_CONTACT}")
        ]])
    )


# ── ПЕРЕХВАТ ТЕКСТА (отзывы + рассылка) ─────────────────────
broadcast_pending: set = set()

@dp.message(F.text & ~F.text.startswith("/"))
async def catch_text(m: types.Message):
    uid = m.from_user.id

    # Ждём текст отзыва
    if uid in pending_feedback:
        rating = pending_feedback.pop(uid)
        save_feedback(uid, m.from_user.username or m.from_user.full_name, m.text, rating)
        stars = "⭐" * rating
        await m.answer(
            f"✅ <b>Отзыв принят!</b>\n\n{stars}\n<i>{m.text}</i>\n\nСпасибо за обратную связь! 🙏",
            parse_mode="HTML"
        )
        # Шлём отзыв в чат поддержки
        for admin_id in ADMIN_IDS:
            try:
                await bot.send_message(
                    admin_id,
                    f"⭐ <b>Новый отзыв!</b>\n\n"
                    f"👤 @{m.from_user.username or m.from_user.full_name} (ID: <code>{uid}</code>)\n"
                    f"Оценка: {stars}\n\n<i>{m.text}</i>",
                    parse_mode="HTML"
                )
            except Exception:
                pass
        return

    # Рассылка (только для админов)
    if uid in broadcast_pending and uid in ADMIN_IDS:
        broadcast_pending.discard(uid)
        user_ids = get_all_user_ids()
        sent = failed = 0
        for u in user_ids:
            try:
                await bot.send_message(u, m.text)
                sent += 1
                await asyncio.sleep(0.04)
            except Exception:
                failed += 1
        await m.answer(f"📢 Рассылка завершена!\n✅ Доставлено: {sent}\n❌ Ошибок: {failed}")


# ── WEB APP ──────────────────────────────────────────────────
@dp.message(F.web_app_data)
async def web_app_data_handler(m: types.Message):
    upsert_user(m.from_user)
    try:
        data      = json.loads(m.web_app_data.data)
        item      = data.get("item", "Товар")
        price_rub = float(data.get("price_rub", 0))

        if price_rub <= 0:
            await m.answer("❌ Некорректная сумма."); return

        amount_usdt = max(0.1, round(price_rub / USDT_RATE_RUB, 2))
        invoice = await crypto.create_invoice(
            asset="USDT", amount=amount_usdt,
            description=f"GODLIKE: {item}",
            payload=f"{m.from_user.id}:{item}"
        )
        save_invoice(invoice.invoice_id, m.from_user.id, item, amount_usdt, price_rub)

        await m.answer(
            f"🧾 <b>Счёт создан!</b>\n\n"
            f"📦 Товар: <b>{item}</b>\n"
            f"💵 К оплате: <b>{amount_usdt} USDT</b>\n"
            f"💱 Курс: 1 USDT = {USDT_RATE_RUB} ₽\n\n"
            f"После оплаты нажми <b>«Проверить оплату»</b> 👇",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text=f"💳 Оплатить {amount_usdt} USDT", url=invoice.bot_invoice_url)],
                [InlineKeyboardButton(text="✅ Проверить оплату", callback_data=f"check:{invoice.invoice_id}")]
            ]),
            parse_mode="HTML"
        )
    except Exception as e:
        logging.error(f"web_app: {e}")
        await m.answer("❌ Ошибка создания счёта. Напиши в поддержку.")


# ── ПРОВЕРКА ОПЛАТЫ ──────────────────────────────────────────
@dp.callback_query(F.data.startswith("check:"))
async def check_payment(cb: types.CallbackQuery):
    invoice_id = int(cb.data.split(":")[1])
    row = get_invoice(invoice_id)
    if not row:
        await cb.answer("❌ Счёт не найден.", show_alert=True); return
    if row["user_id"] != cb.from_user.id:
        await cb.answer("❌ Это не ваш счёт.", show_alert=True); return
    if row["status"] == "paid":
        await cb.answer("✅ Уже оплачено!", show_alert=True); return

    try:
        invoices = await crypto.get_invoices(invoice_ids=[invoice_id])
        if not invoices:
            await cb.answer("❌ Счёт не найден в CryptoBot.", show_alert=True); return
        inv = invoices[0]

        if inv.status == "paid":
            mark_paid(invoice_id)
            await cb.message.edit_text(
                f"✅ <b>Оплата подтверждена!</b>\n\n"
                f"📦 Товар: <b>{row['product']}</b>\n"
                f"💵 Оплачено: <b>{row['amount_usdt']} USDT</b>\n\n"
                f"⏱ Товар будет передан в течение <b>5–10 минут</b>.\n"
                f"Прошло больше? Напиши в поддержку 👇",
                parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
                    InlineKeyboardButton(text="🆘 Поддержка", url=f"https://t.me/{SUPPORT_CONTACT}")
                ]])
            )
            await cb.answer("✅ Оплата подтверждена!", show_alert=True)

            # Авто-запрос отзыва через 10 минут
            asyncio.create_task(ask_feedback_later(cb.from_user.id, row['product']))

            for admin_id in ADMIN_IDS:
                try:
                    await bot.send_message(admin_id,
                        f"🛒 <b>Новый заказ!</b>\n\n"
                        f"👤 @{cb.from_user.username or cb.from_user.full_name} (ID: <code>{cb.from_user.id}</code>)\n"
                        f"📦 <b>{row['product']}</b>\n💵 <b>{row['amount_usdt']} USDT</b>",
                        parse_mode="HTML")
                except Exception:
                    pass

        elif inv.status == "expired":
            await cb.answer("⏳ Счёт истёк. Создай новый заказ.", show_alert=True)
            with get_conn() as conn:
                conn.execute("UPDATE invoices SET status='expired' WHERE invoice_id=?", (invoice_id,))
                conn.commit()
        else:
            await cb.answer("⏳ Оплата ещё не поступила. Попробуй через пару секунд.", show_alert=True)
    except Exception as e:
        logging.error(f"check_payment: {e}")
        await cb.answer("❌ Ошибка проверки. Попробуй позже.", show_alert=True)


async def ask_feedback_later(user_id: int, product: str):
    """Через 10 минут после покупки просим оставить отзыв."""
    await asyncio.sleep(600)
    try:
        await bot.send_message(
            user_id,
            f"👋 Привет! Как тебе <b>{product}</b>?\n\n"
            f"Оставь отзыв — это займёт 30 секунд и поможет другим покупателям 🙏",
            parse_mode="HTML",
            reply_markup=rating_kb()
        )
    except Exception:
        pass


# ── ЕЖЕДНЕВНЫЕ СОВЕТЫ (каждый день в 12:00 МСК) ─────────────
TIPS = [
    "💡 <b>Совет дня:</b> Используй промокод <code>GODLIKE</code> и получи скидку 10% на любой товар!",
    "💡 <b>Совет дня:</b> Покупай подписку на 90 дней — это выгоднее на 30% по сравнению с 7-дневной!",
    "💡 <b>Совет дня:</b> Пригласи друга по своей реферальной ссылке и получи бонус. Кнопка в меню 👥",
    "💡 <b>Совет дня:</b> iOS Assistant работает без Jailbreak — просто установи наш профиль за 3 минуты.",
    "💡 <b>Совет дня:</b> Оплата в USDT — самый быстрый способ. Деньги приходят мгновенно, выдача в течение 10 минут!",
    "💡 <b>Совет дня:</b> Server Assistant позволяет создавать свои читы и продавать их. Инвестиция в бизнес 💰",
    "💡 <b>Совет дня:</b> Можно продать нам голду прямо в магазине! Курс: 0.74₽ за 1 голд.",
]

async def daily_tips_task():
    """Шлём советы всем пользователям раз в день."""
    import random
    while True:
        now = datetime.now()
        # Считаем сколько секунд до следующего полудня
        next_noon = now.replace(hour=9, minute=0, second=0, microsecond=0)
        if now >= next_noon:
            next_noon = next_noon.replace(day=now.day+1)
        wait = (next_noon - now).total_seconds()
        await asyncio.sleep(wait)

        tip = random.choice(TIPS)
        user_ids = get_all_user_ids()
        for uid in user_ids:
            try:
                await bot.send_message(uid, tip, parse_mode="HTML",
                    reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
                        InlineKeyboardButton(text="🛒 Открыть магазин", web_app=WebAppInfo(url=WEB_APP_URL))
                    ]]))
                await asyncio.sleep(0.05)
            except Exception:
                pass


# ── АДМИН-ПАНЕЛЬ ─────────────────────────────────────────────
def is_admin(uid): return uid in ADMIN_IDS

@dp.message(Command("admin"))
async def cmd_admin(m: types.Message):
    if not is_admin(m.from_user.id): return
    st = get_global_stats()
    await m.answer(
        f"⚙️ <b>Админ-панель</b>\n\n"
        f"👥 Пользователей: <b>{st['users']}</b>\n"
        f"🛒 Всего заказов: <b>{st['orders']}</b>\n"
        f"📅 Заказов сегодня: <b>{st['today']}</b>\n"
        f"💰 Выручка: <b>{st['revenue']} USDT</b>\n"
        f"⭐ Отзывов: <b>{st['reviews']}</b>",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="📋 Последние заказы",  callback_data="adm:orders")],
            [InlineKeyboardButton(text="⭐ Последние отзывы",  callback_data="adm:reviews")],
            [InlineKeyboardButton(text="📢 Рассылка всем",     callback_data="adm:broadcast")],
        ])
    )

@dp.callback_query(F.data == "adm:orders")
async def adm_orders(cb: types.CallbackQuery):
    if not is_admin(cb.from_user.id): return
    orders = get_recent_orders(10)
    if not orders:
        await cb.answer("Заказов пока нет.", show_alert=True); return
    text = "📋 <b>Последние заказы:</b>\n\n"
    for o in orders:
        name = f"@{o['username']}" if o['username'] else o['full_name'] or "—"
        date = (o['paid_at'] or "")[:10]
        text += f"• {name} — <b>{o['product']}</b> · {o['amount_usdt']} USDT · {date}\n"
    await cb.message.edit_text(text, parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="◀️ Назад", callback_data="adm:back")]]))
    await cb.answer()

@dp.callback_query(F.data == "adm:reviews")
async def adm_reviews(cb: types.CallbackQuery):
    if not is_admin(cb.from_user.id): return
    rows = get_recent_feedback(10)
    if not rows:
        await cb.answer("Отзывов пока нет.", show_alert=True); return
    text = "⭐ <b>Последние отзывы:</b>\n\n"
    for r in rows:
        stars = "⭐" * r["rating"]
        name  = r["username"] or "—"
        text += f"@{name} {stars}\n<i>{r['text'][:100]}</i>\n\n"
    await cb.message.edit_text(text, parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="◀️ Назад", callback_data="adm:back")]]))
    await cb.answer()

@dp.callback_query(F.data == "adm:back")
async def adm_back(cb: types.CallbackQuery):
    if not is_admin(cb.from_user.id): return
    st = get_global_stats()
    await cb.message.edit_text(
        f"⚙️ <b>Админ-панель</b>\n\n"
        f"👥 Пользователей: <b>{st['users']}</b>\n"
        f"🛒 Всего заказов: <b>{st['orders']}</b>\n"
        f"📅 Заказов сегодня: <b>{st['today']}</b>\n"
        f"💰 Выручка: <b>{st['revenue']} USDT</b>\n"
        f"⭐ Отзывов: <b>{st['reviews']}</b>",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="📋 Последние заказы",  callback_data="adm:orders")],
            [InlineKeyboardButton(text="⭐ Последние отзывы",  callback_data="adm:reviews")],
            [InlineKeyboardButton(text="📢 Рассылка всем",     callback_data="adm:broadcast")],
        ])
    )
    await cb.answer()

@dp.callback_query(F.data == "adm:broadcast")
async def adm_broadcast_start(cb: types.CallbackQuery):
    if not is_admin(cb.from_user.id): return
    broadcast_pending.add(cb.from_user.id)
    await cb.message.answer("📢 Отправь текст рассылки:")
    await cb.answer()

# ============================================================
#  ЗАПУСК
# ============================================================
async def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
    init_db()
    print("🔥 Бот GODLIKE запущен!")
    print(f"💱 Курс USDT: {USDT_RATE_RUB} ₽")
    print(f"👮 Админы: {ADMIN_IDS or 'не заданы'}")
    print(f"🖼 Картинка: {'✅' if WELCOME_IMG.exists() else '❌ не найдена (положи welcome.jpg рядом с ботом)'}")

    # Запускаем ежедневные советы в фоне
    asyncio.create_task(daily_tips_task())

    await dp.start_polling(bot)

if __name__ == "__main__":
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        print("Бот остановлен")
