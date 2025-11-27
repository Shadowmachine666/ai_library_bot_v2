"""Менеджер подтверждений категорий книг.

Модуль управляет запросами на подтверждение категорий книг администратором.
Хранит запросы в файле и предоставляет функции для работы с ними.
"""

import json
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from src.config import Config
from src.utils import setup_logger

logger = setup_logger(__name__)

# Путь к файлу с ожидающими подтверждениями
CONFIRMATIONS_FILE = Path("./data/pending_confirmations.json")


def _ensure_confirmations_dir() -> None:
    """Создаёт директорию для файла подтверждений, если её нет."""
    CONFIRMATIONS_FILE.parent.mkdir(parents=True, exist_ok=True)


def _load_confirmations() -> dict[str, dict[str, Any]]:
    """Загружает запросы на подтверждение из файла.

    Returns:
        Словарь, где ключ - request_id, значение - данные запроса.
        Если файл не существует, возвращает пустой словарь.
    """
    _ensure_confirmations_dir()

    if not CONFIRMATIONS_FILE.exists():
        logger.debug("Файл подтверждений не найден, создаём новый")
        return {}

    try:
        with open(CONFIRMATIONS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            confirmations = data.get("requests", {})
            logger.debug(f"Загружено {len(confirmations)} запросов на подтверждение")
            return confirmations
    except json.JSONDecodeError as e:
        logger.error(f"Ошибка при чтении файла подтверждений: {e}. Создаём новый файл.")
        return {}
    except Exception as e:
        logger.error(f"Ошибка при загрузке подтверждений: {e}")
        return {}


def _save_confirmations(confirmations: dict[str, dict[str, Any]]) -> None:
    """Сохраняет запросы на подтверждение в файл.

    Args:
        confirmations: Словарь с запросами на подтверждение.
    """
    _ensure_confirmations_dir()

    try:
        data = {"requests": confirmations, "updated_at": datetime.now().isoformat()}
        with open(CONFIRMATIONS_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        logger.debug(f"Сохранено {len(confirmations)} запросов на подтверждение")
    except Exception as e:
        logger.error(f"Ошибка при сохранении подтверждений: {e}")
        raise ValueError(f"Не удалось сохранить подтверждения: {e}") from e


def create_confirmation_request(
    file_path: Path,
    book_title: str,
    categories_from_filename: list[str] | None = None,
    categories_llm_recommendation: list[str] | None = None,
    llm_confidence: float | None = None,
    llm_reasoning: str | None = None,
) -> str:
    """Создаёт новый запрос на подтверждение категорий.

    Args:
        file_path: Путь к файлу книги.
        book_title: Название книги.
        categories_from_filename: Категории из имени файла (если есть).
        categories_llm_recommendation: Рекомендация LLM по категориям.
        llm_confidence: Уверенность LLM (0.0-1.0).
        llm_reasoning: Объяснение LLM.

    Returns:
        Уникальный ID запроса (request_id).
    """
    request_id = f"req_{uuid.uuid4().hex[:12]}"

    confirmation = {
        "request_id": request_id,
        "file_path": str(file_path.absolute()),
        "book_title": book_title,
        "categories_from_filename": categories_from_filename or [],
        "categories_llm_recommendation": categories_llm_recommendation or [],
        "llm_confidence": llm_confidence,
        "llm_reasoning": llm_reasoning,
        "status": "pending",
        "created_at": datetime.now().isoformat(),
        "message_id": None,
    }

    confirmations = _load_confirmations()
    confirmations[request_id] = confirmation
    _save_confirmations(confirmations)

    logger.info(
        f"Создан запрос на подтверждение: {request_id} для книги '{book_title}' "
        f"(файл: {file_path.name})"
    )

    return request_id


def get_confirmation_request(request_id: str) -> dict[str, Any] | None:
    """Получает запрос на подтверждение по ID.

    Args:
        request_id: ID запроса.

    Returns:
        Данные запроса или None, если не найден.
    """
    confirmations = _load_confirmations()
    return confirmations.get(request_id)


def update_confirmation_status(
    request_id: str, status: str, message_id: int | None = None
) -> bool:
    """Обновляет статус запроса на подтверждение.

    Args:
        request_id: ID запроса.
        status: Новый статус ("pending", "approved", "rejected", "timeout").
        message_id: ID сообщения в Telegram (опционально).

    Returns:
        True если обновление успешно, False если запрос не найден.
    """
    confirmations = _load_confirmations()

    if request_id not in confirmations:
        logger.warning(f"Запрос на подтверждение не найден: {request_id}")
        return False

    old_status = confirmations[request_id].get("status")
    confirmations[request_id]["status"] = status

    if message_id is not None:
        confirmations[request_id]["message_id"] = message_id

    _save_confirmations(confirmations)

    logger.info(
        f"Статус запроса {request_id} обновлён: {old_status} → {status}"
    )

    return True


def get_pending_confirmations() -> list[dict[str, Any]]:
    """Получает все ожидающие подтверждения.

    Returns:
        Список запросов со статусом "pending".
    """
    confirmations = _load_confirmations()
    pending = [
        req for req in confirmations.values() if req.get("status") == "pending"
    ]
    logger.debug(f"Найдено {len(pending)} ожидающих подтверждений")
    return pending


def get_expired_requests() -> list[str]:
    """Получает список ID истёкших запросов.

    Запрос считается истёкшим, если он в статусе "pending"
    и создан более CONFIRMATION_TIMEOUT_HOURS часов назад.

    Returns:
        Список request_id истёкших запросов.
    """
    confirmations = _load_confirmations()
    expired = []

    timeout_hours = Config.CONFIRMATION_TIMEOUT_HOURS
    timeout_delta = timedelta(hours=timeout_hours)
    now = datetime.now()

    for request_id, request in confirmations.items():
        if request.get("status") != "pending":
            continue

        created_at_str = request.get("created_at")
        if not created_at_str:
            logger.warning(f"Запрос {request_id} не имеет created_at, пропускаем")
            continue

        try:
            created_at = datetime.fromisoformat(created_at_str)
            if now - created_at > timeout_delta:
                expired.append(request_id)
        except (ValueError, TypeError) as e:
            logger.warning(
                f"Ошибка при парсинге created_at для запроса {request_id}: {e}"
            )

    if expired:
        logger.info(
            f"Найдено {len(expired)} истёкших запросов (таймаут: {timeout_hours} часов)"
        )

    return expired


def update_confirmation_categories(
    request_id: str, categories: list[str]
) -> bool:
    """Обновляет категории в запросе на подтверждение.

    Args:
        request_id: ID запроса.
        categories: Новый список категорий.

    Returns:
        True если обновление успешно, False если запрос не найден.
    """
    confirmations = _load_confirmations()

    if request_id not in confirmations:
        logger.warning(f"Запрос на подтверждение не найден для обновления категорий: {request_id}")
        return False

    confirmations[request_id]["categories_llm_recommendation"] = categories
    confirmations[request_id]["categories_from_filename"] = []  # Очищаем категории из имени файла, так как они были изменены вручную
    _save_confirmations(confirmations)

    logger.info(
        f"Категории обновлены для запроса {request_id}: {categories}"
    )
    return True


def delete_confirmation_request(request_id: str) -> bool:
    """Удаляет запрос на подтверждение.

    Args:
        request_id: ID запроса.

    Returns:
        True если удаление успешно, False если запрос не найден.
    """
    confirmations = _load_confirmations()

    if request_id not in confirmations:
        logger.warning(f"Запрос на подтверждение не найден для удаления: {request_id}")
        return False

    del confirmations[request_id]
    _save_confirmations(confirmations)

    logger.info(f"Запрос на подтверждение удалён: {request_id}")
    return True


def get_all_confirmations() -> dict[str, dict[str, Any]]:
    """Получает все запросы на подтверждение.

    Returns:
        Словарь всех запросов (включая обработанные).
    """
    return _load_confirmations()


def cleanup_old_confirmations(days: int = 7) -> int:
    """Удаляет старые обработанные запросы.

    Удаляет запросы со статусом "approved", "rejected" или "timeout",
    которые старше указанного количества дней.

    Args:
        days: Количество дней для хранения старых запросов.

    Returns:
        Количество удалённых запросов.
    """
    confirmations = _load_confirmations()
    deleted_count = 0

    cutoff_date = datetime.now() - timedelta(days=days)
    old_statuses = {"approved", "rejected", "timeout"}

    to_delete = []
    for request_id, request in confirmations.items():
        if request.get("status") not in old_statuses:
            continue

        created_at_str = request.get("created_at")
        if not created_at_str:
            continue

        try:
            created_at = datetime.fromisoformat(created_at_str)
            if created_at < cutoff_date:
                to_delete.append(request_id)
        except (ValueError, TypeError):
            continue

    for request_id in to_delete:
        del confirmations[request_id]
        deleted_count += 1

    if deleted_count > 0:
        _save_confirmations(confirmations)
        logger.info(f"Удалено {deleted_count} старых запросов (старше {days} дней)")

    return deleted_count

