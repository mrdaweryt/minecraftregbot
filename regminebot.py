import os
import logging
from aiogram import Bot, Dispatcher, types, F
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import Update
from aiogram.filters import Command
from aiogram.client.default import DefaultBotProperties # <-- НОВЫЙ ИМПОРТ ДЛЯ parse_mode
from aiohttp import web

# Установим уровень логирования
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

# --- 2. ИНИЦИАЛИЗАЦИЯ ДИСПЕТЧЕРА ---
storage = MemoryStorage() 
dp = Dispatcher(storage=storage)

# --- 3. FSM (Finite State Machine) - Состояния для анкеты ---
class ApplicationStates(StatesGroup):
    waiting_for_minecraft_nick = State()
    waiting_for_discord_nick = State()
    waiting_for_source = State()
    waiting_for_activity = State()

# --- 4. ОБРАБОТЧИКИ КОМАНД И СООБЩЕНИЙ ---

@dp.message(Command("start")) 
async def send_welcome(message: types.Message):
    """Обработка команды /start"""
    keyboard = types.InlineKeyboardMarkup(inline_keyboard=[
        [types.InlineKeyboardButton(text="📝 Подать заявку", callback_data="start_application")]
    ])
    
    await message.answer(
        "Добро пожаловать в систему подачи заявок! Нажмите кнопку, чтобы начать.",
        reply_markup=keyboard
    )

@dp.callback_query(F.data == "start_application")
async def start_application(call: types.CallbackQuery, state: FSMContext):
    """Запуск процесса анкетирования"""
    await call.message.edit_text("Отлично! **Ваш никнейм в Minecraft?**")
    await state.set_state(ApplicationStates.waiting_for_minecraft_nick)
    await call.answer()

@dp.message(ApplicationStates.waiting_for_minecraft_nick, F.text)
async def process_mc_nick(message: types.Message, state: FSMContext):
    """Шаг 1: Получаем ник в Minecraft"""
    await state.update_data(mc_nick=message.text)
    await message.answer("Хорошо. **Ваш никнейм в Discord (включая тег)?**")
    await state.set_state(ApplicationStates.waiting_for_discord_nick)

@dp.message(ApplicationStates.waiting_for_discord_nick, F.text)
async def process_discord_nick(message: types.Message, state: FSMContext):
    """Шаг 2: Получаем ник в Discord"""
    await state.update_data(discord_nick=message.text)
    await message.answer("Почти готово. **Где Вы узнали о нашем сервере?**")
    await state.set_state(ApplicationStates.waiting_for_source)

@dp.message(ApplicationStates.waiting_for_source, F.text)
async def process_source(message: types.Message, state: FSMContext):
    """Шаг 3: Получаем источник"""
    await state.update_data(source=message.text)
    await message.answer("Последний вопрос: **Чем планируете заниматься на сервере?**")
    await state.set_state(ApplicationStates.waiting_for_activity)

@dp.message(ApplicationStates.waiting_for_activity, F.text)
async def process_activity(message: types.Message, state: FSMContext):
    """Шаг 4: Получаем планы и отправляем заявку"""
    await state.update_data(activity=message.text)
    data = await state.get_data()
    
    await message.answer("Спасибо! Ваша заявка принята и отправлена на рассмотрение. Мы сообщим Вам о решении.")
    await state.clear()
    
    # --- ФОРМИРОВАНИЕ И ОТПРАВКА ЗАЯВКИ АДМИНАМ ---
    application_text = (
        "🔥 **НОВАЯ ЗАЯВКА НА СЕРВЕР** 🔥\n\n"
        f"**От Пользователя:** @{message.from_user.username or message.from_user.id}\n"
        f"**ID Telegram:** `{message.from_user.id}`\n\n"
        f"**MC Ник:** `{data['mc_nick']}`\n"
        f"**Discord Ник:** `{data['discord_nick']}`\n"
        f"**Источник:** {data['source']}\n"
        f"**Планы на сервере:** {data['activity']}\n"
    )

    admin_keyboard = types.InlineKeyboardMarkup(inline_keyboard=[
        [types.InlineKeyboardButton("✅ ОДОБРИТЬ", callback_data=f"approve_{message.from_user.id}"),
         types.InlineKeyboardButton("❌ ОТКЛОНИТЬ", callback_data=f"reject_{message.from_user.id}")]
    ])
    
    if ADMIN_CHAT_ID:
        await message.bot.send_message(
            chat_id=ADMIN_CHAT_ID,
            text=application_text,
            reply_markup=admin_keyboard,
            parse_mode='Markdown'
        )

@dp.callback_query(lambda c: c.data and (c.data.startswith('approve_') or c.data.startswith('reject_')))
async def process_admin_decision(call: types.CallbackQuery):
    action, user_id = call.data.split('_')
    
    if action == 'approve':
        await call.bot.send_message(user_id, "🥳 **Поздравляем! Ваша заявка одобрена!** Теперь вам доступно меню сервера. /start")
        await call.answer("Заявка одобрена.", show_alert=True)
    elif action == 'reject':
        await call.bot.send_message(user_id, "😔 **К сожалению, Ваша заявка отклонена.** Вы можете попробовать позже.")
        await call.answer("Заявка отклонена.", show_alert=True)

    await call.message.edit_text(
        call.message.text + f"\n\n**СТАТУС:** {'✅ Одобрено' if action == 'approve' else '❌ Отклонено'} (Модератор: {call.from_user.full_name})", 
        reply_markup=None, 
        parse_mode='Markdown'
    )

# --- 5. ЗАПУСК БОТА (Webhooks) ---

async def on_startup(bot: Bot):
    """Устанавливаем Webhook при запуске"""
    if WEBHOOK_HOST:
        await bot.set_webhook(f"{WEBHOOK_HOST}{WEBHOOK_PATH}")
        logging.info(f"Webhook установлен: {WEBHOOK_HOST}{WEBHOOK_PATH}")

async def on_shutdown(bot: Bot):
    """Снимаем Webhook при отключении"""
    await bot.delete_webhook()
    logging.info("Webhook удален.")

async def handle_webhook(request):
    """Обработка входящих Webhook-запросов от Telegram"""
    
    update_json = await request.json()
    update = Update.model_validate(update_json) 
    await dp.feed_update(update, bot=app['bot'])
    
    return web.Response()


if __name__ == '__main__':
    if not all([BOT_TOKEN, ADMIN_CHAT_ID_RAW, WEBHOOK_HOST]):
        logging.error("ОШИБКА: Не все переменные окружения установлены! BOT_TOKEN, ADMIN_CHAT_ID и WEBHOOK_URL обязательны.")
    else:
        # ИСПРАВЛЕНО: Используем DefaultBotProperties для parse_mode
        bot = Bot(
            token=BOT_TOKEN, 
            default=DefaultBotProperties(parse_mode='HTML')
        )
        
        app = web.Application()
        app['bot'] = bot

        app.router.add_post(WEBHOOK_PATH, handle_webhook)

        app.on_startup.append(lambda app: on_startup(app['bot']))
        app.on_shutdown.append(lambda app: on_shutdown(app['bot']))

        logging.info("Starting AIOHTTP web application...")
        web.run_app(
            app,
            host=WEBAPP_HOST,
            port=WEBAPP_PORT
        )
