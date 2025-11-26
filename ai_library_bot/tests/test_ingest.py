"""Тесты для ingest_service.py."""

from pathlib import Path
from unittest.mock import patch

import pytest

from src.config import Config
from src.ingest_service import (
    SUPPORTED_EXTENSIONS,
    _chunk_text,
    _extract_metadata,
    _process_file,
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
    """Тест: обработка файлов в папке (mock)."""
    # Создаём временную папку с mock-файлами
    folder = tmp_path / "books"
    folder.mkdir()

    # Создаём mock-файлы разных форматов
    (folder / "book1.txt").write_text("Test content " * 1000)  # Достаточно для чанков
    (folder / "book2.pdf").write_text("PDF content " * 1000)

    # Мокаем все внешние зависимости
    with (
        patch("src.ingest_service._read_txt_file") as mock_read_txt,
        patch("src.ingest_service._read_pdf_file") as mock_read_pdf,
        patch("src.ingest_service._create_embeddings_batch") as mock_embeddings,
        patch("src.ingest_service._save_to_faiss") as mock_save,
    ):

        # Настраиваем моки
        mock_read_txt.return_value = "Test content " * 1000
        mock_read_pdf.return_value = "PDF content " * 1000
        mock_embeddings.return_value = [[0.0] * 1536] * 10  # Mock embeddings

        # Вызываем функцию
        await ingest_books(str(folder))

        # Проверяем, что функции были вызваны
        assert mock_read_txt.called or mock_read_pdf.called
        assert mock_embeddings.called
        assert mock_save.called


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
    assert metadata["file_type"] == ".txt"


def test_supported_extensions():
    """Тест: проверка поддерживаемых форматов."""
    assert ".txt" in SUPPORTED_EXTENSIONS
    assert ".pdf" in SUPPORTED_EXTENSIONS
    assert ".epub" in SUPPORTED_EXTENSIONS
    assert ".fb2" in SUPPORTED_EXTENSIONS
    assert ".doc" not in SUPPORTED_EXTENSIONS
