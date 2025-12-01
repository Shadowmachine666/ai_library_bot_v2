"""Telegram бот для ai_library_bot.

Обрабатывает команды и сообщения от пользователей, выполняет поиск
релевантных чанков и генерирует ответы на основе загруженных книг.
"""

import asyncio
import time
from typing import Any

from telegram import Update
from telegram.error import BadRequest
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from src.admin_messages import (
    create_confirmation_keyboard,
    create_index_books_keyboard,
    format_confirmation_message,
    format_confirmation_result_message,
    format_edit_categories_keyboard,
    format_edit_categories_message,
    format_pending_books_list,
    format_pending_books_message,
    format_pending_confirmations_list,
)
from src.admin_utils import is_admin, require_admin
from src.analyzer import AnalysisResponse, analyze
from src.config import Config
from src.confirmation_manager import (
    get_confirmation_request,
    get_pending_confirmations,
    update_confirmation_categories,
    update_confirmation_status,
)
from src.ingest_service import (
    check_and_cleanup_expired_confirmations,
    check_for_new_books,
    continue_indexing_after_confirmation,
    ingest_books,
)
from src.formatters import (
    create_categories_keyboard,
    create_query_categories_keyboard,
    create_response_keyboard,
    format_categories_message,
    format_response,
    format_start_message,
)
from src.retriever_service import NOT_FOUND, retrieve_chunks
from src.pending_books_manager import (
    add_pending_book,
    get_pending_books,
    mark_notification_sent,
    remove_missing_files,
    remove_pending_book,
)
from src.query_context import (
    cleanup_expired_contexts,
    delete_query_context,
    get_query_context,
    save_query_context,
    update_query_selected_categories,
)
from src.user_categories import (
    clear_user_categories,
    get_user_categories,
    has_user_selected_categories,
    set_user_categories,
)
from src.utils import setup_logger

logger = setup_logger(__name__)

from src.cache_utils import cache, clear_cache as clear_cache_util


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


async def clear_cache() -> None:
    """Очищает весь кэш ответов LLM.
    
    Используется при удалении книг из индекса, чтобы гарантировать,
    что пользователи не получат устаревшие ответы, основанные на удаленных книгах.
    
    Это обёртка над функцией из cache_utils для обратной совместимости.
    """
    await clear_cache_util()


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обработчик команды /start.

    Показывает приветственное сообщение и клавиатуру для выбора категорий.

    Args:
        update: Объект Update от Telegram.
        context: Контекст обработчика.
    """
    user = update.effective_user
    if not user:
        return
    logger.info(f"Команда /start от пользователя {user.id} (@{user.username})")

    message = format_start_message()
    selected_categories = get_user_categories(user.id)
    keyboard = create_categories_keyboard(selected_categories)
    
    if update.message:
        await update.message.reply_text(
            message, 
            parse_mode="Markdown",
            reply_markup=keyboard
        )


async def _process_query_with_categories(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    user_query: str,
    filter_categories: list[str] | None,
    user_id: int,
    processing_message: Any | None = None,
) -> None:
    """Обрабатывает запрос пользователя с указанными категориями.
    
    Args:
        update: Объект Update от Telegram.
        context: Контекст обработчика.
        user_query: Текст запроса пользователя.
        filter_categories: Категории для фильтрации (None = все категории).
        user_id: ID пользователя.
        processing_message: Сообщение "Ищу информацию..." (если уже создано).
    """
    if processing_message is None:
        processing_message = await update.message.reply_text("🔍 Ищу информацию...")
    
    total_start_time = time.perf_counter()
    
    try:
        # 1. Проверка кэша (с учетом категорий)
        cache_start_time = time.perf_counter()
        logger.debug(f"[TELEGRAM_BOT] Этап 1/7: Проверка кэша")
        cache_key = f"query:{user_query.lower()}:cats:{sorted(filter_categories) if filter_categories else 'all'}"
        cached_response = await _get_from_cache(cache_key)
        cache_time = time.perf_counter() - cache_start_time

        if cached_response:
            total_time = time.perf_counter() - total_start_time
            logger.info(
                f"[TELEGRAM_BOT] ✅ Ответ из кэша: {user_query[:50]}... "
                f"(время: {total_time:.3f}с)"
            )
            # Сохраняем контекст запроса для кнопки изменения категорий
            query_hash = save_query_context(user_id, user_query, filter_categories)
            keyboard = create_response_keyboard(query_hash)
            await processing_message.edit_text(
                cached_response,
                parse_mode="Markdown",
                reply_markup=keyboard
            )
            return
        
        logger.debug(
            f"[TELEGRAM_BOT] Кэш не содержит ответа, продолжаем обработку "
            f"(время проверки кэша: {cache_time:.3f}с)"
        )

        # 2. Поиск релевантных чанков
        retrieval_start_time = time.perf_counter()
        logger.info(f"[TELEGRAM_BOT] Поиск релевантных чанков...")
        chunks = await retrieve_chunks(user_query, filter_categories=filter_categories)
        retrieval_time = time.perf_counter() - retrieval_start_time

        if chunks == NOT_FOUND:
            total_time = time.perf_counter() - total_start_time
            
            # Проверяем, была ли применена фильтрация по категориям
            if filter_categories:
                logger.warning(
                    f"[TELEGRAM_BOT] ❌ Не найдено релевантных чанков в выбранных категориях "
                    f"({filter_categories}) для запроса: {user_query[:50]}... "
                    f"(время поиска: {retrieval_time:.3f}с, общее время: {total_time:.3f}с)"
                )
                # Формируем информативное сообщение о том, что в выбранных категориях нет информации
                from src.formatters import escape_markdown
                categories_str = ", ".join(filter_categories)
                categories_escaped = escape_markdown(categories_str)
                response_text = (
                    f"❌ *Информация не найдена*\n\n"
                    f"В выбранных категориях \\({categories_escaped}\\) не найдено информации "
                    f"по вашему запросу\\.\n\n"
                    f"*Попробуйте:*\n"
                    f"• Выбрать другие категории\n"
                    f"• Использовать 'Все категории'\n"
                    f"• Переформулировать вопрос"
                )
            else:
                logger.warning(
                    f"[TELEGRAM_BOT] ❌ Не найдено релевантных чанков для запроса: {user_query[:50]}... "
                    f"(время поиска: {retrieval_time:.3f}с, общее время: {total_time:.3f}с)"
                )
                response_text = format_response(
                    AnalysisResponse(status="NOT_FOUND", clarification_question=None, result=None),
                    used_categories=filter_categories
                )
            
            # Сохраняем контекст запроса для возможности изменения категорий
            query_hash = save_query_context(user_id, user_query, filter_categories)
            keyboard = create_response_keyboard(query_hash)
            await processing_message.edit_text(
                response_text,
                parse_mode="Markdown",
                reply_markup=keyboard
            )
            return
        
        if not isinstance(chunks, list):
            total_time = time.perf_counter() - total_start_time
            logger.error(
                f"[TELEGRAM_BOT] ❌ Неожиданный тип chunks: {type(chunks)} "
                f"(время поиска: {retrieval_time:.3f}с, общее время: {total_time:.3f}с)"
            )
            response_text = format_response(
                AnalysisResponse(status="NOT_FOUND", clarification_question=None, result=None),
                used_categories=filter_categories
            )
            query_hash = save_query_context(user_id, user_query, filter_categories)
            keyboard = create_response_keyboard(query_hash)
            await processing_message.edit_text(
                response_text,
                parse_mode="Markdown",
                reply_markup=keyboard
            )
            return

        logger.debug(
            f"[TELEGRAM_BOT] ✅ Найдено {len(chunks)} релевантных чанков "
            f"(время поиска: {retrieval_time:.3f}с)"
        )

        # 3. Анализ чанков
        analysis_start_time = time.perf_counter()
        logger.info(f"[TELEGRAM_BOT] Анализ через LLM...")
        analysis_response = await analyze(chunks, user_query)
        analysis_time = time.perf_counter() - analysis_start_time
        logger.debug(
            f"[TELEGRAM_BOT] ✅ Анализ завершён, статус: {analysis_response.status} "
            f"(время анализа: {analysis_time:.3f}с)"
        )

        # 4. Форматирование ответа
        formatting_start_time = time.perf_counter()
        logger.debug(f"[TELEGRAM_BOT] Этап 4/7: Форматирование ответа")
        response_text = format_response(analysis_response, used_categories=filter_categories)
        formatting_time = time.perf_counter() - formatting_start_time
        logger.debug(
            f"[TELEGRAM_BOT] Сформирован ответ длиной {len(response_text)} символов "
            f"(время форматирования: {formatting_time:.3f}с)"
        )

        # 5. Сохранение в кэш
        cache_save_start_time = time.perf_counter()
        logger.debug(f"[TELEGRAM_BOT] Этап 5/7: Сохранение в кэш")
        await _set_to_cache(cache_key, response_text)
        cache_save_time = time.perf_counter() - cache_save_start_time

        # 6. Сохранение контекста запроса для кнопки изменения категорий
        query_hash = save_query_context(user_id, user_query, filter_categories)
        keyboard = create_response_keyboard(query_hash)

        # 7. Отправка ответа
        send_start_time = time.perf_counter()
        logger.debug(f"[TELEGRAM_BOT] Этап 6/7: Отправка ответа пользователю")
        try:
            await processing_message.edit_text(
                response_text,
                parse_mode="Markdown",
                reply_markup=keyboard
            )
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
                await processing_message.edit_text(
                    fallback_text,
                    reply_markup=keyboard
                )
                logger.info("[TELEGRAM_BOT] ✅ Ответ успешно отправлен без форматирования")
            except Exception as fallback_error:
                logger.error(
                    f"[TELEGRAM_BOT] ❌ Не удалось отправить ответ даже без форматирования: {fallback_error}. "
                    f"Проблема может быть в длине сообщения ({len(response_text)} символов) или специальных символах."
                )
                # Пробуем отправить урезанную версию
                try:
                    truncated_text = response_text[:4000] + "\n\n... (сообщение обрезано из-за ограничений Telegram)"
                    await processing_message.edit_text(
                        truncated_text,
                        reply_markup=keyboard
                    )
                except Exception as final_error:
                    logger.error(f"[TELEGRAM_BOT] ❌ Критическая ошибка: не удалось отправить ответ: {final_error}")
                    await processing_message.edit_text(
                        "❌ Произошла ошибка при отправке ответа. Ответ слишком длинный или содержит недопустимые символы."
                    )
        
        send_time = time.perf_counter() - send_start_time
        total_time = time.perf_counter() - total_start_time
        
        logger.info(
            f"[TELEGRAM_BOT] 📊 Производительность: "
            f"поиск={retrieval_time:.3f}с, анализ={analysis_time:.3f}с, "
            f"отправка={send_time:.3f}с, всего={total_time:.3f}с"
        )

    except Exception as e:
        total_time = time.perf_counter() - total_start_time if 'total_start_time' in locals() else 0
        error_type = type(e).__name__
        error_details = str(e)
        
        logger.error(
            f"[TELEGRAM_BOT] ❌ Критическая ошибка при обработке запроса: "
            f"тип={error_type}, сообщение={error_details}, "
            f"запрос='{user_query[:100]}...', пользователь={user_id}, "
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

    # Проверяем, есть ли у пользователя сохраненные категории
    user_categories = get_user_categories(user.id)
    
    # Если у пользователя нет сохраненных категорий, показываем клавиатуру выбора
    if not has_user_selected_categories(user.id):
        logger.info(
            f"[TELEGRAM_BOT] У пользователя {user.id} нет сохраненных категорий, "
            f"показываем клавиатуру выбора категорий"
        )
        # Сохраняем контекст запроса
        query_hash = save_query_context(user.id, user_query, None, selected_categories=[])
        # Показываем клавиатуру выбора категорий
        keyboard = create_query_categories_keyboard(query_hash, selected_categories=[])
        await update.message.reply_text(
            "🔍 Выберите категории для поиска (можно несколько):\n\n"
            "Нажмите на категорию, чтобы выбрать/снять выбор.\n"
            "Когда будете готовы, нажмите '🔍 Начать поиск'.\n\n"
            "Или используйте '🤖 Автоопределение' для автоматического выбора.",
            reply_markup=keyboard
        )
        return

    # Если есть сохраненные категории, используем их сразу
    await _process_query_with_categories(
        update, context, user_query, user_categories, user.id
    )


async def handle_confirmation_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обработчик нажатий на кнопки подтверждения категорий.

    Обрабатывает действия: confirm, reject, edit.

    Args:
        update: Объект Update от Telegram.
        context: Контекст обработчика.
    """
    query = update.callback_query
    user = update.effective_user

    logger.info(
        f"[TELEGRAM_BOT] [CALLBACK] Получен callback_query: "
        f"user_id={user.id if user else None}, "
        f"callback_data={query.data if query else None}"
    )

    if not query or not user:
        logger.warning("[TELEGRAM_BOT] [CALLBACK] ❌ query или user отсутствует")
        return

    # Проверка прав администратора
    if not is_admin(user.id):
        await query.answer("❌ У вас нет прав администратора", show_alert=True)
        logger.warning(f"[TELEGRAM_BOT] [CALLBACK] Попытка доступа к подтверждениям от неавторизованного пользователя: {user.id}")
        return

    # Парсинг callback_data: "confirm:req_123" или "reject:req_123" или "edit:req_123"
    callback_data = query.data
    if not callback_data:
        logger.error("[TELEGRAM_BOT] [CALLBACK] ❌ callback_data отсутствует")
        await query.answer("❌ Ошибка: неверный формат запроса", show_alert=True)
        return

    try:
        action, request_id = callback_data.split(":", 1)
        logger.info(
            f"[TELEGRAM_BOT] [CALLBACK] Парсинг callback_data: action='{action}', request_id='{request_id}'"
        )
    except ValueError as e:
        logger.error(f"[TELEGRAM_BOT] [CALLBACK] ❌ Ошибка парсинга callback_data '{callback_data}': {e}")
        await query.answer("❌ Ошибка: неверный формат запроса", show_alert=True)
        return

    logger.info(
        f"[TELEGRAM_BOT] [CALLBACK] Обработка действия '{action}' для запроса {request_id} от администратора {user.id}"
    )

    # Получаем запрос на подтверждение
    request = get_confirmation_request(request_id)
    if not request:
        logger.warning(f"[TELEGRAM_BOT] [CALLBACK] ❌ Запрос на подтверждение не найден: {request_id}")
        await query.answer("❌ Запрос не найден или устарел", show_alert=True)
        return

    logger.info(
        f"[TELEGRAM_BOT] [CALLBACK] Запрос найден: request_id={request_id}, "
        f"book_title={request.get('book_title', 'N/A')}, status={request.get('status', 'N/A')}"
    )

    # Обработка действий
    try:
        if action == "confirm":
            logger.info(f"[TELEGRAM_BOT] [CALLBACK] Обработка подтверждения для запроса {request_id}")
            # Подтверждение: используем категории из LLM рекомендации или из имени файла
            categories = request.get("categories_llm_recommendation", [])
            if not categories:
                categories = request.get("categories_from_filename", [])

            logger.info(f"[TELEGRAM_BOT] [CALLBACK] Категории для подтверждения: {categories}")

            # Обновляем статус
            update_confirmation_status(request_id, "approved", query.message.message_id if query.message else None)
            logger.info(f"[TELEGRAM_BOT] [CALLBACK] Статус обновлён на 'approved' для запроса {request_id}")

            # Формируем сообщение о результате
            result_message = format_confirmation_result_message(request, "approved")

            await query.answer("✅ Категории подтверждены")
            if query.message:
                try:
                    await query.message.edit_text(result_message, parse_mode="Markdown")
                    logger.info(f"[TELEGRAM_BOT] [CALLBACK] Сообщение обновлено для запроса {request_id}")
                except Exception as e:
                    logger.error(f"[TELEGRAM_BOT] [CALLBACK] ❌ Ошибка при обновлении сообщения: {e}", exc_info=True)
                    # Пытаемся отправить новое сообщение без Markdown
                    try:
                        await query.message.edit_text(result_message.replace("*", "").replace("`", ""))
                    except Exception as e2:
                        logger.error(f"[TELEGRAM_BOT] [CALLBACK] ❌ Ошибка при отправке сообщения без Markdown: {e2}")

            logger.info(
                f"[TELEGRAM_BOT] [CALLBACK] ✅ Категории подтверждены для запроса {request_id}: {categories}"
            )

            # Продолжаем индексацию файла после подтверждения
            logger.info(f"[TELEGRAM_BOT] [CALLBACK] Запуск продолжения индексации для запроса {request_id}")
            indexing_success = await continue_indexing_after_confirmation(request_id)
            if indexing_success:
                logger.info(f"[TELEGRAM_BOT] [CALLBACK] ✅ Индексация успешно продолжена для запроса {request_id}")
            else:
                logger.error(f"[TELEGRAM_BOT] [CALLBACK] ❌ Ошибка при продолжении индексации для запроса {request_id}")

        elif action == "reject":
            logger.info(f"[TELEGRAM_BOT] [CALLBACK] Обработка отклонения для запроса {request_id}")
            # Отклонение: файл будет удалён
            update_confirmation_status(request_id, "rejected", query.message.message_id if query.message else None)
            logger.info(f"[TELEGRAM_BOT] [CALLBACK] Статус обновлён на 'rejected' для запроса {request_id}")

            result_message = format_confirmation_result_message(request, "rejected")

            await query.answer("❌ Категории отклонены")
            if query.message:
                try:
                    await query.message.edit_text(result_message, parse_mode="Markdown")
                    logger.info(f"[TELEGRAM_BOT] [CALLBACK] Сообщение обновлено для запроса {request_id}")
                except Exception as e:
                    logger.error(f"[TELEGRAM_BOT] [CALLBACK] ❌ Ошибка при обновлении сообщения: {e}", exc_info=True)
                    # Пытаемся отправить новое сообщение без Markdown
                    try:
                        await query.message.edit_text(result_message.replace("*", "").replace("`", ""))
                    except Exception as e2:
                        logger.error(f"[TELEGRAM_BOT] [CALLBACK] ❌ Ошибка при отправке сообщения без Markdown: {e2}")

            logger.info(f"[TELEGRAM_BOT] [CALLBACK] ❌ Категории отклонены для запроса {request_id}")

            # TODO: Здесь можно добавить логику для удаления файла
            # (будет реализовано в шаге 4.1)

        elif action == "edit":
            logger.info(f"[TELEGRAM_BOT] [CALLBACK] Запрос на изменение категорий для запроса {request_id}")
            # Получаем текущие категории из запроса
            current_categories = request.get("categories_llm_recommendation", [])
            if not current_categories:
                current_categories = request.get("categories_from_filename", [])
            
            # Показываем клавиатуру для редактирования категорий
            edit_message = format_edit_categories_message(request, current_categories)
            edit_keyboard = format_edit_categories_keyboard(request_id, current_categories)
            
            await query.answer("✏️ Выберите категории")
            if query.message:
                try:
                    await query.message.edit_text(
                        edit_message,
                        parse_mode="Markdown",
                        reply_markup=edit_keyboard
                    )
                    logger.info(f"[TELEGRAM_BOT] [CALLBACK] Показана клавиатура редактирования для запроса {request_id}")
                except Exception as e:
                    logger.error(f"[TELEGRAM_BOT] [CALLBACK] ❌ Ошибка при обновлении сообщения: {e}", exc_info=True)

        else:
            logger.warning(f"[TELEGRAM_BOT] [CALLBACK] ❌ Неизвестное действие в callback: {action}")
            await query.answer("❌ Неизвестное действие", show_alert=True)

    except BadRequest as e:
        error_msg = str(e)
        if "Query is too old" in error_msg or "query is too old" in error_msg.lower():
            logger.warning(
                f"[TELEGRAM_BOT] [CALLBACK] ⚠️ Callback query истёк: {query.data[:50] if query and query.data else 'unknown'}"
            )
        else:
            logger.error(
                f"[TELEGRAM_BOT] [CALLBACK] ❌ BadRequest: {e}",
                exc_info=True
            )
        try:
            await query.answer("❌ Запрос устарел. Попробуйте снова.", show_alert=True)
        except Exception:
            pass  # Игнорируем ошибки при ответе на истёкший query
    except Exception as e:
        logger.error(
            f"[TELEGRAM_BOT] [CALLBACK] ❌ Критическая ошибка при обработке callback: {e}",
            exc_info=True
        )
        try:
            await query.answer("❌ Произошла ошибка при обработке запроса", show_alert=True)
        except Exception as e2:
            logger.error(f"[TELEGRAM_BOT] [CALLBACK] ❌ Не удалось отправить ответ об ошибке: {e2}")


async def handle_query_category_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обработчик выбора категорий при запросе.
    
    Обрабатывает callback'и:
    - query_cat:query_hash:category - выбор категории
    - query_auto:query_hash - автоопределение категорий
    - query_all:query_hash - все категории
    
    Args:
        update: Объект Update от Telegram.
        context: Контекст обработчика.
    """
    query = update.callback_query
    user = update.effective_user
    
    if not query or not user:
        return
    
    await query.answer()
    
    callback_data = query.data
    logger.info(f"[TELEGRAM_BOT] [QUERY_CAT] Получен callback: {callback_data} от пользователя {user.id}")
    
    try:
        if callback_data.startswith("query_cat:"):
            # Toggle категории: query_cat:query_hash:category
            parts = callback_data.split(":", 2)
            if len(parts) != 3:
                await query.answer("❌ Ошибка: неверный формат", show_alert=True)
                return
            
            _, query_hash, category = parts
            
            # Получаем контекст запроса
            query_context = get_query_context(query_hash)
            if not query_context:
                await query.answer("❌ Запрос устарел. Задайте вопрос заново.", show_alert=True)
                if query.message:
                    await query.message.edit_text("❌ Запрос устарел. Пожалуйста, задайте вопрос заново.")
                return
            
            # Проверяем, что это запрос от того же пользователя
            if query_context["user_id"] != user.id:
                await query.answer("❌ Это не ваш запрос", show_alert=True)
                return
            
            # Получаем текущий список выбранных категорий
            selected_categories = query_context.get("selected_categories", [])
            
            # Toggle категории (добавить/удалить)
            if category in selected_categories:
                selected_categories = [cat for cat in selected_categories if cat != category]
            else:
                selected_categories = selected_categories + [category]
            
            # Обновляем контекст запроса
            update_query_selected_categories(query_hash, selected_categories)
            
            # Обновляем клавиатуру с новым состоянием
            keyboard = create_query_categories_keyboard(query_hash, selected_categories)
            
            # Формируем сообщение с информацией о выбранных категориях
            if selected_categories:
                categories_str = ", ".join(selected_categories)
                message_text = (
                    f"🔍 Выберите категории для поиска (можно несколько):\n\n"
                    f"✅ Выбрано: {categories_str}\n\n"
                    f"Нажмите на категорию, чтобы выбрать/снять выбор.\n"
                    f"Когда будете готовы, нажмите '🔍 Начать поиск'."
                )
            else:
                message_text = (
                    f"🔍 Выберите категории для поиска (можно несколько):\n\n"
                    f"Нажмите на категорию, чтобы выбрать.\n"
                    f"Когда будете готовы, нажмите '🔍 Начать поиск'.\n\n"
                    f"Или используйте '🤖 Автоопределение' для автоматического выбора."
                )
            
            # Обновляем сообщение с новой клавиатурой
            if query.message:
                await query.message.edit_text(message_text, reply_markup=keyboard)
            
            logger.info(
                f"[TELEGRAM_BOT] [QUERY_CAT] Пользователь {user.id} изменил выбор категорий: {selected_categories}"
            )
            
        elif callback_data.startswith("query_search:"):
            # Запуск поиска с выбранными категориями: query_search:query_hash
            parts = callback_data.split(":", 1)
            if len(parts) != 2:
                await query.answer("❌ Ошибка: неверный формат", show_alert=True)
                return
            
            _, query_hash = parts
            
            # Получаем контекст запроса
            query_context = get_query_context(query_hash)
            if not query_context:
                await query.answer("❌ Запрос устарел. Задайте вопрос заново.", show_alert=True)
                if query.message:
                    await query.message.edit_text("❌ Запрос устарел. Пожалуйста, задайте вопрос заново.")
                return
            
            # Проверяем, что это запрос от того же пользователя
            if query_context["user_id"] != user.id:
                await query.answer("❌ Это не ваш запрос", show_alert=True)
                return
            
            # Получаем выбранные категории
            selected_categories = query_context.get("selected_categories", [])
            
            if not selected_categories:
                await query.answer("❌ Выберите хотя бы одну категорию", show_alert=True)
                return
            
            user_query = query_context["query_text"]
            filter_categories = selected_categories
            
            # Обновляем сообщение
            if query.message:
                await query.message.edit_text("🔍 Ищу информацию...")
            
            # Обрабатываем запрос с выбранными категориями
            await _process_query_with_categories(
                update, context, user_query, filter_categories, user.id, query.message
            )
            
        elif callback_data.startswith("query_reset:"):
            # Сброс выбора категорий: query_reset:query_hash
            parts = callback_data.split(":", 1)
            if len(parts) != 2:
                await query.answer("❌ Ошибка: неверный формат", show_alert=True)
                return
            
            _, query_hash = parts
            
            # Получаем контекст запроса
            query_context = get_query_context(query_hash)
            if not query_context:
                await query.answer("❌ Запрос устарел. Задайте вопрос заново.", show_alert=True)
                if query.message:
                    await query.message.edit_text("❌ Запрос устарел. Пожалуйста, задайте вопрос заново.")
                return
            
            # Проверяем, что это запрос от того же пользователя
            if query_context["user_id"] != user.id:
                await query.answer("❌ Это не ваш запрос", show_alert=True)
                return
            
            # Сбрасываем выбор категорий
            update_query_selected_categories(query_hash, [])
            
            # Обновляем клавиатуру
            keyboard = create_query_categories_keyboard(query_hash, selected_categories=[])
            message_text = (
                f"🔍 Выберите категории для поиска (можно несколько):\n\n"
                f"Выбор сброшен.\n\n"
                f"Нажмите на категорию, чтобы выбрать.\n"
                f"Когда будете готовы, нажмите '🔍 Начать поиск'.\n\n"
                f"Или используйте '🤖 Автоопределение' для автоматического выбора."
            )
            
            if query.message:
                await query.message.edit_text(message_text, reply_markup=keyboard)
            
            logger.info(f"[TELEGRAM_BOT] [QUERY_CAT] Пользователь {user.id} сбросил выбор категорий")
            
        elif callback_data.startswith("query_auto:"):
            # Автоопределение категорий: query_auto:query_hash
            parts = callback_data.split(":", 1)
            if len(parts) != 2:
                await query.answer("❌ Ошибка: неверный формат", show_alert=True)
                return
            
            _, query_hash = parts
            
            # Получаем контекст запроса
            query_context = get_query_context(query_hash)
            if not query_context:
                await query.answer("❌ Запрос устарел. Задайте вопрос заново.", show_alert=True)
                if query.message:
                    await query.message.edit_text("❌ Запрос устарел. Пожалуйста, задайте вопрос заново.")
                return
            
            # Проверяем, что это запрос от того же пользователя
            if query_context["user_id"] != user.id:
                await query.answer("❌ Это не ваш запрос", show_alert=True)
                return
            
            user_query = query_context["query_text"]
            
            # Автоматически определяем категории через LLM
            from src.category_classifier import classify_query_category
            
            # Обновляем сообщение
            if query.message:
                await query.message.edit_text("🤖 Определяю категории...")
            
            filter_categories = await classify_query_category(user_query)
            if not filter_categories:
                filter_categories = None
            
            logger.info(
                f"[TELEGRAM_BOT] [QUERY_CAT] LLM определил категории: {filter_categories}"
            )
            
            # Обрабатываем запрос с определенными категориями
            if query.message:
                await query.message.edit_text("🔍 Ищу информацию...")
            
            await _process_query_with_categories(
                update, context, user_query, filter_categories, user.id, query.message
            )
            
        elif callback_data.startswith("query_all:"):
            # Все категории: query_all:query_hash
            parts = callback_data.split(":", 1)
            if len(parts) != 2:
                await query.answer("❌ Ошибка: неверный формат", show_alert=True)
                return
            
            _, query_hash = parts
            
            # Получаем контекст запроса
            query_context = get_query_context(query_hash)
            if not query_context:
                await query.answer("❌ Запрос устарел. Задайте вопрос заново.", show_alert=True)
                if query.message:
                    await query.message.edit_text("❌ Запрос устарел. Пожалуйста, задайте вопрос заново.")
                return
            
            # Проверяем, что это запрос от того же пользователя
            if query_context["user_id"] != user.id:
                await query.answer("❌ Это не ваш запрос", show_alert=True)
                return
            
            user_query = query_context["query_text"]
            filter_categories = None  # Все категории
            
            # Обновляем сообщение
            if query.message:
                await query.message.edit_text("🔍 Ищу информацию...")
            
            # Обрабатываем запрос со всеми категориями
            await _process_query_with_categories(
                update, context, user_query, filter_categories, user.id, query.message
            )
            
    except BadRequest as e:
        error_msg = str(e)
        if "Query is too old" in error_msg or "query is too old" in error_msg.lower():
            logger.warning(
                f"[TELEGRAM_BOT] [QUERY_CAT] ⚠️ Callback query истёк: {callback_data[:50] if 'callback_data' in locals() else 'unknown'}"
            )
        else:
            logger.error(
                f"[TELEGRAM_BOT] [QUERY_CAT] ❌ BadRequest: {e}",
                exc_info=True
            )
        try:
            await query.answer("❌ Запрос устарел. Задайте вопрос заново.", show_alert=True)
        except Exception:
            pass  # Игнорируем ошибки при ответе на истёкший query
    except Exception as e:
        logger.error(
            f"[TELEGRAM_BOT] [QUERY_CAT] ❌ Ошибка при обработке callback: {e}",
            exc_info=True
        )
        try:
            await query.answer("❌ Произошла ошибка", show_alert=True)
            if query.message:
                await query.message.edit_text("❌ Произошла ошибка при обработке запроса. Попробуйте задать вопрос заново.")
        except Exception as e2:
            logger.error(f"[TELEGRAM_BOT] [QUERY_CAT] ❌ Не удалось отправить ответ об ошибке: {e2}")


async def handle_change_categories_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обработчик изменения категорий из ответа.
    
    Обрабатывает callback: change_cats:query_hash
    
    Args:
        update: Объект Update от Telegram.
        context: Контекст обработчика.
    """
    query = update.callback_query
    user = update.effective_user
    
    if not query or not user:
        return
    
    await query.answer()
    
    callback_data = query.data
    logger.info(f"[TELEGRAM_BOT] [CHANGE_CATS] Получен callback: {callback_data} от пользователя {user.id}")
    
    try:
        if callback_data.startswith("change_cats:"):
            # Изменение категорий: change_cats:query_hash
            parts = callback_data.split(":", 1)
            if len(parts) != 2:
                await query.answer("❌ Ошибка: неверный формат", show_alert=True)
                return
            
            _, query_hash = parts
            
            # Получаем контекст запроса
            query_context = get_query_context(query_hash)
            if not query_context:
                await query.answer("❌ Запрос устарел. Задайте вопрос заново.", show_alert=True)
                if query.message:
                    await query.message.edit_text("❌ Запрос устарел. Пожалуйста, задайте вопрос заново.")
                return
            
            # Проверяем, что это запрос от того же пользователя
            if query_context["user_id"] != user.id:
                await query.answer("❌ Это не ваш запрос", show_alert=True)
                return
            
            # Показываем клавиатуру выбора категорий
            current_categories = query_context.get("used_categories", [])
            keyboard = create_query_categories_keyboard(query_hash)
            
            message_text = "🔍 Выберите категории для поиска или используйте автоопределение:"
            if current_categories:
                categories_str = ", ".join(current_categories)
                message_text += f"\n\nТекущие категории: {categories_str}"
            
            if query.message:
                await query.message.edit_text(message_text, reply_markup=keyboard)
                logger.info(
                    f"[TELEGRAM_BOT] [CHANGE_CATS] Показана клавиатура выбора категорий "
                    f"для запроса {query_hash}"
                )
            
    except BadRequest as e:
        error_msg = str(e)
        if "Query is too old" in error_msg or "query is too old" in error_msg.lower():
            logger.warning(
                f"[TELEGRAM_BOT] [CHANGE_CATS] ⚠️ Callback query истёк: {query.data[:50] if query and query.data else 'unknown'}"
            )
        else:
            logger.error(
                f"[TELEGRAM_BOT] [CHANGE_CATS] ❌ BadRequest: {e}",
                exc_info=True
            )
        try:
            await query.answer("❌ Запрос устарел. Задайте вопрос заново.", show_alert=True)
        except Exception:
            pass  # Игнорируем ошибки при ответе на истёкший query
    except Exception as e:
        logger.error(
            f"[TELEGRAM_BOT] [CHANGE_CATS] ❌ Ошибка при обработке callback: {e}",
            exc_info=True
        )
        try:
            await query.answer("❌ Произошла ошибка", show_alert=True)
        except Exception as e2:
            logger.error(f"[TELEGRAM_BOT] [CHANGE_CATS] ❌ Не удалось отправить ответ об ошибке: {e2}")


async def handle_category_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обработчик callback для выбора категорий пользователем.

    Args:
        update: Объект Update от Telegram.
        context: Контекст обработчика.
    """
    query = update.callback_query
    if not query or not query.data:
        return

    user = update.effective_user
    if not user:
        return

    await query.answer()

    callback_data = query.data
    logger.info(f"Обработка выбора категории: {callback_data} от пользователя {user.id}")

    current_categories = get_user_categories(user.id) or []

    if callback_data == "select_all_cats":
        # Выбрать все категории (None означает все)
        set_user_categories(user.id, None)
        message = format_categories_message(None)
        keyboard = create_categories_keyboard(None)
        await query.edit_message_text(
            message, 
            parse_mode="Markdown",
            reply_markup=keyboard
        )
        logger.info(f"Пользователь {user.id} выбрал все категории")

    elif callback_data == "clear_cats":
        # Сбросить выбор (все категории)
        clear_user_categories(user.id)
        message = format_categories_message(None)
        keyboard = create_categories_keyboard(None)
        await query.edit_message_text(
            message,
            parse_mode="Markdown",
            reply_markup=keyboard
        )
        logger.info(f"Пользователь {user.id} сбросил выбор категорий")

    elif callback_data.startswith("toggle_cat:"):
        # Переключить категорию
        category = callback_data.split(":", 1)[1]
        
        # Получаем текущий список категорий
        if current_categories is None:
            # Если выбраны все, создаем список всех категорий кроме выбранной
            current_categories = [cat for cat in Config.CATEGORIES if cat != category]
        else:
            # Переключаем категорию
            if category in current_categories:
                current_categories = [cat for cat in current_categories if cat != category]
            else:
                current_categories = current_categories + [category]
        
        # Если все категории выбраны, устанавливаем None
        if set(current_categories) == set(Config.CATEGORIES):
            set_user_categories(user.id, None)
            message = format_categories_message(None)
            keyboard = create_categories_keyboard(None)
        else:
            set_user_categories(user.id, current_categories)
            message = format_categories_message(current_categories)
            keyboard = create_categories_keyboard(current_categories)
        
        await query.edit_message_text(
            message,
            parse_mode="Markdown",
            reply_markup=keyboard
        )
        logger.info(f"Пользователь {user.id} изменил выбор категорий: {current_categories}")


async def handle_edit_categories_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обработчик callback для редактирования категорий при подтверждении.

    Обрабатывает:
    - edit_cat:request_id:category - переключение категории
    - edit_done:request_id - завершение редактирования
    - edit_cancel:request_id - отмена редактирования

    Args:
        update: Объект Update от Telegram.
        context: Контекст обработчика.
    """
    query = update.callback_query
    user = update.effective_user

    if not query or not user or not query.data:
        return

    # Проверка прав администратора
    if not is_admin(user.id):
        await query.answer("❌ У вас нет прав администратора", show_alert=True)
        logger.warning(f"[TELEGRAM_BOT] [EDIT_CAT] Попытка редактирования от неавторизованного пользователя: {user.id}")
        return

    callback_data = query.data
    logger.info(f"[TELEGRAM_BOT] [EDIT_CAT] Получен callback: {callback_data} от администратора {user.id}")

    try:
        if callback_data.startswith("edit_cat:"):
            # Переключение категории: edit_cat:request_id:category
            parts = callback_data.split(":", 2)
            if len(parts) != 3:
                await query.answer("❌ Ошибка: неверный формат запроса", show_alert=True)
                return

            _, request_id, category = parts

            # Получаем запрос
            request = get_confirmation_request(request_id)
            if not request:
                await query.answer("❌ Запрос не найден", show_alert=True)
                logger.warning(f"[TELEGRAM_BOT] [EDIT_CAT] Запрос не найден: {request_id}")
                return

            # Получаем текущие категории
            current_categories = request.get("categories_llm_recommendation", [])
            if not current_categories:
                current_categories = request.get("categories_from_filename", [])

            # Переключаем категорию
            if category in current_categories:
                current_categories = [cat for cat in current_categories if cat != category]
            else:
                current_categories = current_categories + [category]

            # Сохраняем обновленные категории в запрос
            update_confirmation_categories(request_id, current_categories)
            
            # Обновляем запрос для получения актуальных данных
            request = get_confirmation_request(request_id)

            # Обновляем клавиатуру
            edit_message = format_edit_categories_message(request, current_categories)
            edit_keyboard = format_edit_categories_keyboard(request_id, current_categories)

            await query.answer()
            if query.message:
                try:
                    await query.message.edit_text(
                        edit_message,
                        parse_mode="Markdown",
                        reply_markup=edit_keyboard
                    )
                    logger.info(f"[TELEGRAM_BOT] [EDIT_CAT] Категория '{category}' переключена для запроса {request_id}, новые категории: {current_categories}")
                except Exception as e:
                    logger.error(f"[TELEGRAM_BOT] [EDIT_CAT] ❌ Ошибка при обновлении сообщения: {e}", exc_info=True)

        elif callback_data.startswith("edit_done:"):
            # Завершение редактирования: edit_done:request_id
            parts = callback_data.split(":", 1)
            if len(parts) != 2:
                await query.answer("❌ Ошибка: неверный формат запроса", show_alert=True)
                return

            _, request_id = parts

            # Получаем запрос
            request = get_confirmation_request(request_id)
            if not request:
                await query.answer("❌ Запрос не найден", show_alert=True)
                logger.warning(f"[TELEGRAM_BOT] [EDIT_CAT] Запрос не найден: {request_id}")
                return

            # Получаем текущие категории из запроса (они уже обновлены через edit_cat)
            current_categories = request.get("categories_llm_recommendation", [])
            if not current_categories:
                current_categories = request.get("categories_from_filename", [])

            # Показываем обновленное сообщение подтверждения
            # Обновляем запрос для получения актуальных данных
            request = get_confirmation_request(request_id)
            confirmation_message = format_confirmation_message(request)
            confirmation_keyboard = create_confirmation_keyboard(request_id)

            await query.answer("✅ Категории сохранены")
            if query.message:
                try:
                    await query.message.edit_text(
                        confirmation_message,
                        parse_mode="Markdown",
                        reply_markup=confirmation_keyboard
                    )
                    logger.info(f"[TELEGRAM_BOT] [EDIT_CAT] ✅ Редактирование завершено для запроса {request_id}, категории: {current_categories}")
                except Exception as e:
                    logger.error(f"[TELEGRAM_BOT] [EDIT_CAT] ❌ Ошибка при обновлении сообщения: {e}", exc_info=True)

        elif callback_data.startswith("edit_cancel:"):
            # Отмена редактирования: edit_cancel:request_id
            parts = callback_data.split(":", 1)
            if len(parts) != 2:
                await query.answer("❌ Ошибка: неверный формат запроса", show_alert=True)
                return

            _, request_id = parts

            # Получаем запрос
            request = get_confirmation_request(request_id)
            if not request:
                await query.answer("❌ Запрос не найден", show_alert=True)
                logger.warning(f"[TELEGRAM_BOT] [EDIT_CAT] Запрос не найден: {request_id}")
                return

            # Возвращаемся к исходному сообщению подтверждения
            confirmation_message = format_confirmation_message(request)
            confirmation_keyboard = create_confirmation_keyboard(request_id)

            await query.answer("❌ Редактирование отменено")
            if query.message:
                try:
                    await query.message.edit_text(
                        confirmation_message,
                        parse_mode="Markdown",
                        reply_markup=confirmation_keyboard
                    )
                    logger.info(f"[TELEGRAM_BOT] [EDIT_CAT] Редактирование отменено для запроса {request_id}")
                except Exception as e:
                    logger.error(f"[TELEGRAM_BOT] [EDIT_CAT] ❌ Ошибка при обновлении сообщения: {e}", exc_info=True)

    except Exception as e:
        logger.error(
            f"[TELEGRAM_BOT] [EDIT_CAT] ❌ Критическая ошибка при обработке callback: {e}",
            exc_info=True
        )
        try:
            await query.answer("❌ Произошла ошибка при обработке запроса", show_alert=True)
        except Exception as e2:
            logger.error(f"[TELEGRAM_BOT] [EDIT_CAT] ❌ Не удалось отправить ответ об ошибке: {e2}")


async def send_confirmation_to_admin(
    request: dict[str, Any], context: ContextTypes.DEFAULT_TYPE
) -> int | None:
    """Отправляет уведомление администратору о необходимости подтверждения категорий.

    Args:
        request: Словарь с данными запроса на подтверждение.
        context: Контекст бота для отправки сообщения.

    Returns:
        ID отправленного сообщения или None, если не удалось отправить.
    """
    admin_id = Config.ADMIN_TELEGRAM_ID
    if not admin_id:
        logger.error("ADMIN_TELEGRAM_ID не установлен, невозможно отправить уведомление")
        return None

    try:
        message_text = format_confirmation_message(request)
        keyboard = create_confirmation_keyboard(request["request_id"])

        sent_message = await context.bot.send_message(
            chat_id=admin_id,
            text=message_text,
            reply_markup=keyboard,
            parse_mode="Markdown",
        )

        message_id = sent_message.message_id

        # Обновляем message_id в запросе
        update_confirmation_status(request["request_id"], "pending", message_id)

        logger.info(
            f"Уведомление отправлено администратору {admin_id} для запроса {request['request_id']}"
        )

        return message_id

    except Exception as e:
        logger.error(
            f"Ошибка при отправке уведомления администратору {admin_id}: {e}",
            exc_info=True,
        )
        return None


async def check_expired_confirmations_job(context: ContextTypes.DEFAULT_TYPE) -> None:
    """Фоновая задача для проверки истёкших запросов на подтверждение.

    Выполняется периодически (каждый час) для проверки таймаутов
    и удаления файлов, для которых истёк срок ожидания подтверждения.

    Args:
        context: Контекст бота.
    """
    logger.info("[BACKGROUND JOB] Запуск проверки истёкших запросов на подтверждение...")

    try:
        deleted_count = await check_and_cleanup_expired_confirmations()

        if deleted_count > 0:
            logger.info(
                f"[BACKGROUND JOB] ✅ Проверка завершена: удалено {deleted_count} файлов"
            )

            # Отправляем уведомление администратору (опционально)
            admin_id = Config.ADMIN_TELEGRAM_ID
            if admin_id and deleted_count > 0:
                try:
                    await context.bot.send_message(
                        chat_id=admin_id,
                        text=(
                            f"⏰ *Автоматическая проверка таймаутов*\n\n"
                            f"Удалено файлов из-за истечения срока ожидания: *{deleted_count}*"
                        ),
                        parse_mode="Markdown",
                    )
                except Exception as e:
                    logger.warning(
                        f"Не удалось отправить уведомление администратору о таймаутах: {e}"
                    )
        else:
            logger.debug("[BACKGROUND JOB] Истёкших запросов не найдено")

    except Exception as e:
        logger.error(
            f"[BACKGROUND JOB] ❌ Ошибка при проверке истёкших запросов: {e}",
            exc_info=True,
        )


async def categories_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обработчик команды /categories для управления выбором категорий.

    Args:
        update: Объект Update от Telegram.
        context: Контекст обработчика.
    """
    user = update.effective_user
    if not user or not update.message:
        return

    logger.info(f"Команда /categories от пользователя {user.id} (@{user.username})")

    selected_categories = get_user_categories(user.id)
    message = format_categories_message(selected_categories)
    keyboard = create_categories_keyboard(selected_categories)

    await update.message.reply_text(
        message,
        parse_mode="Markdown",
        reply_markup=keyboard
    )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обработчик команды /help для отображения справки по командам.

    Показывает список всех доступных команд с описаниями.
    Для администраторов показывает дополнительные команды.

    Args:
        update: Объект Update от Telegram.
        context: Контекст обработчика.
    """
    user = update.effective_user
    if not user or not update.message:
        return

    logger.info(f"Команда /help от пользователя {user.id}")

    # Базовые команды для всех пользователей
    help_text = "📚 *Доступные команды:*\n\n"
    help_text += "`/start` - Начать работу с ботом\n"
    help_text += "`/help` - Показать эту справку\n\n"

    # Проверяем, является ли пользователь администратором
    if is_admin(user.id):
        help_text += "🔐 *Команды администратора:*\n\n"
        help_text += "`/pending` - Показать список ожидающих подтверждения файлов\n"
        help_text += "`/pending_books` - Показать список непроиндексированных книг\n"
        help_text += "`/cleanup` - Очистить старые запросы (старше 1 дня)\n"
        help_text += "`/cleanup_pending_books` - Полностью очистить список непроиндексированных книг\n"
        help_text += "`/categories` - Управление категориями для фильтрации\n\n"
        logger.info(f"Показана справка для администратора {user.id}")
    else:
        logger.info(f"Показана справка для обычного пользователя {user.id}")

    help_text += "💡 *Как использовать бота:*\n\n"
    help_text += "Просто отправьте боту ваш вопрос, и он ответит на основе загруженных книг.\n\n"
    help_text += "Бот использует искусственный интеллект для поиска релевантной информации в библиотеке."

    try:
        await update.message.reply_text(help_text, parse_mode="Markdown")
    except Exception as e:
        logger.error(f"Ошибка при отправке справки: {e}")
        # Отправляем без Markdown в случае ошибки
        help_text_plain = help_text.replace("*", "").replace("`", "")
        await update.message.reply_text(help_text_plain)


async def cleanup_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обработчик команды /cleanup для очистки старых запросов.

    Удаляет запросы со статусами "approved", "rejected", "timeout",
    которые старше 1 дня.

    Args:
        update: Объект Update от Telegram.
        context: Контекст обработчика.
    """
    from src.confirmation_manager import cleanup_old_confirmations

    user = update.effective_user
    if not user or not update.message:
        return

    # Проверка прав администратора
    if not is_admin(user.id):
        await update.message.reply_text("❌ У вас нет прав администратора")
        logger.warning(f"Попытка доступа к /cleanup от неавторизованного пользователя: {user.id}")
        return

    logger.info(f"Команда /cleanup от администратора {user.id}")

    try:
        # Очищаем все запросы (обработанные + pending) независимо от возраста
        deleted_count = cleanup_old_confirmations(ignore_age=True, include_pending=True)

        if deleted_count > 0:
            message = (
                f"🧹 *Очистка всех запросов*\n\n"
                f"✅ Удалено запросов: *{deleted_count}*\n\n"
                f"Удалены все запросы со статусами: approved, rejected, timeout, pending\n"
                f"(независимо от возраста)"
            )
            logger.info(f"Очищено {deleted_count} запросов (включая pending) администратором {user.id}")
        else:
            message = (
                f"🧹 *Очистка всех запросов*\n\n"
                f"✅ Запросов для удаления не найдено.\n\n"
                f"Все запросы актуальны (младше 1 дня)."
            )
            logger.info(f"Старых запросов не найдено для очистки")

        await update.message.reply_text(message, parse_mode="Markdown")

    except Exception as e:
        logger.error(f"Ошибка при очистке старых запросов: {e}", exc_info=True)
        await update.message.reply_text(
            "❌ Произошла ошибка при очистке старых запросов."
        )


async def cleanup_pending_books_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обработчик команды /cleanup_pending_books для очистки списка непроиндексированных книг.

    Удаляет все книги из списка ожидания индексации.

    Args:
        update: Объект Update от Telegram.
        context: Контекст обработчика.
    """
    from src.pending_books_manager import clear_all_pending_books

    user = update.effective_user
    if not user or not update.message:
        return

    # Проверка прав администратора
    if not is_admin(user.id):
        await update.message.reply_text("❌ У вас нет прав администратора")
        logger.warning(f"Попытка доступа к /cleanup_pending_books от неавторизованного пользователя: {user.id}")
        return

    logger.info(f"Команда /cleanup_pending_books от администратора {user.id}")

    try:
        # Очищаем весь список непроиндексированных книг
        deleted_count = clear_all_pending_books()

        if deleted_count > 0:
            message = (
                f"🧹 *Очистка списка непроиндексированных книг*\n\n"
                f"✅ Удалено книг из списка ожидания: *{deleted_count}*\n\n"
                f"Все книги удалены из списка непроиндексированных."
            )
            logger.info(f"Очищено {deleted_count} книг из списка ожидания администратором {user.id}")
        else:
            message = (
                f"🧹 *Очистка списка непроиндексированных книг*\n\n"
                f"✅ Список ожидания пуст.\n\n"
                f"Нет книг для удаления."
            )
            logger.info(f"Список непроиндексированных книг пуст")

        await update.message.reply_text(message, parse_mode="Markdown")

    except Exception as e:
        logger.error(f"Ошибка при очистке списка непроиндексированных книг: {e}", exc_info=True)
        await update.message.reply_text(
            "❌ Произошла ошибка при очистке списка непроиндексированных книг."
        )


async def check_and_notify_new_books(context: ContextTypes.DEFAULT_TYPE) -> None:
    """Проверяет наличие новых книг и отправляет уведомление администратору.
    
    Args:
        context: Контекст бота для отправки сообщений.
    """
    if not Config.ADMIN_TELEGRAM_ID:
        logger.debug("[NEW_BOOKS] ADMIN_TELEGRAM_ID не установлен, пропускаем проверку новых книг")
        return
    
    # Путь к папке с книгами (по умолчанию)
    books_folder = "./data/books"
    
    try:
        # Удаляем несуществующие файлы из списка ожидания
        remove_missing_files()
        
        # Проверяем новые книги
        new_files = await check_for_new_books(books_folder)
        
        if not new_files:
            logger.debug("[NEW_BOOKS] Новых книг не найдено")
            return
        
        # Добавляем новые книги в список ожидания
        added_count = 0
        for file_path in new_files:
            if add_pending_book(file_path):
                added_count += 1
        
        if added_count == 0:
            logger.debug("[NEW_BOOKS] Все новые книги уже в списке ожидания")
            return
        
        logger.info(f"[NEW_BOOKS] Добавлено {added_count} новых книг в список ожидания")
        
        # Получаем список непроиндексированных книг (включая только те, для которых не отправлялось уведомление)
        pending_books = get_pending_books()
        books_to_notify = [book for book in pending_books if not book.get("notification_sent", False)]
        
        if not books_to_notify:
            logger.debug("[NEW_BOOKS] Нет книг для уведомления (все уведомления уже отправлены)")
            return
        
        # Отправляем уведомление администратору
        message_text = format_pending_books_message(books_to_notify)
        keyboard = create_index_books_keyboard()
        
        try:
            sent_message = await context.bot.send_message(
                chat_id=Config.ADMIN_TELEGRAM_ID,
                text=message_text,
                parse_mode="Markdown",
                reply_markup=keyboard
            )
            
            # Отмечаем, что уведомление отправлено для всех книг
            for book in books_to_notify:
                mark_notification_sent(book["file_path"], sent_message.message_id)
            
            logger.info(
                f"[NEW_BOOKS] ✅ Уведомление о {len(books_to_notify)} новых книгах отправлено администратору"
            )
        except Exception as e:
            logger.error(
                f"[NEW_BOOKS] ❌ Ошибка при отправке уведомления администратору: {e}",
                exc_info=True
            )
    
    except Exception as e:
        logger.error(
            f"[NEW_BOOKS] ❌ Ошибка при проверке новых книг: {e}",
            exc_info=True
        )


async def handle_index_books_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обработчик callback для индексации непроиндексированных книг.
    
    Обрабатывает:
    - index_books:confirm - запуск индексации
    - index_books:cancel - отмена (удаление уведомления)
    - index_books:list - показать детальный список
    
    Args:
        update: Объект Update от Telegram.
        context: Контекст обработчика.
    """
    query = update.callback_query
    user = update.effective_user
    
    if not query or not user:
        return
    
    # Проверка прав администратора
    if not is_admin(user.id):
        await query.answer("❌ У вас нет прав администратора", show_alert=True)
        return
    
    await query.answer()
    
    callback_data = query.data
    logger.info(f"[INDEX_BOOKS] Получен callback: {callback_data} от администратора {user.id}")
    
    try:
        if callback_data == "index_books:confirm":
            # Запуск индексации
            pending_books = get_pending_books()
            
            if not pending_books:
                await query.message.edit_text("✅ Нет непроиндексированных книг.")
                return
            
            # Обновляем сообщение
            await query.message.edit_text("🔄 Начинаю индексацию книг...")
            
            # Запускаем индексацию
            books_folder = "./data/books"
            
            try:
                await ingest_books(books_folder, force=False)
                
                # Проверяем, сколько книг осталось в списке ожидания
                remaining_books = get_pending_books()
                
                if remaining_books:
                    message = (
                        f"✅ *Индексация завершена*\n\n"
                        f"Некоторые книги могут требовать подтверждения категорий.\n"
                        f"Осталось непроиндексированных: {len(remaining_books)}"
                    )
                else:
                    message = (
                        f"✅ *Индексация завершена*\n\n"
                        f"Все книги успешно проиндексированы!"
                    )
                
                await query.message.edit_text(message, parse_mode="Markdown")
                logger.info(f"[INDEX_BOOKS] ✅ Индексация завершена администратором {user.id}")
                
            except Exception as e:
                error_msg = f"❌ Ошибка при индексации: {str(e)}"
                await query.message.edit_text(error_msg)
                logger.error(f"[INDEX_BOOKS] ❌ Ошибка при индексации: {e}", exc_info=True)
        
        elif callback_data == "index_books:cancel":
            # Отмена - просто удаляем уведомление, книги остаются
            await query.message.edit_text(
                "❌ Индексация отменена.\n\n"
                "Книги остаются в папке, но не будут проиндексированы.\n"
                "Вы можете запустить индексацию позже через команду /pending_books"
            )
            logger.info(f"[INDEX_BOOKS] Индексация отменена администратором {user.id}")
        
        elif callback_data == "index_books:list":
            # Показать детальный список
            pending_books = get_pending_books()
            message_text = format_pending_books_list(pending_books)
            keyboard = create_index_books_keyboard()
            
            try:
                await query.message.edit_text(
                    message_text,
                    parse_mode="Markdown",
                    reply_markup=keyboard
                )
            except Exception as e:
                logger.error(f"[INDEX_BOOKS] Ошибка при отправке списка: {e}")
                await query.message.edit_text(
                    "❌ Ошибка при формировании списка книг."
                )
    
    except Exception as e:
        logger.error(
            f"[INDEX_BOOKS] ❌ Ошибка при обработке callback: {e}",
            exc_info=True
        )
        try:
            await query.answer("❌ Произошла ошибка", show_alert=True)
        except Exception:
            pass


async def pending_books_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обработчик команды /pending_books для просмотра непроиндексированных книг.
    
    Args:
        update: Объект Update от Telegram.
        context: Контекст обработчика.
    """
    user = update.effective_user
    if not user or not update.message:
        return
    
    # Проверка прав администратора
    if not is_admin(user.id):
        await update.message.reply_text("❌ У вас нет прав администратора")
        logger.warning(f"Попытка доступа к /pending_books от неавторизованного пользователя: {user.id}")
        return
    
    logger.info(f"Команда /pending_books от администратора {user.id}")
    
    # Получаем непроиндексированные книги
    pending_books = get_pending_books()
    
    if not pending_books:
        await update.message.reply_text("✅ Нет непроиндексированных книг.")
        return
    
    # Форматируем список
    message_text = format_pending_books_message(pending_books)
    keyboard = create_index_books_keyboard()
    
    try:
        await update.message.reply_text(
            message_text,
            parse_mode="Markdown",
            reply_markup=keyboard
        )
    except Exception as e:
        logger.error(f"Ошибка при отправке списка непроиндексированных книг: {e}")
        await update.message.reply_text(
            "❌ Произошла ошибка при формировании списка книг."
        )


async def pending_confirmations_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обработчик команды /pending для просмотра ожидающих подтверждений.

    Показывает список всех запросов на подтверждение со статусом "pending".

    Args:
        update: Объект Update от Telegram.
        context: Контекст обработчика.
    """
    user = update.effective_user
    if not user or not update.message:
        return

    # Проверка прав администратора
    if not is_admin(user.id):
        await update.message.reply_text("❌ У вас нет прав администратора")
        logger.warning(f"Попытка доступа к /pending от неавторизованного пользователя: {user.id}")
        return

    logger.info(f"Команда /pending от администратора {user.id}")

    # Получаем ожидающие подтверждения
    pending = get_pending_confirmations()

    if not pending:
        await update.message.reply_text("✅ Нет ожидающих подтверждений.")
        return

    # Форматируем список
    message = format_pending_confirmations_list(pending)

    try:
        await update.message.reply_text(message, parse_mode="Markdown")
    except Exception as e:
        logger.error(f"Ошибка при отправке списка подтверждений: {e}")
        await update.message.reply_text(
            "❌ Произошла ошибка при формировании списка подтверждений."
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
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("categories", categories_command))
    application.add_handler(CommandHandler("pending", pending_confirmations_command))
    application.add_handler(CommandHandler("pending_books", pending_books_command))
    application.add_handler(CommandHandler("cleanup", cleanup_command))
    application.add_handler(CommandHandler("cleanup_pending_books", cleanup_pending_books_command))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    # Регистрация обработчиков callback для подтверждений
    application.add_handler(
        CallbackQueryHandler(handle_confirmation_callback, pattern=r"^(confirm|reject|edit):")
    )
    
    # Регистрация обработчиков callback для редактирования категорий при подтверждении
    application.add_handler(
        CallbackQueryHandler(
            handle_edit_categories_callback,
            pattern=r"^(edit_cat:|edit_done:|edit_cancel:)"
        )
    )
    
    # Регистрация обработчиков callback для выбора категорий
    application.add_handler(
        CallbackQueryHandler(
            handle_category_callback,
            pattern=r"^(toggle_cat:|select_all_cats|clear_cats)"
        )
    )
    
    # Регистрация обработчиков callback для выбора категорий при запросе
    application.add_handler(
        CallbackQueryHandler(
            handle_query_category_callback,
            pattern=r"^query_(cat|auto|all|search|reset):"
        )
    )
    
    # Регистрация обработчиков callback для изменения категорий из ответа
    application.add_handler(
        CallbackQueryHandler(
            handle_change_categories_callback,
            pattern=r"^change_cats:"
        )
    )
    
    # Регистрация обработчиков callback для индексации книг
    application.add_handler(
        CallbackQueryHandler(
            handle_index_books_callback,
            pattern=r"^index_books:"
        )
    )

    logger.info(
        "Обработчики зарегистрированы: /start, /help, /categories, /pending, /pending_books, /cleanup, /cleanup_pending_books, "
        "текстовые сообщения, callback для подтверждений, callback для категорий, callback для индексации книг"
    )

    return application


async def send_pending_notifications_on_startup(context: ContextTypes.DEFAULT_TYPE) -> None:
    """Отправляет накопленные уведомления администратору при запуске бота.

    Проверяет все запросы на подтверждение без message_id и отправляет уведомления.

    Args:
        context: Контекст бота.
    """
    from src.confirmation_manager import get_all_confirmations

    logger.info("[STARTUP] Проверка накопленных уведомлений о подтверждении категорий...")
    
    # Автоматическая очистка старых запросов при старте
    from src.confirmation_manager import cleanup_old_confirmations
    cleaned_count = cleanup_old_confirmations(days=1)
    if cleaned_count > 0:
        logger.info(f"[STARTUP] Автоматически очищено {cleaned_count} старых запросов (старше 1 дня)")
    
    all_confirmations = get_all_confirmations()
    pending_without_message = [
        req for req in all_confirmations.values()
        if req.get("status") == "pending" and req.get("message_id") is None
    ]
    
    if not pending_without_message:
        logger.info("[STARTUP] Нет накопленных уведомлений для отправки")
        return
    
    logger.info(
        f"[STARTUP] Найдено {len(pending_without_message)} запросов без уведомлений, "
        f"отправляем администратору..."
    )
    
    admin_id = Config.ADMIN_TELEGRAM_ID
    if not admin_id:
        logger.warning(
            "[STARTUP] ⚠️ ADMIN_TELEGRAM_ID не установлен, "
            "уведомления не будут отправлены"
        )
        return
    
    sent_count = 0
    failed_count = 0
    
    for request in pending_without_message:
        try:
            message_id = await send_confirmation_to_admin(request, context)
            if message_id:
                sent_count += 1
            else:
                failed_count += 1
        except Exception as e:
            failed_count += 1
            logger.error(
                f"[STARTUP] ❌ Ошибка при отправке уведомления для запроса "
                f"{request.get('request_id')}: {e}",
                exc_info=True
            )
    
    if sent_count > 0:
        logger.info(
            f"[STARTUP] ✅ Отправлено {sent_count} накопленных уведомлений администратору"
        )
    if failed_count > 0:
        logger.warning(
            f"[STARTUP] ⚠️ Не удалось отправить {failed_count} уведомлений"
        )


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

    # Регистрация фоновой задачи для проверки таймаутов
    # Проверка выполняется каждый час (3600 секунд)
    job_queue = application.job_queue
    if job_queue:
        job_queue.run_repeating(
            check_expired_confirmations_job,
            interval=3600,  # 1 час в секундах
            first=60,  # Первый запуск через 60 секунд после старта
            name="check_expired_confirmations",
        )
        logger.info(
            "Фоновая задача для проверки таймаутов зарегистрирована "
            "(интервал: 1 час, первый запуск: через 60 секунд)"
        )
    else:
        logger.warning("JobQueue недоступен, фоновая проверка таймаутов не будет выполняться")
    
    # Регистрация периодической задачи для проверки новых книг
    if job_queue:
        # Проверка каждые 10 минут (600 секунд)
        job_queue.run_repeating(
            check_and_notify_new_books,
            interval=600,  # 10 минут в секундах
            first=60,  # Первый запуск через 60 секунд после старта
            name="check_new_books",
        )
        logger.info(
            "Фоновая задача для проверки новых книг зарегистрирована "
            "(интервал: 10 минут, первый запуск: через 60 секунд)"
        )
    else:
        logger.warning("JobQueue недоступен, фоновая проверка новых книг не будет выполняться")

    # Запуск бота
    logger.info("Бот запущен и готов к работе")
    await application.initialize()
    await application.start()
    if application.updater:
        await application.updater.start_polling()
        
        # Отправляем накопленные уведомления после запуска бота
        # Создаем простой context-подобный объект для отправки уведомлений
        class StartupContext:
            def __init__(self, bot):
                self.bot = bot
        
        if application.bot:
            startup_context = StartupContext(application.bot)
            await send_pending_notifications_on_startup(startup_context)
            
            # Проверяем новые книги при старте
            await check_and_notify_new_books(startup_context)
        
        # Очищаем истекшие контексты запросов при старте
        expired_count = cleanup_expired_contexts()
        if expired_count > 0:
            logger.info(f"[STARTUP] Очищено {expired_count} истекших контекстов запросов")

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
