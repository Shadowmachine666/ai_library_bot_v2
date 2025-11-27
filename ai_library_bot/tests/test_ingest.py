"""Тесты для ingest_service.py."""

from pathlib import Path
from unittest.mock import patch

import pytest

from src.config import Config
from src.ingest_service import (
    SUPPORTED_EXTENSIONS,
    _chunk_text,
    _delete_file_completely,
    _determine_categories,
    _extract_metadata,
    _process_file,
    check_and_cleanup_expired_confirmations,
    ingest_books,
)


@pytest.mark.asyncio
async def test_ingest_books_folder_not_found():
    """Тест: папка не существует."""
    with pytest.raises(FileNotFoundError):
        await ingest_books("/nonexistent/folder")


@pytest.mark.asyncio
async def test_ingest_books_empty_folder(tmp_path):
    """Тест: пустая папка."""
    # Создаём временную папку
    folder = tmp_path / "empty_books"
    folder.mkdir()

    # Должно завершиться без ошибок, но с предупреждением
    await ingest_books(str(folder))


@pytest.mark.asyncio
async def test_ingest_books_with_mock_files(tmp_path):
    """Тест: обработка файлов в папке с реальным чтением файлов."""
    # Создаём временную папку с тестовыми файлами
    folder = tmp_path / "books"
    folder.mkdir()

    # Создаём информативные тестовые файлы с категориями в имени
    # Это позволяет избежать вызова LLM и делает тест быстрее
    book1_content = (
        "Эта книга рассказывает о психологии поведения человека, "
        "о том, как работает мозг и как люди принимают решения. "
        "Психология — это наука о психике и поведении человека. "
        "Она изучает процессы восприятия, мышления, памяти, эмоций. "
    ) * 200  # Достаточно для чанков (минимум 2000+ символов)

    book2_content = (
        "Маркетинг — это комплексная система управления производственно-сбытовой "
        "деятельностью предприятия, направленная на получение прибыли через "
        "удовлетворение потребностей покупателей. В современном бизнесе маркетинг "
        "играет ключевую роль в достижении конкурентных преимуществ. "
    ) * 200  # Достаточно для чанков

    # Создаём файлы с категориями в имени (чтобы не вызывать LLM)
    (folder / "Психология поведения (психология).txt").write_text(
        book1_content, encoding="utf-8"
    )
    (folder / "Основы маркетинга (бизнес, маркетинг).txt").write_text(
        book2_content, encoding="utf-8"
    )

    # Мокаем только дорогие операции (embeddings и FAISS)
    # Чтение файлов теперь реальное
    with (
        patch("src.ingest_service._create_embeddings_batch") as mock_embeddings,
        patch("src.ingest_service._save_to_faiss") as mock_save,
    ):
        # Настраиваем моки для embeddings
        mock_embeddings.return_value = [[0.0] * 1536] * 10  # Mock embeddings

        # Словарь для хранения категорий по файлам
        book_categories = {}

        # Перехватываем вызовы _save_to_faiss для проверки категорий
        def save_to_faiss_side_effect(*args, **kwargs):
            """Перехватывает вызов _save_to_faiss и сохраняет категории."""
            # _save_to_faiss(embeddings, chunks, metadata, file_path, file_hash, file_index)
            if len(args) >= 4:
                metadata = args[2]  # metadata - третий аргумент
                file_path = args[3]  # file_path - четвертый аргумент
                file_name = Path(file_path).name
                
                # Извлекаем категории из метаданных
                if metadata and len(metadata) > 0:
                    # metadata - это список словарей, берем первый для примера
                    first_meta = metadata[0]
                    categories = first_meta.get("topics", [])
                    book_categories[file_name] = categories
                    print(f"\n📚 Книга: {file_name}")
                    print(f"   Категории: {categories}")

        mock_save.side_effect = save_to_faiss_side_effect

        # Вызываем функцию
        await ingest_books(str(folder))

        # Проверяем, что функции были вызваны
        assert mock_embeddings.called, "Embeddings должны быть созданы"
        assert mock_save.called, "Данные должны быть сохранены в FAISS"

        # Проверяем категории для каждой книги
        print("\n" + "=" * 60)
        print("РЕЗУЛЬТАТЫ КЛАССИФИКАЦИИ КНИГ:")
        print("=" * 60)
        
        expected_categories = {
            "Психология поведения (психология).txt": ["психология"],
            "Основы маркетинга (бизнес, маркетинг).txt": ["бизнес", "маркетинг"],
        }

        for file_name, expected_cats in expected_categories.items():
            actual_cats = book_categories.get(file_name, [])
            print(f"\n📖 {file_name}")
            print(f"   Ожидаемые категории: {expected_cats}")
            print(f"   Фактические категории: {actual_cats}")
            
            # Проверяем, что категории определены правильно
            assert file_name in book_categories, f"Книга {file_name} не была обработана"
            assert set(actual_cats) == set(expected_cats), (
                f"Категории для {file_name} не совпадают: "
                f"ожидалось {expected_cats}, получено {actual_cats}"
            )
            print(f"   ✅ Категории определены правильно!")

        print("\n" + "=" * 60)
        print(f"Всего обработано книг: {len(book_categories)}")
        print("=" * 60)


@pytest.mark.asyncio
async def test_ingest_real_books_from_folder(tmp_path, monkeypatch):
    """Тест: обработка реальных файлов из папки books (если она существует).
    
    Этот тест проверяет реальные файлы из папки books и показывает,
    в какие категории они были определены.
    """
    # Путь к папке books (относительно корня ai_library_bot)
    # Папка находится в data/books согласно структуре проекта
    books_folder = Path("data/books")
    
    # Если папка не существует, пропускаем тест
    if not books_folder.exists() or not books_folder.is_dir():
        pytest.skip(f"Папка {books_folder.absolute()} не существует. Пропускаем тест.")
    
    # Получаем список файлов
    book_files = [
        f for f in books_folder.iterdir()
        if f.is_file() and f.suffix.lower() in [".txt", ".pdf", ".epub", ".fb2"]
    ]
    
    if not book_files:
        pytest.skip(f"В папке {books_folder.absolute()} нет файлов книг. Пропускаем тест.")
    
    print(f"\n{'=' * 60}")
    print(f"НАЙДЕНО ФАЙЛОВ В ПАПКЕ: {len(book_files)}")
    print(f"{'=' * 60}")
    for f in book_files:
        print(f"  - {f.name}")
    
    # Словарь для хранения категорий по файлам
    book_categories = {}
    
    # Мокаем только дорогие операции (embeddings и FAISS)
    # Перехватываем create_confirmation_request для получения категорий
    with (
        patch("src.ingest_service._create_embeddings_batch") as mock_embeddings,
        patch("src.ingest_service._save_to_faiss") as mock_save,
        patch("src.ingest_service.create_confirmation_request") as mock_create_confirmation,
    ):
        # Настраиваем моки для embeddings
        mock_embeddings.return_value = [[0.0] * 1536] * 10  # Mock embeddings
        
        # Перехватываем вызовы _save_to_faiss для проверки категорий (для файлов с категориями в имени)
        def save_to_faiss_side_effect(*args, **kwargs):
            """Перехватывает вызов _save_to_faiss и сохраняет категории."""
            if len(args) >= 4:
                metadata = args[2]  # metadata - третий аргумент
                file_path = args[3]  # file_path - четвертый аргумент
                file_name = Path(file_path).name
                
                # Извлекаем категории из метаданных
                if metadata and len(metadata) > 0:
                    first_meta = metadata[0]
                    categories = first_meta.get("topics", [])
                    book_categories[file_name] = categories
                    print(f"\n📚 Книга (индексирована): {file_name}")
                    print(f"   Категории: {categories}")
        
        mock_save.side_effect = save_to_faiss_side_effect
        
        # Перехватываем create_confirmation_request для получения категорий из LLM
        def create_confirmation_side_effect(*args, **kwargs):
            """Перехватывает создание запроса на подтверждение и сохраняет категории."""
            # Получаем категории из LLM рекомендации или из имени файла
            llm_categories = kwargs.get("categories_llm_recommendation", [])
            categories_from_filename = kwargs.get("categories_from_filename", [])
            file_path = kwargs.get("file_path")
            
            # Если file_path не в kwargs, берем из args
            if not file_path and args:
                file_path = args[0] if len(args) > 0 else None
            
            if file_path:
                file_name = Path(file_path).name
                # Используем категории из LLM, если есть, иначе из имени файла
                categories = llm_categories if llm_categories else categories_from_filename
                book_categories[file_name] = categories
                
                print(f"\n📚 Книга (требует подтверждения): {file_name}")
                if llm_categories:
                    print(f"   Категории (LLM): {llm_categories}")
                    print(f"   ⚠️  Требуется подтверждение администратора")
                elif categories_from_filename:
                    print(f"   Категории (из имени файла): {categories_from_filename}")
                else:
                    print(f"   ⚠️  Категории не определены")
            
            # Возвращаем mock request_id
            import uuid
            return str(uuid.uuid4())
        
        mock_create_confirmation.side_effect = create_confirmation_side_effect
        
        # Используем реальную папку books
        await ingest_books(str(books_folder))
    
    # Загружаем категории из уже проиндексированных файлов
    # Читаем метаданные из FAISS индекса
    from src.config import Config
    import pickle
    import faiss
    
    metadata_path = Config.FAISS_PATH.with_suffix(".metadata.pkl")
    if metadata_path.exists():
        try:
            print(f"\n📂 Загрузка категорий из индекса: {metadata_path}")
            with open(metadata_path, "rb") as f:
                all_metadata = pickle.load(f)
            
            print(f"   Найдено {len(all_metadata)} записей метаданных в индексе")
            
            # Группируем метаданные по файлам и извлекаем категории
            file_categories_from_index = {}
            for meta in all_metadata:
                file_path_str = meta.get("file_path", "")
                if file_path_str:
                    # Извлекаем имя файла из абсолютного или относительного пути
                    file_name = Path(file_path_str).name
                    categories = meta.get("topics", [])
                    
                    # Если для файла уже есть категории, объединяем (убираем дубликаты)
                    if file_name not in file_categories_from_index:
                        file_categories_from_index[file_name] = set()
                    if categories:
                        file_categories_from_index[file_name].update(categories)
            
            print(f"   Найдено {len(file_categories_from_index)} уникальных файлов в индексе")
            
            # Добавляем категории из индекса в book_categories
            for file_name, categories_set in file_categories_from_index.items():
                if file_name not in book_categories:
                    categories_list = sorted(list(categories_set)) if categories_set else []
                    book_categories[file_name] = categories_list
                    print(f"\n📚 Книга (из индекса): {file_name}")
                    if categories_list:
                        print(f"   Категории: {categories_list}")
                    else:
                        print(f"   ⚠️  Категории не определены (файл был проиндексирован до добавления категорий)")
                        
                        # Для файлов без категорий определяем их через LLM
                        file_path = books_folder / file_name
                        if file_path.exists():
                            print(f"   🔍 Определяем категории через LLM...")
                            try:
                                # Читаем файл и определяем категории
                                from src.ingest_service import _read_txt_file, _read_pdf_file, _read_fb2_file, _read_epub_file
                                from src.category_parser import parse_categories_from_filename
                                from src.category_classifier import classify_book_category
                                
                                # Определяем формат и читаем файл
                                extension = file_path.suffix.lower()
                                if extension == ".txt":
                                    content = await _read_txt_file(file_path)
                                elif extension == ".pdf":
                                    content = await _read_pdf_file(file_path)
                                elif extension == ".epub":
                                    content = await _read_epub_file(file_path)
                                elif extension == ".fb2":
                                    content = await _read_fb2_file(file_path)
                                else:
                                    content = None
                                
                                if content:
                                    # Извлекаем название из имени файла
                                    book_title, categories_from_filename = parse_categories_from_filename(file_path)
                                    
                                    # Если категорий нет в имени файла, используем LLM
                                    if not categories_from_filename:
                                        content_preview = content[:2000].strip() if content else None
                                        llm_result = await classify_book_category(book_title, content_preview)
                                        llm_categories = llm_result.get("topics", [])
                                        
                                        if llm_categories:
                                            book_categories[file_name] = llm_categories
                                            print(f"   ✅ Категории определены (LLM): {llm_categories}")
                                        else:
                                            print(f"   ❌ LLM не смог определить категории")
                                    else:
                                        # Категории есть в имени файла
                                        book_categories[file_name] = categories_from_filename
                                        print(f"   ✅ Категории из имени файла: {categories_from_filename}")
                            except Exception as e:
                                print(f"   ❌ Ошибка при определении категорий: {e}")
        except Exception as e:
            print(f"\n⚠️  Не удалось загрузить категории из индекса: {e}")
            import traceback
            traceback.print_exc()
    
    # Выводим результаты
    print(f"\n{'=' * 60}")
    print("РЕЗУЛЬТАТЫ КЛАССИФИКАЦИИ РЕАЛЬНЫХ КНИГ:")
    print(f"{'=' * 60}")
    
    for file_name in sorted(book_categories.keys()):
        categories = book_categories[file_name]
        print(f"\n📖 {file_name}")
        if categories:
            print(f"   ✅ Категории: {', '.join(categories)}")
        else:
            print(f"   ⚠️  Категории не определены (требуется подтверждение администратора)")
    
    print(f"\n{'=' * 60}")
    print(f"Всего обработано книг: {len(book_categories)}")
    print(f"Книг с категориями: {sum(1 for cats in book_categories.values() if cats)}")
    print(f"Книг без категорий: {sum(1 for cats in book_categories.values() if not cats)}")
    print(f"{'=' * 60}\n")
    
    # Проверяем, что хотя бы некоторые файлы были обработаны
    assert len(book_categories) > 0, "Ни одна книга не была обработана"


@pytest.mark.asyncio
async def test_process_file_too_large(tmp_path):
    """Тест: файл слишком большой."""
    # Создаём файл больше 20MB (mock)
    large_file = tmp_path / "large.txt"
    large_file.write_text("x" * (21 * 1024 * 1024))  # 21 MB

    with pytest.raises(ValueError, match="слишком большой"):
        await _process_file(large_file)


@pytest.mark.asyncio
async def test_process_file_unsupported_format(tmp_path):
    """Тест: неподдерживаемый формат файла."""
    unsupported_file = tmp_path / "book.doc"
    unsupported_file.write_text("content")

    with pytest.raises(ValueError, match="Неподдерживаемый формат"):
        await _process_file(unsupported_file)


def test_chunk_text():
    """Тест: разбиение текста на чанки."""
    # Создаём текст достаточной длины
    text = "Test sentence. " * 200  # ~3000 символов

    chunks = _chunk_text(text, chunk_size=500, chunk_overlap=50)

    # Проверяем, что чанки созданы
    assert len(chunks) > 0

    # Проверяем, что все чанки больше MIN_CHUNK_SIZE
    for chunk in chunks:
        assert len(chunk.strip()) >= Config.MIN_CHUNK_SIZE

    # Проверяем, что чанки не пустые
    assert all(chunk.strip() for chunk in chunks)


def test_chunk_text_too_short():
    """Тест: текст слишком короткий для чанков."""
    short_text = "Short text"  # Меньше MIN_CHUNK_SIZE

    chunks = _chunk_text(short_text)

    # Должен вернуть пустой список, так как текст слишком короткий
    assert len(chunks) == 0


def test_extract_metadata():
    """Тест: извлечение метаданных."""
    file_path = Path("test_book.txt")
    content = "Some content"

    metadata = _extract_metadata(file_path, content)

    assert "title" in metadata
    assert "author" in metadata
    assert "file_path" in metadata
    assert "file_type" in metadata
    assert "topics" in metadata  # Новое поле
    assert metadata["file_type"] == ".txt"
    assert isinstance(metadata["topics"], list)


def test_extract_metadata_with_categories():
    """Тест: извлечение метаданных с категориями из имени файла."""
    file_path = Path("Книга (бизнес, маркетинг).txt")
    content = "Some content"

    metadata = _extract_metadata(file_path, content)

    assert metadata["title"] == "Книга"
    assert "topics" in metadata
    assert "бизнес" in metadata["topics"]
    assert "маркетинг" in metadata["topics"]


def test_supported_extensions():
    """Тест: проверка поддерживаемых форматов."""
    assert ".txt" in SUPPORTED_EXTENSIONS
    assert ".pdf" in SUPPORTED_EXTENSIONS
    assert ".epub" in SUPPORTED_EXTENSIONS
    assert ".fb2" in SUPPORTED_EXTENSIONS
    assert ".doc" not in SUPPORTED_EXTENSIONS


@pytest.mark.asyncio
async def test_determine_categories_with_filename_categories(tmp_path):
    """Тест: определение категорий с категориями из имени файла."""
    file_path = tmp_path / "Книга (бизнес, маркетинг).txt"
    file_path.write_text("content")

    categories = await _determine_categories(
        file_path, "Книга", ["бизнес", "маркетинг"], content_preview=None
    )

    assert categories == ["бизнес", "маркетинг"]


@pytest.mark.asyncio
async def test_determine_categories_no_categories(tmp_path):
    """Тест: определение категорий без категорий в имени файла."""
    file_path = tmp_path / "Книга.txt"
    file_path.write_text("content")
    content_preview = "Эта книга о бизнесе и маркетинге."

    with patch("src.ingest_service.classify_book_category") as mock_classify:
        mock_classify.return_value = {
            "topics": ["бизнес"],
            "confidence": 0.95,
            "reasoning": "Объяснение",
        }

        with patch("src.ingest_service.create_confirmation_request") as mock_create:
            categories = await _determine_categories(
                file_path, "Книга", [], content_preview=content_preview
            )

            # Должен вернуть None, так как создан запрос на подтверждение
            assert categories is None
            mock_create.assert_called_once()
            # Проверяем, что classify_book_category был вызван с content_preview
            mock_classify.assert_called_once_with("Книга", content_preview)


@pytest.mark.asyncio
async def test_delete_file_completely(tmp_path):
    """Тест: полное удаление файла."""
    # Создаём тестовый файл
    test_file = tmp_path / "test_book.txt"
    test_file.write_text("Test content")

    # Мокаем удаление из индекса и confirmation_manager
    with (
        patch("src.ingest_service._remove_file_from_index") as mock_remove_index,
        patch("src.ingest_service.get_all_confirmations") as mock_get_confirmations,
        patch("src.ingest_service.delete_confirmation_request") as mock_delete_req,
    ):
        mock_get_confirmations.return_value = {}

        await _delete_file_completely(test_file)

        # Проверяем, что файл удалён
        assert not test_file.exists()
        mock_remove_index.assert_called_once()


@pytest.mark.asyncio
async def test_check_and_cleanup_expired_confirmations(tmp_path, monkeypatch):
    """Тест: проверка и очистка истёкших подтверждений."""
    from datetime import datetime, timedelta

    from src import config

    # Устанавливаем таймаут 1 час
    monkeypatch.setattr(config.Config, "CONFIRMATION_TIMEOUT_HOURS", 1)

    # Создаём тестовый файл
    test_file = tmp_path / "expired_book.txt"
    test_file.write_text("Test content")

    # Мокаем функции
    with (
        patch("src.ingest_service.get_expired_requests") as mock_get_expired,
        patch("src.ingest_service.get_confirmation_request") as mock_get_request,
        patch("src.ingest_service.update_confirmation_status") as mock_update_status,
        patch("src.ingest_service._delete_file_completely") as mock_delete,
        patch("src.ingest_service.delete_confirmation_request") as mock_delete_req,
    ):
        # Настраиваем моки
        mock_get_expired.return_value = ["req_123"]
        mock_get_request.return_value = {
            "request_id": "req_123",
            "file_path": str(test_file.absolute()),
            "book_title": "Тестовая книга",
        }

        deleted_count = await check_and_cleanup_expired_confirmations()

        assert deleted_count == 1
        mock_update_status.assert_called_once_with("req_123", "timeout")
        mock_delete.assert_called_once()
        mock_delete_req.assert_called_once()
