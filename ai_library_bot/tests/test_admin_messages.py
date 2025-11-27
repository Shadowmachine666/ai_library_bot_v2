"""Тесты для admin_messages.py."""

from pathlib import Path

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from src.admin_messages import (
    create_confirmation_keyboard,
    format_category_selection_keyboard,
    format_confirmation_message,
    format_confirmation_result_message,
    format_pending_confirmations_list,
    format_timeout_message,
)


def test_format_confirmation_message_with_llm():
    """Тест: форматирование сообщения с рекомендацией LLM."""
    request = {
        "request_id": "req_123",
        "file_path": str(Path("data/books/Книга.pdf").absolute()),
        "book_title": "Основы маркетинга",
        "categories_from_filename": [],
        "categories_llm_recommendation": ["бизнес", "маркетинг"],
        "llm_confidence": 0.95,
        "llm_reasoning": "Книга о маркетинге",
    }

    message = format_confirmation_message(request)

    assert "Основы маркетинга" in message
    assert "Книга.pdf" in message
    assert "бизнес" in message or "маркетинг" in message
    assert "95%" in message or "0.95" in message


def test_format_confirmation_message_with_filename_categories():
    """Тест: форматирование сообщения с категориями из имени файла."""
    request = {
        "request_id": "req_123",
        "file_path": str(Path("data/books/Книга (бизнес).pdf").absolute()),
        "book_title": "Книга",
        "categories_from_filename": ["бизнес"],
        "categories_llm_recommendation": ["бизнес", "маркетинг"],
        "llm_confidence": 0.95,
        "llm_reasoning": "Объяснение",
    }

    message = format_confirmation_message(request)

    assert "Книга" in message
    assert "бизнес" in message


def test_format_confirmation_message_no_categories():
    """Тест: форматирование сообщения без категорий."""
    request = {
        "request_id": "req_123",
        "file_path": str(Path("data/books/Книга.pdf").absolute()),
        "book_title": "Книга",
        "categories_from_filename": [],
        "categories_llm_recommendation": [],
        "llm_confidence": None,
        "llm_reasoning": "",
    }

    message = format_confirmation_message(request)

    assert "Книга" in message
    assert "Категории не определены" in message or "⚠️" in message


def test_create_confirmation_keyboard():
    """Тест: создание клавиатуры для подтверждения."""
    request_id = "req_123"
    keyboard = create_confirmation_keyboard(request_id)

    assert isinstance(keyboard, InlineKeyboardMarkup)

    # Проверяем наличие кнопок
    buttons = keyboard.inline_keyboard
    assert len(buttons) >= 2  # Должно быть минимум 2 ряда кнопок

    # Проверяем callback_data
    all_callbacks = []
    for row in buttons:
        for button in row:
            if isinstance(button, InlineKeyboardButton):
                all_callbacks.append(button.callback_data)

    assert any("confirm:req_123" in cb for cb in all_callbacks if cb)
    assert any("reject:req_123" in cb for cb in all_callbacks if cb)
    assert any("edit:req_123" in cb for cb in all_callbacks if cb)


def test_format_pending_confirmations_list_empty():
    """Тест: форматирование пустого списка подтверждений."""
    message = format_pending_confirmations_list([])

    assert "Нет ожидающих подтверждений" in message


def test_format_pending_confirmations_list_with_items():
    """Тест: форматирование списка с элементами."""
    confirmations = [
        {
            "request_id": "req_123",
            "file_path": str(Path("data/books/Книга1.pdf").absolute()),
            "book_title": "Книга 1",
            "created_at": "2024-01-01T12:00:00",
        },
        {
            "request_id": "req_456",
            "file_path": str(Path("data/books/Книга2.pdf").absolute()),
            "book_title": "Книга 2",
            "created_at": "2024-01-01T13:00:00",
        },
    ]

    message = format_pending_confirmations_list(confirmations)

    assert "Книга 1" in message
    assert "Книга 2" in message
    assert "req_123" in message
    assert "req_456" in message


def test_format_confirmation_result_message_approved():
    """Тест: форматирование сообщения о подтверждении."""
    request = {
        "book_title": "Книга",
        "file_path": str(Path("data/books/Книга.pdf").absolute()),
        "categories_llm_recommendation": ["бизнес", "маркетинг"],
    }

    message = format_confirmation_result_message(request, "approved")

    assert "Подтверждено" in message
    assert "Книга" in message
    assert "бизнес" in message or "маркетинг" in message


def test_format_confirmation_result_message_rejected():
    """Тест: форматирование сообщения об отклонении."""
    request = {
        "book_title": "Книга",
        "file_path": str(Path("data/books/Книга.pdf").absolute()),
    }

    message = format_confirmation_result_message(request, "rejected")

    assert "Отклонено" in message
    assert "Книга" in message
    assert "будет удалён" in message or "удалён" in message


def test_format_confirmation_result_message_edited():
    """Тест: форматирование сообщения об изменении."""
    request = {
        "book_title": "Книга",
        "file_path": str(Path("data/books/Книга.pdf").absolute()),
    }

    message = format_confirmation_result_message(request, "edited", ["психология"])

    assert "Категории изменены" in message
    assert "Книга" in message
    assert "психология" in message


def test_format_timeout_message():
    """Тест: форматирование сообщения об истечении времени."""
    request = {
        "book_title": "Книга",
        "file_path": str(Path("data/books/Книга.pdf").absolute()),
    }

    message = format_timeout_message(request)

    assert "Истёк срок" in message or "истёк" in message
    assert "Книга" in message
    assert "удалён" in message


def test_format_category_selection_keyboard():
    """Тест: создание клавиатуры для выбора категорий."""
    keyboard = format_category_selection_keyboard()

    assert isinstance(keyboard, InlineKeyboardMarkup)

    # Проверяем наличие кнопок категорий
    buttons = keyboard.inline_keyboard
    assert len(buttons) > 0

    # Проверяем наличие кнопок "Готово" и "Отмена"
    all_callbacks = []
    for row in buttons:
        for button in row:
            if isinstance(button, InlineKeyboardButton):
                all_callbacks.append(button.callback_data)

    assert any("cat:done" in cb for cb in all_callbacks if cb)
    assert any("cat:cancel" in cb for cb in all_callbacks if cb)

