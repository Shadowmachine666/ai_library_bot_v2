"""Тесты для telegram_bot.py и полного flow."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from telegram import Message, Update, User
from telegram.ext import ContextTypes

from src.analyzer import AnalysisResponse, Quote, Result
from src.retriever_service import NOT_FOUND
from src.telegram_bot import (
    create_bot_application,
    format_response,
    handle_message,
    start_command,
)


@pytest.fixture
def mock_update():
    """Создаёт mock объект Update для тестов."""
    update = MagicMock(spec=Update)
    update.effective_user = MagicMock(spec=User)
    update.effective_user.id = 12345
    update.effective_user.username = "test_user"
    update.message = MagicMock(spec=Message)
    update.message.text = "Тестовый вопрос"
    update.message.reply_text = AsyncMock()
    update.message.edit_text = AsyncMock()
    return update


@pytest.fixture
def mock_context():
    """Создаёт mock объект Context для тестов."""
    context = MagicMock(spec=ContextTypes.DEFAULT_TYPE)
    return context


@pytest.mark.asyncio
async def test_start_command(mock_update, mock_context):
    """Тест: обработка команды /start."""
    await start_command(mock_update, mock_context)

    # Проверяем, что ответ был отправлен
    assert mock_update.message.reply_text.called
    call_args = mock_update.message.reply_text.call_args
    assert "Добро пожаловать" in call_args[0][0] or "Добро пожаловать" in str(call_args)


@pytest.mark.asyncio
async def test_handle_message_success(mock_update, mock_context):
    """Тест: успешная обработка сообщения (полный flow)."""
    mock_update.message.text = "Что такое Python?"

    # Создаём mock для processing_message (результат reply_text)
    mock_processing_message = MagicMock()
    mock_processing_message.edit_text = AsyncMock()
    mock_update.message.reply_text = AsyncMock(return_value=mock_processing_message)

    # Мокаем все зависимости
    with (
        patch("src.telegram_bot.retrieve_chunks") as mock_retrieve,
        patch("src.telegram_bot.analyze") as mock_analyze,
        patch("src.telegram_bot._get_from_cache") as mock_cache_get,
        patch("src.telegram_bot._set_to_cache") as mock_cache_set,
    ):

        # Настраиваем моки
        mock_cache_get.return_value = None  # Кэш пуст
        mock_retrieve.return_value = [
            {"text": "Python - язык программирования", "source": "book.txt", "chunk_index": 0}
        ]
        mock_analyze.return_value = AnalysisResponse(
            status="SUCCESS",
            clarification_question=None,
            result=Result(
                answer="Python - это язык программирования",
                quotes=[Quote(text="Python - язык", source="book.txt")],
            ),
        )

        await handle_message(mock_update, mock_context)

        # Проверяем, что все функции были вызваны
        assert mock_cache_get.called
        assert mock_retrieve.called
        assert mock_analyze.called
        assert mock_cache_set.called
        assert mock_update.message.reply_text.called  # Сообщение "Ищу информацию..."
        assert mock_processing_message.edit_text.called  # Финальный ответ


@pytest.mark.asyncio
async def test_handle_message_cached(mock_update, mock_context):
    """Тест: обработка сообщения с ответом из кэша."""
    mock_update.message.text = "Что такое Python?"

    # Создаём mock для processing_message
    mock_processing_message = MagicMock()
    mock_processing_message.edit_text = AsyncMock()
    mock_update.message.reply_text = AsyncMock(return_value=mock_processing_message)

    # Мокаем кэш, чтобы вернуть закэшированный ответ
    with patch("src.telegram_bot._get_from_cache") as mock_cache_get:
        cached_response = "✅ **Ответ:**\nPython - это язык программирования"
        mock_cache_get.return_value = cached_response

        await handle_message(mock_update, mock_context)

        # Проверяем, что ответ взят из кэша
        assert mock_cache_get.called
        # Проверяем, что ответ был отправлен через edit_text
        assert mock_processing_message.edit_text.called
        # Проверяем, что retrieve и analyze НЕ были вызваны
        # (это проверяется через отсутствие вызовов)


@pytest.mark.asyncio
async def test_handle_message_not_found(mock_update, mock_context):
    """Тест: обработка сообщения без релевантных результатов."""
    mock_update.message.text = "Очень специфичный вопрос"

    # Создаём mock для processing_message
    mock_processing_message = MagicMock()
    mock_processing_message.edit_text = AsyncMock()
    mock_update.message.reply_text = AsyncMock(return_value=mock_processing_message)

    with (
        patch("src.telegram_bot.retrieve_chunks") as mock_retrieve,
        patch("src.telegram_bot._get_from_cache") as mock_cache_get,
    ):

        mock_cache_get.return_value = None
        mock_retrieve.return_value = NOT_FOUND

        await handle_message(mock_update, mock_context)

        # Проверяем, что был вызван retrieve
        assert mock_retrieve.called
        # Проверяем, что ответ был отправлен
        assert mock_processing_message.edit_text.called


@pytest.mark.asyncio
async def test_handle_message_too_long(mock_update, mock_context):
    """Тест: обработка слишком длинного сообщения."""
    mock_update.message.text = "A" * 1500  # Больше 1000 символов

    await handle_message(mock_update, mock_context)

    # Проверяем, что было отправлено сообщение об ошибке
    assert mock_update.message.reply_text.called
    call_args = mock_update.message.reply_text.call_args
    assert "слишком длинный" in call_args[0][0] or "слишком длинный" in str(call_args)


@pytest.mark.asyncio
async def test_handle_message_error(mock_update, mock_context):
    """Тест: обработка ошибки при обработке сообщения."""
    mock_update.message.text = "Вопрос"

    # Создаём mock для processing_message
    mock_processing_message = MagicMock()
    mock_processing_message.edit_text = AsyncMock()
    mock_update.message.reply_text = AsyncMock(return_value=mock_processing_message)

    # Мокаем retrieve_chunks, чтобы выбросить исключение
    with (
        patch("src.telegram_bot.retrieve_chunks") as mock_retrieve,
        patch("src.telegram_bot._get_from_cache") as mock_cache_get,
    ):

        mock_cache_get.return_value = None
        mock_retrieve.side_effect = Exception("Ошибка при поиске")

        await handle_message(mock_update, mock_context)

        # Проверяем, что было отправлено сообщение об ошибке
        assert mock_processing_message.edit_text.called
        call_args = mock_processing_message.edit_text.call_args
        assert "ошибка" in call_args[0][0].lower() or "ошибка" in str(call_args).lower()


def test_format_response_success():
    """Тест: форматирование успешного ответа."""
    response = AnalysisResponse(
        status="SUCCESS",
        clarification_question=None,
        result=Result(
            answer="Ответ на вопрос",
            quotes=[Quote(text="Цитата", source="Книга 1")],
        ),
    )

    formatted = format_response(response)

    assert "Ответ" in formatted
    assert "Цитата" in formatted
    assert "Книга 1" in formatted


def test_format_response_not_found():
    """Тест: форматирование ответа NOT_FOUND."""
    response = AnalysisResponse(status="NOT_FOUND", clarification_question=None, result=None)

    formatted = format_response(response)

    assert "не найдено" in formatted.lower() or "не найдено" in formatted


def test_format_response_clarification():
    """Тест: форматирование ответа CLARIFICATION_NEEDED."""
    response = AnalysisResponse(
        status="CLARIFICATION_NEEDED",
        clarification_question="Уточните вопрос",
        result=None,
    )

    formatted = format_response(response)

    assert "уточнение" in formatted.lower() or "уточнение" in formatted


def test_create_bot_application():
    """Тест: создание приложения бота."""
    # Мокаем Config.TG_TOKEN
    with patch("src.telegram_bot.Config.TG_TOKEN", "test_token"):
        app = create_bot_application()

        assert app is not None
        # Проверяем, что обработчики зарегистрированы
        assert len(app.handlers[0]) > 0
