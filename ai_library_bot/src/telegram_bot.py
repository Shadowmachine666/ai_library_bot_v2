"""Telegram бот для ai_library_bot.

Обрабатывает команды и сообщения от пользователей, выполняет поиск
релевантных чанков и генерирует ответы на основе загруженных книг.
"""

import asyncio
import time
from typing import Any

from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes, MessageHandler, filters

from src.analyzer import AnalysisResponse, analyze
from src.config import Config
from src.formatters import format_response, format_start_message
from src.retriever_service import NOT_FOUND, retrieve_chunks
from src.utils import setup_logger

logger = setup_logger(__name__)

from aiocache import Cache

# Инициализация кэша
cache = Cache(Cache.MEMORY)


async def _get_from_cache(key: str) -> Any | None:
    """Получает значение из кэша.

    Args:
        key: Ключ для поиска в кэше.

    Returns:
        Значение из кэша или None, если не найдено.
    """
    try:
        value = await cache.get(key)
        if value:
            logger.debug(f"Значение найдено в кэше: {key}")
        return value
    except Exception as e:
        error_type = type(e).__name__
        logger.warning(
            f"[TELEGRAM_BOT] ⚠️ Ошибка при получении из кэша: "
            f"тип={error_type}, сообщение={str(e)}, ключ={key[:50]}..."
        )
        return None


async def _set_to_cache(key: str, value: Any, ttl: int | None = None) -> None:
    """Сохраняет значение в кэш.

    Args:
        key: Ключ для сохранения.
        value: Значение для сохранения.
        ttl: Время жизни в секундах. По умолчанию из Config.
    """
    if ttl is None:
        ttl = Config.CACHE_TTL

    try:
        await cache.set(key, value, ttl=ttl)
        logger.debug(f"Значение сохранено в кэш: {key}, TTL={ttl}")
    except Exception as e:
        error_type = type(e).__name__
        value_length = len(str(value)) if value else 0
        logger.warning(
            f"[TELEGRAM_BOT] ⚠️ Ошибка при сохранении в кэш: "
            f"тип={error_type}, сообщение={str(e)}, "
            f"ключ={key[:50]}..., длина значения={value_length} символов, TTL={ttl}"
        )


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обработчик команды /start.

    Args:
        update: Объект Update от Telegram.
        context: Контекст обработчика.
    """
    user = update.effective_user
    if not user:
        return
    logger.info(f"Команда /start от пользователя {user.id} (@{user.username})")

    message = format_start_message()
    if update.message:
        await update.message.reply_text(message, parse_mode="Markdown")


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обработчик текстовых сообщений от пользователей.

    Выполняет полный flow:
    1. Проверка кэша
    2. Поиск релевантных чанков (retrieval)
    3. Анализ чанков (analyzer)
    4. Форматирование ответа
    5. Отправка пользователю

    Args:
        update: Объект Update от Telegram.
        context: Контекст обработчика.
    """
    user = update.effective_user
    if not user or not update.message or not update.message.text:
        return
    user_query = update.message.text.strip()

    logger.info(f"[TELEGRAM_BOT] Запрос от пользователя {user.id} (@{user.username}): {user_query}")

    # Ограничение длины запроса
    if len(user_query) > 1000:
        logger.warning(f"[TELEGRAM_BOT] Запрос слишком длинный: {len(user_query)} символов")
        await update.message.reply_text(
            "❌ Запрос слишком длинный. Пожалуйста, ограничьте его 1000 символами."
        )
        return

    # Показываем, что бот обрабатывает запрос
    processing_message = await update.message.reply_text("🔍 Ищу информацию...")

    # Общий таймер обработки запроса
    total_start_time = time.perf_counter()

    try:
        # 1. Проверка кэша
        cache_start_time = time.perf_counter()
        logger.info(f"[TELEGRAM_BOT] Этап 1/6: Проверка кэша")
        cache_key = f"query:{user_query.lower()}"
        cached_response = await _get_from_cache(cache_key)
        cache_time = time.perf_counter() - cache_start_time

        if cached_response:
            total_time = time.perf_counter() - total_start_time
            logger.info(
                f"[TELEGRAM_BOT] ✅ Ответ найден в кэше для запроса: {user_query[:50]}... "
                f"(время проверки кэша: {cache_time:.3f}с, общее время: {total_time:.3f}с)"
            )
            await processing_message.edit_text(cached_response, parse_mode="Markdown")
            return
        logger.info(
            f"[TELEGRAM_BOT] Кэш не содержит ответа, продолжаем обработку "
            f"(время проверки кэша: {cache_time:.3f}с)"
        )

        # 2. Поиск релевантных чанков
        retrieval_start_time = time.perf_counter()
        logger.info(f"[TELEGRAM_BOT] Этап 2/6: Поиск релевантных чанков")
        chunks = await retrieve_chunks(user_query)
        retrieval_time = time.perf_counter() - retrieval_start_time

        if chunks == NOT_FOUND:
            total_time = time.perf_counter() - total_start_time
            logger.warning(
                f"[TELEGRAM_BOT] ❌ Не найдено релевантных чанков для запроса: {user_query[:50]}... "
                f"(время поиска: {retrieval_time:.3f}с, общее время: {total_time:.3f}с)"
            )
            response_text = format_response(
                AnalysisResponse(status="NOT_FOUND", clarification_question=None, result=None)
            )
            await processing_message.edit_text(response_text, parse_mode="Markdown")
            return
        
        if isinstance(chunks, list):
            logger.info(
                f"[TELEGRAM_BOT] ✅ Найдено {len(chunks)} релевантных чанков "
                f"(время поиска: {retrieval_time:.3f}с)"
            )
            for i, chunk in enumerate(chunks):
                logger.debug(f"[TELEGRAM_BOT] Чанк {i+1}: source={chunk.get('source')}, score={chunk.get('score')}, text_length={len(chunk.get('text', ''))}")
        else:
            total_time = time.perf_counter() - total_start_time
            logger.error(
                f"[TELEGRAM_BOT] ❌ Неожиданный тип chunks: {type(chunks)} "
                f"(время поиска: {retrieval_time:.3f}с, общее время: {total_time:.3f}с)"
            )
            response_text = format_response(
                AnalysisResponse(status="NOT_FOUND", clarification_question=None, result=None)
            )
            await processing_message.edit_text(response_text, parse_mode="Markdown")
            return

        # 3. Анализ чанков
        analysis_start_time = time.perf_counter()
        logger.info(f"[TELEGRAM_BOT] Этап 3/6: Анализ чанков через LLM")
        analysis_response = await analyze(chunks, user_query)
        analysis_time = time.perf_counter() - analysis_start_time
        logger.info(
            f"[TELEGRAM_BOT] ✅ Анализ завершён, статус: {analysis_response.status} "
            f"(время анализа: {analysis_time:.3f}с)"
        )

        # 4. Форматирование ответа
        formatting_start_time = time.perf_counter()
        logger.info(f"[TELEGRAM_BOT] Этап 4/6: Форматирование ответа")
        response_text = format_response(analysis_response)
        formatting_time = time.perf_counter() - formatting_start_time
        logger.debug(
            f"[TELEGRAM_BOT] Сформирован ответ длиной {len(response_text)} символов "
            f"(время форматирования: {formatting_time:.3f}с)"
        )

        # 5. Сохранение в кэш
        cache_save_start_time = time.perf_counter()
        logger.info(f"[TELEGRAM_BOT] Этап 5/6: Сохранение в кэш")
        await _set_to_cache(cache_key, response_text)
        cache_save_time = time.perf_counter() - cache_save_start_time

        # 6. Отправка ответа
        send_start_time = time.perf_counter()
        logger.info(f"[TELEGRAM_BOT] Этап 6/6: Отправка ответа пользователю")
        try:
            await processing_message.edit_text(response_text, parse_mode="Markdown")
        except Exception as e:
            # Если ошибка парсинга Markdown, отправляем без форматирования
            error_type = type(e).__name__
            logger.warning(
                f"[TELEGRAM_BOT] ⚠️ Ошибка при отправке с Markdown (тип: {error_type}): {e}. "
                f"Отправляем без форматирования. Длина ответа: {len(response_text)} символов"
            )
            try:
                # Убираем Markdown разметку для fallback
                fallback_text = response_text.replace("**", "").replace("_", "").replace("`", "")
                await processing_message.edit_text(fallback_text)
                logger.info("[TELEGRAM_BOT] ✅ Ответ успешно отправлен без форматирования")
            except Exception as fallback_error:
                logger.error(
                    f"[TELEGRAM_BOT] ❌ Не удалось отправить ответ даже без форматирования: {fallback_error}. "
                    f"Проблема может быть в длине сообщения ({len(response_text)} символов) или специальных символах."
                )
                # Пробуем отправить урезанную версию
                try:
                    truncated_text = response_text[:4000] + "\n\n... (сообщение обрезано из-за ограничений Telegram)"
                    await processing_message.edit_text(truncated_text)
                except Exception as final_error:
                    logger.error(f"[TELEGRAM_BOT] ❌ Критическая ошибка: не удалось отправить ответ: {final_error}")
                    await processing_message.edit_text(
                        "❌ Произошла ошибка при отправке ответа. Ответ слишком длинный или содержит недопустимые символы."
                    )
        
        send_time = time.perf_counter() - send_start_time
        total_time = time.perf_counter() - total_start_time
        
        logger.info(
            f"[TELEGRAM_BOT] ✅ Ответ успешно отправлен пользователю {user.id} "
            f"(время отправки: {send_time:.3f}с, общее время: {total_time:.3f}с)"
        )
        logger.info(
            f"[TELEGRAM_BOT] 📊 Производительность: "
            f"поиск={retrieval_time:.3f}с, "
            f"анализ={analysis_time:.3f}с, "
            f"форматирование={formatting_time:.3f}с, "
            f"кэш={cache_save_time:.3f}с, "
            f"отправка={send_time:.3f}с, "
            f"всего={total_time:.3f}с"
        )

    except Exception as e:
        total_time = time.perf_counter() - total_start_time if 'total_start_time' in locals() else 0
        error_type = type(e).__name__
        error_details = str(e)
        
        logger.error(
            f"[TELEGRAM_BOT] ❌ Критическая ошибка при обработке запроса: "
            f"тип={error_type}, сообщение={error_details}, "
            f"запрос='{user_query[:100]}...', пользователь={user.id}, "
            f"время до ошибки={total_time:.3f}с",
            exc_info=True
        )
        
        # Более информативное сообщение об ошибке для пользователя
        error_message = (
            "❌ Произошла ошибка при обработке вашего запроса.\n\n"
            "Пожалуйста, попробуйте:\n"
            "• Переформулировать вопрос\n"
            "• Попробовать позже\n"
            "• Проверить, что вопрос не слишком длинный"
        )
        
        try:
            await processing_message.edit_text(error_message)
        except Exception as send_error:
            logger.error(
                f"[TELEGRAM_BOT] ❌ Не удалось отправить сообщение об ошибке: {send_error}"
            )


def create_bot_application() -> Application:
    """Создаёт и настраивает приложение Telegram бота.

    Returns:
        Настроенное приложение Application.
    """
    if not Config.TG_TOKEN:
        raise ValueError("TG_TOKEN не установлен в переменных окружения")

    logger.info("Создание приложения Telegram бота...")

    # Создание приложения
    application = Application.builder().token(Config.TG_TOKEN).build()

    # Регистрация обработчиков
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    logger.info("Обработчики зарегистрированы: /start, текстовые сообщения")

    return application


async def run_bot() -> None:
    """Запускает Telegram бота.

    Бот работает до получения сигнала остановки (Ctrl+C).
    """
    logger.info("Запуск Telegram бота...")

    # Валидация конфигурации
    if not Config.validate():
        logger.error("Конфигурация невалидна. Проверьте переменные окружения.")
        return

    # Проверка подключения к OpenAI
    logger.info("Проверка подключения к OpenAI API...")
    openai_connected = await Config.check_openai_connection()
    if not openai_connected:
            logger.error(
                "❌ OpenAI API недоступен. Бот не может работать без валидного OPENAI_API_KEY."
            )
            return
    else:
        logger.info("✅ OpenAI API готов к использованию")

    # Создание приложения
    application = create_bot_application()

    # Запуск бота
    logger.info("Бот запущен и готов к работе")
    await application.initialize()
    await application.start()
    if application.updater:
        await application.updater.start_polling()

    # Ожидание сигнала остановки
    try:
        await asyncio.Event().wait()  # Бесконечное ожидание
    except KeyboardInterrupt:
        logger.info("Получен сигнал остановки...")
    finally:
        if application.updater:
            await application.updater.stop()
        await application.stop()
        await application.shutdown()
        logger.info("Бот остановлен")


if __name__ == "__main__":
    asyncio.run(run_bot())
