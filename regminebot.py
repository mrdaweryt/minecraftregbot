import os
import logging
from aiogram import Bot, Dispatcher, types, F
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import Update
from aiogram.filters import Command
from aiogram.client.default import DefaultBotProperties
from aiohttp import web

logging.basicConfig(level=logging.INFO)

# --- 1. НАСТРОЙКИ ---
BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_CHAT_ID_RAW = os.getenv("ADMIN_CHAT_ID")
WEBHOOK_HOST = os.getenv("WEBHOOK_URL")

try:
    ADMIN_CHAT_ID = int(ADMIN_CHAT_ID_RAW)
except (TypeError, ValueError):
    ADMIN_CHAT_ID = None
    logging.error("ADMIN_CHAT_ID отсутствует или недействителен.")

WEBHOOK_PATH = '/'
WEBAPP_HOST = '0.0.0.0'
WEBAPP_PORT = int(os.getenv("PORT", 8080))

# --- 2. ИНИЦИАЛИЗАЦИЯ ---
storage = MemoryStorage() 
dp = Dispatcher(storage=storage)

# --- 3. FSM ---
class ApplicationStates(StatesGroup):
    waiting_for_minecraft_nick = State()
    waiting_for_discord_nick = State()
    waiting_for_source = State()
    waiting_for_activity = State()

# --- 4. ОБРАБОТЧИКИ ---

@dp.message(Command("start")) 
async def send_welcome(message: types.Message):
    keyboard = types.InlineKeyboardMarkup(inline_keyboard=[
        [types.InlineKeyboardButton(text="📝 Подать заявку", callback_data="start_application")]
    ])
    await message.answer("Добро пожаловать! Нажмите кнопку, чтобы начать.", reply_markup=keyboard)

@dp.callback_query(F.data == "start_application")
async def start_application(call: types.CallbackQuery, state: FSMContext):
    await call.message.edit_text("Отлично! **Ваш никнейм в Minecraft?**")
    await state.set_state(ApplicationStates.waiting_for_minecraft_nick)
    await call.answer()

@dp.message(ApplicationStates.waiting_for_minecraft_nick, F.text)
async def process_mc_nick(message: types.Message, state: FSMContext):
    await state.update_data(mc_nick=message.text)
    await message.answer("Хорошо. **Ваш никнейм в Discord (включая тег)?**")
    await state.set_state(ApplicationStates.waiting_for_discord_nick)

@dp.message(ApplicationStates.waiting_for_discord_nick, F.text)
async def process_discord_nick(message: types.Message, state: FSMContext):
    await state.update_data(discord_nick=message.text)
    await message.answer("Почти готово. **Где Вы узнали о нашем сервере?**")
    await state.set_state(ApplicationStates.waiting_for_source)

@dp.message(ApplicationStates.waiting_for_source, F.text)
async def process_source(message: types.Message, state: FSMContext):
    await state.update_data(source=message.text)
    await message.answer("Последний вопрос: **Чем планируете заниматься на сервере?**")
    await state.set_state(ApplicationStates.waiting_for_activity)

@dp.message(ApplicationStates.waiting_for_activity, F.text)
async def process_activity(message: types.Message, state: FSMContext):
    await state.update_data(activity=message.text)
    data = await state.get_data()
    
    await message.answer("Спасибо! Ваша заявка принята и отправлена на рассмотрение.")
    await state.clear()
    
    application_text = (
        "🔥 **НОВАЯ ЗАЯВКА** 🔥\n\n"
        f"**User:** @{message.from_user.username or message.from_user.id}\n"
        f"**MC:** `{data['mc_nick']}`\n"
        f"**DC:** `{data['discord_nick']}`\n"
        f"**Info:** {data['source']}\n"
        f"**Plan:** {data['activity']}\n"
    )

    admin_keyboard = types.InlineKeyboardMarkup(inline_keyboard=[
        [types.InlineKeyboardButton("✅ ОДОБРИТЬ", callback_data=f"approve_{message.from_user.id}"),
         types.InlineKeyboardButton("❌ ОТКЛОНИТЬ", callback_data=f"reject_{message.from_user.id}")]
    ])
    
    if ADMIN_CHAT_ID:
        await message.bot.send_message(chat_id=ADMIN_CHAT_ID, text=application_text, reply_markup=admin_keyboard, parse_mode='Markdown')

@dp.callback_query(lambda c: c.data and (c.data.startswith('approve_') or c.data.startswith('reject_')))
async def process_admin_decision(call: types.CallbackQuery):
    action, user_id = call.data.split('_')
    
    if action == 'approve':
        await call.bot.send_message(user_id, "🥳 **Ваша заявка одобрена!** /start")
        await call.answer("Одобрено", show_alert=True)
    elif action == 'reject':
        await call.bot.send_message(user_id, "😔 **Заявка отклонена.**")
        await call.answer("Отклонено", show_alert=True)

    await call.message.edit_text(
        call.message.text + f"\n\n**СТАТУС:** {'✅' if action == 'approve' else '❌'} (Модератор: {call.from_user.full_name})", 
        reply_markup=None, parse_mode='Markdown'
    )

# --- 5. ЗАПУСК ---

async def on_startup(bot: Bot):
    if WEBHOOK_HOST:
        await bot.set_webhook(f"{WEBHOOK_HOST}{WEBHOOK_PATH}")
        logging.info(f"Webhook установлен: {WEBHOOK_HOST}{WEBHOOK_PATH}")

async def on_shutdown(bot: Bot):
    await bot.delete_webhook()
    await bot.session.close()
    logging.info("Webhook удален.")

async def handle_webhook(request):
    update_json = await request.json()
    update = Update.model_validate(update_json) 
    await dp.feed_update(bot=app['bot'], update=update)
    return web.Response()

# --- НОВАЯ ФУНКЦИЯ HEALTH CHECK ---
async def health_check(request):
    return web.Response(text="Bot is alive!", status=200)

if __name__ == '__main__':
    if not all([BOT_TOKEN, ADMIN_CHAT_ID_RAW, WEBHOOK_HOST]):
        logging.error("ОШИБКА: Проверьте переменные окружения!")
    else:
        bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode='HTML'))
        app = web.Application()
        app['bot'] = bot

        # Регистрируем маршруты
        app.router.add_post(WEBHOOK_PATH, handle_webhook) # Для Telegram
        app.router.add_get('/', health_check)             # Для Render Health Check (ГЛАВНОЕ ИСПРАВЛЕНИЕ)
        app.router.add_get('/health', health_check)       # Доп. проверка

        app.on_startup.append(lambda app: on_startup(app['bot']))
        app.on_shutdown.append(lambda app: on_shutdown(app['bot']))

        logging.info("Starting AIOHTTP web application...")
        web.run_app(app, host=WEBAPP_HOST, port=WEBAPP_PORT)
