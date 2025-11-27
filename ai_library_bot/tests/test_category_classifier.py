"""Тесты для category_classifier.py."""

import json
from unittest.mock import AsyncMock, patch

import pytest

from src.category_classifier import (
    CategoryClassificationResult,
    _parse_classification_response,
    classify_book_category,
)


@pytest.mark.asyncio
async def test_classify_book_category_success():
    """Тест: успешное определение категорий через LLM."""
    book_title = "Основы маркетинга"

    # Мокаем ответ LLM
    mock_response = {
        "topics": ["бизнес", "маркетинг"],
        "confidence": 0.95,
        "reasoning": "Книга о маркетинге относится к бизнесу и маркетингу",
    }

    with patch("src.category_classifier._call_llm_for_classification") as mock_llm:
        mock_llm.return_value = json.dumps(mock_response, ensure_ascii=False)

        result = await classify_book_category(book_title)

        assert result["topics"] == ["бизнес", "маркетинг"]
        assert result["confidence"] == 0.95
        assert "reasoning" in result
        mock_llm.assert_called_once()


@pytest.mark.asyncio
async def test_classify_book_category_with_content_preview():
    """Тест: успешное определение категорий с использованием превью содержимого."""
    book_title = "book1"
    content_preview = "Эта книга рассказывает о психологии поведения человека, о том, как работает мозг и как люди принимают решения."

    # Мокаем ответ LLM
    mock_response = {
        "topics": ["психология"],
        "confidence": 0.92,
        "reasoning": "Содержимое книги явно относится к психологии",
    }

    with patch("src.category_classifier._call_llm_for_classification") as mock_llm:
        mock_llm.return_value = json.dumps(mock_response, ensure_ascii=False)

        result = await classify_book_category(book_title, content_preview)

        assert result["topics"] == ["психология"]
        assert result["confidence"] == 0.92
        assert "reasoning" in result
        mock_llm.assert_called_once()
        
        # Проверяем, что промпт содержит превью содержимого
        call_args = mock_llm.call_args[0][0]
        assert content_preview in call_args


@pytest.mark.asyncio
async def test_classify_book_category_empty_title():
    """Тест: определение категорий с пустым названием."""
    with pytest.raises(ValueError, match="Название книги не может быть пустым"):
        await classify_book_category("")


@pytest.mark.asyncio
async def test_parse_classification_response_valid():
    """Тест: парсинг валидного ответа LLM."""
    response_text = json.dumps(
        {
            "topics": ["бизнес", "маркетинг"],
            "confidence": 0.95,
            "reasoning": "Объяснение",
        },
        ensure_ascii=False,
    )

    result = _parse_classification_response(response_text)

    assert isinstance(result, CategoryClassificationResult)
    assert result.topics == ["бизнес", "маркетинг"]
    assert result.confidence == 0.95
    assert result.reasoning == "Объяснение"


@pytest.mark.asyncio
async def test_parse_classification_response_invalid_json():
    """Тест: парсинг невалидного JSON."""
    invalid_json = "Это не JSON"

    with pytest.raises(ValueError, match="Невалидный JSON"):
        _parse_classification_response(invalid_json)


@pytest.mark.asyncio
async def test_parse_classification_response_invalid_schema():
    """Тест: парсинг JSON с невалидной схемой."""
    invalid_schema = {"invalid": "data"}

    with pytest.raises(ValueError, match="не соответствует схеме"):
        _parse_classification_response(json.dumps(invalid_schema))


def test_category_classification_result_model():
    """Тест: валидация модели CategoryClassificationResult."""
    # Валидный результат
    valid_result = CategoryClassificationResult(
        topics=["бизнес", "маркетинг"],
        confidence=0.95,
        reasoning="Объяснение",
    )

    assert valid_result.topics == ["бизнес", "маркетинг"]
    assert valid_result.confidence == 0.95

    # Невалидная уверенность (больше 1.0)
    with pytest.raises(ValueError):
        CategoryClassificationResult(
            topics=["бизнес"],
            confidence=1.5,  # Больше 1.0
            reasoning="Объяснение",
        )

    # Невалидная уверенность (меньше 0.0)
    with pytest.raises(ValueError):
        CategoryClassificationResult(
            topics=["бизнес"],
            confidence=-0.5,  # Меньше 0.0
            reasoning="Объяснение",
        )


@pytest.mark.asyncio
async def test_classify_book_category_llm_error():
    """Тест: обработка ошибки LLM."""
    book_title = "Книга"

    with patch("src.category_classifier._call_llm_for_classification") as mock_llm:
        mock_llm.side_effect = ValueError("Ошибка LLM")

        with pytest.raises(ValueError, match="Не удалось определить категории"):
            await classify_book_category(book_title)

