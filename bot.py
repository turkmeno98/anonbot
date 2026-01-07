import asyncio
from typing import Dict

from aiogram import Bot, Dispatcher, F, Router
from aiogram.client.default import DefaultBotProperties
from aiogram.filters import CommandStart
from aiogram.types import Message, CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup

# ТВОИ ДАННЫЕ (токен замени на НОВЫЙ!)
BOT_TOKEN = "8430859086:AAEsdPIGXI-xG-6COFj48AUnU69yseZOnZo"  # ← НОВЫЙ ТОКЕН СЮДА
ADMIN_CHAT_ID = -1003267199569  # ← ТВОЙ ID исправлен

bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode="HTML"))
dp = Dispatcher()
router = Router()
dp.include_router(router)

questions_storage: Dict[int, dict] = {}


def make_answer_keyboard(question_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="Ответить", callback_data=f"answer:{question_id}")]]
    )


@router.message(CommandStart())
async def cmd_start(message: Message):
    bot_info = await bot.get_me()
    deep_link = f"https://t.me/{bot_info.username}?start={message.from_user.id}"
    await message.answer(
        f"Привет! Твоя ссылка:
<code>{deep_link}</code>

"
        "Поделись с друзьями для анонимных вопросов."
    )


@router.message(F.text & F.text.startswith("/start"))
async def deep_link(message: Message):
    parts = message.text.split(maxsplit=1)
    if len(parts) < 2:
        return
    
    try:
        target_id = int(parts[1])
    except ValueError:
        return await message.answer("❌ Некорректная ссылка.")
    
    await message.answer("📝 Напиши вопрос.")
    message.bot_data.setdefault("ask_target", {})
    message.bot_data["ask_target"][message.from_user.id] = target_id


@router.message(F.text & ~F.text.startswith("/start"))
async def ask_question(message: Message):
    user = message.from_user
    targets = message.bot_data.setdefault("ask_target", {})
    
    if user.id not in targets:
        return await message.answer("🔗 Перейди по ссылке получателя.")
    
    target_id = targets.pop(user.id)
    text = message.text
    
    # Сохраняем вопрос
    questions_storage[message.message_id] = {"from_id": user.id, "to_id": target_id}
    
    # Получателю
    await bot.send_message(
        target_id,
        f"🗨️ Анонимный вопрос:

<b>{text}</b>",
        reply_markup=make_answer_keyboard(message.message_id)
    )
    
    # Спрашивающему
    await message.answer("✅ Отправлено!")
    
    # Админу
    await bot.send_message(
        ADMIN_CHAT_ID,
        f"❗️ Вопрос
От: {user.full_name} (@{user.username or 'нет'})
"
        f"ID: <code>{user.id}</code>
Кому: <code>{target_id}</code>

{text}"
    )


@router.callback_query(F.data.startswith("answer:"))
async def answer_btn(callback: CallbackQuery):
    q_id = int(callback.data.split(":", 1)[1])
    info = questions_storage.get(q_id)
    
    if not info or info["to_id"] != callback.from_user.id:
        return await callback.answer("❌ Не твой вопрос.")
    
    callback.bot_data.setdefault("answer_target", {})
    callback.bot_data["answer_target"][callback.from_user.id] = info["from_id"]
    
    await callback.message.answer("💬 Напиши ответ.")
    await callback.answer()


@router.message(F.text)
async def send_answer(message: Message):
    user = message.from_user
    targets = message.bot_data.setdefault("answer_target", {})
    
    if user.id not in targets:
        return
    
    asker_id = targets.pop(user.id)
    text = message.text
    
    await bot.send_message(asker_id, f"📩 Ответ:

<b>{text}</b>")
    await message.answer("✅ Отправлено!")
    
    await bot.send_message(
        ADMIN_CHAT_ID,
        f"📩 Ответ
От ID: <code>{user.id}</code>
Кому ID: <code>{asker_id}</code>

{text}"
    )


async def main():
    print("🤖 Bot запущен")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
