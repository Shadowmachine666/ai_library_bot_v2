"""Сервис индексации книг для ai_library_bot.

Обрабатывает файлы книг (TXT, PDF, EPUB, FB2), разбивает на чанки,
создаёт эмбеддинги и сохраняет в FAISS индекс.
"""

import hashlib
import pickle
from datetime import datetime
from pathlib import Path
from typing import Any

from src.config import Config
from src.utils import run_in_executor, setup_logger
from src.category_parser import parse_categories_from_filename
from src.category_classifier import classify_book_category
from src.confirmation_manager import (
    create_confirmation_request,
    delete_confirmation_request,
    get_all_confirmations,
    get_confirmation_request,
    get_expired_requests,
    get_pending_confirmations,
    update_confirmation_status,
)
from src.admin_messages import (
    create_confirmation_keyboard,
    format_confirmation_message,
)

logger = setup_logger(__name__)

# Поддерживаемые форматы файлов
SUPPORTED_EXTENSIONS = {".txt", ".pdf", ".epub", ".fb2"}


async def _send_notification_to_admin_direct(request: dict[str, Any]) -> int | None:
    """Отправляет уведомление администратору напрямую через Telegram Bot API.

    Работает независимо от запущенного бота. Используется при индексации через CLI.

    Args:
        request: Словарь с данными запроса на подтверждение.

    Returns:
        ID отправленного сообщения или None, если не удалось отправить.
    """
    admin_id = Config.ADMIN_TELEGRAM_ID
    if not admin_id:
        logger.warning(
            "ADMIN_TELEGRAM_ID не установлен, уведомление администратору не будет отправлено"
        )
        return None

    if not Config.TG_TOKEN:
        logger.warning(
            "TG_TOKEN не установлен, уведомление администратору не будет отправлено"
        )
        return None

    try:
        from telegram import Bot

        bot = Bot(token=Config.TG_TOKEN)
        message_text = format_confirmation_message(request)
        keyboard = create_confirmation_keyboard(request["request_id"])

        sent_message = await bot.send_message(
            chat_id=admin_id,
            text=message_text,
            reply_markup=keyboard,
            parse_mode="Markdown",
        )

        message_id = sent_message.message_id

        # Обновляем message_id в запросе
        update_confirmation_status(request["request_id"], "pending", message_id)

        logger.info(
            f"[INDEXING] ✅ Уведомление отправлено администратору {admin_id} "
            f"для запроса {request['request_id']} (файл: {Path(request.get('file_path', '')).name})"
        )

        return message_id

    except Exception as e:
        logger.error(
            f"[INDEXING] ❌ Ошибка при отправке уведомления администратору {admin_id}: {e}",
            exc_info=True,
        )
        return None

# Тип для индекса файлов
FileIndex = dict[str, dict[str, Any]]


def _get_file_index_path() -> Path:
    """Возвращает путь к файлу индекса файлов.

    Returns:
        Путь к файлу index.files.pkl в той же директории, что и FAISS индекс.
    """
    return Config.FAISS_PATH.with_suffix(".files.pkl")


@run_in_executor
def _calculate_file_hash(file_path: Path) -> str:
    """Вычисляет SHA256 хеш файла.

    Используется для определения, изменился ли файл с момента последней индексации.

    Args:
        file_path: Путь к файлу.

    Returns:
        SHA256 хеш файла в виде hex-строки.
    """
    logger.debug(f"Вычисление хеша файла: {file_path}")
    sha256_hash = hashlib.sha256()
    
    try:
        with open(file_path, "rb") as f:
            # Читаем файл блоками для экономии памяти
            for byte_block in iter(lambda: f.read(4096), b""):
                sha256_hash.update(byte_block)
        
        file_hash = sha256_hash.hexdigest()
        logger.debug(f"Хеш файла {file_path.name}: {file_hash[:16]}...")
        return file_hash
    except Exception as e:
        logger.error(f"Ошибка при вычислении хеша файла {file_path}: {e}")
        raise ValueError(f"Не удалось вычислить хеш файла: {e}") from e


def _load_file_index() -> FileIndex:
    """Загружает индекс файлов из файла.

    Индекс файлов содержит информацию о всех проиндексированных файлах:
    - file_hash: SHA256 хеш содержимого файла
    - file_size: Размер файла в байтах
    - indexed_at: Timestamp индексации (ISO format)
    - chunks_count: Количество чанков
    - first_chunk_index: Индекс первого чанка в FAISS
    - last_chunk_index: Индекс последнего чанка в FAISS
    - file_type: Тип файла (.txt, .pdf, .epub, .fb2)

    Returns:
        Словарь, где ключ - полный путь к файлу (str), значение - словарь с информацией о файле.
        Если файл индекса не существует, возвращает пустой словарь.
    """
    index_path = _get_file_index_path()
    
    if not index_path.exists():
        logger.debug("Индекс файлов не найден, создаём новый")
        return {}
    
    try:
        with open(index_path, "rb") as f:
            file_index = pickle.load(f)
        logger.info(f"Загружен индекс файлов: {len(file_index)} файлов")
        return file_index
    except Exception as e:
        logger.error(f"Ошибка при загрузке индекса файлов: {e}")
        logger.warning("Создаём новый индекс файлов")
        return {}


def _save_file_index(file_index: FileIndex) -> None:
    """Сохраняет индекс файлов в файл.

    Args:
        file_index: Словарь с информацией о проиндексированных файлах.
    """
    index_path = _get_file_index_path()
    
    try:
        # Создаём директорию, если её нет
        index_path.parent.mkdir(parents=True, exist_ok=True)
        
        with open(index_path, "wb") as f:
            pickle.dump(file_index, f, protocol=4)
        
        logger.info(f"Индекс файлов сохранён: {index_path} ({len(file_index)} файлов)")
    except Exception as e:
        logger.error(f"Ошибка при сохранении индекса файлов: {e}")
        raise ValueError(f"Не удалось сохранить индекс файлов: {e}") from e


async def _should_index_file(
    file_path: Path, file_index: FileIndex, force: bool = False
) -> tuple[bool, str, dict[str, Any] | None]:
    """Проверяет, нужно ли индексировать файл.

    Определяет статус файла:
    - "new": файл новый, не был проиндексирован
    - "changed": файл изменился (хеш не совпадает)
    - "unchanged": файл не изменился (хеш совпадает)
    - "not_found": файл не существует физически

    Args:
        file_path: Путь к файлу для проверки.
        file_index: Индекс файлов (словарь с информацией о проиндексированных файлах).
        force: Если True, принудительно индексировать даже если файл не изменился.

    Returns:
        Кортеж (should_index, reason, existing_file_info):
        - should_index: True если нужно индексировать, False если пропустить
        - reason: Причина ("new", "changed", "unchanged", "not_found")
        - existing_file_info: Информация о существующем файле из индекса или None
    """
    file_path_str = str(file_path.absolute())
    
    # Проверяем, существует ли файл физически
    if not file_path.exists():
        logger.warning(f"Файл не существует: {file_path}")
        return False, "not_found", None
    
    # Получаем информацию о файле из индекса
    existing_file_info = file_index.get(file_path_str)
    
    # Если файла нет в индексе - это новый файл
    if existing_file_info is None:
        logger.info(f"Новый файл для индексации: {file_path.name}")
        return True, "new", None
    
    # Если принудительная переиндексация - индексируем
    if force:
        logger.info(f"Принудительная переиндексация: {file_path.name}")
        return True, "changed", existing_file_info
    
    # Вычисляем текущий хеш файла
    try:
        current_hash = await _calculate_file_hash(file_path)
        stored_hash = existing_file_info.get("file_hash")
        
        # Сравниваем хеши
        if current_hash == stored_hash:
            # Файл не изменился
            logger.debug(f"Файл не изменился, пропускаем: {file_path.name}")
            return False, "unchanged", existing_file_info
        else:
            # Файл изменился
            logger.info(
                f"Файл изменился, требуется переиндексация: {file_path.name} "
                f"(старый хеш: {stored_hash[:16]}..., новый: {current_hash[:16]}...)"
            )
            return True, "changed", existing_file_info
            
    except Exception as e:
        logger.error(f"Ошибка при проверке файла {file_path}: {e}")
        # В случае ошибки лучше попробовать переиндексировать
        return True, "changed", existing_file_info


async def _remove_file_from_index(file_path: Path, file_index: FileIndex) -> None:
    """Удаляет все чанки файла из FAISS индекса.

    Поскольку FAISS не поддерживает удаление отдельных векторов,
    пересоздаёт индекс без чанков удаляемого файла.

    Args:
        file_path: Путь к файлу, чанки которого нужно удалить.
        file_index: Индекс файлов (будет обновлён после удаления).
    """
    import faiss
    import numpy as np

    file_path_str = str(file_path.absolute())
    
    # Проверяем, есть ли файл в индексе
    file_info = file_index.get(file_path_str)
    if file_info is None:
        logger.debug(f"Файл {file_path.name} не найден в индексе, нечего удалять")
        return
    
    logger.info(f"Удаление файла из индекса: {file_path.name}")
    
    index_path = Config.FAISS_PATH
    metadata_path = index_path.with_suffix(".metadata.pkl")
    
    # Проверяем существование индекса
    if not index_path.exists() or not metadata_path.exists():
        logger.warning("Индекс не найден, нечего удалять")
        # Удаляем запись из индекса файлов
        file_index.pop(file_path_str, None)
        return
    
    # Загружаем текущий индекс и метаданные
    try:
        old_index = faiss.read_index(str(index_path))
        with open(metadata_path, "rb") as f:
            all_metadata = pickle.load(f)
    except Exception as e:
        logger.error(f"Ошибка при загрузке индекса для удаления: {e}")
        raise ValueError(f"Не удалось загрузить индекс для удаления: {e}") from e
    
    logger.info(f"Загружен индекс: {old_index.ntotal} векторов, {len(all_metadata)} метаданных")
    
    # Находим индексы чанков, которые нужно удалить
    chunks_to_remove = set()
    for idx, meta in enumerate(all_metadata):
        meta_file_path = meta.get("file_path", "")
        # Сравниваем абсолютные пути
        if str(Path(meta_file_path).absolute()) == file_path_str:
            chunks_to_remove.add(idx)
    
    if not chunks_to_remove:
        logger.warning(f"Чанки файла {file_path.name} не найдены в метаданных")
        # Удаляем запись из индекса файлов
        file_index.pop(file_path_str, None)
        return
    
    logger.info(f"Найдено {len(chunks_to_remove)} чанков для удаления из файла {file_path.name}")
    
    # Фильтруем метаданные и векторы (оставляем только те, что не нужно удалять)
    new_metadata = []
    vectors_to_keep = []
    
    for idx, meta in enumerate(all_metadata):
        if idx not in chunks_to_remove:
            new_metadata.append(meta)
            # Получаем вектор из старого индекса
            vector = old_index.reconstruct(idx)
            vectors_to_keep.append(vector)
    
    # Если не осталось векторов - создаём пустой индекс
    if not vectors_to_keep:
        logger.info("Все векторы удалены, создаём пустой индекс")
        embedding_dim = old_index.d
        new_index = faiss.IndexFlatL2(embedding_dim)
        new_metadata = []
    else:
        # Создаём новый индекс с оставшимися векторами
        embedding_dim = len(vectors_to_keep[0])
        new_index = faiss.IndexFlatL2(embedding_dim)
        vectors_array = np.array(vectors_to_keep, dtype=np.float32)
        new_index.add(vectors_array)
        logger.info(f"Создан новый индекс: {new_index.ntotal} векторов (было {old_index.ntotal})")
    
    # Обновляем индексы чанков в метаданных (они сдвинулись)
    # Группируем метаданные по файлам для обновления first/last_chunk_index
    files_chunks: dict[str, list[int]] = {}
    for new_idx, meta in enumerate(new_metadata):
        meta_file_path = str(Path(meta.get("file_path", "")).absolute())
        if meta_file_path not in files_chunks:
            files_chunks[meta_file_path] = []
        files_chunks[meta_file_path].append(new_idx)
        # Обновляем chunk_index в метаданных
        meta["chunk_index"] = new_idx
    
    # Обновляем first_chunk_index и last_chunk_index в индексе файлов
    for meta_file_path, chunk_indices in files_chunks.items():
        if chunk_indices:
            file_info = file_index.get(meta_file_path)
            if file_info:
                file_info["first_chunk_index"] = min(chunk_indices)
                file_info["last_chunk_index"] = max(chunk_indices)
                file_info["chunks_count"] = len(chunk_indices)
    
    # Удаляем запись о файле из индекса файлов
    file_index.pop(file_path_str, None)
    
    # Сохраняем новый индекс и метаданные
    faiss.write_index(new_index, str(index_path))
    with open(metadata_path, "wb") as f:
        pickle.dump(new_metadata, f, protocol=4)
    
    logger.info(
        f"Файл {file_path.name} удалён из индекса: "
        f"удалено {len(chunks_to_remove)} чанков, осталось {new_index.ntotal} векторов"
    )


async def _delete_file_completely(file_path: Path) -> None:
    """Полностью удаляет файл и все связанные с ним данные.

    Выполняет:
    1. Удаление файла из файловой системы
    2. Удаление чанков из FAISS индекса
    3. Удаление записи из file_index
    4. Удаление запроса из pending_confirmations (если есть)

    Args:
        file_path: Путь к файлу для удаления.

    Raises:
        ValueError: Если произошла ошибка при удалении.
    """
    file_path_str = str(file_path.absolute())
    logger.info(f"Начало полного удаления файла: {file_path.name}")

    # 1. Удаление из FAISS индекса и file_index
    file_index = _load_file_index()
    try:
        await _remove_file_from_index(file_path, file_index)
        logger.info(f"Файл {file_path.name} удалён из индекса")
    except Exception as e:
        logger.warning(
            f"Ошибка при удалении файла {file_path.name} из индекса: {e}. "
            f"Продолжаем удаление файла из файловой системы."
        )

    # 2. Удаление запроса из pending_confirmations (если есть)
    # Ищем запрос по file_path
    all_confirmations = get_all_confirmations()
    for request_id, request in all_confirmations.items():
        request_file_path = request.get("file_path", "")
        if str(Path(request_file_path).absolute()) == file_path_str:
            try:
                delete_confirmation_request(request_id)
                logger.info(
                    f"Запрос на подтверждение {request_id} удалён для файла {file_path.name}"
                )
            except Exception as e:
                logger.warning(
                    f"Ошибка при удалении запроса на подтверждение {request_id}: {e}"
                )
            break

    # 3. Удаление файла из файловой системы
    if file_path.exists():
        try:
            file_path.unlink()
            logger.info(f"Файл {file_path.name} удалён из файловой системы")
        except Exception as e:
            logger.error(f"Ошибка при удалении файла {file_path.name} из файловой системы: {e}")
            raise ValueError(
                f"Не удалось удалить файл {file_path.name} из файловой системы: {e}"
            ) from e
    else:
        logger.warning(f"Файл {file_path.name} не существует в файловой системе")

    logger.info(f"✅ Файл {file_path.name} полностью удалён и все связанные данные очищены")


async def check_and_cleanup_expired_confirmations() -> int:
    """Проверяет истёкшие запросы на подтверждение и удаляет файлы.

    Находит все запросы, которые истекли по таймауту, обновляет их статус
    на "timeout" и полностью удаляет связанные файлы.

    Returns:
        Количество удалённых файлов.
    """
    logger.info("Проверка истёкших запросов на подтверждение...")

    expired_request_ids = get_expired_requests()

    if not expired_request_ids:
        logger.debug("Истёкших запросов не найдено")
        return 0

    logger.info(f"Найдено {len(expired_request_ids)} истёкших запросов")

    deleted_count = 0

    for request_id in expired_request_ids:
        try:
            # Получаем запрос
            request = get_confirmation_request(request_id)
            if not request:
                logger.warning(f"Запрос {request_id} не найден, пропускаем")
                continue

            file_path_str = request.get("file_path", "")
            if not file_path_str:
                logger.warning(f"Запрос {request_id} не содержит file_path, пропускаем")
                # Обновляем статус и удаляем запрос
                update_confirmation_status(request_id, "timeout")
                delete_confirmation_request(request_id)
                continue

            file_path = Path(file_path_str)
            book_title = request.get("book_title", "Неизвестно")

            logger.info(
                f"Обработка истёкшего запроса {request_id} для файла {file_path.name}"
            )

            # Обновляем статус на "timeout"
            update_confirmation_status(request_id, "timeout")

            # Удаляем файл полностью
            try:
                await _delete_file_completely(file_path)
                deleted_count += 1
                logger.info(
                    f"✅ Файл {file_path.name} удалён из-за истечения таймаута подтверждения"
                )
            except Exception as e:
                logger.error(
                    f"Ошибка при удалении файла {file_path.name} для запроса {request_id}: {e}",
                    exc_info=True,
                )
                # Продолжаем обработку других запросов

            # Удаляем запрос из pending_confirmations
            delete_confirmation_request(request_id)

        except Exception as e:
            logger.error(
                f"Ошибка при обработке истёкшего запроса {request_id}: {e}",
                exc_info=True,
            )
            # Продолжаем обработку других запросов

    logger.info(
        f"Проверка истёкших запросов завершена: удалено {deleted_count} файлов"
    )

    return deleted_count


@run_in_executor
def _read_txt_file(file_path: Path) -> str:
    """Читает текстовый файл.

    Args:
        file_path: Путь к файлу.

    Returns:
        Содержимое файла как строка.
    """
    logger.debug(f"Чтение TXT файла {file_path}")
    
    # Сначала проверяем размер файла
    file_size = file_path.stat().st_size
    logger.info(f"Размер файла {file_path.name}: {file_size} байт")
    
    # Пробуем разные кодировки для корректного чтения русских текстов
    encodings = ["utf-8", "utf-8-sig", "cp1251", "windows-1251", "latin-1"]
    for encoding in encodings:
        try:
            # Читаем файл в бинарном режиме и декодируем
            with open(file_path, "rb") as f:
                raw_content = f.read()
            
            # Проверяем наличие null-байтов или других проблемных символов
            if b'\x00' in raw_content:
                logger.warning(f"Файл {file_path.name} содержит null-байты, удаляем их")
                raw_content = raw_content.replace(b'\x00', b'')
            
            # Пробуем декодировать
            # ВАЖНО: Если файл в cp1251, нужно правильно декодировать
            # Python строки хранят текст в Unicode, но нужно убедиться, что декодирование правильное
            if encoding in ["cp1251", "windows-1251"]:
                # Для cp1251: декодируем байты напрямую в Unicode строку
                # Python автоматически конвертирует cp1251 в Unicode при decode
                content = raw_content.decode("cp1251", errors="replace")
                # Проверяем, что декодирование прошло правильно
                # Если текст содержит кракозябры, значит файл не в cp1251
                preview = content[:100]
                # Проверяем наличие кириллицы
                has_cyrillic = any('\u0400' <= c <= '\u04FF' for c in preview)
                if not has_cyrillic and len(preview) > 10:
                    # Если нет кириллицы, но текст длинный, возможно неправильная кодировка
                    logger.warning(f"Файл {file_path.name} декодирован с {encoding}, но не содержит кириллицы. Пробуем другую кодировку.")
                    continue
            else:
                content = raw_content.decode(encoding, errors="replace")
            
            logger.info(f"Файл {file_path.name} успешно прочитан с кодировкой {encoding}, длина: {len(content)} символов")
            
            # Проверяем первые 100 символов на наличие кракозябр
            preview = content[:100]
            if "спекуляция" in preview.lower() or "Спекуляция" in preview:
                logger.info(f"✅ Файл {file_path.name} содержит слово 'спекуляция' в начале")
            
            # Проверяем, что файл прочитан полностью
            if len(content) < 100:
                logger.warning(f"Файл {file_path.name} прочитан, но очень короткий ({len(content)} символов). Возможно, проблема с кодировкой.")
            elif file_size > 0 and len(content) < file_size / 2:
                logger.warning(f"Файл {file_path.name} прочитан, но длина текста ({len(content)} символов) намного меньше размера файла ({file_size} байт). Возможно, файл содержит бинарные данные.")
            
            return content
        except (UnicodeDecodeError, LookupError) as e:
            logger.debug(f"Не удалось прочитать {file_path.name} с кодировкой {encoding}: {e}")
            continue
    
    # Если ничего не помогло, пробуем с игнорированием ошибок
    with open(file_path, "rb") as f:
        raw_content = f.read()
    # Удаляем null-байты
    raw_content = raw_content.replace(b'\x00', b'')
    content = raw_content.decode("utf-8", errors="replace")
    logger.warning(f"Файл {file_path.name} прочитан с игнорированием ошибок, длина: {len(content)} символов")
    return content


@run_in_executor
def _read_pdf_file(file_path: Path) -> str:
    """Читает PDF файл.

    Args:
        file_path: Путь к PDF файлу.

    Returns:
        Извлечённый текст из PDF.

    Raises:
        ValueError: Если PDF содержит больше MAX_PDF_PAGES страниц.
    """
    import PyPDF2

    logger.debug(f"Чтение PDF файла {file_path}")

    try:
        with open(file_path, "rb") as file:
            reader = PyPDF2.PdfReader(file)
            
            num_pages = len(reader.pages)
            
            # Проверка количества страниц
            if num_pages > Config.MAX_PDF_PAGES:
                raise ValueError(
                    f"PDF содержит {num_pages} страниц, "
                    f"максимум разрешено {Config.MAX_PDF_PAGES}"
                )
            
            # Предупреждение для больших PDF (больше 500 страниц)
            if num_pages > 500:
                file_name = Path(file_path).name
                logger.warning(
                    f"⚠️ PDF файл {file_name} содержит {num_pages} страниц "
                    f"(больше рекомендуемых 500). Индексация может занять больше времени."
                )
            
            # Извлекаем текст со всех страниц
            text_parts = []
            for page_num, page in enumerate(reader.pages, 1):
                try:
                    text = page.extract_text()
                    if text.strip():
                        text_parts.append(text)
                except Exception as e:
                    logger.warning(f"Ошибка при извлечении текста со страницы {page_num}: {e}")
                    continue
            
            content = "\n\n".join(text_parts)
            file_name = Path(file_path).name
            logger.info(
                f"Извлечено {len(content)} символов из {num_pages} страниц PDF файла {file_name}"
            )
            return content
            
    except Exception as e:
        logger.error(f"Ошибка при чтении PDF файла {file_path}: {e}")
        raise ValueError(f"Не удалось прочитать PDF файл: {e}") from e


@run_in_executor
def _read_epub_file(file_path: Path) -> str:
    """Читает EPUB файл.

    Args:
        file_path: Путь к EPUB файлу.

    Returns:
        Извлечённый текст из EPUB.
    """
    import ebooklib
    from ebooklib import epub
    from bs4 import BeautifulSoup

    logger.debug(f"Чтение EPUB файла {file_path}")

    try:
        book = epub.read_epub(str(file_path))
        text_parts = []
        
        for item in book.get_items():
            if item.get_type() == ebooklib.ITEM_DOCUMENT:
                # Извлекаем текст из HTML
                soup = BeautifulSoup(item.get_content(), "html.parser")
                text = soup.get_text(separator="\n", strip=True)
                if text.strip():
                    text_parts.append(text)
        
        content = "\n\n".join(text_parts)
        logger.debug(f"Извлечено {len(content)} символов из EPUB")
        return content
        
    except Exception as e:
        logger.error(f"Ошибка при чтении EPUB файла {file_path}: {e}")
        raise ValueError(f"Не удалось прочитать EPUB файл: {e}") from e


@run_in_executor
def _read_fb2_file(file_path: Path) -> str:
    """Читает FB2 файл.

    Использует BeautifulSoup для парсинга XML структуры FB2,
    аналогично обработке EPUB файлов.

    Args:
        file_path: Путь к FB2 файлу.

    Returns:
        Извлечённый текст из FB2.
    """
    from bs4 import BeautifulSoup

    logger.debug(f"Чтение FB2 файла {file_path}")

    try:
        # FB2 - это XML формат, читаем как XML
        with open(file_path, "rb") as f:
            raw_content = f.read()
        
        # Парсим XML с помощью BeautifulSoup (как для EPUB)
        soup = BeautifulSoup(raw_content, "xml")
        
        # Извлекаем текст из всех элементов body
        text_parts = []
        bodies = soup.find_all("body")
        
        for body in bodies:
            sections = body.find_all("section", recursive=True)
            if not sections:
                # Если нет секций, извлекаем текст напрямую из body
                body_text = body.get_text(separator="\n", strip=True)
                if body_text:
                    text_parts.append(body_text)
            else:
                for section in sections:
                    # Извлекаем весь текст из секции, включая вложенные элементы
                    section_text = section.get_text(separator="\n", strip=True)
                    if section_text:
                        text_parts.append(section_text)
        
        content = "\n\n".join(text_parts)
        logger.debug(f"Извлечено {len(content)} символов из FB2")
        
        if not content.strip():
            logger.warning(f"FB2 файл {file_path.name} не содержит текста")
        
        return content
        
    except Exception as e:
        logger.error(f"Ошибка при чтении FB2 файла {file_path}: {e}")
        raise ValueError(f"Не удалось прочитать FB2 файл: {e}") from e


def _extract_metadata(file_path: Path, content: str) -> dict[str, Any]:
    """Извлекает метаданные из файла (название, автор, категории).

    Args:
        file_path: Путь к файлу.
        content: Содержимое файла.

    Returns:
        Словарь с метаданными: title, author, file_path, topics.
    """
    logger.debug(f"Извлечение метаданных из {file_path}")

    # Парсим категории из имени файла
    book_title, categories = parse_categories_from_filename(file_path)

    # Простое извлечение метаданных из имени файла
    # В будущем можно добавить парсинг метаданных из PDF/EPUB/FB2
    return {
        "title": book_title,  # Название книги без категорий
        "author": "Unknown",  # Автор по умолчанию
        "file_path": str(file_path),
        "file_type": file_path.suffix.lower(),
        "topics": categories,  # Категории из имени файла (могут быть пустыми)
    }


def _chunk_text(
    text: str, chunk_size: int | None = None, chunk_overlap: int | None = None
) -> list[str]:
    """Разбивает текст на чанки.

    Args:
        text: Текст для разбиения.
        chunk_size: Размер чанка в символах. По умолчанию из Config.
        chunk_overlap: Перекрытие между чанками. По умолчанию из Config.

    Returns:
        Список чанков текста.
    """
    if chunk_size is None:
        chunk_size = Config.CHUNK_SIZE
    if chunk_overlap is None:
        chunk_overlap = Config.CHUNK_OVERLAP

    logger.debug(f"Разбиение текста на чанки: размер={chunk_size}, перекрытие={chunk_overlap}")

    chunks = []
    start = 0
    text_length = len(text)

    while start < text_length:
        end = start + chunk_size
        chunk = text[start:end]

        # Игнорируем чанки меньше MIN_CHUNK_SIZE
        if len(chunk.strip()) >= Config.MIN_CHUNK_SIZE:
            chunks.append(chunk.strip())

        # Переходим к следующему чанку с учётом перекрытия
        start = end - chunk_overlap
        if start >= text_length:
            break

    logger.info(f"Создано {len(chunks)} чанков из текста длиной {text_length} символов")
    return chunks


async def _create_embeddings_batch(texts: list[str]) -> list[list[float]]:
    """Создаёт эмбеддинги для батча текстов.

    Args:
        texts: Список текстов для создания эмбеддингов.

    Returns:
        Список эмбеддингов (каждый эмбеддинг - список float).

    Raises:
        ValueError: Если не удалось создать эмбеддинги.
    """
    if not Config.OPENAI_API_KEY:
        raise ValueError("OPENAI_API_KEY не установлен")

    from openai import AsyncOpenAI

    client = AsyncOpenAI(api_key=Config.OPENAI_API_KEY)
    
    logger.debug(f"Создание эмбеддингов для {len(texts)} текстов через OpenAI API")
    
    try:
        response = await client.embeddings.create(
            model=Config.EMBEDDING_MODEL,
            input=texts
        )
        embeddings = [item.embedding for item in response.data]
        logger.debug(f"Успешно создано {len(embeddings)} эмбеддингов")
        return embeddings
    except Exception as e:
        logger.error(f"Ошибка при создании эмбеддингов: {e}")
        raise ValueError(f"Не удалось создать эмбеддинги: {e}") from e


async def _save_to_faiss(
    embeddings: list[list[float]],
    chunks: list[str],
    metadata: list[dict[str, Any]],
    file_path: Path,
    file_hash: str,
    file_index: FileIndex | None = None,
) -> None:
    """Сохраняет эмбеддинги и метаданные в FAISS индекс.

    Также обновляет индекс файлов с информацией о проиндексированном файле.

    Args:
        embeddings: Список эмбеддингов.
        chunks: Список текстовых чанков.
        metadata: Список метаданных для каждого чанка.
        file_path: Путь к проиндексированному файлу.
        file_hash: SHA256 хеш файла.
        file_index: Индекс файлов для обновления. Если None, загружается автоматически.
    """
    import faiss
    import numpy as np
    import pickle

    if not embeddings:
        logger.warning("Нет эмбеддингов для сохранения")
        return

    embedding_dim = len(embeddings[0])
    logger.debug(f"Сохранение {len(embeddings)} эмбеддингов в FAISS индекс (размерность: {embedding_dim})")

    # Преобразуем в numpy array
    embeddings_array = np.array(embeddings, dtype=np.float32)

    # Загружаем существующий индекс или создаём новый
    index_path = Config.FAISS_PATH
    metadata_path = index_path.with_suffix(".metadata.pkl")

    if index_path.exists():
        # Загружаем существующий индекс
        index = faiss.read_index(str(index_path))
        logger.info(f"Загружен существующий индекс с {index.ntotal} векторами")
        
        # Загружаем метаданные
        if metadata_path.exists():
            with open(metadata_path, "rb") as f:
                all_metadata = pickle.load(f)
        else:
            all_metadata = []
    else:
        # Создаём новый индекс
        index = faiss.IndexFlatL2(embedding_dim)
        all_metadata = []
        logger.info(f"Создан новый FAISS индекс с размерностью {embedding_dim}")

    # Запоминаем индекс первого чанка (до добавления)
    first_chunk_index = len(all_metadata)

    # Добавляем новые эмбеддинги
    index.add(embeddings_array)
    all_metadata.extend(metadata)

    # Вычисляем индекс последнего чанка (после добавления)
    last_chunk_index = len(all_metadata) - 1
    chunks_count = len(embeddings)

    # Сохраняем индекс и метаданные
    faiss.write_index(index, str(index_path))
    # Используем протокол pickle 4 для лучшей поддержки больших объектов и UTF-8
    with open(metadata_path, "wb") as f:
        pickle.dump(all_metadata, f, protocol=4)

    logger.info(f"Индекс сохранён: {index_path} ({index.ntotal} векторов, {len(all_metadata)} метаданных)")

    # Обновляем индекс файлов
    if file_index is None:
        file_index = _load_file_index()
    
    file_path_str = str(file_path.absolute())
    file_size = file_path.stat().st_size
    file_type = file_path.suffix.lower()
    
    # Сохраняем информацию о файле в индекс файлов
    file_index[file_path_str] = {
        "file_hash": file_hash,
        "file_size": file_size,
        "indexed_at": datetime.now().isoformat(),
        "chunks_count": chunks_count,
        "first_chunk_index": first_chunk_index,
        "last_chunk_index": last_chunk_index,
        "file_type": file_type,
    }
    
    # Сохраняем обновлённый индекс файлов
    _save_file_index(file_index)
    
    logger.info(
        f"Файл {file_path.name} добавлен в индекс файлов: "
        f"{chunks_count} чанков (индексы {first_chunk_index}-{last_chunk_index})"
    )


async def _determine_categories(
    file_path: Path,
    book_title: str,
    categories_from_filename: list[str],
    content_preview: str | None = None,
) -> list[str] | None:
    """Определяет категории для книги.

    Логика:
    1. Если категории найдены в имени файла - используем их
    2. Если категорий нет - вызываем LLM для определения (с использованием содержимого, если доступно)
    3. Если LLM определил - создаём запрос на подтверждение и возвращаем None
    4. Если LLM не смог - создаём запрос и возвращаем None

    Args:
        file_path: Путь к файлу.
        book_title: Название книги.
        categories_from_filename: Категории из имени файла.
        content_preview: Первые символы содержимого книги для анализа LLM (опционально).

    Returns:
        Список категорий или None, если требуется подтверждение администратора.
    """
    # Если категории найдены в имени файла - используем их
    if categories_from_filename:
        logger.info(
            f"[INDEXING] ✅ Категории найдены в имени файла {file_path.name}: {categories_from_filename}"
        )
        return categories_from_filename

    # Категории не найдены - вызываем LLM
    logger.info(
        f"[INDEXING] Категории не найдены в имени файла {file_path.name}, "
        f"определяем через LLM..."
    )
    if content_preview:
        logger.debug(
            f"Используется превью содержимого для классификации "
            f"({len(content_preview)} символов)"
        )

    try:
        llm_result = await classify_book_category(book_title, content_preview)
        llm_categories = llm_result.get("topics", [])
        llm_confidence = llm_result.get("confidence", 0.0)
        llm_reasoning = llm_result.get("reasoning", "")

        if llm_categories:
            logger.info(
                f"[INDEXING] LLM определил категории для '{book_title}': {llm_categories} "
                f"(confidence: {llm_confidence:.2f})"
            )

            # Создаём запрос на подтверждение
            request_id = create_confirmation_request(
                file_path=file_path,
                book_title=book_title,
                categories_from_filename=[],
                categories_llm_recommendation=llm_categories,
                llm_confidence=llm_confidence,
                llm_reasoning=llm_reasoning,
            )

            logger.info(
                f"[INDEXING] Создан запрос на подтверждение категорий: {request_id} "
                f"для файла {file_path.name}"
            )

            # Отправляем уведомление администратору
            request_data = get_confirmation_request(request_id)
            if request_data:
                await _send_notification_to_admin_direct(request_data)
            else:
                logger.warning(
                    f"[INDEXING] ⚠️ Не удалось получить данные запроса {request_id} "
                    f"для отправки уведомления"
                )

            # Возвращаем None - файл не будет проиндексирован до подтверждения
            return None
        else:
            logger.warning(
                f"[INDEXING] LLM не смог определить категории для '{book_title}'"
            )

            # Создаём запрос на подтверждение без рекомендации
            request_id = create_confirmation_request(
                file_path=file_path,
                book_title=book_title,
                categories_from_filename=[],
                categories_llm_recommendation=[],
                llm_confidence=0.0,
                llm_reasoning="LLM не смог определить категории",
            )

            logger.info(
                f"[INDEXING] Создан запрос на подтверждение категорий (без рекомендации): {request_id} "
                f"для файла {file_path.name}"
            )

            # Отправляем уведомление администратору
            request_data = get_confirmation_request(request_id)
            if request_data:
                await _send_notification_to_admin_direct(request_data)
            else:
                logger.warning(
                    f"[INDEXING] ⚠️ Не удалось получить данные запроса {request_id} "
                    f"для отправки уведомления"
                )

            return None

    except Exception as e:
        logger.error(
            f"[INDEXING] ❌ Ошибка при определении категорий через LLM для '{book_title}': {e}",
            exc_info=True,
        )

        # Создаём запрос на подтверждение с ошибкой
        request_id = create_confirmation_request(
            file_path=file_path,
            book_title=book_title,
            categories_from_filename=[],
            categories_llm_recommendation=[],
            llm_confidence=0.0,
            llm_reasoning=f"Ошибка при определении категорий: {str(e)}",
        )

        logger.info(
            f"[INDEXING] Создан запрос на подтверждение категорий (с ошибкой): {request_id} "
            f"для файла {file_path.name}"
        )

        # Отправляем уведомление администратору
        request_data = get_confirmation_request(request_id)
        if request_data:
            await _send_notification_to_admin_direct(request_data)
        else:
            logger.warning(
                f"[INDEXING] ⚠️ Не удалось получить данные запроса {request_id} "
                f"для отправки уведомления"
            )

        return None


async def _process_file(
    file_path: Path, file_index: FileIndex | None = None
) -> None:
    """Обрабатывает один файл: читает, разбивает на чанки, создаёт эмбеддинги, сохраняет.

    Args:
        file_path: Путь к файлу для обработки.
        file_index: Индекс файлов для обновления. Если None, загружается автоматически.

    Raises:
        ValueError: Если файл слишком большой или имеет неподдерживаемый формат.
    """
    logger.info(f"[INDEXING] ===== Начало обработки файла: {file_path.name} =====")

    # Проверка размера файла
    file_size_mb = file_path.stat().st_size / (1024 * 1024)
    if file_size_mb > Config.MAX_FILE_SIZE_MB:
        raise ValueError(
            f"Файл {file_path} слишком большой: {file_size_mb:.2f} MB "
            f"(максимум {Config.MAX_FILE_SIZE_MB} MB)"
        )

    # Проверка формата
    if file_path.suffix.lower() not in SUPPORTED_EXTENSIONS:
        raise ValueError(f"Неподдерживаемый формат файла: {file_path.suffix}")

    # Вычисляем хеш файла для сохранения в индекс файлов
    file_hash = await _calculate_file_hash(file_path)

    # Чтение файла в зависимости от формата
    extension = file_path.suffix.lower()
    if extension == ".txt":
        content = await _read_txt_file(file_path)  # type: ignore[misc]
    elif extension == ".pdf":
        content = await _read_pdf_file(file_path)  # type: ignore[misc]
    elif extension == ".epub":
        content = await _read_epub_file(file_path)  # type: ignore[misc]
    elif extension == ".fb2":
        content = await _read_fb2_file(file_path)  # type: ignore[misc]
    else:
        raise ValueError(f"Неподдерживаемый формат: {extension}")

    # Извлечение метаданных
    logger.info(f"[INDEXING] Извлечение метаданных из файла: {file_path.name}")
    metadata_base = _extract_metadata(file_path, content)
    categories_from_filename = metadata_base.get("topics", [])
    book_title = metadata_base.get("title", "")
    
    logger.info(
        f"[INDEXING] Метаданные извлечены: "
        f"название='{book_title}', "
        f"категории из имени файла={categories_from_filename}, "
        f"длина содержимого={len(content)} символов"
    )

    # Подготавливаем превью содержимого для классификации (первые 2000 символов)
    content_preview = content[:2000].strip() if content else None
    if content_preview:
        logger.debug(
            f"[INDEXING] Превью содержимого подготовлено: {len(content_preview)} символов"
        )

    # Определение категорий
    logger.info(f"[INDEXING] Определение категорий для файла: {file_path.name}")
    final_categories = await _determine_categories(
        file_path,
        book_title,
        categories_from_filename,
        content_preview,
    )

    # Если категории не определены (нужно подтверждение), не индексируем файл
    if final_categories is None:
        logger.info(
            f"[INDEXING] ⏸️ Файл {file_path.name} не будет проиндексирован: "
            f"требуется подтверждение категорий администратором"
        )
        logger.info(f"[INDEXING] ===== Обработка файла {file_path.name} приостановлена =====\n")
        return

    # Продолжаем индексацию с определенными категориями
    await _continue_indexing_with_categories(
        file_path, file_index, metadata_base, content, file_hash, final_categories
    )


async def _continue_indexing_with_categories(
    file_path: Path,
    file_index: FileIndex | None,
    metadata_base: dict[str, Any],
    content: str,
    file_hash: str,
    categories: list[str],
) -> None:
    """Продолжает индексацию файла с уже определенными категориями.

    Используется после подтверждения категорий администратором.

    Args:
        file_path: Путь к файлу.
        file_index: Индекс файлов для обновления.
        metadata_base: Базовые метаданные файла.
        content: Содержимое файла.
        file_hash: Хеш файла.
        categories: Список категорий для файла.
    """
    logger.info(
        f"[INDEXING] Продолжение индексации файла {file_path.name} с категориями: {categories}"
    )

    # Обновляем категории в метаданных
    metadata_base["topics"] = categories
    logger.info(
        f"[INDEXING] ✅ Категории для файла {file_path.name} определены: {categories}"
    )
    
    # Проверяем, что категории действительно сохранены
    if metadata_base.get("topics") != categories:
        logger.error(
            f"[INDEXING] ❌ ОШИБКА: Категории не сохранены в метаданные! "
            f"Ожидалось: {categories}, получено: {metadata_base.get('topics')}"
        )
    else:
        logger.debug(
            f"[INDEXING] ✅ Проверка: категории корректно сохранены в метаданные: {metadata_base.get('topics')}"
        )

    # Разбиение на чанки
    logger.info(
        f"[INDEXING] Разбиение файла {file_path.name} на чанки "
        f"(длина текста: {len(content)} символов)"
    )
    chunks = _chunk_text(content)
    logger.info(
        f"[INDEXING] ✅ Создано {len(chunks)} чанков из файла {file_path.name}"
    )

    if not chunks:
        logger.warning(
            f"Файл {file_path} не содержит валидных чанков (все меньше {Config.MIN_CHUNK_SIZE} символов)"
        )
        return

    # Создание эмбеддингов батчами
    logger.info(
        f"[INDEXING] Создание эмбеддингов для {len(chunks)} чанков "
        f"(размер батча: {Config.EMBEDDING_BATCH_SIZE})"
    )
    all_embeddings = []
    batch_size = Config.EMBEDDING_BATCH_SIZE
    total_batches = (len(chunks) + batch_size - 1) // batch_size

    for i in range(0, len(chunks), batch_size):
        batch_num = (i // batch_size) + 1
        batch = chunks[i : i + batch_size]
        logger.debug(
            f"[INDEXING] Обработка батча {batch_num}/{total_batches} "
            f"({len(batch)} чанков)"
        )
        batch_embeddings = await _create_embeddings_batch(batch)
        all_embeddings.extend(batch_embeddings)
        logger.debug(
            f"[INDEXING] Батч {batch_num}/{total_batches} обработан: "
            f"создано {len(batch_embeddings)} эмбеддингов"
        )
    
    logger.info(
        f"[INDEXING] ✅ Создано {len(all_embeddings)} эмбеддингов для файла {file_path.name}"
    )

    # Подготовка метаданных для каждого чанка
    logger.info(
        f"[INDEXING] Подготовка метаданных для {len(chunks)} чанков"
    )
    chunks_metadata = []
    categories_check_failed = 0
    
    for idx, chunk in enumerate(chunks):
        chunk_meta = metadata_base.copy()
        chunk_meta["chunk_index"] = idx
        
        # Убеждаемся, что текст в UTF-8 перед сохранением
        # chunk уже должен быть строкой после _read_txt_file, но на всякий случай проверяем
        if isinstance(chunk, bytes):
            # Если это bytes, пробуем декодировать
            try:
                chunk = chunk.decode("utf-8")
            except UnicodeDecodeError:
                try:
                    chunk = chunk.decode("cp1251")
                except UnicodeDecodeError:
                    chunk = chunk.decode("utf-8", errors="replace")
        elif not isinstance(chunk, str):
            chunk = str(chunk)
        
        # Просто сохраняем строку как есть - Python и pickle должны правильно обработать UTF-8
        # Главное - убедиться, что это действительно строка, а не bytes
        chunk_meta["chunk_text"] = chunk
        # Добавляем source для удобства (название файла)
        chunk_meta["source"] = file_path.name
        
        # КРИТИЧЕСКАЯ ПРОВЕРКА: убеждаемся, что категории сохранены в метаданные чанка
        if chunk_meta.get("topics") != categories:
            categories_check_failed += 1
            logger.error(
                f"[INDEXING] ❌ ОШИБКА: Чанк {idx} не содержит правильные категории! "
                f"Ожидалось: {categories}, получено: {chunk_meta.get('topics')}"
            )
            # Исправляем категории
            chunk_meta["topics"] = categories
            logger.warning(
                f"[INDEXING] ⚠️ Категории исправлены для чанка {idx}"
            )
        
        chunks_metadata.append(chunk_meta)
        
        # Проверяем первые 100 символов на наличие кракозябр (только для отладки)
        preview = chunk[:100]
        # Проверяем на наличие нечитаемых символов (не буквы, не цифры, не пунктуация, не пробелы, не кириллица)
        unreadable_count = sum(1 for c in preview if ord(c) > 127 and not c.isprintable() and c not in "\n\r\t" and c not in "абвгдеёжзийклмнопрстуфхцчшщъыьэюяАБВГДЕЁЖЗИЙКЛМНОПРСТУФХЦЧШЩЪЫЬЭЮЯ")
        if unreadable_count > 10:  # Если больше 10 нечитаемых символов
            logger.warning(
                f"[INDEXING] ⚠️ Чанк {idx} может содержать проблемы с кодировкой: {preview[:50]}..."
            )
    
    if categories_check_failed > 0:
        logger.error(
            f"[INDEXING] ❌ КРИТИЧЕСКАЯ ОШИБКА: {categories_check_failed} чанков "
            f"не содержали правильные категории (исправлено)"
        )
    else:
        logger.info(
            f"[INDEXING] ✅ Проверка категорий: все {len(chunks_metadata)} чанков "
            f"содержат правильные категории: {categories}"
        )

    # Загружаем индекс файлов, если не передан
    if file_index is None:
        file_index = _load_file_index()

    # Сохранение в FAISS с обновлением индекса файлов
    await _save_to_faiss(
        all_embeddings, chunks, chunks_metadata, file_path, file_hash, file_index
    )

    logger.info(
        f"[INDEXING] ✅ Файл {file_path.name} успешно обработан: "
        f"{len(chunks)} чанков, категории: {categories}"
    )
    logger.info(f"[INDEXING] ===== Обработка файла {file_path.name} завершена =====\n")


async def continue_indexing_after_confirmation(request_id: str) -> bool:
    """Продолжает индексацию файла после подтверждения категорий администратором.

    Args:
        request_id: ID запроса на подтверждение.

    Returns:
        True если индексация успешно продолжена, False в случае ошибки.
    """
    from src.confirmation_manager import get_confirmation_request

    logger.info(f"[INDEXING] Продолжение индексации после подтверждения для запроса {request_id}")

    # Получаем запрос на подтверждение
    request = get_confirmation_request(request_id)
    if not request:
        logger.error(f"[INDEXING] ❌ Запрос на подтверждение не найден: {request_id}")
        return False

    # Проверяем, что запрос подтвержден
    if request.get("status") != "approved":
        logger.warning(
            f"[INDEXING] ⚠️ Запрос {request_id} не подтвержден (статус: {request.get('status')})"
        )
        return False

    file_path = Path(request.get("file_path", ""))
    if not file_path.exists():
        logger.error(f"[INDEXING] ❌ Файл не найден: {file_path}")
        return False

    # Получаем категории из запроса
    categories = request.get("categories_llm_recommendation", [])
    if not categories:
        categories = request.get("categories_from_filename", [])

    if not categories:
        logger.error(f"[INDEXING] ❌ Категории не найдены в запросе {request_id}")
        return False

    try:
        # Загружаем индекс файлов
        file_index = _load_file_index()

        # Читаем файл
        extension = file_path.suffix.lower()
        if extension == ".txt":
            content = await _read_txt_file(file_path)  # type: ignore[misc]
        elif extension == ".pdf":
            content = await _read_pdf_file(file_path)  # type: ignore[misc]
        elif extension == ".epub":
            content = await _read_epub_file(file_path)  # type: ignore[misc]
        elif extension == ".fb2":
            content = await _read_fb2_file(file_path)  # type: ignore[misc]
        else:
            logger.error(f"[INDEXING] ❌ Неподдерживаемый формат: {extension}")
            return False

        # Извлекаем метаданные
        metadata_base = _extract_metadata(file_path, content)
        
        # Вычисляем хеш файла
        file_hash = await _calculate_file_hash(file_path)

        # Продолжаем индексацию с категориями
        await _continue_indexing_with_categories(
            file_path, file_index, metadata_base, content, file_hash, categories
        )

        logger.info(f"[INDEXING] ✅ Индексация успешно продолжена для файла {file_path.name}")
        return True

    except Exception as e:
        logger.error(
            f"[INDEXING] ❌ Ошибка при продолжении индексации для запроса {request_id}: {e}",
            exc_info=True
        )
        return False


async def ingest_books(folder_path: str, force: bool = False) -> None:
    """Основная функция индексации книг из папки.

    Обрабатывает все поддерживаемые файлы в указанной папке:
    - Проверяет, какие файлы нужно индексировать (новые/изменённые)
    - Удаляет старые чанки изменённых файлов
    - Индексирует только новые/изменённые файлы
    - Удаляет из индекса файлы, которые были удалены из папки

    Args:
        folder_path: Путь к папке с книгами.
        force: Если True, принудительно переиндексировать все файлы, даже если они не изменились.

    Raises:
        FileNotFoundError: Если папка не существует.
        ValueError: Если в папке нет поддерживаемых файлов.
    """
    folder = Path(folder_path)

    if not folder.exists():
        raise FileNotFoundError(f"Папка не найдена: {folder_path}")

    if not folder.is_dir():
        raise ValueError(f"Указанный путь не является папкой: {folder_path}")

    logger.info(f"[INDEXING] ===== НАЧАЛО ИНДЕКСАЦИИ КНИГ =====")
    logger.info(f"[INDEXING] Папка: {folder_path}")
    if force:
        logger.info("[INDEXING] ⚠️ Режим принудительной переиндексации: все файлы будут переиндексированы")

    # Загружаем индекс файлов
    file_index = _load_file_index()
    if file_index:
        logger.info(f"[INDEXING] Загружен индекс файлов: {len(file_index)} файлов")
    else:
        logger.info("[INDEXING] Индекс файлов пуст, создаём новый")

    # Поиск всех поддерживаемых файлов в папке
    files_in_folder: list[Path] = []
    for ext in SUPPORTED_EXTENSIONS:
        files_in_folder.extend(folder.glob(f"*{ext}"))
        files_in_folder.extend(folder.glob(f"*{ext.upper()}"))
    
    # Убираем дубликаты (если файл найден и с .txt и с .TXT)
    files_in_folder = list(dict.fromkeys(files_in_folder))  # Сохраняет порядок

    if not files_in_folder and not file_index:
        logger.warning(f"[INDEXING] ⚠️ В папке {folder_path} не найдено поддерживаемых файлов и индекс пуст")
        return

    logger.info(f"[INDEXING] Найдено {len(files_in_folder)} файлов в папке")

    # Проверяем каждый файл и определяем, что нужно сделать
    files_to_index: list[Path] = []  # Файлы для индексации
    files_to_remove: list[Path] = []  # Файлы, которые изменились (нужно удалить старые чанки)
    files_skipped = 0  # Файлы, которые не изменились

    for file_path in files_in_folder:
        should_index, reason, existing_info = await _should_index_file(file_path, file_index, force)
        
        if should_index:
            if reason == "changed" and existing_info:
                # Файл изменился - нужно удалить старые чанки перед индексацией
                files_to_remove.append(file_path)
            files_to_index.append(file_path)
            logger.info(f"[INDEXING] Новый файл для индексации: {file_path.name}")
            logger.info(f"[INDEXING] Файл {file_path.name}: {reason} → будет проиндексирован")
        else:
            files_skipped += 1
            logger.debug(f"[INDEXING] Файл {file_path.name}: {reason} → пропущен")

    # Проверяем удалённые файлы (есть в индексе, но нет в папке)
    folder_abs = folder.absolute()
    files_in_folder_abs = {str(f.absolute()) for f in files_in_folder}
    files_to_delete_from_index: list[str] = []
    
    for indexed_file_path_str in file_index.keys():
        indexed_file_path = Path(indexed_file_path_str)
        # Проверяем, находится ли файл в той же папке
        try:
            if indexed_file_path.parent.absolute() == folder_abs:
                if indexed_file_path_str not in files_in_folder_abs:
                    # Файл был в индексе, но его нет в папке
                    files_to_delete_from_index.append(indexed_file_path_str)
        except Exception:
            # Если путь невалидный, пропускаем
            continue

    # Удаляем файлы из индекса
    if files_to_delete_from_index:
        logger.info(f"[INDEXING] Удаление {len(files_to_delete_from_index)} файлов из индекса (файлы удалены из папки)")
    for file_path_str in files_to_delete_from_index:
        file_path = Path(file_path_str)
        logger.info(f"[INDEXING] Файл {file_path.name} удалён из папки, удаляем из индекса")
        try:
            await _remove_file_from_index(file_path, file_index)
        except Exception as e:
            logger.error(f"[INDEXING] ❌ Ошибка при удалении файла {file_path.name} из индекса: {e}")

    # Удаляем старые чанки изменённых файлов
    if files_to_remove:
        logger.info(f"[INDEXING] Удаление старых чанков для {len(files_to_remove)} изменённых файлов")
    for file_path in files_to_remove:
        logger.info(f"[INDEXING] Удаление старых чанков изменённого файла: {file_path.name}")
        try:
            await _remove_file_from_index(file_path, file_index)
        except Exception as e:
            logger.error(f"[INDEXING] ❌ Ошибка при удалении старых чанков файла {file_path.name}: {e}")

    # Индексируем новые/изменённые файлы
    processed = 0
    errors = 0
    pending_confirmation = 0

    if files_to_index:
        logger.info(f"[INDEXING] Начинаем индексацию {len(files_to_index)} файлов\n")
        for file_path in files_to_index:
            try:
                # Проверяем, был ли файл проиндексирован или требует подтверждения
                before_confirmation_count = len(get_pending_confirmations())
                await _process_file(file_path, file_index)
                after_confirmation_count = len(get_pending_confirmations())
                
                # Если количество запросов на подтверждение увеличилось, файл требует подтверждения
                if after_confirmation_count > before_confirmation_count:
                    pending_confirmation += 1
                else:
                    processed += 1
            except Exception as e:
                errors += 1
                logger.error(
                    f"[INDEXING] ❌ Ошибка при обработке файла {file_path}: {e}",
                    exc_info=True
                )
    else:
        logger.info("[INDEXING] Нет файлов для индексации")

    # Получаем финальное количество запросов на подтверждение
    final_pending = len(get_pending_confirmations())

    # Итоговая статистика
    logger.info(f"[INDEXING] ===== ИТОГОВАЯ СТАТИСТИКА ИНДЕКСАЦИИ =====")
    logger.info(f"[INDEXING] Всего файлов в папке: {len(files_in_folder)}")
    logger.info(f"[INDEXING] ✅ Успешно проиндексировано: {processed} файлов")
    logger.info(f"[INDEXING] ⏸️ Требует подтверждения категорий: {pending_confirmation} файлов")
    logger.info(f"[INDEXING] ⏭️ Пропущено (не изменились): {files_skipped} файлов")
    logger.info(f"[INDEXING] 🗑️ Удалено из индекса: {len(files_to_delete_from_index)} файлов")
    logger.info(f"[INDEXING] ❌ Ошибок: {errors} файлов")
    logger.info(f"[INDEXING] 📋 Всего ожидает подтверждения: {final_pending} файлов")
    
    if final_pending > 0:
        logger.info(
            f"[INDEXING] ⚠️ ВНИМАНИЕ: {final_pending} файлов ожидают подтверждения категорий. "
            f"Используйте команду /pending в боте для просмотра."
        )
    
    logger.info(f"[INDEXING] ===== ИНДЕКСАЦИЯ ЗАВЕРШЕНА =====\n")
