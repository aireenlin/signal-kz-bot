import sys
import os

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import Application, CommandHandler, MessageHandler, filters, CallbackQueryHandler, ContextTypes, \
    ConversationHandler
import sqlite3
import os
import logging
from datetime import datetime

# Состояния для ConversationHandler
CATEGORY, DESCRIPTION, LOCATION, PHOTO, CONFIRM = range(5)
COMMENT = 0  # Для ввода комментария при изменении статуса

# Категории нарушений
VIOLATION_CATEGORIES = [
    "Незаконная свалка",
    "Загрязнение воды",
    "Выброс отходов",
    "Пожар",
    "Незаконная вырубка",
    "Скотомогильник",
    "Незаконная охота",
    "Незаконное рыболовство",
    "Другое"
]


# Создание базы данных
def setup_database():
    conn = sqlite3.connect('signal_kz.db')
    cursor = conn.cursor()

    # Таблица пользователей
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            first_name TEXT,
            last_name TEXT,
            role TEXT DEFAULT 'user',
            reg_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')

    # Таблица обращений
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS reports (
            report_id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            category TEXT,
            description TEXT,
            latitude REAL,
            longitude REAL,
            photo_id TEXT,
            status TEXT DEFAULT 'На модерации',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(user_id)
        )
    ''')

    # Таблица обновлений статуса
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS status_updates (
            update_id INTEGER PRIMARY KEY AUTOINCREMENT,
            report_id INTEGER,
            official_id INTEGER,
            status TEXT,
            comment TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (report_id) REFERENCES reports(report_id),
            FOREIGN KEY (official_id) REFERENCES users(user_id)
        )
    ''')

    conn.commit()
    conn.close()


# Регистрация пользователя
def register_user(update: Update):
    user = update.effective_user
    conn = sqlite3.connect('signal_kz.db')
    cursor = conn.cursor()

    cursor.execute('''
                   INSERT
                   OR IGNORE INTO users (user_id, username, first_name, last_name, role, reg_date)
    VALUES (?, ?, ?, ?, ?, ?)
                   ''', (user.id, user.username, user.first_name, user.last_name, 'user', datetime.now()))

    conn.commit()
    conn.close()


# Команда /start
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    register_user(update)

    await update.message.reply_text(
        f"Добро пожаловать в бот Signal KZ!\n\n"
        f"Здесь вы можете сообщить об экологических нарушениях на территории Казахстана.\n\n"
        f"Для подачи обращения используйте команду /report\n"
        f"Для просмотра ваших обращений используйте /myreports\n"
        f"Для получения помощи используйте /help"
    )


# Начало создания обращения
async def start_report(update: Update, context: ContextTypes.DEFAULT_TYPE):
    register_user(update)

    # Создаем клавиатуру с категориями
    keyboard = []
    for category in VIOLATION_CATEGORIES:
        keyboard.append([InlineKeyboardButton(category, callback_data=f"cat_{category}")])

    reply_markup = InlineKeyboardMarkup(keyboard)

    await update.message.reply_text(
        "Выберите категорию нарушения:",
        reply_markup=reply_markup
    )



    return CATEGORY


# Обработка выбора категории
async def category_selected(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    category = query.data.replace("cat_", "")
    context.user_data['category'] = category

    await query.edit_message_text(
        f"Выбрана категория: {category}\n\n"
        f"Теперь напишите краткое описание проблемы."
    )

    return DESCRIPTION


# Обработка описания
async def get_description(update: Update, context: ContextTypes.DEFAULT_TYPE):
    description = update.message.text
    context.user_data['description'] = description

    # Запрашиваем местоположение
    location_button = KeyboardButton(
        "Отправить геолокацию",
        request_location=True
    )
    reply_markup = ReplyKeyboardMarkup(
        [[location_button]],
        one_time_keyboard=True,
        resize_keyboard=True
    )

    await update.message.reply_text(
        "Пожалуйста, отправьте вашу геолокацию, чтобы указать место нарушения.",
        reply_markup=reply_markup
    )

    return LOCATION


# Обработка геолокации
async def get_location(update: Update, context: ContextTypes.DEFAULT_TYPE):
    location = update.message.location
    context.user_data['latitude'] = location.latitude
    context.user_data['longitude'] = location.longitude

    await update.message.reply_text(
        "Теперь, пожалуйста, отправьте фото нарушения."
    )

    return PHOTO


# Обработка фото
async def get_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    photo_file = await update.message.photo[-1].get_file()
    photo_id = photo_file.file_id
    context.user_data['photo_id'] = photo_id

    # Отображаем данные для подтверждения
    await update.message.reply_photo(
        photo=photo_id,
        caption=f"Проверьте данные обращения:\n\n"
                f"Категория: {context.user_data['category']}\n"
                f"Описание: {context.user_data['description']}\n"
                f"Координаты: {context.user_data['latitude']}, {context.user_data['longitude']}\n\n"
                f"Всё верно?",
        reply_markup=InlineKeyboardMarkup([
            [
                InlineKeyboardButton("Да, отправить", callback_data="confirm_yes"),
                InlineKeyboardButton("Отменить", callback_data="confirm_no")
            ]
        ])
    )

    return CONFIRM


# Подтверждение и сохранение обращения
async def confirm_report(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if query.data == "confirm_yes":
        user_id = update.effective_user.id

        # Сохраняем обращение в БД
        conn = sqlite3.connect('signal_kz.db')
        cursor = conn.cursor()

        cursor.execute('''
                       INSERT INTO reports
                       (user_id, category, description, latitude, longitude, photo_id, status, created_at, updated_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                       ''', (
                           user_id,
                           context.user_data['category'],
                           context.user_data['description'],
                           context.user_data['latitude'],
                           context.user_data['longitude'],
                           context.user_data['photo_id'],
                           'На модерации',
                           datetime.now(),
                           datetime.now()
                       ))

        report_id = cursor.lastrowid
        conn.commit()
        await notify_moderators(context, report_id, context.user_data)
        conn.close()

        # Оповещаем пользователя
        await query.edit_message_caption(
            caption=f"Ваше обращение №{report_id} успешно отправлено на модерацию!\n\n"
                    f"Вы можете отслеживать его статус с помощью команды /myreports"
        )

        # Очищаем данные
        context.user_data.clear()

    else:
        await query.edit_message_caption(
            caption="Отправка обращения отменена."
        )
        context.user_data.clear()


    return ConversationHandler.END


# Оповещение модераторов о новом обращении
async def notify_moderators(context, report_id, report_data):
    print(report_data)
    conn = sqlite3.connect('signal_kz.db')
    cursor = conn.cursor()

    # Получаем список всех модераторов
    cursor.execute('''
    SELECT user_id FROM users WHERE role = "moderator"
    ''')
    moderators = cursor.fetchall()
    print(moderators)
    conn.close()

    # Отправляем уведомление каждому модератору
    for moderator in moderators:
        moderator_id = moderator[0]
        print(moderator_id)
        try:
            await context.bot.send_photo(
                chat_id=moderator_id,
                photo=report_data['photo_id'],
                caption=f"🚨 НОВОЕ ОБРАЩЕНИЕ НА МОДЕРАЦИИ №{report_id} 🚨\n\n"
                        f"Категория: {report_data['category']}\n"
                        f"Описание: {report_data['description']}\n"
                        f"Координаты: {report_data['latitude']}, {report_data['longitude']}\n\n",
                reply_markup=InlineKeyboardMarkup([
                    [
                        InlineKeyboardButton("Одобрить", callback_data=f"mod_approve_{report_id}"),
                        InlineKeyboardButton("Отклонить", callback_data=f"mod_reject_{report_id}")
                    ],
                    [InlineKeyboardButton(
                        "Открыть на карте",
                        url=f"https://www.google.com/maps/search/?api=1&query={report_data['latitude']},{report_data['longitude']}"
                    )]
                ])
            )
        except Exception as e:
            logging.error(f"Ошибка при отправке уведомления модератору {moderator_id}: {e}")


# Обработка решения модератора
async def moderator_decision(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    data = query.data.split("_")
    action = data[1]  # approve или reject
    report_id = int(data[2])

    conn = sqlite3.connect('signal_kz.db')
    cursor = conn.cursor()

    # Получаем информацию об обращении
    cursor.execute('SELECT * FROM reports WHERE report_id = ?', (report_id,))
    report = cursor.fetchone()

    if not report:
        await query.edit_message_text("Обращение не найдено.")
        conn.close()
        return

    if action == "approve":
        # Обновляем статус на "Новое"
        cursor.execute('UPDATE reports SET status = "Новое", updated_at = ? WHERE report_id = ?',
                       (datetime.now(), report_id))
        conn.commit()

        # Получаем данные для оповещения госорганов
        cursor.execute('''
                       SELECT r.category, r.description, r.latitude, r.longitude, r.photo_id, r.user_id
                       FROM reports r
                       WHERE r.report_id = ?
                       ''', (report_id,))
        report_data = cursor.fetchone()

        report_info = {
            'category': report_data[0],
            'description': report_data[1],
            'latitude': report_data[2],
            'longitude': report_data[3],
            'photo_id': report_data[4],
            'user_id': report_data[5]
        }

        # Оповещаем всех госслужащих
        await notify_officials(context, report_id, report_info)

        # Оповещаем пользователя об одобрении
        try:
            await context.bot.send_message(
                chat_id=report_info['user_id'],
                text=f"✅ Ваше обращение №{report_id} одобрено модератором и передано в работу!"
            )
        except Exception as e:
            logging.error(f"Ошибка при оповещении пользователя: {e}")

        await query.edit_message_caption(
            caption=f"✅ Обращение №{report_id} одобрено и передано госорганам."
        )

    else:  # reject
        # Обновляем статус на "Отклонено модератором"
        cursor.execute('UPDATE reports SET status = "Отклонено модератором", updated_at = ? WHERE report_id = ?',
                       (datetime.now(), report_id))
        conn.commit()

        # Получаем user_id для оповещения
        cursor.execute('SELECT user_id FROM reports WHERE report_id = ?', (report_id,))
        user_id = cursor.fetchone()[0]

        # Оповещаем пользователя об отклонении
        try:
            await context.bot.send_message(
                chat_id=user_id,
                text=f"❌ Ваше обращение №{report_id} отклонено модератором."
            )
        except Exception as e:
            logging.error(f"Ошибка при оповещении пользователя: {e}")

        await query.edit_message_caption(
            caption=f"❌ Обращение №{report_id} отклонено."
        )

    conn.close()


# Оповещение госслужащих о новом одобренном обращении
async def notify_officials(context, report_id, report_data):
    conn = sqlite3.connect('signal_kz.db')
    cursor = conn.cursor()

    # Получаем список всех госслужащих
    cursor.execute('SELECT user_id FROM users WHERE role = "official"')
    officials = cursor.fetchall()
    conn.close()

    # Отправляем уведомление каждому госслужащему
    for official in officials:
        official_id = official[0]

        try:
            await context.bot.send_photo(
                chat_id=official_id,
                photo=report_data['photo_id'],
                caption=f"🚨 НОВОЕ ОБРАЩЕНИЕ №{report_id} 🚨\n\n"
                        f"Категория: {report_data['category']}\n"
                        f"Описание: {report_data['description']}\n"
                        f"Координаты: {report_data['latitude']}, {report_data['longitude']}\n\n"
                        f"Для изменения статуса используйте команду /update_status {report_id}",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton(
                        "Открыть на карте",
                        url=f"https://www.google.com/maps/search/?api=1&query={report_data['latitude']},{report_data['longitude']}"
                    )],
                    [InlineKeyboardButton("Изменить статус", callback_data=f"change_status_{report_id}")]
                ])
            )
        except Exception as e:
            logging.error(f"Ошибка при отправке уведомления госслужащему {official_id}: {e}")


# Просмотр своих обращений
async def my_reports(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id

    conn = sqlite3.connect('signal_kz.db')
    cursor = conn.cursor()

    cursor.execute('''
                   SELECT report_id, category, description, status, created_at
                   FROM reports
                   WHERE user_id = ?
                   ORDER BY created_at DESC
                   ''', (user_id,))

    reports = cursor.fetchall()
    conn.close()

    if not reports:
        await update.message.reply_text("У вас пока нет обращений.")
        return

    for report in reports:
        report_id, category, description, status, created_at = report

        await update.message.reply_text(
            f"Обращение №{report_id}\n"
            f"Категория: {category}\n"
            f"Описание: {description}\n"
            f"Статус: {status}\n"
            f"Дата создания: {created_at}\n",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton(f"Подробнее о №{report_id}", callback_data=f"view_{report_id}")]
            ])
        )


# Обработчик кнопки "Изменить статус"
async def change_status_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    data = query.data.split("_")
    report_id = int(data[2])

    # Проверяем, является ли пользователь госслужащим
    user_id = update.effective_user.id
    conn = sqlite3.connect('signal_kz.db')
    cursor = conn.cursor()

    cursor.execute('SELECT role FROM users WHERE user_id = ?', (user_id,))
    role = cursor.fetchone()[0]
    conn.close()

    if role != "official":
        await query.edit_message_text("Эта функция доступна только для представителей госорганов.")
        return

    # Предлагаем выбрать новый статус
    statuses = ["В обработке", "Проверка", "Подтверждено", "Решено", "Отклонено"]
    keyboard = []
    for status in statuses:
        keyboard.append([InlineKeyboardButton(status, callback_data=f"status_{report_id}_{status}")])

    reply_markup = InlineKeyboardMarkup(keyboard)

    await query.edit_message_caption(
        caption=f"Выберите новый статус для обращения №{report_id}:",
        reply_markup=reply_markup
    )


# Обработка выбора нового статуса
async def status_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    data = query.data.split("_")
    report_id = int(data[1])
    new_status = "_".join(data[2:])  # Для статусов с пробелами

    # Сохраняем во временные данные
    context.user_data['pending_status_update'] = {
        'report_id': report_id,
        'new_status': new_status
    }

    if query.message.photo or query.message.video:
        await query.edit_message_caption(
            caption=f"Вы выбрали статус '{new_status}' для обращения №{report_id}.\n"
                    f"Пожалуйста, напишите комментарий к обновлению статуса:"
        )
    else:
        await query.edit_message_text(
            text=f"Вы выбрали статус '{new_status}' для обращения №{report_id}.\n"
                 f"Пожалуйста, напишите комментарий к обновлению статуса:"
        )


    return COMMENT


# Обработка комментария к статусу
async def process_status_comment(update: Update, context: ContextTypes.DEFAULT_TYPE):
    comment = update.message.text
    report_id = context.user_data['pending_status_update']['report_id']
    new_status = context.user_data['pending_status_update']['new_status']
    official_id = update.effective_user.id

    conn = sqlite3.connect('signal_kz.db')
    cursor = conn.cursor()

    # Обновляем статус обращения
    cursor.execute('''
                   UPDATE reports
                   SET status     = ?,
                       updated_at = ?
                   WHERE report_id = ?
                   ''', (new_status, datetime.now(), report_id))

    # Добавляем запись в историю обновлений статуса
    cursor.execute('''
                   INSERT INTO status_updates (report_id, official_id, status, comment, created_at)
                   VALUES (?, ?, ?, ?, ?)
                   ''', (report_id, official_id, new_status, comment, datetime.now()))

    # Получаем информацию о пользователе, создавшем обращение
    cursor.execute('SELECT user_id FROM reports WHERE report_id = ?', (report_id,))
    user_id = cursor.fetchone()[0]

    conn.commit()
    conn.close()

    # Отправляем уведомление пользователю
    try:
        await context.bot.send_message(
            chat_id=user_id,
            text=f"📣 Обновление статуса обращения №{report_id}\n\n"
                 f"Новый статус: {new_status}\n"
                 f"Комментарий: {comment}"
        )
    except Exception as e:
        logging.error(f"Ошибка при отправке уведомления пользователю {user_id}: {e}")

    await update.message.reply_text(
        f"✅ Статус обращения №{report_id} успешно обновлен на '{new_status}'."
    )

    # Очищаем временные данные
    context.user_data.pop('pending_status_update', None)

    return ConversationHandler.END


# Изменение статуса обращения (для госслужащих) - командный вариант
async def update_status_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id

    # Проверяем, является ли пользователь госслужащим
    conn = sqlite3.connect('signal_kz.db')
    cursor = conn.cursor()

    cursor.execute('SELECT role FROM users WHERE user_id = ?', (user_id,))
    role = cursor.fetchone()[0]
    conn.close()

    if role != "official":
        await update.message.reply_text("Эта команда доступна только для представителей госорганов.")
        return

    # Проверяем, указан ли ID обращения
    if not context.args or not context.args[0].isdigit():
        await update.message.reply_text("Пожалуйста, укажите ID обращения: /update_status ID")
        return

    report_id = int(context.args[0])

    # Получаем информацию об обращении
    conn = sqlite3.connect('signal_kz.db')
    cursor = conn.cursor()

    cursor.execute('SELECT * FROM reports WHERE report_id = ?', (report_id,))
    report = cursor.fetchone()
    conn.close()

    if not report:
        await update.message.reply_text(f"Обращение №{report_id} не найдено.")
        return

    # Предлагаем выбрать новый статус
    statuses = ["В обработке", "Проверка", "Подтверждено", "Решено", "Отклонено"]
    keyboard = []
    for status in statuses:
        keyboard.append([InlineKeyboardButton(status, callback_data=f"status_{report_id}_{status}")])

    reply_markup = InlineKeyboardMarkup(keyboard)

    await update.message.reply_text(
        f"Выберите новый статус для обращения №{report_id}:",
        reply_markup=reply_markup
    )


# Помощь
async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id

    # Проверяем роль пользователя
    conn = sqlite3.connect('signal_kz.db')
    cursor = conn.cursor()

    cursor.execute('SELECT role FROM users WHERE user_id = ?', (user_id,))
    result = cursor.fetchone()
    role = result[0] if result else "user"
    conn.close()

    # Базовая помощь для всех
    help_text = (
        "Доступные команды:\n\n"
        "/start - Начать работу с ботом\n"
        "/report - Отправить новое обращение о нарушении\n"
        "/myreports - Просмотреть свои обращения\n"
        "/help - Показать эту справку\n\n"
    )

    # Дополнительные команды для модераторов
    if role == "moderator":
        help_text += (
            "Для модераторов:\n"
            "/pending_reports - Просмотреть обращения на модерации\n"
        )

    # Дополнительные команды для госслужащих
    if role == "official":
        help_text += (
            "Для госслужащих:\n"
            "/update_status ID - Обновить статус обращения\n"
            "/all_reports - Просмотреть все активные обращения\n"
        )

    # Команды для администраторов
    if role == "admin":
        help_text += (
            "Для администраторов:\n"
            "/set_role ID ROLE - Назначить роль пользователю (user, moderator, official, admin)\n"
            "/register_official - Регистрация госслужащего\n"
            "/register_moderator - Регистрация модератора\n"
        )

    await update.message.reply_text(help_text)


# Назначение роли (для админов)
async def set_role(update: Update, context: ContextTypes.DEFAULT_TYPE):
    admin_id = update.effective_user.id

    # Проверяем, является ли пользователь админом
    conn = sqlite3.connect('signal_kz.db')
    cursor = conn.cursor()

    cursor.execute('SELECT role FROM users WHERE user_id = ?', (admin_id,))
    role = cursor.fetchone()[0]

    if role != "admin":
        await update.message.reply_text("Эта команда доступна только для администраторов.")
        conn.close()
        return

    # Проверяем аргументы
    if len(context.args) != 2:
        await update.message.reply_text("Использование: /set_role USER_ID ROLE")
        conn.close()
        return

    try:
        user_id = int(context.args[0])
        new_role = context.args[1]
    except ValueError:
        await update.message.reply_text("Неверный формат ID пользователя.")
        conn.close()
        return

    # Проверяем, существует ли пользователь
    cursor.execute('SELECT * FROM users WHERE user_id = ?', (user_id,))
    user = cursor.fetchone()

    if not user:
        await update.message.reply_text(f"Пользователь с ID {user_id} не найден.")
        conn.close()
        return

    # Проверяем, является ли роль допустимой
    if new_role not in ["user", "moderator", "official", "admin"]:
        await update.message.reply_text("Допустимые роли: user, moderator, official, admin")
        conn.close()
        return

    # Обновляем роль
    cursor.execute('UPDATE users SET role = ? WHERE user_id = ?', (new_role, user_id))
    conn.commit()
    conn.close()

    await update.message.reply_text(f"Роль пользователя с ID {user_id} изменена на {new_role}.")


# Регистрация госслужащего
async def register_official(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id

    conn = sqlite3.connect('signal_kz.db')
    cursor = conn.cursor()

    cursor.execute('UPDATE users SET role = "official" WHERE user_id = ?', (user_id,))
    conn.commit()
    conn.close()

    await update.message.reply_text(
        "Вы успешно зарегистрированы как представитель госоргана.\n"
        "Теперь вы будете получать уведомления о новых обращениях и сможете обновлять их статусы."
    )


# Регистрация модератора
async def register_moderator(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id

    conn = sqlite3.connect('signal_kz.db')
    cursor = conn.cursor()

    cursor.execute('UPDATE users SET role = "moderator" WHERE user_id = ?', (user_id,))
    conn.commit()
    conn.close()

    await update.message.reply_text(
        "Вы успешно зарегистрированы как модератор.\n"
        "Теперь вы будете получать уведомления о новых обращениях и сможете одобрять или отклонять их."
    )


# Просмотр ожидающих модерации обращений
async def pending_reports(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id

    # Проверяем, является ли пользователь модератором
    conn = sqlite3.connect('signal_kz.db')
    cursor = conn.cursor()

    cursor.execute('SELECT role FROM users WHERE user_id = ?', (user_id,))
    role = cursor.fetchone()[0]

    if role != "moderator" and role != "admin":
        await update.message.reply_text("Эта команда доступна только для модераторов.")
        conn.close()
        return

    ## Просмотр ожидающих модерации обращений
async def pending_reports(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id

    # Проверяем, является ли пользователь модератором
    conn = sqlite3.connect('signal_kz.db')
    cursor = conn.cursor()

    cursor.execute('SELECT role FROM users WHERE user_id = ?', (user_id,))
    role = cursor.fetchone()[0]

    if role != "moderator" and role != "admin":
        await update.message.reply_text("Эта команда доступна только для модераторов.")
        conn.close()
        return

    # Получаем список обращений на модерации
    cursor.execute('''
    SELECT report_id, category, description, created_at FROM reports 
    WHERE status = 'На модерации'
    ORDER BY created_at DESC
    ''')

    reports = cursor.fetchall()
    conn.close()

    if not reports:
        await update.message.reply_text("На данный момент нет обращений, ожидающих модерации.")
        return

    for report in reports:
        report_id, category, description, created_at = report

        # Получаем фото и другие данные для отображения
        conn = sqlite3.connect('signal_kz.db')
        cursor = conn.cursor()

        cursor.execute('SELECT photo_id, latitude, longitude FROM reports WHERE report_id = ?', (report_id,))
        photo_id, latitude, longitude = cursor.fetchone()
        conn.close()

        await update.message.reply_photo(
            photo=photo_id,
            caption=f"Обращение №{report_id}\n"
                   f"Категория: {category}\n"
                   f"Описание: {description}\n"
                   f"Дата создания: {created_at}\n"
                   f"Координаты: {latitude}, {longitude}",
            reply_markup=InlineKeyboardMarkup([
                [
                    InlineKeyboardButton("Одобрить", callback_data=f"mod_approve_{report_id}"),
                    InlineKeyboardButton("Отклонить", callback_data=f"mod_reject_{report_id}")
                ],
                [InlineKeyboardButton(
                    "Открыть на карте",
                    url=f"https://www.google.com/maps/search/?api=1&query={latitude},{longitude}"
                )]
            ])
        )

# Просмотр всех активных обращений (для госслужащих)
async def all_reports(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id

    # Проверяем, является ли пользователь госслужащим
    conn = sqlite3.connect('signal_kz.db')
    cursor = conn.cursor()

    cursor.execute('SELECT role FROM users WHERE user_id = ?', (user_id,))
    role = cursor.fetchone()[0]

    if role != "official" and role != "admin":
        await update.message.reply_text("Эта команда доступна только для представителей госорганов.")
        conn.close()
        return

    # Получаем список активных обращений
    cursor.execute('''
    SELECT report_id, category, description, status, created_at FROM reports 
    WHERE status != 'На модерации' AND status != 'Отклонено модератором' AND status != 'Решено'
    ORDER BY created_at DESC LIMIT 10
    ''')

    reports = cursor.fetchall()
    conn.close()

    if not reports:
        await update.message.reply_text("На данный момент нет активных обращений.")
        return

    for report in reports:
        report_id, category, description, status, created_at = report

        # Получаем фото и координаты
        conn = sqlite3.connect('signal_kz.db')
        cursor = conn.cursor()

        cursor.execute('SELECT photo_id, latitude, longitude FROM reports WHERE report_id = ?', (report_id,))
        photo_id, latitude, longitude = cursor.fetchone()
        conn.close()

        await update.message.reply_photo(
            photo=photo_id,
            caption=f"Обращение №{report_id}\n"
                   f"Категория: {category}\n"
                   f"Описание: {description}\n"
                   f"Статус: {status}\n"
                   f"Дата создания: {created_at}\n"
                   f"Координаты: {latitude}, {longitude}",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("Изменить статус", callback_data=f"change_status_{report_id}")],
                [InlineKeyboardButton(
                    "Открыть на карте",
                    url=f"https://www.google.com/maps/search/?api=1&query={latitude},{longitude}"
                )]
            ])
        )

# Подробная информация об обращении
async def view_report_details(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    report_id = int(query.data.split("_")[1])

    conn = sqlite3.connect('signal_kz.db')
    cursor = conn.cursor()

    # Получаем информацию об обращении
    cursor.execute('''
    SELECT category, description, latitude, longitude, photo_id, status, created_at, updated_at
    FROM reports WHERE report_id = ?
    ''', (report_id,))

    report = cursor.fetchone()

    if not report:
        await query.edit_message_text("Обращение не найдено.")
        conn.close()
        return

    category, description, latitude, longitude, photo_id, status, created_at, updated_at = report

    # Получаем историю изменений статуса
    cursor.execute('''
    SELECT s.status, s.comment, s.created_at, u.first_name, u.last_name
    FROM status_updates s
    JOIN users u ON s.official_id = u.user_id
    WHERE s.report_id = ?
    ORDER BY s.created_at DESC
    ''', (report_id,))

    status_history = cursor.fetchall()
    conn.close()

    # Формируем сообщение с деталями
    details = f"Обращение №{report_id}\n\n"
    details += f"Категория: {category}\n"
    details += f"Описание: {description}\n"
    details += f"Статус: {status}\n"
    details += f"Дата создания: {created_at}\n"
    details += f"Последнее обновление: {updated_at}\n"
    details += f"Координаты: {latitude}, {longitude}\n\n"

    if status_history:
        details += "История изменений статуса:\n"
        for sh in status_history[:3]:  # Показываем только 3 последних изменения
            status, comment, date, first_name, last_name = sh
            official_name = f"{first_name} {last_name}" if first_name and last_name else "Госслужащий"
            details += f"• {date}: {status} ({official_name})\n"
            if comment:
                details += f"  Комментарий: {comment}\n"

    # Отправляем фото с подробной информацией
    await query.message.reply_photo(
        photo=photo_id,
        caption=details,
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton(
                "Открыть на карте",
                url=f"https://www.google.com/maps/search/?api=1&query={latitude},{longitude}"
            )]
        ])
    )





# Отмена текущего действия
async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    await update.message.reply_text("Действие отменено.")
    return ConversationHandler.END

def main():
    # Настройка логирования
    logging.basicConfig(
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        level=logging.INFO
    )

    # Создание базы данных
    setup_database()

    # Создание приложения
    application = Application.builder().token("8061380333:AAF8QAg0JDHVthZ8fLeATG1bYE4Y9FRLQ9c").build()

    # Добавление обработчиков команд
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("myreports", my_reports))
    application.add_handler(CommandHandler("update_status", update_status_command))
    application.add_handler(CommandHandler("register_official", register_official))
    application.add_handler(CommandHandler("register_moderator", register_moderator))
    application.add_handler(CommandHandler("pending_reports", pending_reports))
    application.add_handler(CommandHandler("all_reports", all_reports))
    application.add_handler(CommandHandler("set_role", set_role))

    # Обработчик создания обращения
    report_conv_handler = ConversationHandler(
        entry_points=[CommandHandler("report", start_report)],
        states={
            CATEGORY: [CallbackQueryHandler(category_selected, pattern=r"^cat_")],
            DESCRIPTION: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_description)],
            LOCATION: [MessageHandler(filters.LOCATION, get_location)],
            PHOTO: [MessageHandler(filters.PHOTO, get_photo)],
            CONFIRM: [CallbackQueryHandler(confirm_report, pattern=r"^confirm_")]
        },
        fallbacks=[CommandHandler("cancel", cancel)]
    )

    application.add_handler(report_conv_handler)

    # Обработчик обновления статуса
    status_update_handler = ConversationHandler(
        entry_points=[CallbackQueryHandler(status_callback, pattern=r"^status_")],
        states={
            COMMENT: [MessageHandler(filters.TEXT & ~filters.COMMAND, process_status_comment)]
        },
        fallbacks=[CommandHandler("cancel", cancel)]
    )

    application.add_handler(status_update_handler)

    # Обработчики колбэков
    application.add_handler(CallbackQueryHandler(moderator_decision, pattern=r"^mod_"))
    application.add_handler(CallbackQueryHandler(change_status_callback, pattern=r"^change_status_"))
    application.add_handler(CallbackQueryHandler(view_report_details, pattern=r"^view_"))

    # Запуск бота
    application.run_polling()

if __name__ == "__main__":
    main()