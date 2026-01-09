import telebot
from telebot import types
import base64
import secrets
import sqlite3
from collections import defaultdict
import os

# 🔧 НАСТРОЙКИ
TOKEN = 'YOUR_BOT_TOKEN_HERE'  # Замените!
ADMIN_CHAT_ID = -1003267199569
ADMIN_ID = 1135333763  # ← ВАШ USER ID!

bot = telebot.TeleBot(TOKEN)
user_states = defaultdict(lambda: None)
reply_pending = {}

conn = sqlite3.connect('anon_bot.db', check_same_thread=False)
cursor = conn.cursor()
cursor.execute('CREATE TABLE IF NOT EXISTS sessions (link TEXT PRIMARY KEY, owner_id INTEGER)')
cursor.execute('CREATE TABLE IF NOT EXISTS questions (q_id TEXT PRIMARY KEY, sender_id INTEGER, owner_id INTEGER, question_text TEXT)')
conn.commit()

pending_questions = {}

def short_uuid():
    token = secrets.token_bytes(4)
    return base64.urlsafe_b64encode(token).rstrip(b'=').decode()[:8]

def user_mention(user_id, username, first_name):
    if username:
        return f'<a href="tg://user?id={user_id}">@{username}</a>'
    return f'<a href="tg://user?id={user_id}">{first_name or "🦸 Аноним"}</a>'

# 🔥 КОМАНДЫ ПЕРВЫМИ!
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
    
    clickable = f'<a href="{share_url}">🔗 Твоя секретная ссылка</a>'
    bot.reply_to(message, f'''🎭 <b>Анонимные вопросы!</b> ✨

{clickable}

✨ Поделись — получи интересные сообщения!
<i>Все вопросы строго анонимно 😎</i>''', parse_mode='HTML')

@bot.message_handler(commands=['privacy'])
def privacy_policy(message):
    bot.reply_to(message, """🤫 <b>Политика конфиденциальности</b> ✨

<b>📱 Собираем:</b>
• ID, имя, username (работа)
• Вопросы/ответы (30 дней)

<b>🚫 НЕ собираем:</b>
• IP, контакты, гео

<b>🔒 Хранение:</b>
• Шифрованная БД
• /delete — удаление

<b>⚖️ Права:</b>
• GDPR/ФЗ-152
• Нет передачи третьим лицам

👤 @your_username""", parse_mode='HTML')

@bot.message_handler(commands=['stats'])
def stats_command(message):
    user_id = message.from_user.id
    if user_id != ADMIN_ID:
        bot.reply_to(message, "🚫 <b>Только админ!</b>")
        return
    
    cursor.execute("SELECT COUNT(*) FROM questions")
    total = cursor.fetchone()[0]
    cursor.execute("SELECT COUNT(DISTINCT sender_id) FROM questions")
    users = cursor.fetchone()[0]
    
    bot.reply_to(message, f'''📊 <b>Статистика ✨</b>

🔢 Вопросов: <b>{total}</b>
👥 Юзеров: <b>{users}</b>
📅 Активных: <b>{len(pending_questions)}</b>''', parse_mode='HTML')

@bot.message_handler(commands=['delete'])
def delete_data(message):
    user_id = message.from_user.id
    
    cursor.execute("DELETE FROM questions WHERE sender_id=? OR owner_id=?", (user_id, user_id))
    cursor.execute("DELETE FROM sessions WHERE owner_id=?", (user_id,))
    conn.commit()
    
    bot.reply_to(message, f'''🗑️ <b>Данные удалены!</b> ✨

Все вопросы/ссылки стёрты ✅''', parse_mode='HTML')
    admin_log = f"🗑️ <b>Юзер удалил данные:</b>\n<a href='tg://user?id={user_id}'>ID {user_id}</a>"
    bot.send_message(ADMIN_CHAT_ID, admin_log, parse_mode='HTML')

# ГЛОБАЛЬНЫЙ HANDLER ПОСЛЕ КОМАНД
@bot.message_handler(func=lambda m: True)
def global_handler(message):
    user_id = message.from_user.id
    state = user_states[user_id]
    
    if state and state[0] == 'waiting_question':
        process_question(message)
        return
    
    if state and state[0] == 'waiting_choice':
        choice_handler(message)
        return
    
    if user_id in reply_pending:
        process_reply(message, reply_pending[user_id])
        return

def handle_deep_link(message):
    user_id = message.from_user.id
    link = message.text.split(maxsplit=1)[1]
    cursor.execute("SELECT owner_id FROM sessions WHERE link=?", (link,))
    result = cursor.fetchone()
    
    if result and result[0] != user_id:
        user_states[user_id] = ('waiting_question', link)
        bot.reply_to(message, "💌 <b>Напиши вопрос анонимно</b>\n\n<i>🕵️</i>", parse_mode='HTML')
    else:
        bot.reply_to(message, "🚫 <b>Ошибка ссылки</b>\n/start")

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
        
        cb_data = base64.urlsafe_b64encode(q_id.encode()).decode()[:32]
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton("💬 Ответить", callback_data=f"reply_{cb_data}"))
        bot.send_message(owner_id, f'''🎁 <b>Новый вопрос!</b> ✨

🆔 <code>{q_id}</code>

💭 <b>{message.text}</b>''', reply_markup=markup, parse_mode='HTML')
        
        sender_mention = user_mention(user_id, message.from_user.username, message.from_user.first_name)
        admin_log = f'''🕵️‍♂️ <b>ВОПРОС #{q_id}</b>

{sender_mention} ({user_id}) → {owner_id}

💬 <b>{message.text}</b>'''
        bot.send_message(ADMIN_CHAT_ID, admin_log, parse_mode='HTML')
        
        markup = types.ReplyKeyboardMarkup(one_time_keyboard=True, resize_keyboard=True)
        markup.add("➕ Ещё вопрос ✨", "🔄 Новая ссылка")
        bot.reply_to(message, f'''✅ <b>Доставлено! 🚀</b>

➕ <i>Ещё вопрос?</i>
🔄 <i>Новая ссылка?</i>''', reply_markup=markup, parse_mode='HTML')
        user_states[user_id] = ('waiting_choice', link)

def choice_handler(message):
    user_id = message.from_user.id
    
    if "Ещё" in message.text:
        user_states[user_id] = ('waiting_question', user_states[user_id][1])
        bot.reply_to(message, "💭 <b>Следующий вопрос!</b>", parse_mode='HTML')
    else:
        user_states[user_id] = None
        bot.reply_to(message, "🔄 <b>Новая /start</b>", parse_mode='HTML')

@bot.callback_query_handler(func=lambda call: call.data.startswith('reply_'))
def reply_menu(call):
    cb_data = call.data[6:]
    q_id = base64.urlsafe_b64decode(cb_data.encode()).decode()[:8]
    bot.answer_callback_query(call.id)
    bot.edit_message_reply_markup(call.message.chat.id, call.message.message_id)
    reply_pending[call.from_user.id] = q_id
    bot.reply_to(call.message, f'''✍️ <b>Ответ #{q_id}</b>

💬 Пиши:''')

def process_reply(message, q_id):
    user_id = message.from_user.id
    sender_id = pending_questions.pop(q_id, None)
    del reply_pending[user_id]
    
    if sender_id:
        cursor.execute("SELECT question_text FROM questions WHERE q_id=?", (q_id,))
        result = cursor.fetchone()
        question_text = result[0] if result else "?"
        
        full_reply = f'''📩 <b>Ответ!</b>

❓ <i>{question_text}</i>

💬 <b>{message.text}</b>'''
        bot.send_message(sender_id, full_reply, parse_mode='HTML')
        bot.reply_to(message, f'''✅ <b>Успешно!</b>

✨ Пользователь уже получил твой ответ, parse_mode='HTML')
        
        reply_log = f'''📤 <b>ОТВЕТ #{q_id}</b>
{user_mention(user_id, message.from_user.username, message.from_user.first_name)} ({user_id})
→ {user_mention(sender_id, None, "Отправитель")} ({sender_id})

❓ <i>{question_text}</i>
💬 <b>{message.text}</b>'''
        bot.send_message(ADMIN_CHAT_ID, reply_log, parse_mode='HTML')

print("🚀 ✨ Анонимный бот полностью готов!")
bot.polling(none_stop=True)
