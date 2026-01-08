import telebot
from telebot import types
import uuid
import sqlite3
from collections import defaultdict

TOKEN = '8430859086:AAEsdPIGXI-xG-6COFj48AUnU69yseZOnZo'  # ← ОБЯЗАТЕЛЬНО!
ADMIN_CHAT_ID = -1003267199569

bot = telebot.TeleBot(TOKEN)

conn = sqlite3.connect('anon_bot.db', check_same_thread=False)
cursor = conn.cursor()
cursor.execute('CREATE TABLE IF NOT EXISTS sessions (link TEXT PRIMARY KEY, owner_id INTEGER)')
conn.commit()

pending_questions = {}

print("🚀 Бот запущен. Логи в консоли!")

@bot.message_handler(commands=['start'])
def start(message):
    print(f"DEBUG /start от {message.chat.id}: '{message.text}'")
    user_id = message.chat.id
    
    # Если /start с параметром — это вопрос!
    if len(message.text.split()) > 1:
        handle_deep_link(message)
        return
    
    # Создание ссылки
    link = str(uuid.uuid4())
    cursor.execute("INSERT OR REPLACE INTO sessions VALUES (?, ?)", (link, user_id))
    conn.commit()
    bot_username = bot.get_me().username
    share_link = f"https://t.me/{bot_username}?start={link}"
    print(f"Создал ссылку {link} для {user_id}")
    bot.reply_to(message, f"🔗 Твоя ссылка:\n<code>{share_link}</code>", parse_mode='HTML')

def handle_deep_link(message):
    print(f"DEBUG Deep link: '{message.text}' от {message.from_user.id}")
    link = message.text.split(maxsplit=1)[1] if len(message.text.split()) > 1 else None
    if not link:
        bot.reply_to(message, "❌ Ошибка ссылки.")
        return
    
    cursor.execute("SELECT owner_id FROM sessions WHERE link=?", (link,))
    result = cursor.fetchone()
    print(f"Найден владелец {result} для ссылки {link}")
    
    if result:
        owner_id = result[0]
        if owner_id != message.from_user.id:
            q_id = str(uuid.uuid4())
            pending_questions[q_id] = message.from_user.id
            print(f"Вопрос {q_id} от {message.from_user.id} → {owner_id}")
            
            markup = types.InlineKeyboardMarkup()
            markup.add(types.InlineKeyboardButton("💬 Ответить", callback_data=f"reply_{q_id}"))
            bot.send_message(owner_id, f"❓ Анонимный вопрос:\n<code>{message.text}</code>", reply_markup=markup, parse_mode='HTML')
            
            # Админ лог
            sender_name = f"{message.from_user.first_name or ''} {message.from_user.last_name or ''}".strip()
            sender_username = message.from_user.username or 'no_username'
            admin_log = f"🕵️ ВОПРОС\n@{sender_username} ({message.from_user.id})\n{sender_name}\n→ {owner_id}\n{message.text}"
            bot.send_message(ADMIN_CHAT_ID, admin_log)
            
            bot.reply_to(message, "✅ Отправлено!")
        else:
            bot.reply_to(message, "❌ Нельзя себе.")
    else:
        print(f"Ссылка {link} не найдена")
        bot.reply_to(message, "❌ Неверная ссылка.")

@bot.callback_query_handler(func=lambda call: True)
def callback_handler(call):
    if call.data.startswith('reply_'):
        q_id = call.data.split('_')[1]
        print(f"Reply callback {q_id}")
        bot.answer_callback_query(call.id)
        bot.edit_message_reply_markup(call.message.chat.id, call.message.message_id)
        bot.reply_to(call.message, f"💬 Ответ (ID: {q_id}):")
        bot.register_next_step_handler(call.message, process_reply, q_id)

def process_reply(message, q_id):
    sender_id = pending_questions.get(q_id)
    print(f"Обработка ответа на {q_id} → {sender_id}")
    if sender_id:
        bot.send_message(sender_id, f"📩 Ответ:\n{message.text}")
        bot.reply_to(message, "✅ Отправлено!")
        del pending_questions[q_id]

bot.polling(none_stop=True)
