"""Форматирование сообщений для администратора.

Модуль предоставляет функции для создания сообщений и клавиатур
для администратора при работе с подтверждениями категорий книг.
"""

import re
from pathlib import Path
from typing import Any

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from src.utils import setup_logger

logger = setup_logger(__name__)


def escape_markdown_v2(text: str) -> str:
    """Экранирует специальные символы Markdown V2 для Telegram.

    Args:
        text: Текст для экранирования.

    Returns:
        Экранированный текст.
    """
    # Список специальных символов Markdown V2, которые нужно экранировать
    special_chars = r"_*[]()~`>#+-=|{}.!"
    # Экранируем каждый специальный символ
    escaped = re.sub(f"([{re.escape(special_chars)}])", r"\\\1", text)
    return escaped


def escape_markdown(text: str) -> str:
    """Экранирует специальные символы Markdown для Telegram.

    Args:
        text: Текст для экранирования.

    Returns:
        Экранированный текст.
    """
    # Список специальных символов Markdown, которые нужно экранировать
    special_chars = r"_*[]()~`>#+-=|{}.!"
    # Экранируем каждый специальный символ
    escaped = re.sub(f"([{re.escape(special_chars)}])", r"\\\1", text)
    return escaped


def format_confirmation_message(request: dict[str, Any]) -> str:
    """Форматирует сообщение для подтверждения категорий книги.

    Args:
        request: Словарь с данными запроса на подтверждение.

    Returns:
        Отформатированное сообщение в Markdown.
    """
    book_title = request.get("book_title", "Неизвестно")
    file_path = Path(request.get("file_path", ""))
    file_name = file_path.name if file_path else "Неизвестно"

    categories_from_filename = request.get("categories_from_filename", [])
    categories_llm = request.get("categories_llm_recommendation", [])
    llm_confidence = request.get("llm_confidence")
    llm_reasoning = request.get("llm_reasoning", "")

    # Экранируем специальные символы Markdown
    book_title_escaped = escape_markdown(book_title)
    file_name_escaped = escape_markdown(file_name)

    # Формируем сообщение
    message_parts = [
        "📚 *Новая книга требует подтверждения категорий*\n",
        f"📖 *Название:* {book_title_escaped}",
        f"📁 *Файл:* `{file_name_escaped}`\n",
    ]

    # Если есть категории из имени файла
    if categories_from_filename:
        categories_str = ", ".join(categories_from_filename)
        message_parts.append(f"📝 *Указано в имени файла:* {categories_str}")

    # Если есть рекомендация LLM
    if categories_llm:
        categories_str = ", ".join(categories_llm)
        confidence_str = (
            f"{llm_confidence * 100:.0f}%" if llm_confidence is not None else "N/A"
        )
        message_parts.append(f"\n🤖 *Рекомендация LLM:*")
        message_parts.append(f"   Категории: {categories_str}")
        message_parts.append(f"   Уверенность: {confidence_str}")

        if llm_reasoning:
            # Ограничиваем длину reasoning и экранируем
            reasoning_short = (
                llm_reasoning[:200] + "..." if len(llm_reasoning) > 200 else llm_reasoning
            )
            reasoning_escaped = escape_markdown(reasoning_short)
            message_parts.append(f"   Объяснение: {reasoning_escaped}")

    # Если нет ни категорий из файла, ни рекомендации LLM
    if not categories_from_filename and not categories_llm:
        message_parts.append("\n⚠️ Категории не определены")

    message = "\n".join(message_parts)
    logger.debug(f"Сформировано сообщение для подтверждения (длина: {len(message)} символов)")

    return message


def create_confirmation_keyboard(request_id: str) -> InlineKeyboardMarkup:
    """Создаёт inline-клавиатуру для подтверждения категорий.

    Args:
        request_id: ID запроса на подтверждение.

    Returns:
        InlineKeyboardMarkup с кнопками для подтверждения/отклонения/изменения.
    """
    keyboard = [
        [
            InlineKeyboardButton(
                "✅ Подтвердить", callback_data=f"confirm:{request_id}"
            ),
            InlineKeyboardButton(
                "❌ Отклонить", callback_data=f"reject:{request_id}"
            ),
        ],
        [
            InlineKeyboardButton(
                "✏️ Изменить категории", callback_data=f"edit:{request_id}"
            ),
        ],
    ]

    return InlineKeyboardMarkup(keyboard)


def format_pending_confirmations_list(confirmations: list[dict[str, Any]]) -> str:
    """Форматирует список ожидающих подтверждений.

    Args:
        confirmations: Список запросов на подтверждение.

    Returns:
        Отформатированное сообщение со списком.
    """
    if not confirmations:
        return "✅ Нет ожидающих подтверждений."

    from datetime import datetime, timedelta

    message_parts = [
        f"📋 *Ожидающие подтверждения: {len(confirmations)}*\n",
    ]

    now = datetime.now()

    for i, req in enumerate(confirmations, 1):
        request_id = req.get("request_id", "unknown")
        book_title = req.get("book_title", "Неизвестно")
        file_path = Path(req.get("file_path", ""))
        file_name = file_path.name if file_path else "Неизвестно"
        created_at = req.get("created_at", "")

        # Форматируем дату и вычисляем возраст
        try:
            dt = datetime.fromisoformat(created_at)
            date_str = dt.strftime("%d.%m.%Y %H:%M")
            
            # Вычисляем возраст запроса
            age_delta = now - dt
            age_hours = age_delta.total_seconds() / 3600
            
            if age_hours < 1:
                age_str = f"{int(age_delta.total_seconds() / 60)} мин"
            elif age_hours < 24:
                age_str = f"{int(age_hours)} ч"
            else:
                age_days = int(age_delta.days)
                age_str = f"{age_days} дн"
            
            # Добавляем предупреждение для старых запросов
            if age_hours >= 24:
                age_str = f"⚠️ {age_str} (старше 1 дня)"
            elif age_hours >= 12:
                age_str = f"⏰ {age_str}"
        except (ValueError, TypeError):
            date_str = created_at
            age_str = "неизвестно"

        # Экранируем специальные символы Markdown
        book_title_escaped = escape_markdown(book_title)
        file_name_escaped = escape_markdown(file_name)
        request_id_escaped = escape_markdown(request_id)

        message_parts.append(
            f"{i}. *{book_title_escaped}*\n"
            f"   📁 `{file_name_escaped}`\n"
            f"   🕐 {date_str} ({age_str})\n"
            f"   ID: `{request_id_escaped}`\n"
        )

    message = "\n".join(message_parts)
    return message


def format_confirmation_result_message(
    request: dict[str, Any], action: str, custom_categories: list[str] | None = None
) -> str:
    """Форматирует сообщение о результате подтверждения.

    Args:
        request: Словарь с данными запроса.
        action: Действие ("approved", "rejected", "edited").
        custom_categories: Пользовательские категории (если action="edited").

    Returns:
        Отформатированное сообщение.
    """
    book_title = request.get("book_title", "Неизвестно")
    file_path = Path(request.get("file_path", ""))
    file_name = file_path.name if file_path else "Неизвестно"

    # Экранируем специальные символы Markdown
    book_title_escaped = escape_markdown(book_title)
    file_name_escaped = escape_markdown(file_name)

    if action == "approved":
        categories = request.get("categories_llm_recommendation", [])
        if not categories:
            categories = request.get("categories_from_filename", [])
        categories_str = ", ".join(categories) if categories else "не указаны"
        return (
            f"✅ *Подтверждено*\n\n"
            f"📖 Книга: {book_title_escaped}\n"
            f"📁 Файл: `{file_name_escaped}`\n"
            f"📚 Категории: {categories_str}"
        )

    elif action == "rejected":
        return (
            f"❌ *Отклонено*\n\n"
            f"📖 Книга: {book_title_escaped}\n"
            f"📁 Файл: `{file_name_escaped}`\n\n"
            f"Файл будет удалён из-за отсутствия подтверждения категорий."
        )

    elif action == "edited":
        if custom_categories:
            categories_str = ", ".join(custom_categories)
            return (
                f"✏️ *Категории изменены*\n\n"
                f"📖 Книга: {book_title_escaped}\n"
                f"📁 Файл: `{file_name_escaped}`\n"
                f"📚 Новые категории: {categories_str}"
            )
        else:
            return (
                f"✏️ *Категории изменены*\n\n"
                f"📖 Книга: {book_title_escaped}\n"
                f"📁 Файл: `{file_name_escaped}`\n"
                f"📚 Категории: не указаны"
            )

    else:
        return f"❓ Неизвестное действие: {action}"


def format_timeout_message(request: dict[str, Any]) -> str:
    """Форматирует сообщение об истечении времени ожидания подтверждения.

    Args:
        request: Словарь с данными запроса.

    Returns:
        Отформатированное сообщение.
    """
    book_title = request.get("book_title", "Неизвестно")
    file_path = Path(request.get("file_path", ""))
    file_name = file_path.name if file_path else "Неизвестно"

    # Экранируем специальные символы Markdown
    book_title_escaped = escape_markdown(book_title)
    file_name_escaped = escape_markdown(file_name)

    return (
        f"⏰ *Истёк срок ожидания подтверждения*\n\n"
        f"📖 Книга: {book_title_escaped}\n"
        f"📁 Файл: `{file_name_escaped}`\n\n"
        f"Файл был удалён из-за отсутствия подтверждения в течение "
        f"установленного времени ожидания."
    )


def format_category_selection_keyboard() -> InlineKeyboardMarkup:
    """Создаёт клавиатуру для выбора категорий.

    Используется при редактировании категорий.

    Returns:
        InlineKeyboardMarkup с кнопками категорий.
    """
    from src.config import Config

    categories = Config.CATEGORIES

    # Создаём кнопки по 2 в ряд
    buttons = []
    for i in range(0, len(categories), 2):
        row = [
            InlineKeyboardButton(categories[i], callback_data=f"cat:{categories[i]}")
        ]
        if i + 1 < len(categories):
            row.append(
                InlineKeyboardButton(
                    categories[i + 1], callback_data=f"cat:{categories[i + 1]}"
                )
            )
        buttons.append(row)

    # Кнопка "Готово"
    buttons.append([InlineKeyboardButton("✅ Готово", callback_data="cat:done")])
    buttons.append([InlineKeyboardButton("❌ Отмена", callback_data="cat:cancel")])

    return InlineKeyboardMarkup(buttons)


def format_edit_categories_keyboard(
    request_id: str, selected_categories: list[str] | None = None
) -> InlineKeyboardMarkup:
    """Создаёт клавиатуру для редактирования категорий при подтверждении.

    Args:
        request_id: ID запроса на подтверждение.
        selected_categories: Список выбранных категорий (если None, берутся из запроса).

    Returns:
        InlineKeyboardMarkup с кнопками категорий для редактирования.
    """
    from src.config import Config

    categories = Config.CATEGORIES
    if selected_categories is None:
        selected_categories = []

    # Создаём кнопки по 2 в ряд
    buttons = []
    for i in range(0, len(categories), 2):
        cat1 = categories[i]
        cat1_marked = f"✓ {cat1}" if cat1 in selected_categories else cat1
        row = [
            InlineKeyboardButton(
                cat1_marked, callback_data=f"edit_cat:{request_id}:{cat1}"
            )
        ]
        if i + 1 < len(categories):
            cat2 = categories[i + 1]
            cat2_marked = f"✓ {cat2}" if cat2 in selected_categories else cat2
            row.append(
                InlineKeyboardButton(
                    cat2_marked, callback_data=f"edit_cat:{request_id}:{cat2}"
                )
            )
        buttons.append(row)

    # Кнопка "Готово"
    buttons.append(
        [InlineKeyboardButton("✅ Готово", callback_data=f"edit_done:{request_id}")]
    )
    buttons.append(
        [InlineKeyboardButton("❌ Отмена", callback_data=f"edit_cancel:{request_id}")]
    )

    return InlineKeyboardMarkup(buttons)


def format_edit_categories_message(
    request: dict[str, Any], selected_categories: list[str] | None = None
) -> str:
    """Форматирует сообщение для редактирования категорий.

    Args:
        request: Словарь с данными запроса на подтверждение.
        selected_categories: Список выбранных категорий (если None, берутся из запроса).

    Returns:
        Отформатированное сообщение.
    """
    book_title = request.get("book_title", "Неизвестно")
    file_path = Path(request.get("file_path", ""))
    file_name = file_path.name if file_path else "Неизвестно"

    if selected_categories is None:
        selected_categories = request.get("categories_llm_recommendation", [])
        if not selected_categories:
            selected_categories = request.get("categories_from_filename", [])

    # Экранируем специальные символы Markdown
    book_title_escaped = escape_markdown(book_title)
    file_name_escaped = escape_markdown(file_name)

    categories_str = ", ".join(selected_categories) if selected_categories else "не выбраны"

    message = (
        f"✏️ *Редактирование категорий*\n\n"
        f"📖 *Название:* {book_title_escaped}\n"
        f"📁 *Файл:* `{file_name_escaped}`\n\n"
        f"*Текущие категории:* {categories_str}\n\n"
        f"Выберите категории из списка ниже:"
    )

    return message


def format_pending_books_message(pending_books: list[dict[str, Any]]) -> str:
    """Форматирует сообщение о непроиндексированных книгах.
    
    Args:
        pending_books: Список словарей с информацией о непроиндексированных книгах.
    
    Returns:
        Отформатированное сообщение в Markdown.
    """
    if not pending_books:
        return "✅ Нет непроиндексированных книг."
    
    count = len(pending_books)
    message_parts = [
        f"📚 *Обнаружены новые книги*\n\n",
        f"Найдено непроиндексированных книг: *{count}*\n\n"
    ]
    
    # Показываем список книг (максимум 10, чтобы не перегружать сообщение)
    max_show = min(10, count)
    for i, book in enumerate(pending_books[:max_show], 1):
        file_name = book.get("file_name", "unknown")
        file_size_mb = book.get("file_size", 0) / (1024 * 1024)
        file_name_escaped = escape_markdown(file_name)
        message_parts.append(f"{i}\\. `{file_name_escaped}` \\({file_size_mb:.2f} MB\\)\n")
    
    if count > max_show:
        message_parts.append(f"\n\\.\\.\\. и еще {count - max_show} книг\\.\\.\\.\n")
    
    message_parts.append(
        "\nВыберите действие:\n"
        "• *Индексировать* — начать индексацию всех книг\n"
        "• *Отмена* — оставить книги без индексации"
    )
    
    return "".join(message_parts)


def create_index_books_keyboard() -> InlineKeyboardMarkup:
    """Создает клавиатуру для уведомления о непроиндексированных книгах.
    
    Returns:
        Объект InlineKeyboardMarkup с кнопками индексации.
    """
    keyboard = [
        [
            InlineKeyboardButton(
                "✅ Индексировать",
                callback_data="index_books:confirm"
            ),
            InlineKeyboardButton(
                "❌ Отмена",
                callback_data="index_books:cancel"
            )
        ],
        [
            InlineKeyboardButton(
                "📋 Показать список",
                callback_data="index_books:list"
            )
        ]
    ]
    return InlineKeyboardMarkup(keyboard)


def format_pending_books_list(pending_books: list[dict[str, Any]]) -> str:
    """Форматирует детальный список непроиндексированных книг.
    
    Args:
        pending_books: Список словарей с информацией о непроиндексированных книгах.
    
    Returns:
        Отформатированное сообщение в Markdown.
    """
    if not pending_books:
        return "✅ Нет непроиндексированных книг."
    
    message_parts = [
        f"📚 *Список непроиндексированных книг*\n\n",
        f"Всего: *{len(pending_books)}* книг\n\n"
    ]
    
    for i, book in enumerate(pending_books, 1):
        file_name = book.get("file_name", "unknown")
        file_size_mb = book.get("file_size", 0) / (1024 * 1024)
        added_at = book.get("added_at", "")
        
        file_name_escaped = escape_markdown(file_name)
        
        # Форматируем дату добавления
        date_str = ""
        if added_at:
            try:
                from datetime import datetime
                dt = datetime.fromisoformat(added_at)
                date_str = dt.strftime("%d\\.%m\\.%Y %H:%M")
            except (ValueError, TypeError):
                date_str = added_at
        
        message_parts.append(
            f"{i}\\. *{file_name_escaped}*\n"
            f"   Размер: {file_size_mb:.2f} MB\n"
        )
        if date_str:
            message_parts.append(f"   Добавлено: {date_str}\n")
        message_parts.append("\n")
    
    return "".join(message_parts)


def format_success_notification_message(
    book_title: str, file_name: str, categories: list[str], chunks_count: int
) -> str:
    """Форматирует сообщение об успешной индексации файла.

    Args:
        book_title: Название книги.
        file_name: Имя файла.
        categories: Список категорий.
        chunks_count: Количество созданных чанков.

    Returns:
        Отформатированное сообщение в Markdown V2.
    """
    # Экранируем специальные символы Markdown
    book_title_escaped = escape_markdown(book_title)
    file_name_escaped = escape_markdown(file_name)

    categories_str = ", ".join(categories) if categories else "не указаны"

    message = (
        f"✅ *Файл успешно проиндексирован*\n\n"
        f"📖 *Название:* {book_title_escaped}\n"
        f"📁 *Файл:* `{file_name_escaped}`\n"
        f"📋 *Категории:* {categories_str}\n"
        f"📊 *Чанков создано:* {chunks_count}\n\n"
        f"*Статус:* Проиндексирован автоматически \\(категории найдены в имени файла\\)"
    )

    return message

