"""Тесты для confirmation_manager.py."""

import json
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch

import pytest

from src.confirmation_manager import (
    cleanup_old_confirmations,
    create_confirmation_request,
    delete_confirmation_request,
    get_all_confirmations,
    get_confirmation_request,
    get_expired_requests,
    get_pending_confirmations,
    update_confirmation_status,
)


@pytest.fixture
def temp_confirmations_file(tmp_path, monkeypatch):
    """Фикстура для временного файла подтверждений."""
    from src import confirmation_manager

    temp_file = tmp_path / "pending_confirmations.json"
    monkeypatch.setattr(confirmation_manager, "CONFIRMATIONS_FILE", temp_file)

    # Очищаем файл перед тестом
    if temp_file.exists():
        temp_file.unlink()

    yield temp_file

    # Очищаем файл после теста
    if temp_file.exists():
        temp_file.unlink()


def test_create_confirmation_request(temp_confirmations_file):
    """Тест: создание запроса на подтверждение."""
    file_path = Path("test_book.pdf")
    book_title = "Тестовая книга"

    request_id = create_confirmation_request(
        file_path=file_path,
        book_title=book_title,
        categories_from_filename=["бизнес"],
        categories_llm_recommendation=["бизнес", "маркетинг"],
        llm_confidence=0.95,
        llm_reasoning="Объяснение",
    )

    assert request_id.startswith("req_")
    assert len(request_id) > 4

    # Проверяем, что запрос сохранён
    request = get_confirmation_request(request_id)
    assert request is not None
    assert request["book_title"] == book_title
    assert request["status"] == "pending"


def test_get_confirmation_request(temp_confirmations_file):
    """Тест: получение запроса на подтверждение."""
    file_path = Path("test_book.pdf")
    book_title = "Тестовая книга"

    request_id = create_confirmation_request(
        file_path=file_path,
        book_title=book_title,
    )

    request = get_confirmation_request(request_id)

    assert request is not None
    assert request["request_id"] == request_id
    assert request["book_title"] == book_title
    assert request["status"] == "pending"


def test_get_confirmation_request_not_found(temp_confirmations_file):
    """Тест: получение несуществующего запроса."""
    request = get_confirmation_request("req_nonexistent")

    assert request is None


def test_update_confirmation_status(temp_confirmations_file):
    """Тест: обновление статуса запроса."""
    file_path = Path("test_book.pdf")
    request_id = create_confirmation_request(
        file_path=file_path,
        book_title="Тестовая книга",
    )

    # Обновляем статус
    success = update_confirmation_status(request_id, "approved", message_id=12345)

    assert success is True

    # Проверяем обновление
    request = get_confirmation_request(request_id)
    assert request["status"] == "approved"
    assert request["message_id"] == 12345


def test_update_confirmation_status_not_found(temp_confirmations_file):
    """Тест: обновление статуса несуществующего запроса."""
    success = update_confirmation_status("req_nonexistent", "approved")

    assert success is False


def test_get_pending_confirmations(temp_confirmations_file):
    """Тест: получение ожидающих подтверждений."""
    file_path1 = Path("book1.pdf")
    file_path2 = Path("book2.pdf")

    # Создаём два запроса
    request_id1 = create_confirmation_request(
        file_path=file_path1,
        book_title="Книга 1",
    )
    request_id2 = create_confirmation_request(
        file_path=file_path2,
        book_title="Книга 2",
    )

    # Одному меняем статус
    update_confirmation_status(request_id2, "approved")

    # Получаем ожидающие
    pending = get_pending_confirmations()

    assert len(pending) == 1
    assert pending[0]["request_id"] == request_id1
    assert pending[0]["status"] == "pending"


def test_get_expired_requests(temp_confirmations_file, monkeypatch):
    """Тест: получение истёкших запросов."""
    from src import config

    # Устанавливаем таймаут 1 час
    monkeypatch.setattr(config.Config, "CONFIRMATION_TIMEOUT_HOURS", 1)

    file_path = Path("test_book.pdf")
    request_id = create_confirmation_request(
        file_path=file_path,
        book_title="Тестовая книга",
    )

    # Получаем запрос и изменяем created_at на 2 часа назад
    request = get_confirmation_request(request_id)
    old_created_at = datetime.now() - timedelta(hours=2)
    request["created_at"] = old_created_at.isoformat()

    # Сохраняем изменения
    all_confirmations = get_all_confirmations()
    all_confirmations[request_id] = request
    from src.confirmation_manager import _save_confirmations

    _save_confirmations(all_confirmations)

    # Проверяем истёкшие запросы
    expired = get_expired_requests()

    assert request_id in expired


def test_delete_confirmation_request(temp_confirmations_file):
    """Тест: удаление запроса на подтверждение."""
    file_path = Path("test_book.pdf")
    request_id = create_confirmation_request(
        file_path=file_path,
        book_title="Тестовая книга",
    )

    # Удаляем запрос
    success = delete_confirmation_request(request_id)

    assert success is True

    # Проверяем, что запрос удалён
    request = get_confirmation_request(request_id)
    assert request is None


def test_delete_confirmation_request_not_found(temp_confirmations_file):
    """Тест: удаление несуществующего запроса."""
    success = delete_confirmation_request("req_nonexistent")

    assert success is False


def test_cleanup_old_confirmations(temp_confirmations_file):
    """Тест: очистка старых подтверждений."""
    file_path1 = Path("book1.pdf")
    file_path2 = Path("book2.pdf")

    # Создаём два запроса
    request_id1 = create_confirmation_request(
        file_path=file_path1,
        book_title="Книга 1",
    )
    request_id2 = create_confirmation_request(
        file_path=file_path2,
        book_title="Книга 2",
    )

    # Меняем статусы
    update_confirmation_status(request_id1, "approved")
    update_confirmation_status(request_id2, "rejected")

    # Изменяем created_at на 10 дней назад
    all_confirmations = get_all_confirmations()
    old_date = (datetime.now() - timedelta(days=10)).isoformat()
    all_confirmations[request_id1]["created_at"] = old_date
    all_confirmations[request_id2]["created_at"] = old_date

    from src.confirmation_manager import _save_confirmations

    _save_confirmations(all_confirmations)

    # Очищаем старые (старше 7 дней)
    deleted_count = cleanup_old_confirmations(days=7)

    assert deleted_count == 2

    # Проверяем, что запросы удалены
    assert get_confirmation_request(request_id1) is None
    assert get_confirmation_request(request_id2) is None

