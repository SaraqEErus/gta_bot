import json
import time
import logging
import random
from pathlib import Path
from telegram import Update, ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove
from telegram.ext import (
    Application, CommandHandler, MessageHandler,
    ConversationHandler, filters, ContextTypes
)

# ==================== НАСТРОЙКИ ====================
TOKEN = "8994657997:AAF9PKCxsMIBohrnOp38WBwhjBkU1jnwNGY"   # <-- Вставь токен

DATA_FILE = Path("gta_data.json")
JOB_COOLDOWN = 120
MINE_SALARY = 600
FARM_SALARY_MIN = 1200
FARM_SALARY_MAX = 1500
POLICE_SALARY_MIN = 3000
POLICE_SALARY_MAX = 5000
START_BONUS = 20000
START_BOOST_HOURS = 5
JAIL_TIME = 3600
BAIL_PRICE = 15000
WHEEL_COOLDOWN = 5 * 3600   # 5 часов
# ===================================================

NICKNAME, NATIONALITY = range(2)

logging.basicConfig(format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)


def load_data() -> dict:
    if DATA_FILE.exists():
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def save_data(data: dict):
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def get_user(user_id: int) -> dict | None:
    data = load_data()
    return data.get(str(user_id))


def save_user(user_id: int, user_data: dict):
    data = load_data()
    data[str(user_id)] = user_data
    save_data(data)


def create_user(user_id: int, nickname: str, nationality: str) -> dict:
    user = {
        "nickname": nickname,
        "nationality": nationality,
        "nick_changed": False,
        "health": 100,
        "food": 100,
        "water": 100,
        "cash": 0,
        "bank": 0,
        "level": 1,
        "job_level": 1,
        "mine_works": 0,
        "farm_works": 0,
        "police_works": 0,
        "last_job": 0,
        "boost_until": 0,
        "inventory": {},
        "cars": [],               # список машин [{"name": "...", "speed": 80}, ...]
        "weapon": None,
        "armor": False,
        "jail_until": 0,
        "businesses": [],
        "houses": [],             # список домов [{"name": "...", "slots": 2}, ...]
        "business_last_collect": 0,
        "last_wheel": 0
    }
    save_user(user_id, user)
    return user


def find_user_by_nick(nick: str):
    data = load_data()
    nick_lower = nick.lower()
    for uid, u in data.items():
        if u.get("nickname", "").lower() == nick_lower:
            return uid, u
    return None


def is_in_jail(user: dict) -> bool:
    return user.get("jail_until", 0) > time.time()


def get_garage_slots(user: dict) -> int:
    """Суммарное количество гаражных мест со всех домов"""
    houses = user.get("houses", [])
    if not houses:
        return 1  # без дома можно иметь 1 машину
    return sum(h.get("slots", 2) for h in houses)


def main_keyboard():
    return ReplyKeyboardMarkup(
        [
            [KeyboardButton("👤 Профиль"), KeyboardButton("🎒 Инвентарь")],
            [KeyboardButton("🛒 Магазин"), KeyboardButton("⛏ Работа")],
            [KeyboardButton("🚗 Автосалон"), KeyboardButton("🕶 Чёрный рынок")],
            [KeyboardButton("💼 Бизнесы"), KeyboardButton("🏠 Дома")],
            [KeyboardButton("🎡 Колесо"), KeyboardButton("🏆 Топ")],
            [KeyboardButton("📋 Команды")]
        ],
        resize_keyboard=True
    )


SHOP = {
    "вода": {"price": 1000, "desc": "Восстанавливает 30 воды", "type": "water", "value": 30},
    "еда": {"price": 1000, "desc": "Восстанавливает 30 еды", "type": "food", "value": 30},
    "аптечка": {"price": 2500, "desc": "Восстанавливает 40 здоровья", "type": "health", "value": 40},
    "большая аптечка": {"price": 6000, "desc": "Восстанавливает 80 здоровья", "type": "health", "value": 80},
}

CARS = {
    "матиз": {"price": 1_000_000, "speed": 80},
    "лада семерка": {"price": 1_900_000, "speed": 100},
    "приора": {"price": 3_500_000, "speed": 140},
    "лада веста": {"price": 4_200_000, "speed": 160},
    "камри": {"price": 8_000_000, "speed": 180},
    "тойота ленд крузер": {"price": 18_000_000, "speed": 180},
    "бмв м5": {"price": 25_000_000, "speed": 250},
    "мерседес s-class": {"price": 45_000_000, "speed": 250},
    "порше 911": {"price": 80_000_000, "speed": 300},
    "бугатти широн": {"price": 300_000_000, "speed": 300},
}

WEAPONS = {
    "пистолет": {"price": 20000, "chance": 25},
    "пистолет-пулемёт": {"price": 150000, "chance": 35},
    "дробовик": {"price": 400000, "chance": 42},
    "автомат": {"price": 1200000, "chance": 50},
    "снайперская винтовка": {"price": 3500000, "chance": 55},
    "тяжёлый пулемёт": {"price": 7000000, "chance": 60},
}

ARMOR_PRICE = 250000

BUSINESSES = {
    "банкомат": {"price": 7_000_000, "income": 10000},
    "магазин одежды": {"price": 50_000_000, "income": 15000},
    "автосалон": {"price": 120_000_000, "income": 25000},
    "тюрьма": {"price": 200_000_000, "income": 20000},
    "чёрный рынок": {"price": 400_000_000, "income": 30000},
    "таксопарк": {"price": 800_000_000, "income": 50000},
    "казино": {"price": 1_000_000_000, "income": 100000},
}

# Дома: название -> цена, количество гаражных мест
HOUSES = {
    "квартира": {"price": 5_000_000, "slots": 2},
    "вилла": {"price": 300_000_000, "slots": 5},
}


# ==================== РЕГИСТРАЦИЯ ====================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = get_user(update.effective_user.id)
    if user:
        await update.message.reply_text(f"С возвращением, {user['nickname']}!", reply_markup=main_keyboard())
        return ConversationHandler.END
    await update.message.reply_text(
        "👋 Добро пожаловать в GTA RP!\n\nВведи игровой ник (3-20 символов):",
        reply_markup=ReplyKeyboardRemove()
    )
    return NICKNAME


async def process_nickname(update: Update, context: ContextTypes.DEFAULT_TYPE):
    nick = update.message.text.strip()
    if len(nick) < 3 or len(nick) > 20:
        await update.message.reply_text("Ник должен быть от 3 до 20 символов:")
        return NICKNAME
    context.user_data["nickname"] = nick
    await update.message.reply_text(f"Отлично, {nick}!\nНапиши национальность:")
    return NATIONALITY


async def process_nationality(update: Update, context: ContextTypes.DEFAULT_TYPE):
    nationality = update.message.text.strip()
    if len(nationality) < 2 or len(nationality) > 30:
        await update.message.reply_text("Напиши нормальную национальность:")
        return NATIONALITY
    create_user(update.effective_user.id, context.user_data["nickname"], nationality)
    await update.message.reply_text(
        f"✅ Персонаж создан!\n\nНик: {context.user_data['nickname']}\n"
        f"Национальность: {nationality}\n\nНапиши <b>START</b> для 20 000$",
        reply_markup=main_keyboard(), parse_mode="HTML"
    )
    return ConversationHandler.END


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Отменено. /start")
    return ConversationHandler.END


async def check_jail(update: Update, user: dict) -> bool:
    if is_in_jail(user):
        left = int(user["jail_until"] - time.time())
        await update.message.reply_text(
            f"🚔 Ты в тюрьме ещё {left // 60} мин.\nОткупиться: <code>откупиться</code> ({BAIL_PRICE:,}$)",
            parse_mode="HTML"
        )
        return True
    return False


# ==================== ПРОФИЛЬ ====================
async def profile(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = get_user(update.effective_user.id)
    if not user:
        await update.message.reply_text("Сначала /start")
        return
    if await check_jail(update, user):
        return

    boost = ""
    if user.get("boost_until", 0) > time.time():
        mins = int((user["boost_until"] - time.time()) / 60)
        boost = f"\n🔥 Буст: {mins} мин."

    cars = user.get("cars", [])
    slots = get_garage_slots(user)
    if cars:
        cars_text = f"\n🚗 Машины ({len(cars)}/{slots}):\n" + "\n".join(
            f"  • {c['name'].title()} ({c['speed']} км/ч)" for c in cars
        )
    else:
        cars_text = f"\n🚗 Машины: нет (слотов: {slots})"

    weapon = user.get("weapon")
    weapon_text = f"\n🔫 {weapon.title()}" if weapon else "\n🔫 Оружие: нет"
    armor_text = "\n🛡 Бронежилет: есть" if user.get("armor") else ""

    houses = user.get("houses", [])
    houses_text = ""
    if houses:
        houses_text = "\n\n🏠 Дома:\n" + "\n".join(f"  • {h['name'].title()} ({h['slots']} мест)" for h in houses)

    businesses = user.get("businesses", [])
    bus_text = ""
    if businesses:
        bus_text = "\n\n💼 Бизнесы:\n" + "\n".join(f"  • {b.title()}" for b in businesses)

    text = (
        f"👤 <b>{user['nickname']}</b>\n"
        f"🏳 {user['nationality']}\n\n"
        f"❤️ {user['health']}/100  🍗 {user['food']}/100  💧 {user['water']}/100\n\n"
        f"💵 {user['cash']:,}$   🏦 {user['bank']:,}$\n"
        f"{cars_text}{weapon_text}{armor_text}"
        f"{houses_text}{bus_text}\n\n"
        f"⭐ Ур. {user['level']} | Работа {user['job_level']}\n"
        f"⛏ {user.get('mine_works',0)} | 🌾 {user.get('farm_works',0)} | 👮 {user.get('police_works',0)}"
        f"{boost}"
    )
    await update.message.reply_text(text, parse_mode="HTML")


async def view_profile(update: Update, context: ContextTypes.DEFAULT_TYPE):
    target = None
    if update.message.reply_to_message:
        target = get_user(update.message.reply_to_message.from_user.id)
    else:
        parts = update.message.text.split(maxsplit=1)
        if len(parts) == 2:
            found = find_user_by_nick(parts[1])
            if found:
                target = found[1]
    if not target:
        await update.message.reply_text("Игрок не найден.")
        return
    cars = target.get("cars", [])
    car_text = f"\n🚗 Машин: {len(cars)}" if cars else ""
    text = (
        f"👤 <b>{target['nickname']}</b>\n"
        f"🏳 {target['nationality']}\n"
        f"💵 {target['cash']:,}$ | 🏦 {target['bank']:,}$"
        f"{car_text}\n"
        f"⭐ Ур. {target['level']} | Работа {target['job_level']}"
    )
    await update.message.reply_text(text, parse_mode="HTML")


# ==================== ИНВЕНТАРЬ ====================
async def inventory(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = get_user(update.effective_user.id)
    if not user or await check_jail(update, user):
        return
    inv = user.get("inventory", {})
    items = [f"• {k} × {v}" for k, v in inv.items() if v > 0]
    if not items:
        await update.message.reply_text("Инвентарь пуст.")
        return
    await update.message.reply_text("🎒 <b>Инвентарь:</b>\n\n" + "\n".join(items), parse_mode="HTML")


async def use_item(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = get_user(update.effective_user.id)
    if not user or await check_jail(update, user):
        return
    item = update.message.text.lower().strip()[13:].strip()
    inv = user.get("inventory", {})
    if inv.get(item, 0) < 1:
        await update.message.reply_text(f"У тебя нет «{item}»")
        return
    if item not in SHOP:
        await update.message.reply_text("Нельзя использовать.")
        return
    info = SHOP[item]
    inv[item] -= 1
    if inv[item] <= 0:
        del inv[item]
    if info["type"] == "health":
        user["health"] = min(100, user["health"] + info["value"])
        msg = f"❤️ {user['health']}"
    elif info["type"] == "food":
        user["food"] = min(100, user["food"] + info["value"])
        msg = f"🍗 {user['food']}"
    else:
        user["water"] = min(100, user["water"] + info["value"])
        msg = f"💧 {user['water']}"
    save_user(update.effective_user.id, user)
    await update.message.reply_text(f"✅ {msg}")


# ==================== МАГАЗИН ====================
async def shop(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = get_user(update.effective_user.id)
    if not user or await check_jail(update, user):
        return
    text = "🛒 <b>Магазин</b>\n\n"
    for name, info in SHOP.items():
        text += f"<b>{name}</b> — {info['price']:,}$\n{info['desc']}\n\n"
    text += "Купить: <code>купить вода</code>"
    await update.message.reply_text(text, parse_mode="HTML")


async def buy(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = get_user(update.effective_user.id)
    if not user or await check_jail(update, user):
        return
    item = update.message.text.lower().strip()[7:].strip()
    if item not in SHOP:
        await update.message.reply_text("Такого товара нет.")
        return
    price = SHOP[item]["price"]
    if user["cash"] < price:
        await update.message.reply_text(f"Нужно {price:,}$")
        return
    user["cash"] -= price
    inv = user.setdefault("inventory", {})
    inv[item] = inv.get(item, 0) + 1
    save_user(update.effective_user.id, user)
    await update.message.reply_text(f"✅ {item} за {price:,}$")


# ==================== БАНК ====================
async def bank_deposit(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = get_user(update.effective_user.id)
    if not user or await check_jail(update, user):
        return
    try:
        amount = int(update.message.text.split()[1])
        if amount <= 0: raise ValueError
    except:
        await update.message.reply_text("положить 1000")
        return
    if user["cash"] < amount:
        await update.message.reply_text("Недостаточно наличных.")
        return
    user["cash"] -= amount
    user["bank"] += amount
    save_user(update.effective_user.id, user)
    await update.message.reply_text(f"✅ +{amount:,}$ в банк")


async def bank_withdraw(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = get_user(update.effective_user.id)
    if not user or await check_jail(update, user):
        return
    try:
        amount = int(update.message.text.split()[1])
        if amount <= 0: raise ValueError
    except:
        await update.message.reply_text("снять 500")
        return
    if user["bank"] < amount:
        await update.message.reply_text("Недостаточно в банке.")
        return
    user["bank"] -= amount
    user["cash"] += amount
    save_user(update.effective_user.id, user)
    await update.message.reply_text(f"✅ Снято {amount:,}$")


# ==================== ПЕРЕВОД ====================
async def transfer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = get_user(update.effective_user.id)
    if not user or await check_jail(update, user):
        return
    if not update.message.reply_to_message:
        await update.message.reply_text("Ответь на сообщение:\nпередать 1000")
        return
    try:
        amount = int(update.message.text.split()[1])
        if amount <= 0: raise ValueError
    except:
        await update.message.reply_text("передать 1000")
        return
    if user["cash"] < amount:
        await update.message.reply_text("Недостаточно наличных.")
        return
    target_id = update.message.reply_to_message.from_user.id
    target = get_user(target_id)
    if not target or target_id == update.effective_user.id:
        await update.message.reply_text("Нельзя.")
        return
    user["cash"] -= amount
    target["cash"] += amount
    save_user(update.effective_user.id, user)
    save_user(target_id, target)
    await update.message.reply_text(f"✅ {amount:,}$ → {target['nickname']}")


# ==================== РАБОТЫ ====================
async def job(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = get_user(update.effective_user.id)
    if not user or await check_jail(update, user):
        return
    now = time.time()
    if now - user.get("last_job", 0) < JOB_COOLDOWN:
        left = int(JOB_COOLDOWN - (now - user["last_job"]))
        await update.message.reply_text(f"⏳ {left} сек.")
        return

    job_level = user.get("job_level", 1)
    boost = 1.9 if user.get("boost_until", 0) > now else 1.0
    level_msg = ""

    if job_level == 1:
        salary = int(MINE_SALARY * boost)
        user["mine_works"] = user.get("mine_works", 0) + 1
        job_name = "шахте"
        if user["mine_works"] >= 100:
            user["job_level"] = 2
            level_msg = "\n🎉 Открыта Ферма!"
    elif job_level == 2:
        salary = int(random.randint(FARM_SALARY_MIN, FARM_SALARY_MAX) * boost)
        user["farm_works"] = user.get("farm_works", 0) + 1
        job_name = "ферме"
        if user["farm_works"] >= 500:
            user["job_level"] = 3
            level_msg = "\n🎉 Открыта Полиция!"
    else:
        salary = int(random.randint(POLICE_SALARY_MIN, POLICE_SALARY_MAX) * boost)
        user["police_works"] = user.get("police_works", 0) + 1
        job_name = "полиции"

    user["cash"] += salary
    user["last_job"] = now
    save_user(update.effective_user.id, user)
    await update.message.reply_text(f"Работа на {job_name}: +{salary:,}${level_msg}")


# ==================== АВТОСАЛОН ====================
async def cars_shop(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = get_user(update.effective_user.id)
    if not user or await check_jail(update, user):
        return
    slots = get_garage_slots(user)
    cars_count = len(user.get("cars", []))
    text = f"🚗 <b>Автосалон</b>\nГараж: {cars_count}/{slots}\n\n"
    for name, info in CARS.items():
        text += f"<b>{name.title()}</b> — {info['price']:,}$ ({info['speed']} км/ч)\n"
    text += "\nКупить: <code>купить машину матиз</code>"
    await update.message.reply_text(text, parse_mode="HTML")


async def buy_car(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = get_user(update.effective_user.id)
    if not user or await check_jail(update, user):
        return
    car_name = update.message.text.lower().replace("купить машину", "").strip()
    if car_name not in CARS:
        await update.message.reply_text("Такой машины нет.")
        return

    slots = get_garage_slots(user)
    cars = user.setdefault("cars", [])
    if len(cars) >= slots:
        await update.message.reply_text(f"Гараж полон ({slots} мест). Купи дом побольше.")
        return

    price = CARS[car_name]["price"]
    if user["cash"] + user["bank"] < price:
        await update.message.reply_text(f"Нужно {price:,}$")
        return
    if user["cash"] >= price:
        user["cash"] -= price
    else:
        remaining = price - user["cash"]
        user["cash"] = 0
        user["bank"] -= remaining

    cars.append({"name": car_name, "speed": CARS[car_name]["speed"]})
    save_user(update.effective_user.id, user)
    await update.message.reply_text(f"✅ Куплена <b>{car_name.title()}</b>\nГараж: {len(cars)}/{slots}", parse_mode="HTML")


# ==================== ЧЁРНЫЙ РЫНОК ====================
async def black_market(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = get_user(update.effective_user.id)
    if not user or await check_jail(update, user):
        return
    text = "🕶 <b>Чёрный рынок</b>\n\n"
    text += "<b>Оружие</b> (шанс успешного ограбления):\n"
    for name, info in WEAPONS.items():
        text += f"• {name.title()} — {info['price']:,}$ ({info['chance']}%)\n"
    text += f"\n• Бронежилет — {ARMOR_PRICE:,}$\n\n"
    text += "<code>купить оружие пистолет</code>\n<code>купить бронежилет</code>"
    await update.message.reply_text(text, parse_mode="HTML")


async def buy_weapon(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = get_user(update.effective_user.id)
    if not user or await check_jail(update, user):
        return
    name = update.message.text.lower().replace("купить оружие", "").strip()
    if name not in WEAPONS:
        await update.message.reply_text("Нет такого оружия.")
        return
    price = WEAPONS[name]["price"]
    if user["cash"] < price:
        await update.message.reply_text(f"Нужно {price:,}$")
        return
    user["cash"] -= price
    user["weapon"] = name
    save_user(update.effective_user.id, user)
    await update.message.reply_text(f"✅ {name.title()} (шанс {WEAPONS[name]['chance']}%)")


async def buy_armor(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = get_user(update.effective_user.id)
    if not user or await check_jail(update, user):
        return
    if user.get("armor"):
        await update.message.reply_text("Уже есть.")
        return
    if user["cash"] < ARMOR_PRICE:
        await update.message.reply_text(f"Нужно {ARMOR_PRICE:,}$")
        return
    user["cash"] -= ARMOR_PRICE
    user["armor"] = True
    save_user(update.effective_user.id, user)
    await update.message.reply_text("✅ Бронежилет куплен!")


# ==================== ОГРАБЛЕНИЕ ====================
async def rob(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = get_user(update.effective_user.id)
    if not user or await check_jail(update, user):
        return
    if not user.get("weapon"):
        await update.message.reply_text("Нет оружия.")
        return
    if not update.message.reply_to_message:
        await update.message.reply_text("Ответь на сообщение:\nограбить")
        return
    target_id = update.message.reply_to_message.from_user.id
    if target_id == update.effective_user.id:
        await update.message.reply_text("Нельзя.")
        return
    target = get_user(target_id)
    if not target or is_in_jail(target) or target["cash"] < 1000:
        await update.message.reply_text("Нельзя ограбить.")
        return

    chance = WEAPONS[user["weapon"]]["chance"]
    if target.get("armor"):
        chance = max(10, chance - 15)

    if random.randint(1, 100) <= chance:
        stolen = max(1000, int(target["cash"] * random.uniform(0.3, 0.7)))
        target["cash"] -= stolen
        user["cash"] += stolen
        save_user(target_id, target)
        if random.random() < 0.5:
            user["jail_until"] = time.time() + JAIL_TIME
            save_user(update.effective_user.id, user)
            await update.message.reply_text(f"💰 +{stolen:,}$ у {target['nickname']}\nНо попал в тюрьму.")
        else:
            save_user(update.effective_user.id, user)
            await update.message.reply_text(f"💰 Успех! +{stolen:,}$")
    else:
        if random.random() < 0.7:
            user["jail_until"] = time.time() + JAIL_TIME
            save_user(update.effective_user.id, user)
            await update.message.reply_text("❌ Провал. Тюрьма.")
        else:
            await update.message.reply_text("❌ Провал, но убежал.")


async def bail(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = get_user(update.effective_user.id)
    if not user or not is_in_jail(user):
        await update.message.reply_text("Ты не в тюрьме.")
        return
    if user["cash"] + user["bank"] < BAIL_PRICE:
        await update.message.reply_text(f"Нужно {BAIL_PRICE:,}$")
        return
    if user["cash"] >= BAIL_PRICE:
        user["cash"] -= BAIL_PRICE
    else:
        user["bank"] -= (BAIL_PRICE - user["cash"])
        user["cash"] = 0
    user["jail_until"] = 0
    save_user(update.effective_user.id, user)
    await update.message.reply_text(f"✅ Свободен! (-{BAIL_PRICE:,}$)")


# ==================== БИЗНЕСЫ ====================
async def businesses_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = get_user(update.effective_user.id)
    if not user or await check_jail(update, user):
        return
    text = "💼 <b>Бизнесы</b> (доход раз в час)\n\n"
    for name, info in BUSINESSES.items():
        text += f"<b>{name.title()}</b> — {info['price']:,}$ ({info['income']:,}$/ч)\n"
    text += "\n<code>купить бизнес банкомат</code>\n<code>собрать</code>"
    await update.message.reply_text(text, parse_mode="HTML")


async def buy_business(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = get_user(update.effective_user.id)
    if not user or await check_jail(update, user):
        return
    name = update.message.text.lower().replace("купить бизнес", "").strip()
    if name not in BUSINESSES:
        await update.message.reply_text("Нет такого бизнеса.")
        return
    price = BUSINESSES[name]["price"]
    if user["cash"] + user["bank"] < price:
        await update.message.reply_text(f"Нужно {price:,}$")
        return
    if user["cash"] >= price:
        user["cash"] -= price
    else:
        user["bank"] -= (price - user["cash"])
        user["cash"] = 0
    user.setdefault("businesses", []).append(name)
    if not user.get("business_last_collect"):
        user["business_last_collect"] = time.time()
    save_user(update.effective_user.id, user)
    await update.message.reply_text(f"✅ {name.title()} куплен!")


async def collect_income(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = get_user(update.effective_user.id)
    if not user or await check_jail(update, user):
        return
    businesses = user.get("businesses", [])
    if not businesses:
        await update.message.reply_text("Нет бизнесов.")
        return
    last = user.get("business_last_collect", time.time())
    hours = (time.time() - last) / 3600
    if hours < 1:
        await update.message.reply_text(f"Ещё {int((1-hours)*60)} мин.")
        return
    total = sum(int(BUSINESSES[b]["income"] * hours) for b in businesses if b in BUSINESSES)
    user["cash"] += total
    user["business_last_collect"] = time.time()
    save_user(update.effective_user.id, user)
    await update.message.reply_text(f"💰 Собрано: {total:,}$")


# ==================== ДОМА ====================
async def houses_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = get_user(update.effective_user.id)
    if not user or await check_jail(update, user):
        return
    text = "🏠 <b>Дома</b>\nЧем дороже дом — тем больше гаражных мест\n\n"
    for name, info in HOUSES.items():
        text += f"<b>{name.title()}</b>\n{info['price']:,}$ — {info['slots']} мест в гараже\n\n"
    text += "Купить: <code>купить дом квартира</code> или <code>купить дом вилла</code>"
    await update.message.reply_text(text, parse_mode="HTML")


async def buy_house(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = get_user(update.effective_user.id)
    if not user or await check_jail(update, user):
        return
    name = update.message.text.lower().replace("купить дом", "").strip()
    if name not in HOUSES:
        await update.message.reply_text("Такого дома нет.")
        return
    price = HOUSES[name]["price"]
    if user["cash"] + user["bank"] < price:
        await update.message.reply_text(f"Нужно {price:,}$")
        return
    if user["cash"] >= price:
        user["cash"] -= price
    else:
        user["bank"] -= (price - user["cash"])
        user["cash"] = 0

    slots = HOUSES[name]["slots"]
    user.setdefault("houses", []).append({"name": name, "slots": slots})
    save_user(update.effective_user.id, user)

    total_slots = get_garage_slots(user)
    await update.message.reply_text(
        f"✅ Куплен дом <b>{name.title()}</b>\n"
        f"Гаражных мест в нём: {slots}\n"
        f"Всего мест в гараже: {total_slots}",
        parse_mode="HTML"
    )


# ==================== ТОП И ПРОЧЕЕ ====================
async def top(update: Update, context: ContextTypes.DEFAULT_TYPE):
    data = load_data()
    players = [(u.get("nickname", "?"), u.get("cash", 0) + u.get("bank", 0)) for u in data.values()]
    players.sort(key=lambda x: x[1], reverse=True)
    text = "🏆 <b>Топ:</b>\n\n"
    for i, (name, money) in enumerate(players[:10], 1):
        text += f"{i}. {name} — {money:,}$\n"
    await update.message.reply_text(text, parse_mode="HTML")


async def promo_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = get_user(update.effective_user.id)
    if not user:
        await update.message.reply_text("Сначала /start")
        return
    if user.get("cash", 0) >= START_BONUS or user.get("boost_until", 0) > time.time():
        await update.message.reply_text("Уже активирован.")
        return
    user["cash"] += START_BONUS
    user["boost_until"] = time.time() + START_BOOST_HOURS * 3600
    save_user(update.effective_user.id, user)
    await update.message.reply_text(f"🎁 +{START_BONUS:,}$ + буст!")


# ==================== КОЛЕСО ФОРТУНЫ ====================
async def wheel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = get_user(update.effective_user.id)
    if not user:
        await update.message.reply_text("Сначала /start")
        return
    if await check_jail(update, user):
        return

    now = time.time()
    last = user.get("last_wheel", 0)
    if now - last < WHEEL_COOLDOWN:
        left = int(WHEEL_COOLDOWN - (now - last))
        hours = left // 3600
        mins = (left % 3600) // 60
        await update.message.reply_text(f"🎡 Колесо будет доступно через {hours}ч {mins}мин.")
        return

    user["last_wheel"] = now
    roll = random.random() * 100

    if roll < 0.5:  # 0.5% — машина
        car_name = random.choice(list(CARS.keys()))
        slots = get_garage_slots(user)
        cars = user.setdefault("cars", [])
        if len(cars) < slots:
            cars.append({"name": car_name, "speed": CARS[car_name]["speed"]})
            result = f"🚗 ДЖЕКПОТ! Выпала машина <b>{car_name.title()}</b>!"
        else:
            prize = 500000
            user["cash"] += prize
            result = f"🚗 Выпала машина, но гараж полон.\nВместо неё +{prize:,}$"
    elif roll < 15:  # 14.5% — хороший приз
        prize = random.randint(50000, 150000)
        user["cash"] += prize
        result = f"💰 Хороший приз! +{prize:,}$"
    elif roll < 45:  # 30% — средний
        prize = random.randint(10000, 40000)
        user["cash"] += prize
        result = f"💵 +{prize:,}$"
    elif roll < 70:  # 25% — буст
        user["boost_until"] = now + 3600
        result = "🔥 Буст к зарплате +50% на 1 час!"
    else:  # 30% — ничего особенного
        prize = random.randint(2000, 8000)
        user["cash"] += prize
        result = f"😐 Мелочь: +{prize:,}$"

    save_user(update.effective_user.id, user)
    await update.message.reply_text(f"🎡 Колесо крутится...\n\n{result}", parse_mode="HTML")


# ==================== ПРОДАЖА ИМУЩЕСТВА ====================
async def sell_car(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = get_user(update.effective_user.id)
    if not user or await check_jail(update, user):
        return

    cars = user.get("cars", [])
    if not cars:
        await update.message.reply_text("У тебя нет машин.")
        return

    # продажа машина 1  (по номеру)
    try:
        num = int(update.message.text.split()[-1]) - 1
        if num < 0 or num >= len(cars):
            raise ValueError
    except:
        text = "Твои машины:\n"
        for i, c in enumerate(cars, 1):
            price = CARS.get(c["name"], {}).get("price", 0) // 2
            text += f"{i}. {c['name'].title()} — продать за {price:,}$\n"
        text += "\nЧтобы продать: <code>продать машину 1</code>"
        await update.message.reply_text(text, parse_mode="HTML")
        return

    car = cars.pop(num)
    sell_price = CARS.get(car["name"], {}).get("price", 0) // 2
    user["cash"] += sell_price
    save_user(update.effective_user.id, user)
    await update.message.reply_text(f"✅ Продана {car['name'].title()} за {sell_price:,}$")


async def sell_house(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = get_user(update.effective_user.id)
    if not user or await check_jail(update, user):
        return

    houses = user.get("houses", [])
    if not houses:
        await update.message.reply_text("У тебя нет домов.")
        return

    try:
        num = int(update.message.text.split()[-1]) - 1
        if num < 0 or num >= len(houses):
            raise ValueError
    except:
        text = "Твои дома:\n"
        for i, h in enumerate(houses, 1):
            price = HOUSES.get(h["name"], {}).get("price", 0) // 2
            text += f"{i}. {h['name'].title()} — продать за {price:,}$\n"
        text += "\nЧтобы продать: <code>продать дом 1</code>"
        await update.message.reply_text(text, parse_mode="HTML")
        return

    # Проверяем, хватит ли слотов после продажи
    house = houses[num]
    new_slots = get_garage_slots(user) - house["slots"]
    if new_slots < 1:
        new_slots = 1
    if len(user.get("cars", [])) > new_slots:
        await update.message.reply_text("Сначала продай лишние машины, иначе они не влезут в гараж.")
        return

    houses.pop(num)
    sell_price = HOUSES.get(house["name"], {}).get("price", 0) // 2
    user["cash"] += sell_price
    save_user(update.effective_user.id, user)
    await update.message.reply_text(f"✅ Продан дом {house['name'].title()} за {sell_price:,}$")


async def sell_business(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = get_user(update.effective_user.id)
    if not user or await check_jail(update, user):
        return

    businesses = user.get("businesses", [])
    if not businesses:
        await update.message.reply_text("У тебя нет бизнесов.")
        return

    try:
        num = int(update.message.text.split()[-1]) - 1
        if num < 0 or num >= len(businesses):
            raise ValueError
    except:
        text = "Твои бизнесы:\n"
        for i, b in enumerate(businesses, 1):
            price = BUSINESSES.get(b, {}).get("price", 0) // 2
            text += f"{i}. {b.title()} — продать за {price:,}$\n"
        text += "\nЧтобы продать: <code>продать бизнес 1</code>"
        await update.message.reply_text(text, parse_mode="HTML")
        return

    b_name = businesses.pop(num)
    sell_price = BUSINESSES.get(b_name, {}).get("price", 0) // 2
    user["cash"] += sell_price
    save_user(update.effective_user.id, user)
    await update.message.reply_text(f"✅ Продан бизнес {b_name.title()} за {sell_price:,}$")


async def commands_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (
        "📋 <b>Команды</b>\n\n"
        "👤 Профиль | 🎒 Инвентарь\n"
        "🛒 Магазин | ⛏ Работа\n"
        "🚗 Автосалон | 🕶 Чёрный рынок\n"
        "💼 Бизнесы | 🏠 Дома | 🎡 Колесо\n"
        "🏆 Топ\n\n"
        "ограбить | откупиться | собрать\n"
        "купить бизнес банкомат\n"
        "купить дом квартира / вилла\n"
        "купить машину матиз\n"
        "продать машину 1\n"
        "продать дом 1\n"
        "продать бизнес 1\n"
        "положить 1000 | снять 500\n"
        "передать 1000 | использовать вода\n"
        "профиль Ник | START"
    )
    await update.message.reply_text(text, parse_mode="HTML")


async def text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip().lower()

    if text in ("👤 профиль", "профиль"):
        await profile(update, context)
    elif text.startswith("профиль "):
        await view_profile(update, context)
    elif text in ("🎒 инвентарь", "инвентарь"):
        await inventory(update, context)
    elif text in ("🛒 магазин", "магазин"):
        await shop(update, context)
    elif text in ("⛏ работа", "работа"):
        await job(update, context)
    elif text in ("🚗 автосалон", "автосалон"):
        await cars_shop(update, context)
    elif text in ("🕶 чёрный рынок", "черный рынок", "чёрный рынок"):
        await black_market(update, context)
    elif text in ("💼 бизнесы", "бизнесы"):
        await businesses_menu(update, context)
    elif text in ("🏠 дома", "дома"):
        await houses_menu(update, context)
    elif text in ("🎡 колесо", "колесо"):
        await wheel(update, context)
    elif text in ("🏆 топ", "топ"):
        await top(update, context)
    elif text in ("📋 команды", "команды"):
        await commands_list(update, context)
    elif text == "start":
        await promo_start(update, context)
    elif text == "ограбить":
        await rob(update, context)
    elif text == "откупиться":
        await bail(update, context)
    elif text == "собрать":
        await collect_income(update, context)
    elif text.startswith("продать машину"):
        await sell_car(update, context)
    elif text.startswith("продать дом"):
        await sell_house(update, context)
    elif text.startswith("продать бизнес"):
        await sell_business(update, context)
    elif text.startswith("купить дом"):
        await buy_house(update, context)
    elif text.startswith("купить бизнес"):
        await buy_business(update, context)
    elif text.startswith("купить оружие"):
        await buy_weapon(update, context)
    elif text == "купить бронежилет":
        await buy_armor(update, context)
    elif text.startswith("купить машину"):
        await buy_car(update, context)
    elif text.startswith("купить "):
        await buy(update, context)
    elif text.startswith("использовать "):
        await use_item(update, context)
    elif text.startswith("положить "):
        await bank_deposit(update, context)
    elif text.startswith("снять "):
        await bank_withdraw(update, context)
    elif text.startswith("передать "):
        await transfer(update, context)


def main():
    app = Application.builder().token(TOKEN).build()
    conv = ConversationHandler(
        entry_points=[CommandHandler("start", start)],
        states={
            NICKNAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, process_nickname)],
            NATIONALITY: [MessageHandler(filters.TEXT & ~filters.COMMAND, process_nationality)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )
    app.add_handler(conv)
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_handler))
    print("Бот запущен...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
