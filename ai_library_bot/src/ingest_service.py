"""Сервис индексации книг для ai_library_bot.

Обрабатывает файлы книг (TXT, PDF, EPUB, FB2), разбивает на чанки,
создаёт эмбеддинги и сохраняет в FAISS индекс.
"""

from pathlib import Path
from typing import Any

from src.config import Config
from src.utils import run_in_executor, setup_logger

logger = setup_logger(__name__)

# Поддерживаемые форматы файлов
SUPPORTED_EXTENSIONS = {".txt", ".pdf", ".epub", ".fb2"}


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
            
            # Проверка количества страниц
            if len(reader.pages) > Config.MAX_PDF_PAGES:
                raise ValueError(
                    f"PDF содержит {len(reader.pages)} страниц, "
                    f"максимум разрешено {Config.MAX_PDF_PAGES}"
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
            logger.debug(f"Извлечено {len(content)} символов из {len(reader.pages)} страниц")
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
    """Извлекает метаданные из файла (название, автор).

    Args:
        file_path: Путь к файлу.
        content: Содержимое файла.

    Returns:
        Словарь с метаданными: title, author, file_path.
    """
    logger.debug(f"Извлечение метаданных из {file_path}")

    # Простое извлечение метаданных из имени файла
    # В будущем можно добавить парсинг метаданных из PDF/EPUB/FB2
    return {
        "title": file_path.stem,  # Имя файла без расширения
        "author": "Unknown",  # Автор по умолчанию
        "file_path": str(file_path),
        "file_type": file_path.suffix.lower(),
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
    embeddings: list[list[float]], chunks: list[str], metadata: list[dict[str, Any]]
) -> None:
    """Сохраняет эмбеддинги и метаданные в FAISS индекс.

    Args:
        embeddings: Список эмбеддингов.
        chunks: Список текстовых чанков.
        metadata: Список метаданных для каждого чанка.
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

    # Добавляем новые эмбеддинги
    index.add(embeddings_array)
    all_metadata.extend(metadata)

    # Сохраняем индекс и метаданные
    faiss.write_index(index, str(index_path))
    # Используем протокол pickle 4 для лучшей поддержки больших объектов и UTF-8
    with open(metadata_path, "wb") as f:
        pickle.dump(all_metadata, f, protocol=4)

    logger.info(f"Индекс сохранён: {index_path} ({index.ntotal} векторов, {len(all_metadata)} метаданных)")


async def _process_file(file_path: Path) -> None:
    """Обрабатывает один файл: читает, разбивает на чанки, создаёт эмбеддинги, сохраняет.

    Args:
        file_path: Путь к файлу для обработки.

    Raises:
        ValueError: Если файл слишком большой или имеет неподдерживаемый формат.
    """
    logger.info(f"Обработка файла: {file_path}")

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
    metadata_base = _extract_metadata(file_path, content)

    # Разбиение на чанки
    logger.info(f"Разбиение файла {file_path.name} на чанки (длина текста: {len(content)} символов)")
    chunks = _chunk_text(content)
    logger.info(f"Создано {len(chunks)} чанков из файла {file_path.name}")

    if not chunks:
        logger.warning(
            f"Файл {file_path} не содержит валидных чанков (все меньше {Config.MIN_CHUNK_SIZE} символов)"
        )
        return

    # Создание эмбеддингов батчами
    all_embeddings = []
    batch_size = Config.EMBEDDING_BATCH_SIZE

    for i in range(0, len(chunks), batch_size):
        batch = chunks[i : i + batch_size]
        batch_embeddings = await _create_embeddings_batch(batch)
        all_embeddings.extend(batch_embeddings)

    # Подготовка метаданных для каждого чанка
    chunks_metadata = []
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
        chunks_metadata.append(chunk_meta)
        
        # Проверяем первые 100 символов на наличие кракозябр (только для отладки)
        preview = chunk[:100]
        # Проверяем на наличие нечитаемых символов (не буквы, не цифры, не пунктуация, не пробелы, не кириллица)
        unreadable_count = sum(1 for c in preview if ord(c) > 127 and not c.isprintable() and c not in "\n\r\t" and c not in "абвгдеёжзийклмнопрстуфхцчшщъыьэюяАБВГДЕЁЖЗИЙКЛМНОПРСТУФХЦЧШЩЪЫЬЭЮЯ")
        if unreadable_count > 10:  # Если больше 10 нечитаемых символов
            logger.warning(f"Чанк {idx} может содержать проблемы с кодировкой: {preview[:50]}...")

    # Сохранение в FAISS
    await _save_to_faiss(all_embeddings, chunks, chunks_metadata)

    logger.info(f"Файл {file_path} успешно обработан: {len(chunks)} чанков")


async def ingest_books(folder_path: str) -> None:
    """Основная функция индексации книг из папки.

    Обрабатывает все поддерживаемые файлы в указанной папке:
    - Проверяет размер и формат файлов
    - Читает содержимое
    - Разбивает на чанки
    - Создаёт эмбеддинги
    - Сохраняет в FAISS индекс

    Args:
        folder_path: Путь к папке с книгами.

    Raises:
        FileNotFoundError: Если папка не существует.
        ValueError: Если в папке нет поддерживаемых файлов.
    """
    folder = Path(folder_path)

    if not folder.exists():
        raise FileNotFoundError(f"Папка не найдена: {folder_path}")

    if not folder.is_dir():
        raise ValueError(f"Указанный путь не является папкой: {folder_path}")

    logger.info(f"Начало индексации книг из папки: {folder_path}")

    # Поиск всех поддерживаемых файлов
    files_to_process: list[Path] = []
    for ext in SUPPORTED_EXTENSIONS:
        files_to_process.extend(folder.glob(f"*{ext}"))
        files_to_process.extend(folder.glob(f"*{ext.upper()}"))
    
    # Убираем дубликаты (если файл найден и с .txt и с .TXT)
    files_to_process = list(dict.fromkeys(files_to_process))  # Сохраняет порядок

    if not files_to_process:
        logger.warning(f"В папке {folder_path} не найдено поддерживаемых файлов")
        return

    logger.info(f"Найдено {len(files_to_process)} файлов для обработки")

    # Обработка каждого файла
    processed = 0
    errors = 0

    for file_path in files_to_process:
        try:
            await _process_file(file_path)
            processed += 1
        except Exception as e:
            errors += 1
            logger.error(f"Ошибка при обработке файла {file_path}: {e}")

    logger.info(f"Индексация завершена: обработано {processed} файлов, " f"ошибок {errors}")
