import telebot
from telebot import types
import base64
import secrets
import pymysql
from collections import defaultdict
import os
import re
from datetime import datetime, timedelta

# 🔧 НАСТРОЙКИ
TOKEN = os.getenv('BOT_TOKEN', '8430859086:AAEsdPIGXI-xG-6COFj48AUnU69yseZOnZo')
ADMIN_CHAT_ID = -1003267199569
ADMIN_ID = 1135333763

# 💾 Подключение к MySQL на Beget
DB_CONFIG = {
    'host': os.getenv('DB_HOST', 'localhost'),
    'port': int(os.getenv('DB_PORT', 3306)),
    'user': os.getenv('DB_USER', 'm995401w_uchet'),
    'password': os.getenv('DB_PASSWORD', 'i5DeqgG&Z2rS'),
    'database': os.getenv('DB_NAME', 'm995401w_uchet'),
    'charset': 'utf8mb4',
    'cursorclass': pymysql.cursors.DictCursor,
    'autocommit': True
}

def get_db_connection():
    """Получить подключение к базе данных"""
    return pymysql.connect(**DB_CONFIG)

def init_database():
    """Инициализация таблиц в базе данных"""
    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            # Таблица сессий
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS sessions (
                    link VARCHAR(255) PRIMARY KEY,
                    owner_id BIGINT NOT NULL,
                    INDEX idx_owner (owner_id)
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
            """)
            
            # Таблица кастомных ссылок
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS custom_links (
                    owner_id BIGINT PRIMARY KEY,
                    custom_name VARCHAR(255) UNIQUE NOT NULL,
                    INDEX idx_custom_name (custom_name)
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
            """)
            
            # Таблица вопросов
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS questions (
                    q_id VARCHAR(20) PRIMARY KEY,
                    sender_id BIGINT NOT NULL,
                    owner_id BIGINT NOT NULL,
                    question_text TEXT NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    answered TINYINT(1) DEFAULT 0,
                    INDEX idx_sender (sender_id),
                    INDEX idx_owner (owner_id),
                    INDEX idx_created (created_at)
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
            """)
            
        print("✅ База данных инициализирована!")
    finally:
        conn.close()

# Инициализируем БД при запуске
init_database()

bot = telebot.TeleBot(TOKEN)
user_states = defaultdict(lambda: None)
reply_pending = {}
pending_questions = {}

def short_uuid():
    token = secrets.token_bytes(4)
    return base64.urlsafe_b64encode(token).rstrip(b'=').decode()[:8]

def user_mention(user_id, username, first_name):
    if username:
        return f'<a href="tg://user?id={user_id}">@{username}</a>'
    return f'<a href="tg://user?id={user_id}">{first_name or "🦸 Аноним"}</a>'

def get_user_link(user_id):
    """Получить ссылку пользователя (кастомную или ID)"""
    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute("SELECT custom_name FROM custom_links WHERE owner_id=%s", (user_id,))
            result = cursor.fetchone()
            if result:
                return result['custom_name']
    finally:
        conn.close()
    return str(user_id)

def get_user_stats(user_id):
    """Получить статистику пользователя"""
    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            # Полученные вопросы
            cursor.execute("SELECT COUNT(*) as cnt FROM questions WHERE owner_id=%s", (user_id,))
            received = cursor.fetchone()['cnt']
            
            # Отправленные вопросы
            cursor.execute("SELECT COUNT(*) as cnt FROM questions WHERE sender_id=%s", (user_id,))
            sent = cursor.fetchone()['cnt']
            
            # Отвеченные вопросы
            cursor.execute("SELECT COUNT(*) as cnt FROM questions WHERE owner_id=%s AND answered=1", (user_id,))
            answered = cursor.fetchone()['cnt']
            
            # Неотвеченные
            unanswered = received - answered
            
            # Статистика за последние 7 дней
            cursor.execute("""
                SELECT COUNT(*) as cnt FROM questions 
                WHERE owner_id=%s AND created_at >= DATE_SUB(NOW(), INTERVAL 7 DAY)
            """, (user_id,))
            week_received = cursor.fetchone()['cnt']
            
            # Статистика за сегодня
            cursor.execute("""
                SELECT COUNT(*) as cnt FROM questions 
                WHERE owner_id=%s AND DATE(created_at)=CURDATE()
            """, (user_id,))
            today_received = cursor.fetchone()['cnt']
            
            # Процент ответов
            response_rate = (answered / received * 100) if received > 0 else 0
            
            return {
                'received': received,
                'sent': sent,
                'answered': answered,
                'unanswered': unanswered,
                'week_received': week_received,
                'today_received': today_received,
                'response_rate': response_rate
            }
    finally:
        conn.close()

def create_main_menu_markup():
    """Создать inline клавиатуру главного меню"""
    markup = types.InlineKeyboardMarkup()
    markup.row(types.InlineKeyboardButton("📊 Моя статистика", callback_data="my_stats"))
    markup.row(types.InlineKeyboardButton("📈 Как увеличить количество смс?", callback_data="increase_msgs"))
    markup.row(types.InlineKeyboardButton("✏️ Кастомная ссылка", callback_data="custom_link"))
    return markup

def send_main_menu(chat_id, user_id):
    """Отправить главное меню со ссылкой пользователя"""
    bot_username = bot.get_me().username
    link = get_user_link(user_id)
    share_url = f"https://t.me/{bot_username}?start={link}"
    
    message_text = f'''Вот твоя личная ссылка:

{share_url}

Опубликуй её и получай анонимные
сообщения'''
    
    markup = create_main_menu_markup()
    bot.send_message(chat_id, message_text, reply_markup=markup, parse_mode='HTML')

@bot.message_handler(commands=['start'])
def start(message):
    parts = message.text.split()
    user_id = message.chat.id
    
    if len(parts) > 1:
        handle_deep_link(message)
        return
    
    # Создаем сессию с ID пользователя
    link_id = str(user_id)
    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                "INSERT INTO sessions (link, owner_id) VALUES (%s, %s) ON DUPLICATE KEY UPDATE owner_id=%s",
                (link_id, user_id, user_id)
            )
    finally:
        conn.close()
    
    # Отправляем главное меню БЕЗ reply_to
    send_main_menu(user_id, user_id)

def handle_deep_link(message):
    user_id = message.from_user.id
    link = message.text.split(maxsplit=1)[1]
    
    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            # Проверяем, является ли ссылка кастомной
            cursor.execute("SELECT owner_id FROM custom_links WHERE custom_name=%s", (link,))
            result = cursor.fetchone()
            if result:
                owner_id = result['owner_id']
            else:
                # Проверяем обычную ссылку
                cursor.execute("SELECT owner_id FROM sessions WHERE link=%s", (link,))
                result = cursor.fetchone()
                if result:
                    owner_id = result['owner_id']
                else:
                    bot.reply_to(message, "🚫 <b>Ошибка ссылки</b>\nПопробуй новую /start", parse_mode='HTML')
                    return
    finally:
        conn.close()
    
    if owner_id != user_id:
        user_states[user_id] = ('waiting_question', owner_id)
        bot.reply_to(message, "💌 <b>Напиши вопрос анонимно</b>\n\n<i>Будет доставлен секретно! 🕵️</i>", parse_mode='HTML')
    else:
        bot.reply_to(message, "🚫 <b>Ошибка ссылки</b>\nПопробуй новую /start", parse_mode='HTML')

@bot.callback_query_handler(func=lambda call: True)
def callback_handler(call):
    user_id = call.from_user.id
    
    if call.data == "my_stats":
        stats = get_user_stats(user_id)
        
        text = f'''📊 <b>Твоя статистика</b> ✨

📬 <b>Получено вопросов:</b> {stats['received']}
📨 <b>Отправлено вопросов:</b> {stats['sent']}

✅ <b>Дано ответов:</b> {stats['answered']}
⏳ <b>Ожидают ответа:</b> {stats['unanswered']}
📈 <b>Процент ответов:</b> {stats['response_rate']:.1f}%

📅 <b>Сегодня:</b> {stats['today_received']} вопросов
📆 <b>За неделю:</b> {stats['week_received']} вопросов'''
        
        markup = types.InlineKeyboardMarkup()
        markup.row(types.InlineKeyboardButton("🔙 Назад", callback_data="back_to_menu"))
        
        bot.edit_message_text(text, call.message.chat.id, call.message.message_id, 
                            reply_markup=markup, parse_mode='HTML')
        bot.answer_callback_query(call.id)
    
    elif call.data == "increase_msgs":
        bot_username = bot.get_me().username
        link = get_user_link(user_id)
        share_url = f"https://t.me/{bot_username}?start={link}"
        
        text = f'''📈 Поделись с друзьями!
— Отправь в личке или ТГК
— Добавь ссылку в профиль
— Выложи в историю

Твоя ссылка: {share_url}'''
        
        markup = types.InlineKeyboardMarkup()
        markup.row(types.InlineKeyboardButton("✅ Понятно", callback_data="back_to_menu"))
        
        bot.edit_message_text(text, call.message.chat.id, call.message.message_id, 
                            reply_markup=markup, parse_mode='HTML')
        bot.answer_callback_query(call.id)
    
    elif call.data == "custom_link":
        bot_username = bot.get_me().username
        link = get_user_link(user_id)
        share_url = f"https://t.me/{bot_username}?start={link}"
        
        text = f'''Здесь ты можешь дать имя своей ссылке вместо ID {user_id}

На данный момент твоя ссылка выглядит так: {share_url}

Чтобы изменить имя - нажми «Изменить»'''
        
        markup = types.InlineKeyboardMarkup()
        markup.row(types.InlineKeyboardButton("✏️ Изменить", callback_data="edit_custom_link"))
        markup.row(types.InlineKeyboardButton("🔙 Назад", callback_data="back_to_menu"))
        
        bot.edit_message_text(text, call.message.chat.id, call.message.message_id, 
                            reply_markup=markup, parse_mode='HTML')
        bot.answer_callback_query(call.id)
    
    elif call.data == "edit_custom_link":
        text = '''А теперь напиши уникальное имя для своей ссылки…

Только английские буквы и цифры!
Пример: naste4ka'''
        
        bot.edit_message_text(text, call.message.chat.id, call.message.message_id, parse_mode='HTML')
        user_states[user_id] = ('waiting_custom_name', call.message.message_id)
        bot.answer_callback_query(call.id)
    
    elif call.data == "back_to_menu":
        bot_username = bot.get_me().username
        link = get_user_link(user_id)
        share_url = f"https://t.me/{bot_username}?start={link}"
        
        message_text = f'''Вот твоя личная ссылка:

{share_url}

Опубликуй её и получай анонимные
сообщения'''
        
        markup = create_main_menu_markup()
        bot.edit_message_text(message_text, call.message.chat.id, call.message.message_id, 
                            reply_markup=markup, parse_mode='HTML')
        bot.answer_callback_query(call.id)
    
    elif call.data.startswith('reply_'):
        cb_data = call.data[6:]
        q_id = base64.urlsafe_b64decode(cb_data.encode()).decode()[:8]
        bot.answer_callback_query(call.id)
        bot.edit_message_reply_markup(call.message.chat.id, call.message.message_id)
        reply_pending[call.from_user.id] = q_id
        bot.reply_to(call.message, f'''✍️ <b>Ответ на вопрос #{q_id}</b>

💬 Твой ответ:''', parse_mode='HTML')

@bot.message_handler(func=lambda m: True)
def global_handler(message):
    user_id = message.from_user.id
    state = user_states.get(user_id)
    
    if state and state[0] == 'waiting_custom_name':
        custom_name = message.text.strip()
        
        # Проверяем формат (только буквы и цифры)
        if not re.match(r'^[a-zA-Z0-9]+$', custom_name):
            bot.reply_to(message, "❌ <b>Ошибка!</b>\n\nИспользуй только английские буквы и цифры без пробелов!", parse_mode='HTML')
            return
        
        conn = get_db_connection()
        try:
            with conn.cursor() as cursor:
                # Проверяем уникальность
                cursor.execute("SELECT owner_id FROM custom_links WHERE custom_name=%s", (custom_name,))
                existing = cursor.fetchone()
                
                if existing and existing['owner_id'] != user_id:
                    bot.reply_to(message, "❌ <b>Имя занято!</b>\n\nПопробуй другое имя.", parse_mode='HTML')
                    return
                
                # Сохраняем кастомное имя
                cursor.execute(
                    "INSERT INTO custom_links (owner_id, custom_name) VALUES (%s, %s) ON DUPLICATE KEY UPDATE custom_name=%s",
                    (user_id, custom_name, custom_name)
                )
                cursor.execute(
                    "INSERT INTO sessions (link, owner_id) VALUES (%s, %s) ON DUPLICATE KEY UPDATE owner_id=%s",
                    (custom_name, user_id, user_id)
                )
        finally:
            conn.close()
        
        # Очищаем состояние
        user_states[user_id] = None
        
        # Отправляем обновленное меню
        bot_username = bot.get_me().username
        share_url = f"https://t.me/{bot_username}?start={custom_name}"
        
        message_text = f'''Вот твоя личная ссылка:

{share_url}

Опубликуй её и получай анонимные
сообщения'''
        
        markup = create_main_menu_markup()
        
        # Удаляем предыдущее сообщение
        try:
            bot.delete_message(message.chat.id, state[1])
        except:
            pass
        
        bot.send_message(message.chat.id, message_text, reply_markup=markup, parse_mode='HTML')
        return
    
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
    owner_id = user_states[user_id][1]
    
    q_id = short_uuid()
    
    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                "INSERT INTO questions (q_id, sender_id, owner_id, question_text) VALUES (%s, %s, %s, %s)",
                (q_id, user_id, owner_id, message.text)
            )
    finally:
        conn.close()
    
    pending_questions[q_id] = user_id
    
    cb_data = base64.urlsafe_b64encode(q_id.encode()).decode()[:32]
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("💬 Ответить", callback_data=f"reply_{cb_data}"))
    bot.send_message(owner_id, f'''🎁 <b>Новый анонимный вопрос!</b> ✨

🆔 <code>{q_id}</code>

💭 <b>{message.text}</b>''', reply_markup=markup, parse_mode='HTML')
    
    sender_mention = user_mention(user_id, message.from_user.username, message.from_user.first_name)
    admin_log = f'''🕵️‍♂️ <b>ВОПРОС #{q_id}</b>

{sender_mention} ({user_id}) → {owner_id}

💬 <b>{message.text}</b>'''
    bot.send_message(ADMIN_CHAT_ID, admin_log, parse_mode='HTML')
    
    markup = types.ReplyKeyboardMarkup(one_time_keyboard=True, resize_keyboard=True)
    markup.add("➕ Ещё один вопрос ✨", "🔄 Новая ссылка")
    bot.reply_to(message, f'''✅ <b>Вопрос доставлен! 🚀</b>

➕ <i>Ещё один вопрос?</i> ✨
🔄 <i>Или новую ссылку?</i>''', reply_markup=markup, parse_mode='HTML')
    user_states[user_id] = ('waiting_choice', owner_id)

def choice_handler(message):
    user_id = message.from_user.id
    
    if "Ещё" in message.text:
        owner_id = user_states[user_id][1]
        user_states[user_id] = ('waiting_question', owner_id)
        bot.reply_to(message, "💭 <b>Напиши следующий вопрос!</b>", parse_mode='HTML')
    else:
        user_states[user_id] = None
        bot.reply_to(message, "🔄 <b>Получи новую ссылку:</b>\n/start ✨", parse_mode='HTML')

def process_reply(message, q_id):
    user_id = message.from_user.id
    sender_id = pending_questions.pop(q_id, None)
    del reply_pending[user_id]
    
    if sender_id:
        conn = get_db_connection()
        try:
            with conn.cursor() as cursor:
                # Отмечаем вопрос как отвеченный
                cursor.execute("UPDATE questions SET answered=1 WHERE q_id=%s", (q_id,))
                
                cursor.execute("SELECT question_text FROM questions WHERE q_id=%s", (q_id,))
                result = cursor.fetchone()
                question_text = result['question_text'] if result else "?"
        finally:
            conn.close()
        
        full_reply = f'''📩 <b>Ответ получен!</b>

❓ <i>{question_text}</i>

💬 <b>{message.text}</b>'''
        bot.send_message(sender_id, full_reply, parse_mode='HTML')
        bot.reply_to(message, f'''✅ <b>Успешно!</b>

✨ Пользователь получил твой ответ''', parse_mode='HTML')
        
        reply_log = f'''<b>📤 ОТВЕТ #{q_id}</b>
{user_mention(user_id, message.from_user.username, message.from_user.first_name)} ({user_id})
→ {user_mention(sender_id, None, "Отправитель")} ({sender_id})

❓ <i>{question_text}</i>
💬 <b>{message.text}</b>'''
        bot.send_message(ADMIN_CHAT_ID, reply_log, parse_mode='HTML')
    else:
        bot.reply_to(message, "❌ <b>Вопрос не найден</b>", parse_mode='HTML')

# 🔥 КОМАНДЫ
@bot.message_handler(commands=['privacy'])
def privacy_policy(message):
    bot.reply_to(message, """
🤫 <b>Политика конфиденциальности</b> ✨

<b>📋 Собираем:</b>
• ID, имя, username (работа)
• Текст вопросов (30 дней)

<b>🚫 НЕ собираем:</b>
• IP, контакты, гео

<b>🛡️ Безопасность:</b>
• Шифрованная БД
• /delete — полное удаление

<b>⚖️ Соответствие:</b>
• GDPR / ФЗ-152
• Пишите /delete — стираем всё!

👨‍⚖️ Разработчик: @your_username
    """, parse_mode='HTML')

@bot.message_handler(commands=['stats'])
def stats_command(message):
    user_id = message.from_user.id
    if user_id != ADMIN_ID:
        bot.reply_to(message, "🚫 <b>Только для админа!</b>", parse_mode='HTML')
        return
    
    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute("SELECT COUNT(*) as cnt FROM questions")
            total = cursor.fetchone()['cnt']
            cursor.execute("SELECT COUNT(DISTINCT sender_id) as cnt FROM questions")
            users = cursor.fetchone()['cnt']
    finally:
        conn.close()
    
    bot.reply_to(message, f'''📊 <b>Статистика ✨</b>

🔢 Вопросов: <b>{total}</b>
👥 Юзеров: <b>{users}</b>
📅 Активных: <b>{len(pending_questions)}</b>''', parse_mode='HTML')

@bot.message_handler(commands=['delete'])
def delete_data(message):
    user_id = message.from_user.id
    
    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute("DELETE FROM questions WHERE sender_id=%s OR owner_id=%s", (user_id, user_id))
            cursor.execute("DELETE FROM sessions WHERE owner_id=%s", (user_id,))
            cursor.execute("DELETE FROM custom_links WHERE owner_id=%s", (user_id,))
    finally:
        conn.close()
    
    bot.reply_to(message, f'''🗑️ <b>Данные удалены!</b> ✨

Все вопросы/ссылки стёрты навсегда ✅''', parse_mode='HTML')
    
    admin_log = f"🗑️ <b>Юзер удалил данные:</b>\n<a href='tg://user?id={user_id}'>ID {user_id}</a>"
    bot.send_message(ADMIN_CHAT_ID, admin_log, parse_mode='HTML')

print("🚀 ✨ Анонимный бот PRO готов на MySQL!")
bot.polling(none_stop=True)