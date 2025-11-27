"""Форматтеры для ai_library_bot.

Преобразуют структурированные ответы анализатора в красивые Markdown сообщения
для отправки пользователю через Telegram.
"""

import re

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from src.analyzer import AnalysisResponse, Result
from src.config import Config
from src.utils import setup_logger

logger = setup_logger(__name__)


def escape_markdown(text: str) -> str:
    """Экранирует специальные символы Markdown в тексте.
    
    Экранирует символы, которые имеют специальное значение в Telegram MarkdownV1:
    _ * ` [ ] ( ) - для форматирования и ссылок
    
    Args:
        text: Текст для экранирования.
    
    Returns:
        Текст с экранированными специальными символами.
    """
    # Символы, которые нужно экранировать в Telegram MarkdownV1
    # _ * ` [ ] ( ) - основные символы форматирования
    special_chars = r'_*`[]()'
    
    # Экранируем каждый специальный символ
    for char in special_chars:
        text = text.replace(char, f'\\{char}')
    
    return text


def format_response(
    response: AnalysisResponse,
    used_categories: list[str] | None = None,
) -> str:
    """Форматирует ответ анализатора в Markdown текст.

    Args:
        response: Объект AnalysisResponse от анализатора.
        used_categories: Категории, использованные для поиска (None = все категории).

    Returns:
        Отформатированный текст в Markdown для отправки пользователю.
    """
    if response.status == "NOT_FOUND":
        return format_not_found()

    if response.status == "CLARIFICATION_NEEDED":
        return format_clarification_needed(response.clarification_question)

    if response.status == "CONFLICT":
        return format_conflict(response)

    if response.status == "SUCCESS" and response.result:
        return format_success(response.result, used_categories=used_categories)

    # Fallback для неизвестного статуса
    logger.warning(f"Неизвестный статус ответа: {response.status}")
    return "❌ Произошла ошибка при обработке запроса."


def format_not_found() -> str:
    """Форматирует сообщение об отсутствии информации.

    Returns:
        Markdown текст сообщения.
    """
    return """❌ **Информация не найдена**

К сожалению, в загруженных книгах не найдено информации,
отвечающей на ваш вопрос.

Попробуйте переформулировать вопрос или уточнить его."""


def format_clarification_needed(question: str | None) -> str:
    """Форматирует сообщение с просьбой уточнить вопрос.

    Args:
        question: Вопрос для уточнения (может быть None).

    Returns:
        Markdown текст сообщения.
    """
    if question:
        escaped_question = escape_markdown(question)
        return f"""❓ **Требуется уточнение**

{escaped_question}

Пожалуйста, уточните ваш вопрос, чтобы я мог найти
нужную информацию в загруженных книгах."""

    return """❓ **Требуется уточнение**

Ваш вопрос слишком общий. Пожалуйста, уточните его,
чтобы я мог найти нужную информацию в загруженных книгах."""


def format_conflict(response: AnalysisResponse) -> str:
    """Форматирует сообщение о конфликте данных.

    Args:
        response: Объект AnalysisResponse со статусом CONFLICT.

    Returns:
        Markdown текст сообщения.
    """
    return """⚠️ **Обнаружен конфликт данных**

В загруженных книгах найдена противоречивая информация
по вашему вопросу.

Пожалуйста, уточните вопрос или укажите конкретный источник,
который вас интересует."""


def format_success(result: Result, used_categories: list[str] | None = None) -> str:
    """Форматирует успешный ответ с результатом анализа.

    Args:
        result: Объект Result с ответом и цитатами.
        used_categories: Категории, использованные для поиска (None = все категории).

    Returns:
        Markdown текст сообщения.
    """
    lines = ["✅ **Ответ:**\n"]

    # Добавляем основной ответ (экранируем специальные символы)
    escaped_answer = escape_markdown(result.answer)
    lines.append(f"{escaped_answer}\n")

    # Добавляем цитаты, если есть
    if result.quotes:
        lines.append("\n📚 **Источники:**\n")
        for i, quote in enumerate(result.quotes, 1):
            # Экранируем текст цитаты и источник
            escaped_text = escape_markdown(quote.text)
            escaped_source = escape_markdown(quote.source)
            lines.append(f"{i}\\. _{escaped_text}_")
            lines.append(f"   📖 {escaped_source}\n")

    # Добавляем информацию о категориях поиска
    if used_categories:
        categories_str = ", ".join(used_categories)
        escaped_categories = escape_markdown(categories_str)
        lines.append(f"\n🔍 _Поиск выполнен по категориям: {escaped_categories}_\n")
    else:
        lines.append("\n🔍 _Поиск выполнен по всем категориям_\n")

    # Добавляем дисклеймер
    if result.disclaimer:
        escaped_disclaimer = escape_markdown(result.disclaimer)
        lines.append(f"\n_{escaped_disclaimer}_")

    return "\n".join(lines)


def format_start_message() -> str:
    """Форматирует приветственное сообщение для команды /start.

    Returns:
        Markdown текст приветствия.
    """
    return """👋 **Добро пожаловать в AI-библиотеку!**

Я помогу вам найти информацию в загруженных книгах.

Просто задайте мне вопрос, и я найду релевантные фрагменты
из вашей библиотеки и дам ответ на основе этих данных.

**Примеры вопросов:**
• Что такое машинное обучение?
• Расскажи о Python
• Какие есть методы работы с данными?

Вы можете выбрать интересующие вас категории книг ниже,
или использовать все категории по умолчанию.

Задайте ваш вопрос! 📚"""


def format_categories_message(selected_categories: list[str] | None) -> str:
    """Форматирует сообщение о выбранных категориях.

    Args:
        selected_categories: Список выбранных категорий или None (все категории).

    Returns:
        Markdown текст сообщения.
    """
    if selected_categories is None or len(selected_categories) == 0:
        return """📚 **Категории книг**

Выбраны все категории. Поиск будет выполняться по всем книгам.

Используйте кнопки ниже, чтобы выбрать конкретные категории."""
    
    categories_str = ", ".join(selected_categories)
    return f"""📚 **Выбранные категории**

Вы выбрали следующие категории:
• {categories_str}

Поиск будет выполняться только по книгам из этих категорий.

Используйте кнопки ниже, чтобы изменить выбор."""


def create_categories_keyboard(selected_categories: list[str] | None = None) -> InlineKeyboardMarkup:
    """Создает inline-клавиатуру для выбора категорий книг.

    Args:
        selected_categories: Список уже выбранных категорий или None.

    Returns:
        Объект InlineKeyboardMarkup с кнопками категорий.
    """
    if selected_categories is None:
        selected_categories = []

    keyboard_buttons = []
    
    # Создаем кнопки для каждой категории
    for category in Config.CATEGORIES:
        # Отмечаем выбранные категории галочкой
        emoji = "✅ " if category in selected_categories else ""
        keyboard_buttons.append([
            InlineKeyboardButton(
                f"{emoji}{category}",
                callback_data=f"toggle_cat:{category}"
            )
        ])
    
    # Кнопки управления
    keyboard_buttons.append([
        InlineKeyboardButton("✅ Все категории", callback_data="select_all_cats"),
        InlineKeyboardButton("❌ Сбросить", callback_data="clear_cats")
    ])
    
    return InlineKeyboardMarkup(keyboard_buttons)


def create_response_keyboard(query_hash: str) -> InlineKeyboardMarkup:
    """Создает клавиатуру для ответа с кнопкой изменения категорий.
    
    Args:
        query_hash: Хеш запроса для идентификации при изменении категорий.
    
    Returns:
        Объект InlineKeyboardMarkup с кнопкой изменения категорий.
    """
    keyboard = [
        [
            InlineKeyboardButton(
                "🔄 Изменить категории",
                callback_data=f"change_cats:{query_hash}"
            )
        ]
    ]
    return InlineKeyboardMarkup(keyboard)


def create_query_categories_keyboard(
    query_hash: str, selected_categories: list[str] | None = None
) -> InlineKeyboardMarkup:
    """Создает клавиатуру для выбора категорий при запросе.
    
    Показывает все категории с индикацией выбранных + кнопки управления.
    
    Args:
        query_hash: Хеш запроса для идентификации.
        selected_categories: Список выбранных категорий (для показа галочек).
    
    Returns:
        Объект InlineKeyboardMarkup с кнопками категорий и управления.
    """
    if selected_categories is None:
        selected_categories = []
    
    keyboard_buttons = []
    
    # Создаем кнопки для каждой категории с индикацией выбора
    for category in Config.CATEGORIES:
        # Показываем галочку для выбранных категорий
        display_text = f"✅ {category}" if category in selected_categories else category
        keyboard_buttons.append([
            InlineKeyboardButton(
                display_text,
                callback_data=f"query_cat:{query_hash}:{category}"
            )
        ])
    
    # Кнопки управления
    keyboard_buttons.append([
        InlineKeyboardButton(
            "🔍 Начать поиск",
            callback_data=f"query_search:{query_hash}"
        ),
        InlineKeyboardButton(
            "❌ Сбросить",
            callback_data=f"query_reset:{query_hash}"
        )
    ])
    keyboard_buttons.append([
        InlineKeyboardButton(
            "🤖 Автоопределение",
            callback_data=f"query_auto:{query_hash}"
        )
    ])
    keyboard_buttons.append([
        InlineKeyboardButton(
            "✅ Все категории",
            callback_data=f"query_all:{query_hash}"
        )
    ])
    
    return InlineKeyboardMarkup(keyboard_buttons)
