import telebot
from telebot import types
import uuid
import sqlite3
from collections import defaultdict

TOKEN = '8430859086:AAEsdPIGXI-xG-6COFj48AUnU69yseZOnZo'  # Токен!
ADMIN_CHAT_ID = -1003267199569

bot = telebot.TeleBot(TOKEN)
user_states = {}  # Для состояний

conn = sqlite3.connect('anon_bot.db', check_same_thread=False)
cursor = conn.cursor()
cursor.execute('CREATE TABLE IF NOT EXISTS sessions (link TEXT PRIMARY KEY, owner_id INTEGER)')
conn.commit()

pending_questions = {}

@bot.message_handler(commands=['start'])
def start(message):
    parts = message.text.split()
    user_id = message.chat.id
    
    # Если deep link — перейти к вопросу
    if len(parts) > 1:
        link = parts[1]
        cursor.execute("SELECT owner_id FROM sessions WHERE link=?", (link,))
        result = cursor.fetchone()
        if result and result[0] != user_id:
            # НЕ отправляем /start как вопрос! Просим написать
            user_states[user_id] = ('waiting_question', link)
            markup = types.ReplyKeyboardMarkup(one_time_keyboard=True)
            markup.add(types.KeyboardButton("✍️ Написать вопрос"))
            bot.reply_to(message, "✅ Перешли по ссылке!\nНажми кнопку и напиши вопрос:", reply_markup=markup)
        else:
            bot.reply_to(message, "❌ Неверная ссылка или свой вопрос.")
        return
    
    # Создание ссылки
    link = str(uuid.uuid4())
    cursor.execute("INSERT OR REPLACE INTO sessions VALUES (?, ?)", (link, user_id))
    conn.commit()
    bot_username = bot.get_me().username
    share_link = f"https://t.me/{bot_username}?start={link}"
    bot.reply_to(message, f"🔗 Поделись ссылкой для анонимных вопросов:\n<code>{share_link}</code>", parse_mode='HTML')

@bot.message_handler(func=lambda m: 'Написать вопрос' in m.text)
def ask_question(message):
    user_id = message.from_user.id
    if user_id in user_states and user_states[user_id][0] == 'waiting_question':
        link = user_states[user_id][1]
        del user_states[user_id]
        
        markup = types.ReplyKeyboardRemove()
        msg = bot.reply_to(message, "💬 Напиши свой вопрос:", reply_markup=markup)
        bot.register_next_step_handler(msg, process_question, link)
    else:
        bot.reply_to(message, "❓ Используй /start ссылку.")

def process_question(message, link):
    user_id = message.from_user.id
    cursor.execute("SELECT owner_id FROM sessions WHERE link=?", (link,))
    result = cursor.fetchone()
    if result:
        owner_id = result[0]
        q_id = str(uuid.uuid4())
        pending_questions[q_id] = user_id
        
        # Анонимно владельцу
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton("💬 Ответить", callback_data=f"reply_{q_id}"))
        bot.send_message(owner_id, f"❓ Анонимный вопрос:\n<b>{message.text}</b>", reply_markup=markup, parse_mode='HTML')
        
        # Админ лог
        sender_name = f"{message.from_user.first_name or ''} {message.from_user.last_name or ''}".strip()
        sender_username = message.from_user.username or 'no_username'
        admin_log = f"""🕵️ ВОПРОС
@{sender_username} ({user_id})
<b>{sender_name}</b>
→ <code>{owner_id}</code>
<code>{message.text}</code>"""
        bot.send_message(ADMIN_CHAT_ID, admin_log, parse_mode='HTML')
        
        bot.reply_to(message, "✅ Вопрос отправлен анонимно!")
    else:
        bot.reply_to(message, "❌ Ссылка недействительна.")

@bot.callback_query_handler(func=lambda call: call.data.startswith('reply_'))
def reply_menu(call):
    q_id = call.data.split('_')[1]
    bot.answer_callback_query(call.id)
    bot.edit_message_reply_markup(call.message.chat.id, call.message.message_id)
    msg = bot.reply_to(call.message, "💬 Напишите ответ:")
    bot.register_next_step_handler(msg, process_reply, q_id)

def process_reply(message, q_id):
    sender_id = pending_questions.pop(q_id, None)
    if sender_id:
        bot.send_message(sender_id, f"📩 Ответ на ваш вопрос:\n<b>{message.text}</b>", parse_mode='HTML')
        bot.reply_to(message, "✅ Ответ отправлен!")
        
        admin_reply_log = f"""📤 ОТВЕТ #{q_id}
От: <code>{message.from_user.id}</code>
Кому: <code>{sender_id}</code>
<b>{message.text}</b>"""
        bot.send_message(ADMIN_CHAT_ID, admin_reply_log, parse_mode='HTML')

print("🚀 Бот готов!")
bot.polling(none_stop=True)

