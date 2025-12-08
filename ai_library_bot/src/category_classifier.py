"""Классификатор категорий книг через LLM.

Модуль предоставляет функции для определения категорий книги
по её названию с использованием LLM.
"""

import asyncio
import json
from typing import Any

from pydantic import BaseModel, Field, field_validator

from src.config import Config
from src.utils import setup_logger

logger = setup_logger(__name__)


class CategoryClassificationResult(BaseModel):
    """Результат классификации категорий книги."""

    topics: list[str] = Field(..., description="Список категорий книги")
    confidence: float = Field(..., ge=0.0, le=1.0, description="Уверенность в классификации (0.0-1.0)")
    reasoning: str = Field(..., description="Объяснение выбора категорий")

    @field_validator("topics")
    @classmethod
    def validate_topics(cls, v: list[str]) -> list[str]:
        """Валидирует, что все категории присутствуют в Config.CATEGORIES.
        
        Разрешает пустой список, если LLM не смог определить категории.
        """
        # Если список пустой - это валидный случай (LLM не определил категории)
        if not v:
            return v
        
        # Проверяем, что все категории валидны
        valid_categories = [cat.lower() for cat in Config.CATEGORIES]
        invalid = [cat for cat in v if cat.lower() not in valid_categories]
        
        if invalid:
            logger.warning(
                f"LLM вернул невалидные категории: {invalid}. "
                f"Допустимые категории: {Config.CATEGORIES}"
            )
            # Фильтруем невалидные категории
            v = [cat for cat in v if cat.lower() in valid_categories]
        
        return v


async def classify_query_category(query: str) -> list[str]:
    """Определяет релевантные категории для запроса пользователя через LLM.

    Использует LLM для анализа запроса и определения, к каким категориям
    книг он относится.

    Args:
        query: Текст запроса пользователя.

    Returns:
        Список релевантных категорий из Config.CATEGORIES.
        Если LLM не смог определить категории, возвращает пустой список.
    """
    logger.info(f"[QUERY_CLASSIFIER] Определение категорий для запроса: '{query[:100]}...'")

    categories_list_str = ", ".join(Config.CATEGORIES)
    
    prompt = f"""Определи, к каким категориям книг относится следующий запрос пользователя:

Запрос: "{query}"

Доступные категории: {categories_list_str}

Проанализируй запрос и определи, из каких категорий книг нужно искать информацию для ответа на этот запрос.

Ответь строго в формате JSON:
{{
  "categories": ["категория1", "категория2"],
  "confidence": 0.0-1.0,
  "reasoning": "краткое объяснение выбора категорий"
}}

Важно:
- Используй только категории из предоставленного списка
- Может быть несколько категорий, если запрос охватывает несколько тем
- confidence должен быть от 0.0 до 1.0
- Если не уверен, укажи confidence < 0.7
- reasoning должно быть кратким (1-2 предложения)
- Если запрос слишком общий и не относится к конкретным категориям, верни пустой список категорий"""

    try:
        response_text = await _call_llm_for_classification(prompt)
        
        # Парсим JSON ответ
        try:
            data = json.loads(response_text)
            categories = data.get("categories", [])
            confidence = data.get("confidence", 0.0)
            reasoning = data.get("reasoning", "")
            
            logger.info(
                f"[QUERY_CLASSIFIER] ✅ Категории для запроса определены: "
                f"{categories} (confidence: {confidence:.2f}, reasoning: {reasoning[:100]}...)"
            )
            
            # Валидируем категории
            valid_categories_lower = {cat.lower() for cat in Config.CATEGORIES}
            valid_categories = [
                cat for cat in categories 
                if cat.lower() in valid_categories_lower
            ]
            
            # Приводим к оригинальному регистру из Config
            config_categories_map = {cat.lower(): cat for cat in Config.CATEGORIES}
            normalized_categories = [
                config_categories_map[cat.lower()]
                for cat in valid_categories
                if cat.lower() in config_categories_map
            ]
            
            # Удаляем дубликаты
            normalized_categories = list(dict.fromkeys(normalized_categories))
            
            return normalized_categories
            
        except json.JSONDecodeError as e:
            logger.error(f"[QUERY_CLASSIFIER] ❌ Ошибка парсинга JSON ответа: {e}")
            return []
            
    except Exception as e:
        logger.error(
            f"[QUERY_CLASSIFIER] ❌ Ошибка при определении категорий запроса: {e}",
            exc_info=True
        )
        return []


async def classify_book_category(
    book_title: str, content_preview: str | None = None
) -> dict[str, Any]:
    """Определяет категории книги по её названию и содержимому через LLM.

    Использует LLM для анализа названия книги и (опционально) начала содержимого
    для определения соответствующих категорий из фиксированного списка.

    Args:
        book_title: Название книги.
        content_preview: Первые символы содержимого книги (опционально).
                        Если предоставлено, используется для более точной классификации.

    Returns:
        Словарь с результатами классификации:
        {
            "topics": ["категория1", "категория2"],
            "confidence": 0.95,
            "reasoning": "Объяснение выбора категорий"
        }

    Raises:
        ValueError: Если не удалось получить валидный ответ от LLM.

    Примеры:
        >>> await classify_book_category("Основы маркетинга")
        {
            "topics": ["бизнес", "маркетинг"],
            "confidence": 0.95,
            "reasoning": "Книга о маркетинге относится к бизнесу и маркетингу"
        }
    """
    if not book_title or not book_title.strip():
        raise ValueError("Название книги не может быть пустым")

    logger.info(f"[CATEGORY_CLASSIFIER] Определение категорий для книги: '{book_title}'")
    if content_preview:
        logger.debug(
            f"[CATEGORY_CLASSIFIER] Используется превью содержимого "
            f"({len(content_preview)} символов)"
        )

    # Формируем промпт для LLM
    categories_list = ", ".join(Config.CATEGORIES)
    
    # Базовый промпт с названием
    prompt_parts = [
        f"Определи категории для книги \"{book_title}\" из следующего списка:",
        categories_list,
        "",
    ]
    
    # Добавляем содержимое, если предоставлено
    if content_preview:
        # Ограничиваем длину превью до 2000 символов для экономии токенов
        preview_text = content_preview[:2000].strip()
        prompt_parts.extend([
            "Начало книги (первые страницы):",
            f"{preview_text}",
            "",
            "Проанализируй название книги и начало её содержимого, чтобы определить категории.",
        ])
    else:
        prompt_parts.append("Проанализируй название книги и определи, к каким категориям она относится.")
    
    prompt_parts.extend([
        "Может быть несколько категорий, если книга охватывает несколько тем.",
        "",
        "Ответь строго в формате JSON:",
        "{",
        '  "topics": ["категория1", "категория2"],',
        "  \"confidence\": 0.0-1.0,",
        "  \"reasoning\": \"краткое объяснение выбора категорий\"",
        "}",
        "",
        "Важно:",
        "- Используй только категории из предоставленного списка",
        "- confidence должен быть от 0.0 до 1.0",
        "- Если не уверен, укажи confidence < 0.7",
        "- reasoning должно быть кратким (1-2 предложения)",
    ])
    
    prompt = "\n".join(prompt_parts)

    logger.debug(f"[CATEGORY_CLASSIFIER] Промпт для LLM: {prompt[:200]}...")

    # Вызываем LLM
    try:
        response_text = await _call_llm_for_classification(prompt)
        result = _parse_classification_response(response_text)
        
        logger.info(
            f"[CATEGORY_CLASSIFIER] ✅ Категории определены для '{book_title}': "
            f"{result.topics} (confidence: {result.confidence:.2f})"
        )
        
        return {
            "topics": result.topics,
            "confidence": result.confidence,
            "reasoning": result.reasoning,
        }
    except Exception as e:
        error_type = type(e).__name__
        logger.error(
            f"[CATEGORY_CLASSIFIER] ❌ Ошибка при определении категорий для '{book_title}': "
            f"{error_type}: {str(e)}"
        )
        raise ValueError(
            f"Не удалось определить категории для книги '{book_title}': {error_type}: {str(e)}"
        ) from e


async def _call_llm_for_classification(prompt: str, max_retries: int | None = None) -> str:
    """Вызывает LLM для классификации категорий.

    Args:
        prompt: Промпт для LLM.
        max_retries: Максимальное количество попыток. По умолчанию из Config.

    Returns:
        Ответ LLM в виде строки (JSON).

    Raises:
        ValueError: Если после всех попыток не удалось получить валидный ответ.
    """
    if max_retries is None:
        max_retries = Config.LLM_MAX_RETRIES

    if not Config.OPENAI_API_KEY:
        raise ValueError("OPENAI_API_KEY не установлен")

    from openai import AsyncOpenAI

    client = AsyncOpenAI(api_key=Config.OPENAI_API_KEY)

    logger.debug(
        f"[CATEGORY_CLASSIFIER] Вызов OpenAI LLM API для классификации "
        f"(модель: {Config.LLM_MODEL}, температура: {Config.LLM_TEMPERATURE})"
    )

    system_prompt = (
        "Ты — эксперт по классификации книг. "
        "Твоя задача — определить категории книги по её названию и (если предоставлено) началу содержимого. "
        "Используй только категории из предоставленного списка. "
        "Отвечай строго в формате JSON."
    )

    # Retry логика с экспоненциальной задержкой
    last_error = None
    for attempt in range(max_retries):
        try:
            logger.debug(
                f"[CATEGORY_CLASSIFIER] Отправка запроса к OpenAI API "
                f"(попытка {attempt + 1}/{max_retries})"
            )
            response = await client.chat.completions.create(
                model=Config.LLM_MODEL,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": prompt},
                ],
                temperature=Config.LLM_TEMPERATURE,
                response_format={"type": "json_object"},
            )

            llm_response = response.choices[0].message.content
            if not llm_response:
                raise ValueError("LLM вернул пустой ответ")

            logger.debug(
                f"[CATEGORY_CLASSIFIER] ✅ LLM ответ получен (попытка {attempt + 1}), "
                f"длина: {len(llm_response)} символов"
            )
            logger.debug(f"[CATEGORY_CLASSIFIER] LLM ответ: {llm_response[:300]}...")
            return llm_response

        except Exception as e:
            last_error = e
            error_type = type(e).__name__
            logger.warning(
                f"[CATEGORY_CLASSIFIER] ⚠️ Ошибка при вызове LLM (попытка {attempt + 1}/{max_retries}): "
                f"тип={error_type}, сообщение={str(e)}"
            )
            if attempt < max_retries - 1:
                # Экспоненциальная задержка перед повтором
                delay = 2**attempt
                logger.debug(
                    f"[CATEGORY_CLASSIFIER] Повтор через {delay} секунд... "
                    f"(осталось попыток: {max_retries - attempt - 1})"
                )
                await asyncio.sleep(delay)
            else:
                logger.error(
                    f"[CATEGORY_CLASSIFIER] ❌ Все попытки исчерпаны. "
                    f"Последняя ошибка: {error_type}: {str(last_error)}"
                )

    # Если все попытки исчерпаны
    raise ValueError(
        f"Не удалось получить валидный ответ от LLM после {max_retries} попыток: {last_error}"
    ) from last_error


def _parse_classification_response(response_text: str) -> CategoryClassificationResult:
    """Парсит ответ LLM и валидирует его через Pydantic.

    Args:
        response_text: Ответ LLM в виде строки (JSON).

    Returns:
        Валидированный объект CategoryClassificationResult.

    Raises:
        ValueError: Если ответ не является валидным JSON или не соответствует схеме.
    """
    logger.debug(
        f"[CATEGORY_CLASSIFIER] Парсинг JSON ответа, длина: {len(response_text)} символов"
    )

    try:
        # Парсим JSON
        data = json.loads(response_text)
        logger.debug(f"[CATEGORY_CLASSIFIER] JSON успешно распарсен, ключи: {list(data.keys())}")
    except json.JSONDecodeError as e:
        logger.error(
            f"[CATEGORY_CLASSIFIER] ❌ Ошибка парсинга JSON: {e}. "
            f"Позиция ошибки: строка {e.lineno}, столбец {e.colno}. "
            f"Длина ответа: {len(response_text)} символов"
        )
        logger.error(
            f"[CATEGORY_CLASSIFIER] Проблемный JSON (первые 500 символов): {response_text[:500]}"
        )
        raise ValueError(
            f"Невалидный JSON: {e}. Позиция ошибки: строка {e.lineno}, столбец {e.colno}"
        ) from e

    try:
        # Валидируем через Pydantic
        result = CategoryClassificationResult(**data)
        logger.debug(
            f"[CATEGORY_CLASSIFIER] ✅ Ответ валидирован через Pydantic, "
            f"категории: {result.topics}, confidence: {result.confidence:.2f}"
        )
        return result
    except Exception as e:
        error_type = type(e).__name__
        logger.error(
            f"[CATEGORY_CLASSIFIER] ❌ Ошибка валидации через Pydantic: {error_type}: {e}. "
            f"Полученные данные: {list(data.keys()) if isinstance(data, dict) else type(data)}"
        )
        logger.error(
            f"[CATEGORY_CLASSIFIER] JSON данные (первые 500 символов): "
            f"{json.dumps(data, ensure_ascii=False, indent=2)[:500]}"
        )
        raise ValueError(
            f"Ответ не соответствует схеме: {error_type}: {e}. "
            f"Полученные ключи: {list(data.keys()) if isinstance(data, dict) else 'не словарь'}"
        ) from e







