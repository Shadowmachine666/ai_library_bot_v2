"""Анализатор для ai_library_bot.

Анализирует релевантные чанки и генерирует структурированный ответ
на основе LLM с использованием строгого JSON формата.
"""

import asyncio
import json
import re
import time
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field, field_validator

from src.config import Config
from src.utils import setup_logger

logger = setup_logger(__name__)


class Quote(BaseModel):
    """Цитата из источника."""

    text: str = Field(..., description="Текст цитаты")
    source: str = Field(..., description="Источник (название книги, страница/глава)")


class Result(BaseModel):
    """Результат анализа."""

    answer: str = Field(..., description="Ответ на вопрос пользователя")
    quotes: list[Quote] = Field(default_factory=list, description="Цитаты из источников")
    disclaimer: str = Field(
        default="Это анализ на основе загруженных текстов.",
        description="Дисклеймер",
    )


class AnalysisResponse(BaseModel):
    """Структурированный ответ анализатора."""

    status: str = Field(
        ...,
        description="Статус ответа: SUCCESS, NOT_FOUND, CLARIFICATION_NEEDED, CONFLICT",
    )
    clarification_question: str | None = Field(
        default=None, description="Вопрос для уточнения (если status=CLARIFICATION_NEEDED)"
    )
    result: Result | None = Field(
        default=None, description="Результат анализа (если status=SUCCESS)"
    )

    @field_validator("status")
    @classmethod
    def validate_status(cls, v: str) -> str:
        """Проверяет валидность статуса."""
        valid_statuses = {"SUCCESS", "NOT_FOUND", "CLARIFICATION_NEEDED", "CONFLICT"}
        if v not in valid_statuses:
            raise ValueError(f"Статус должен быть одним из: {valid_statuses}")
        return v


def _load_system_prompt() -> str:
    """Загружает системный промпт из файла.

    Returns:
        Содержимое системного промпта.
    """
    prompt_path = Path(__file__).parent / "prompts" / "system_librarian.txt"
    try:
        with open(prompt_path, encoding="utf-8") as f:
            return f.read().strip()
    except FileNotFoundError:
        logger.error(f"Файл системного промпта не найден: {prompt_path}")
        raise
    except Exception as e:
        logger.error(f"Ошибка при загрузке системного промпта: {e}")
        raise


def _build_prompt(chunks: list[dict[str, Any]], user_query: str) -> str:
    """Собирает промпт из системного промпта, чанков и запроса пользователя.

    Args:
        chunks: Список релевантных чанков.
        user_query: Запрос пользователя.

    Returns:
        Полный промпт для LLM.
    """
    system_prompt = _load_system_prompt()

    # Формируем контекст из чанков
    chunks_text = "\n\n".join(
        [
            f"--- Фрагмент {i+1} (источник: {chunk.get('source', 'unknown')}) ---\n{chunk.get('text', '')}"
            for i, chunk in enumerate(chunks)
        ]
    )

    # Собираем полный промпт
    full_prompt = f"""{system_prompt}

Контекст из загруженных книг:

{chunks_text}

Вопрос пользователя: {user_query}

Ответь строго в формате JSON согласно инструкциям выше."""

    return full_prompt


def _build_fallback_prompt(chunks: list[dict[str, Any]], user_query: str) -> str:
    """Собирает fallback промпт с более явными инструкциями для поиска информации.

    Используется, когда LLM вернул NOT_FOUND, но есть релевантные чанки.

    Args:
        chunks: Список релевантных чанков.
        user_query: Запрос пользователя.

    Returns:
        Полный fallback промпт для LLM.
    """
    system_prompt = _load_system_prompt()

    # Формируем контекст из чанков с указанием релевантности
    chunks_text = "\n\n".join(
        [
            f"--- Фрагмент {i+1} (источник: {chunk.get('source', 'unknown')}, релевантность: {chunk.get('score', 0):.3f}) ---\n{chunk.get('text', '')}"
            for i, chunk in enumerate(chunks)
        ]
    )

    # Fallback промпт с более явными инструкциями
    full_prompt = f"""{system_prompt}

ВАЖНО: В предоставленных фрагментах текста найдена релевантная информация по вашему вопросу.
Внимательно проанализируйте ВСЕ фрагменты и найдите ответ на вопрос пользователя.
Даже если информация представлена косвенно или требует интерпретации, попробуйте сформировать ответ.

Контекст из загруженных книг:

{chunks_text}

Вопрос пользователя: {user_query}

Проанализируйте все фрагменты и сформируйте ответ на основе найденной информации.
Если в фрагментах есть любая информация, связанная с вопросом (даже косвенно), верните статус SUCCESS.
Ответь строго в формате JSON согласно инструкциям выше."""

    return full_prompt


async def _call_llm(prompt: str, max_retries: int | None = None) -> str:
    """Вызывает LLM для генерации ответа.

    Args:
        prompt: Промпт для LLM.
        max_retries: Максимальное количество попыток. По умолчанию из Config.

    Returns:
        Ответ LLM в виде строки (JSON).

    Raises:
        ValueError: Если после всех попыток не удалось получить валидный JSON.
    """
    if max_retries is None:
        max_retries = Config.LLM_MAX_RETRIES

    if not Config.OPENAI_API_KEY:
        raise ValueError("OPENAI_API_KEY не установлен")

    from openai import AsyncOpenAI

    client = AsyncOpenAI(api_key=Config.OPENAI_API_KEY)

    logger.info(f"[ANALYZER] Вызов OpenAI LLM API")
    logger.info(f"[ANALYZER] Модель: {Config.LLM_MODEL}, температура: {Config.LLM_TEMPERATURE}")

    # Разделяем системный промпт и пользовательский промпт
    system_prompt = _load_system_prompt()
    logger.debug(f"[ANALYZER] Системный промпт загружен, длина: {len(system_prompt)} символов")
    
    if "Контекст из загруженных книг:" in prompt:
        # Извлекаем пользовательский промпт (часть после системного промпта)
        user_prompt = prompt.split("Контекст из загруженных книг:")[-1]
        logger.debug(f"[ANALYZER] Пользовательский промпт извлечён, длина: {len(user_prompt)} символов")
    else:
        user_prompt = prompt
        logger.debug(f"[ANALYZER] Используется полный промпт, длина: {len(user_prompt)} символов")

    # Retry логика с экспоненциальной задержкой
    last_error = None
    for attempt in range(max_retries):
        try:
            logger.info(f"[ANALYZER] Отправка запроса к OpenAI API (попытка {attempt + 1}/{max_retries})")
            response = await client.chat.completions.create(
                model=Config.LLM_MODEL,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ],
                temperature=Config.LLM_TEMPERATURE,
                response_format={"type": "json_object"}
            )
            
            llm_response = response.choices[0].message.content
            if not llm_response:
                raise ValueError("LLM вернул пустой ответ")
            
            logger.info(f"[ANALYZER] ✅ LLM ответ получен (попытка {attempt + 1}), длина: {len(llm_response)} символов")
            logger.debug(f"[ANALYZER] LLM ответ: {llm_response[:500]}...")
            return llm_response

        except Exception as e:
            last_error = e
            error_type = type(e).__name__
            logger.error(
                f"[ANALYZER] ❌ Ошибка при вызове LLM (попытка {attempt + 1}/{max_retries}): "
                f"тип={error_type}, сообщение={str(e)}, "
                f"модель={Config.LLM_MODEL}"
            )
            if attempt < max_retries - 1:
                # Экспоненциальная задержка перед повтором
                delay = 2 ** attempt
                logger.warning(
                    f"[ANALYZER] Повтор через {delay} секунд... "
                    f"(осталось попыток: {max_retries - attempt - 1})"
                )
                await asyncio.sleep(delay)
            else:
                logger.error(
                    f"[ANALYZER] ❌ Все попытки исчерпаны. "
                    f"Последняя ошибка: {error_type}: {str(e)}. "
                    f"Модель: {Config.LLM_MODEL}"
                )

    # Если все попытки исчерпаны
    raise ValueError(f"Не удалось получить валидный ответ после {max_retries} попыток: {last_error}") from last_error


async def _parse_llm_response(response_text: str) -> AnalysisResponse:
    """Парсит ответ LLM и валидирует его через Pydantic.

    Args:
        response_text: Ответ LLM в виде строки (JSON).

    Returns:
        Валидированный объект AnalysisResponse.

    Raises:
        ValueError: Если ответ не является валидным JSON или не соответствует схеме.
    """
    logger.debug(f"[ANALYZER] Парсинг JSON ответа, длина: {len(response_text)} символов")
    
    try:
        # Парсим JSON
        data = json.loads(response_text)
        logger.debug(f"[ANALYZER] JSON успешно распарсен, ключи: {list(data.keys())}")
        
        # Исправляем неправильный статус "FOUND" на "SUCCESS"
        if data.get("status") == "FOUND":
            logger.warning("[ANALYZER] LLM вернул статус 'FOUND', заменяю на 'SUCCESS'")
            data["status"] = "SUCCESS"
    except json.JSONDecodeError as e:
        logger.error(
            f"[ANALYZER] ❌ Ошибка парсинга JSON: {e}. "
            f"Позиция ошибки: строка {e.lineno}, столбец {e.colno}. "
            f"Длина ответа: {len(response_text)} символов"
        )
        logger.error(f"[ANALYZER] Проблемный JSON (первые 500 символов): {response_text[:500]}")
        logger.error(f"[ANALYZER] Проблемный JSON (последние 500 символов): {response_text[-500:]}")
        raise ValueError(
            f"Невалидный JSON: {e}. Позиция ошибки: строка {e.lineno}, столбец {e.colno}"
        ) from e

    try:
        # Валидируем через Pydantic
        response = AnalysisResponse(**data)
        logger.info(f"[ANALYZER] ✅ Ответ валидирован через Pydantic, статус: {response.status}")
        return response
    except Exception as e:
        error_type = type(e).__name__
        logger.error(
            f"[ANALYZER] ❌ Ошибка валидации через Pydantic: {error_type}: {e}. "
            f"Полученные данные: {list(data.keys()) if isinstance(data, dict) else type(data)}"
        )
        logger.error(
            f"[ANALYZER] JSON данные (первые 1000 символов): "
            f"{json.dumps(data, ensure_ascii=False, indent=2)[:1000]}"
        )
        raise ValueError(
            f"Ответ не соответствует схеме: {error_type}: {e}. "
            f"Полученные ключи: {list(data.keys()) if isinstance(data, dict) else 'не словарь'}"
        ) from e


async def analyze(chunks: list[dict[str, Any]], user_query: str) -> AnalysisResponse:
    """Анализирует релевантные чанки и генерирует структурированный ответ.

    Процесс:
    1. Загружает системный промпт
    2. Собирает промпт из чанков и запроса пользователя
    3. Вызывает LLM с retry policy (5 попыток, экспоненциальная задержка)
    4. Парсит и валидирует ответ через Pydantic
    5. Возвращает структурированный ответ

    Args:
        chunks: Список релевантных чанков из retriever.
        user_query: Запрос пользователя.

    Returns:
        Валидированный объект AnalysisResponse.

    Raises:
        ValueError: Если не удалось получить валидный ответ после всех попыток.
    """
    if not chunks:
        logger.warning("Получен пустой список чанков, возвращаю NOT_FOUND")
        return AnalysisResponse(
            status="NOT_FOUND",
            clarification_question=None,
            result=None,
        )

    analysis_start_time = time.perf_counter()
    logger.info(f"[ANALYZER] ===== Начало анализа =====")
    logger.info(f"[ANALYZER] Запрос: {user_query}")
    logger.info(f"[ANALYZER] Количество чанков для анализа: {len(chunks)}")
    
    # Логируем информацию о чанках
    for i, chunk in enumerate(chunks):
        logger.info(
            f"[ANALYZER] Чанк {i+1}: source={chunk.get('source')}, "
            f"score={chunk.get('score')}, text_length={len(chunk.get('text', ''))}, "
            f"text_preview={chunk.get('text', '')[:100]}..."
        )

    # Собираем промпт
    prompt_start_time = time.perf_counter()
    logger.info(f"[ANALYZER] Этап 1/3: Сборка промпта")
    prompt = _build_prompt(chunks, user_query)
    prompt_time = time.perf_counter() - prompt_start_time
    logger.info(f"[ANALYZER] Промпт собран, длина: {len(prompt)} символов (время: {prompt_time:.3f}с)")
    logger.debug(f"[ANALYZER] Промпт (первые 500 символов): {prompt[:500]}...")

    # Вызываем LLM с retry policy
    llm_start_time = time.perf_counter()
    logger.info(f"[ANALYZER] Этап 2/3: Вызов LLM (модель: {Config.LLM_MODEL}, max_retries: {Config.LLM_MAX_RETRIES})")
    max_retries = Config.LLM_MAX_RETRIES
    last_error = None

    for attempt in range(max_retries):
        try:
            logger.info(f"[ANALYZER] Попытка {attempt + 1}/{max_retries}: вызов LLM")
            # Вызов LLM
            response_text = await _call_llm(prompt, max_retries=1)
            llm_time = time.perf_counter() - llm_start_time
            logger.info(f"[ANALYZER] ✅ LLM ответ получен, длина: {len(response_text)} символов (время: {llm_time:.3f}с)")
            logger.debug(f"[ANALYZER] LLM ответ (первые 500 символов): {response_text[:500]}...")

            # Парсинг и валидация
            parse_start_time = time.perf_counter()
            logger.info(f"[ANALYZER] Этап 3/3: Парсинг и валидация ответа")
            response = await _parse_llm_response(response_text)
            parse_time = time.perf_counter() - parse_start_time
            logger.debug(f"[ANALYZER] Парсинг и валидация завершены за {parse_time:.3f}с")

            # Fallback логика: если LLM вернул NOT_FOUND, но есть релевантные чанки, пробуем еще раз
            if response.status == "NOT_FOUND" and chunks:
                # Проверяем, есть ли чанки с хорошим score (> 0.4)
                top_scores = [chunk.get("score", 0) for chunk in chunks[:3]]
                max_score = max(top_scores) if top_scores else 0
                
                if max_score >= 0.4:
                    logger.warning(
                        f"[ANALYZER] ⚠️ LLM вернул NOT_FOUND, но найдены релевантные чанки "
                        f"(максимальный score: {max_score:.3f}). Пробуем fallback с расширенным контекстом..."
                    )
                    
                    # Пробуем еще раз с более явным промптом
                    fallback_prompt = _build_fallback_prompt(chunks, user_query)
                    logger.info(f"[ANALYZER] Fallback: повторный вызов LLM с расширенным промптом")
                    
                    try:
                        fallback_response_text = await _call_llm(fallback_prompt, max_retries=1)
                        fallback_response = await _parse_llm_response(fallback_response_text)
                        
                        if fallback_response.status == "SUCCESS":
                            analysis_time = time.perf_counter() - analysis_start_time
                            logger.info(
                                f"[ANALYZER] ✅ Fallback успешен! LLM нашел ответ при повторной попытке. "
                                f"Причина первоначального NOT_FOUND: возможно, недостаточно явный контекст."
                            )
                            if fallback_response.result:
                                logger.info(f"[ANALYZER] Ответ содержит {len(fallback_response.result.quotes)} цитат")
                            logger.info(
                                f"[ANALYZER] ===== Анализ завершён ===== "
                                f"(время: сборка промпта={prompt_time:.3f}с, LLM={llm_time:.3f}с, "
                                f"парсинг={parse_time:.3f}с, всего={analysis_time:.3f}с)"
                            )
                            return fallback_response
                        else:
                            logger.warning(
                                f"[ANALYZER] Fallback также вернул {fallback_response.status}. "
                                f"Чанки найдены (score: {max_score:.3f}), но LLM не смог сформировать ответ. "
                                f"Возможные причины: недостаточно релевантная информация в чанках или "
                                f"вопрос требует более специфичного контекста."
                            )
                    except Exception as e:
                        logger.warning(f"[ANALYZER] Ошибка при fallback попытке: {e}. Возвращаем исходный NOT_FOUND.")
                else:
                    logger.info(
                        f"[ANALYZER] LLM вернул NOT_FOUND. Score чанков низкий (максимальный: {max_score:.3f}), "
                        f"поэтому fallback не применяется."
                    )

            analysis_time = time.perf_counter() - analysis_start_time
            logger.info(f"[ANALYZER] ✅ Анализ завершён успешно, статус: {response.status}")
            if response.result:
                logger.info(f"[ANALYZER] Ответ содержит {len(response.result.quotes)} цитат")
            logger.info(
                f"[ANALYZER] ===== Анализ завершён ===== "
                f"(время: сборка промпта={prompt_time:.3f}с, LLM={llm_time:.3f}с, "
                f"парсинг={parse_time:.3f}с, всего={analysis_time:.3f}с)"
            )
            return response

        except ValueError as e:
            last_error = e
            error_type = type(e).__name__
            analysis_time_so_far = time.perf_counter() - analysis_start_time
            
            logger.error(
                f"[ANALYZER] ❌ Ошибка на попытке {attempt + 1}/{max_retries}: "
                f"тип={error_type}, сообщение={str(e)}, "
                f"запрос='{user_query[:100]}...', "
                f"чанков={len(chunks)}, "
                f"время до ошибки={analysis_time_so_far:.3f}с"
            )
            
            if attempt < max_retries - 1:
                # Экспоненциальная задержка перед повторной попыткой
                delay = 2**attempt
                logger.warning(
                    f"[ANALYZER] Повтор через {delay} секунд... "
                    f"(осталось попыток: {max_retries - attempt - 1})"
                )
                await asyncio.sleep(delay)
            else:
                analysis_time = time.perf_counter() - analysis_start_time
                logger.error(
                    f"[ANALYZER] ❌ Все {max_retries} попыток исчерпаны. "
                    f"Последняя ошибка: {error_type}: {str(e)}. "
                    f"Общее время анализа: {analysis_time:.3f}с. "
                    f"Запрос: '{user_query[:100]}...', чанков: {len(chunks)}"
                )
                raise ValueError(
                    f"Не удалось получить валидный ответ после {max_retries} попыток. "
                    f"Последняя ошибка: {error_type}: {str(e)}. "
                    f"Запрос: '{user_query[:100]}...'"
                ) from e

    # Если дошли сюда, все попытки исчерпаны
    analysis_time = time.perf_counter() - analysis_start_time
    raise ValueError(
        f"Не удалось получить валидный ответ после {max_retries} попыток: {last_error}. "
        f"Время анализа: {analysis_time:.3f}с. Запрос: '{user_query[:100]}...'"
    ) from last_error
