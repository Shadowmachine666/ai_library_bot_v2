"""Тесты для admin_utils.py."""

import pytest

from src.admin_utils import get_admin_id, is_admin, require_admin


def test_is_admin_with_valid_id(monkeypatch):
    """Тест: проверка прав администратора с валидным ID."""
    from src import config

    # Устанавливаем ADMIN_TELEGRAM_ID
    monkeypatch.setattr(config.Config, "ADMIN_TELEGRAM_ID", 123456789)

    assert is_admin(123456789) is True
    assert is_admin(987654321) is False


def test_is_admin_without_id(monkeypatch):
    """Тест: проверка прав администратора без установленного ID."""
    from src import config

    # Убираем ADMIN_TELEGRAM_ID
    monkeypatch.setattr(config.Config, "ADMIN_TELEGRAM_ID", None)

    assert is_admin(123456789) is False
    assert is_admin(987654321) is False


def test_get_admin_id(monkeypatch):
    """Тест: получение ID администратора."""
    from src import config

    # Устанавливаем ADMIN_TELEGRAM_ID
    monkeypatch.setattr(config.Config, "ADMIN_TELEGRAM_ID", 123456789)

    assert get_admin_id() == 123456789


def test_get_admin_id_none(monkeypatch):
    """Тест: получение ID администратора, когда не установлен."""
    from src import config

    # Убираем ADMIN_TELEGRAM_ID
    monkeypatch.setattr(config.Config, "ADMIN_TELEGRAM_ID", None)

    assert get_admin_id() is None


def test_require_admin_success(monkeypatch):
    """Тест: require_admin с валидным администратором."""
    from src import config

    # Устанавливаем ADMIN_TELEGRAM_ID
    monkeypatch.setattr(config.Config, "ADMIN_TELEGRAM_ID", 123456789)

    # Не должно выбрасывать исключение
    require_admin(123456789)


def test_require_admin_failure(monkeypatch):
    """Тест: require_admin с невалидным пользователем."""
    from src import config

    # Устанавливаем ADMIN_TELEGRAM_ID
    monkeypatch.setattr(config.Config, "ADMIN_TELEGRAM_ID", 123456789)

    # Должно выбрасывать исключение
    with pytest.raises(PermissionError, match="Доступ запрещён"):
        require_admin(987654321)


def test_require_admin_no_id(monkeypatch):
    """Тест: require_admin когда ID не установлен."""
    from src import config

    # Убираем ADMIN_TELEGRAM_ID
    monkeypatch.setattr(config.Config, "ADMIN_TELEGRAM_ID", None)

    # Должно выбрасывать исключение
    with pytest.raises(PermissionError, match="Доступ запрещён"):
        require_admin(123456789)

