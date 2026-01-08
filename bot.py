import telebot
from telebot import types
import base64
import secrets
import sqlite3
from collections import defaultdict

TOKEN = '8430859086:AAEsdPIGXI-xG-6COFj48AUnU69yseZOnZo'
ADMIN_CHAT_ID = -1003267199569

bot = telebot.TeleBot(TOKEN)
user_states = {}

conn = sqlite3.connect('anon_bot.db', check_same_thread=False)
cursor = conn.cursor()
cursor.execute('CREATE TABLE IF NOT EXISTS sessions (link TEXT PRIMARY KEY, owner_id INTEGER)')
cursor.execute('CREATE TABLE IF NOT EXISTS questions (q_id TEXT PRIMARY KEY, sender_id INTEGER, owner_id INTEGER, question_text TEXT)')
conn.commit()

pending_questions = {}

def short_uuid():
    token = secrets.token_bytes(4)
    return base64.urlsafe_b64encode(token).rstrip(b'=').decode()[:8]

@bot.message_handler(commands=['start'])
def start(message):
    parts = message.text.split()
    user_id = message.chat.id
    
    if len(parts) > 1:
        handle_deep_link(message)
        return
    
    link_id = short_uuid()
    cursor.execute("INSERT OR REPLACE INTO sessions VALUES (?, ?)", (link_id, user_id))
    conn.commit()
    bot_username = bot.get_me().username
    share_url = f"https://t.me/{bot_username}?start={link_id}"
    
    clickable = f"🔗 [Поделись ссылкой]({share_url})"
    bot.reply_to(message, clickable + "\n\nАнонимные вопросы!", parse_mode='Markdown')

def handle_deep_link(message):
    user_id = message.from_user.id
    link = message.text.split(maxsplit=1)[1]
    cursor.execute("SELECT owner_id FROM sessions WHERE link=?", (link,))
    result = cursor.fetchone()
    
    if result and result[0] != user_id:
        user_states[user_id] = ('waiting_question', link)
        bot.reply_to(message, "💬 Напишите свой вопрос анонимно:")
    else:
        bot.reply_to(message, "❌ Неверная ссылка.")

@bot.message_handler(func=lambda m: m.from_user.id in user_states and user_states[m.from_user.id][0] == 'waiting_question')
def process_question(message):
    user_id = message.from_user.id
    link = user_states[user_id][1]
    cursor.execute("SELECT owner_id FROM sessions WHERE link=?", (link,))
    result = cursor.fetchone()
    
    if result:
        owner_id = result[0]
        q_id = short_uuid()
        
        cursor.execute("INSERT INTO questions VALUES (?, ?, ?, ?)", (q_id, user_id, owner_id, message.text))
        conn.commit()
        pending_questions[q_id] = user_id
        
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton("💬 Ответить", callback_data=f"reply_{q_id}"))
        bot.send_message(owner_id, f"❓ #{q_id}\n<b>{message.text}</b>", reply_markup=markup, parse_mode='HTML')
        
        # Админ лог
        sender_name = f"{message.from_user.first_name or ''} {message.from_user.last_name or ''}".strip()
        sender_username = message.from_user.username or 'no_username'
        admin_log = f"""🕵️ #{q_id}
@{sender_username} ({user_id})
{sender_name} → {owner_id}
<b>{message.text}</b>"""
        bot.send_message(ADMIN_CHAT_ID, admin_log, parse_mode='HTML')
        
        markup = types.ReplyKeyboardMarkup(one_time_keyboard=True, resize_keyboard=True)
        markup.add("➕ Ещё вопрос", "🔄 Новая ссылка")
        bot.reply_to(message, "✅ Отправлено!\nЧто дальше?", reply_markup=markup)
        user_states[user_id] = ('waiting_choice', link)
    else:
        bot.reply_to(message, "❌ Ошибка.")

@bot.message_handler(func=lambda m: m.from_user.id in user_states and user_states[m.from_user.id][0] == 'waiting_choice')
def choice_handler(message):
    user_id = message.from_user.id
    
    if "Ещё вопрос" in message.text:
        del user_states[user_id]
        bot.reply_to(message, "💬 Напишите следующий вопрос анонимно:")
        user_states[user_id] = ('waiting_question', user_states[user_id][1])
    elif "Новая ссылка" in message.text:
        bot.reply_to(message, "🔄 Получите новую /start")
        user_states[user_id] = None

@bot.callback_query_handler(func=lambda call: call.data.startswith('reply_'))
def reply_menu(call):
    q_id = call.data.split('_')[1]
    bot.answer_callback_query(call.id)
    bot.edit_message_reply_markup(call.message.chat.id, call.message.message_id)
    msg = bot.reply_to(call.message, f"💬 Ответ на #{q_id}:")
    bot.register_next_step_handler(msg, process_reply, q_id)

def process_reply(message, q_id):
    sender_id = pending_questions.pop(q_id, None)
    if sender_id:
        # ЦИТАТА ВОПРОСА + ОТВЕТ
        cursor.execute("SELECT question_text FROM questions WHERE q_id=?", (q_id,))
        result = cursor.fetchone()
        question_text = result[0] if result else "Вопрос удалён"
        
        full_reply = f"📩 Ответ на ваш вопрос:\n<i>{question_text}</i>\n\n<b>{message.text}</b>"
        bot.send_message(sender_id, full_reply, parse_mode='HTML')
        bot.reply_to(message, "✅ Ответ отправлен с цитатой!")
        
        # Админ лог
        reply_log = f"""📤 #{q_id}
От {message.from_user.id} → {sender_id}
❓ {question_text}
💬 <b>{message.text}</b>"""
        bot.send_message(ADMIN_CHAT_ID, reply_log, parse_mode='HTML')
    else:
        bot.reply_to(message, "❌ Вопрос не найден.")

print("🚀 Бот с цитатами вопросов готов!")
bot.polling(none_stop=True)
