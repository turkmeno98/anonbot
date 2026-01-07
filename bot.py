import asyncio
from typing import Dict, Optional

from aiogram import Bot, Dispatcher, F, Router
from aiogram.filters import Command, CommandStart
from aiogram.types import (
    Message,
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
)
from aiogram.utils.deep_linking import decode_payload

# ---------------- НАСТРОЙКИ ----------------

BOT_TOKEN = "8430859086:AAEsdPIGXI-xG-6COFj48AUnU69yseZOnZo"
# ID админской группы/канала, куда будут дублироваться все вопросы/ответы
# Пример: -1001234567890
ADMIN_CHAT_ID = -5103997622

bot = Bot(token=BOT_TOKEN, parse_mode="HTML")
dp = Dispatcher()
router = Router()
dp.include_router(router)

# ---------------- ПРОСТОЕ "ХРАНИЛИЩЕ" В ПАМЯТИ ----------------
# Для простоты без базы: вопрос_id -> {from_id, to_id}
questions_storage: Dict[int, Dict[str, int]] = {}


# ---------------- ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ----------------

def make_answer_keyboard(question_id: int) -> InlineKeyboardMarkup:
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="Ответить",
                    callback_data=f"answer:{question_id}",
                )
            ]
        ]
    )
    return kb


# ---------------- ХЭНДЛЕР /start ДЛЯ ПОЛУЧАТЕЛЯ ВОПРОСОВ ----------------

@router.message(CommandStart())
async def cmd_start(message: Message):
    """
    Пользователь пишет /start → бот даёт ему персональную ссылку,
    по которой другие будут задавать вопросы.
    payload (аргумент) для /start нам тут не нужен, поэтому игнорируем.
    """
    user = message.from_user
    user_id = user.id

    bot_info = await bot.get_me()
    bot_username = bot_info.username

    # "Глубокая" ссылка с payload = ID пользователя
    # Простой вариант: без кодирования, просто ?start=123456789
    deep_link = f"https://t.me/{bot_username}?start={user_id}"

    text = (
        "Привет!\n\n"
        "Вот твоя личная ссылка для анонимных вопросов:\n"
        f"<code>{deep_link}</code>\n\n"
        "Отправь её друзьям/подписчикам. Все вопросы, которые придут по этой ссылке,\n"
        "я буду пересылать тебе анонимно.\n\n"
    )

    await message.answer(text)


# ---------------- ПРИЁМ ВОПРОСА ОТ СПРАШИВАЮЩЕГО ----------------

@router.message(F.text & F.text.startswith("/start"))
async def deep_link_handler(message: Message):
    """
    Обрабатываем /start с аргументом: /start 123456789
    Это вызывается, когда кто-то переходит по ссылке вида
    t.me/бот?start=ID_ПОЛУЧАТЕЛЯ
    """
    # message.text может быть типа "/start 123456789" или "/start abc"
    parts = message.text.split(maxsplit=1)
    if len(parts) == 1:
        # Это обычный /start без аргумента → обработает cmd_start
        return

    payload_raw = parts[1].strip()

    # Тут два варианта:
    # 1) payload — просто user_id (число)
    # 2) payload закодирован base64 (decode_payload)
    # Для простоты считаем, что это просто число.
    try:
        target_user_id = int(payload_raw)
    except ValueError:
        await message.answer("Некорректная ссылка или аргумент /start.")
        return

    # Сохраняем, кому этот пользователь собирается задать вопрос
    # и просим отправить сам вопрос
    # Можно просто положить target_user_id в message.chat_data,
    # но для простоты попросим написать вопрос сразу.

    await message.answer(
        "Напиши свой вопрос одним сообщением.\n"
        "Он будет отправлен пользователю анонимно."
    )

    # Чтобы знать, кому задаётся вопрос, можно:
    # - использовать FSM
    # - или очень простой подход: временно хранить "кому" в памяти по from_id
    # Для минимального примера сделаем второе.
    message.bot_data.setdefault("ask_targets", {})
    message.bot_data["ask_targets"][message.from_user.id] = target_user_id


@router.message(F.text & ~F.text.startswith("/start"))
async def handle_question_from_asker(message: Message):
    """
    Любой текст (который не /start) расцениваем как вопрос,
    если для этого пользователя есть сохранённый target_user_id.
    """
    user = message.from_user
    bot_data = message.bot_data
    ask_targets: Dict[int, int] = bot_data.get("ask_targets", {})

    if user.id not in ask_targets:
        # Пользователь не переходил по чужой ссылке,
        # а просто что-то пишет боту.
        await message.answer(
            "Чтобы задать анонимный вопрос, сначала пройди по личной ссылке того, "
            "кому хочешь задать вопрос."
        )
        return

    target_user_id = ask_targets[user.id]
    question_text = message.text

    # Шлём вопрос получателю (анонимно для него)
    sent_msg = await bot.send_message(
        chat_id=target_user_id,
        text=(
            "Тебе пришёл новый анонимный вопрос:\n\n"
            f"<b>{question_text}</b>\n\n"
            "Нажми кнопку ниже, чтобы ответить."
        ),
        reply_markup=make_answer_keyboard(message.message_id),
    )

    # Сохраняем в памяти, кто кому пишет
    questions_storage[message.message_id] = {
        "from_id": user.id,         # спрашивающий
        "to_id": target_user_id,    # получатель
    }

    # Ответ спрашивающему
    await message.answer("Вопрос отправлен!")

    # Лог в админ‑группу
    await bot.send_message(
        ADMIN_CHAT_ID,
        (
            "❗️Новый вопрос\n"
            f"От: {user.full_name} (@{user.username})\n"
            f"ID отправителя: <code>{user.id}</code>\n"
            f"Кому (ID): <code>{target_user_id}</code>\n\n"
            f"Текст:\n{question_text}"
        ),
    )

    # Удаляем target, чтобы следующее сообщение не считалось вопросом автоматически
    del ask_targets[user.id]


# ---------------- ОБРАБОТКА КНОПКИ "ОТВЕТИТЬ" ----------------

@router.callback_query(F.data.startswith("answer:"))
async def cb_answer(callback: CallbackQuery):
    """
    Пользователь, который получил вопрос, нажимает кнопку "Ответить".
    """
    user = callback.from_user

    try:
        _, question_id_str = callback.data.split(":", maxsplit=1)
        question_id = int(question_id_str)
    except Exception:
        await callback.answer("Ошибка данных кнопки.", show_alert=True)
        return

    info = questions_storage.get(question_id)
    if not info:
        await callback.answer("Не удалось найти вопрос (возможно, бот перезапускался).", show_alert=True)
        return

    if info["to_id"] != user.id:
        await callback.answer("Этот вопрос адресован не тебе.", show_alert=True)
        return

    # Запоминаем, на какой вопрос этот пользователь собирается отвечать
    callback.bot_data.setdefault("answer_targets", {})
    callback.bot_data["answer_targets"][user.id] = info["from_id"]

    await callback.message.answer(
        "Напиши свой ответ одним сообщением.\n"
        "Он будет отправлен автору вопроса."
    )
    await callback.answer()


@router.message(F.text)
async def handle_answer_from_target(message: Message):
    """
    Если у пользователя есть ожидаемый "answer_targets",
    то текст считаем ответом.
    """
    user = message.from_user
    bot_data = message.bot_data
    answer_targets: Dict[int, int] = bot_data.get("answer_targets", {})

    if user.id not in answer_targets:
        # Это не ответ, а просто сообщение → игнорируем, чтобы не конфликтовать
        # с другими хэндлерами (тут уже ниже по коду их нет, но на будущее).
        return

    asker_id = answer_targets[user.id]
    answer_text = message.text

    # Отправляем ответ автору вопроса
    await bot.send_message(
        chat_id=asker_id,
        text=(
            "Ты получил ответ на свой анонимный вопрос:\n\n"
            f"<b>{answer_text}</b>"
        ),
    )

    await message.answer("Ответ отправлен!")

    # Лог в админ‑группу
    await bot.send_message(
        ADMIN_CHAT_ID,
        (
            "📩 Новый ответ на вопрос\n"
            f"От (ID): <code>{user.id}</code>\n"
            f"Кому (ID): <code>{asker_id}</code>\n\n"
            f"Текст ответа:\n{answer_text}"
        ),
    )

    # Удаляем цель ответа
    del answer_targets[user.id]


# ---------------- ЗАПУСК ----------------

async def main():
    print("Bot started")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
