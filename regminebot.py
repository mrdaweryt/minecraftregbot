import os
from aiogram import Bot, Dispatcher, types
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.dispatcher import FSMContext
from aiogram.dispatcher.filters.state import State, StatesGroup
from aiogram.utils.executor import start_webhook

# --- 1. НАСТРОЙКИ ---
# Получаем переменные окружения, которые вы настроили на Render
BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_CHAT_ID = os.getenv("ADMIN_CHAT_ID")
WEBHOOK_HOST = os.getenv("WEBHOOK_URL")

# Настройки Webhook (стандартные для Render)
WEBHOOK_PATH = '/'
WEBAPP_HOST = '0.0.0.0'
WEBAPP_PORT = os.getenv("PORT", 8080) # Render использует переменную PORT

# --- 2. ИНИЦИАЛИЗАЦИЯ ---
bot = Bot(token=BOT_TOKEN)
# MemoryStorage нужен для хранения состояний FSM
storage = MemoryStorage() 
dp = Dispatcher(bot, storage=storage)

# --- 3. FSM (Finite State Machine) - Состояния для анкеты ---
# Определяем шаги/состояния, через которые пройдет пользователь
class ApplicationStates(StatesGroup):
    waiting_for_minecraft_nick = State()
    waiting_for_discord_nick = State()
    waiting_for_source = State()
    waiting_for_activity = State()
    
# --- 4. ОБРАБОТЧИКИ КОМАНД И СООБЩЕНИЙ ---

@dp.message_handler(commands=['start'], state='*')
async def send_welcome(message: types.Message):
    """Обработка команды /start"""
    # ⚠️ Здесь нужно добавить проверку статуса заявки (ОДОБРЕНА/В РАССМОТРЕНИИ)
    # Сейчас бот просто предложит подать заявку
    
    keyboard = types.InlineKeyboardMarkup()
    keyboard.add(types.InlineKeyboardButton(text="📝 Подать заявку", callback_data="start_application"))
    
    await message.answer(
        "Добро пожаловать в систему подачи заявок! Нажмите кнопку, чтобы начать.",
        reply_markup=keyboard
    )

@dp.callback_query_handler(text="start_application", state='*')
async def start_application(call: types.CallbackQuery):
    """Запуск процесса анкетирования"""
    await call.message.edit_text("Отлично! **Ваш никнейм в Minecraft?**")
    await ApplicationStates.waiting_for_minecraft_nick.set()
    await call.answer()

@dp.message_handler(state=ApplicationStates.waiting_for_minecraft_nick)
async def process_mc_nick(message: types.Message, state: FSMContext):
    """Шаг 1: Получаем ник в Minecraft"""
    await state.update(mc_nick=message.text)
    await message.answer("Хорошо. **Ваш никнейм в Discord (включая тег)?**")
    await ApplicationStates.waiting_for_discord_nick.set()

@dp.message_handler(state=ApplicationStates.waiting_for_discord_nick)
async def process_discord_nick(message: types.Message, state: FSMContext):
    """Шаг 2: Получаем ник в Discord"""
    await state.update(discord_nick=message.text)
    await message.answer("Почти готово. **Где Вы узнали о нашем сервере?**")
    await ApplicationStates.waiting_for_source.set()

@dp.message_handler(state=ApplicationStates.waiting_for_source)
async def process_source(message: types.Message, state: FSMContext):
    """Шаг 3: Получаем источник"""
    await state.update(source=message.text)
    await message.answer("Последний вопрос: **Чем планируете заниматься на сервере?**")
    await ApplicationStates.waiting_for_activity.set()

@dp.message_handler(state=ApplicationStates.waiting_for_activity)
async def process_activity(message: types.Message, state: FSMContext):
    """Шаг 4: Получаем планы и отправляем заявку"""
    await state.update(activity=message.text)
    data = await state.get_data()
    
    await message.answer("Спасибо! Ваша заявка принята и отправлена на рассмотрение. Мы сообщим Вам о решении.")
    await state.finish()
    
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

    # Кнопки для модерации
    admin_keyboard = types.InlineKeyboardMarkup()
    admin_keyboard.add(
        types.InlineKeyboardButton("✅ ОДОБРИТЬ", callback_data=f"approve_{message.from_user.id}"),
        types.InlineKeyboardButton("❌ ОТКЛОНИТЬ", callback_data=f"reject_{message.from_user.id}")
    )
    
    if ADMIN_CHAT_ID:
        await bot.send_message(
            chat_id=ADMIN_CHAT_ID,
            text=application_text,
            reply_markup=admin_keyboard,
            parse_mode='Markdown'
        )
        
# Обработка нажатий кнопок модерации (для администраторов)
@dp.callback_query_handler(lambda c: c.data.startswith('approve_') or c.data.startswith('reject_'))
async def process_admin_decision(call: types.CallbackQuery):
    action, user_id = call.data.split('_')
    
    # ⚠️ В реальном проекте здесь должна быть проверка, что нажал АДМИН
    # и обращение к базе данных для изменения статуса заявки
    
    if action == 'approve':
        await bot.send_message(user_id, "🥳 **Поздравляем! Ваша заявка одобрена!** Теперь вам доступно меню сервера. /start")
        await call.answer("Заявка одобрена.", show_alert=True)
    elif action == 'reject':
        await bot.send_message(user_id, "😔 **К сожалению, Ваша заявка отклонена.** Вы можете попробовать позже.")
        await call.answer("Заявка отклонена.", show_alert=True)

    # Редактируем сообщение в админ-чате, чтобы показать, что оно обработано
    await call.message.edit_text(call.message.text + f"\n\n**СТАТУС:** {'✅ Одобрено' if action == 'approve' else '❌ Отклонено'} (Модератор: {call.from_user.full_name})", 
                                 reply_markup=None, parse_mode='Markdown')

# --- 5. ЗАПУСК БОТА (Webhooks) ---
async def on_startup(dp):
    """Устанавливаем Webhook при запуске"""
    await bot.set_webhook(WEBHOOK_HOST + WEBHOOK_PATH)
    print(f"Webhook установлен: {WEBHOOK_HOST + WEBHOOK_PATH}")

async def on_shutdown(dp):
    """Снимаем Webhook при отключении"""
    # logгирование
    await bot.delete_webhook()

if __name__ == '__main__':
    if not all([BOT_TOKEN, ADMIN_CHAT_ID, WEBHOOK_HOST]):
        print("ОШИБКА: Не все переменные окружения установлены! BOT_TOKEN, ADMIN_CHAT_ID и WEBHOOK_URL обязательны.")
    else:
        # Запуск через Webhook (идеально для Render)
        start_webhook(
            dispatcher=dp,
            webhook_path=WEBHOOK_PATH,
            on_startup=on_startup,
            on_shutdown=on_shutdown,
            host=WEBAPP_HOST,
            port=WEBAPP_PORT,
        )
