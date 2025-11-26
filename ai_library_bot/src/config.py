"""Модуль конфигурации для ai_library_bot.

Загружает переменные окружения и предоставляет настройки приложения.
Все ключи внешних API загружаются из .env файла (не захардкожены).
"""

import os
from pathlib import Path

from dotenv import load_dotenv

# Загружаем переменные окружения из .env файла
load_dotenv()


class Config:
    """Конфигурация приложения."""

    # Telegram Bot
    TG_TOKEN: str | None = os.getenv("TG_TOKEN")

    # OpenAI
    OPENAI_API_KEY: str | None = os.getenv("OPENAI_API_KEY")

    # FAISS Vector Store
    FAISS_PATH: Path = Path(os.getenv("FAISS_PATH", "./data/index.faiss"))
    FAISS_INDEX_DIR: Path = FAISS_PATH.parent
    FAISS_INDEX_DIR.mkdir(parents=True, exist_ok=True)

    # Кэш
    CACHE_BACKEND: str = os.getenv("CACHE_BACKEND", "memory")
    CACHE_TTL: int = int(os.getenv("CACHE_TTL", "3600"))  # 1 час

    # Логирование
    LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO")
    LOG_DIR: Path = Path("./logs")
    LOG_DIR.mkdir(parents=True, exist_ok=True)

    # Настройки индексации
    MAX_FILE_SIZE_MB: int = 20
    MAX_PDF_PAGES: int = 1000  # Увеличено с 500 до 1000 для поддержки больших книг
    MIN_CHUNK_SIZE: int = 200
    CHUNK_SIZE: int = 1500
    CHUNK_OVERLAP: int = 200

    # Настройки поиска
    TOP_K: int = 10  # Оптимизировано: уменьшено с 20 до 10 для экономии токенов без потери качества
    SCORE_THRESHOLD: float = 0.2  # Понижен для векторного поиска (L2 расстояние может давать низкие score)
    # Умная фильтрация: если топ-5 чанков имеют score > 0.4, использовать только их
    SMART_FILTERING_ENABLED: bool = True
    SMART_FILTERING_TOP_N: int = 5  # Количество чанков для проверки в умной фильтрации
    SMART_FILTERING_SCORE_THRESHOLD: float = 0.4  # Порог релевантности для умной фильтрации

    # Настройки эмбеддингов
    EMBEDDING_BATCH_SIZE: int = 128
    EMBEDDING_MODEL: str = "text-embedding-3-small"

    # Настройки LLM
    LLM_MODEL: str = os.getenv("LLM_MODEL", "gpt-4o-mini")
    LLM_TEMPERATURE: float = 0.0
    LLM_MAX_RETRIES: int = 5

    @classmethod
    def validate(cls) -> bool:
        """Проверяет наличие обязательных настроек конфигурации.

        Returns:
            True если конфигурация валидна, False в противном случае.
        """
        if not cls.TG_TOKEN:
            print("ПРЕДУПРЕЖДЕНИЕ: TG_TOKEN не установлен в переменных окружения")
            return False
        if not cls.OPENAI_API_KEY:
            print("ПРЕДУПРЕЖДЕНИЕ: OPENAI_API_KEY не установлен в переменных окружения")
            return False
        return True

    @classmethod
    async def check_openai_connection(cls) -> bool:
        """Проверяет подключение к OpenAI API.

        Returns:
            True если подключение успешно, False в противном случае.
        """
        import logging

        logger = logging.getLogger(__name__)

        if not cls.OPENAI_API_KEY:
            logger.error("OPENAI_API_KEY не установлен - проверка подключения невозможна")
            return False

        # Проверяем, не является ли ключ mock/placeholder
        if cls.OPENAI_API_KEY.lower() in [
            "mock",
            "placeholder",
            "test",
            "mock_openai_key_for_testing",
            "placeholder_for_mock_mode",
        ]:
            logger.warning(
                "OPENAI_API_KEY выглядит как mock/placeholder - реальное подключение не будет выполнено"
            )
            return False

        try:
            from openai import AsyncOpenAI

            client = AsyncOpenAI(api_key=cls.OPENAI_API_KEY)
            # Простой тестовый запрос для проверки подключения
            response = await client.models.list()
            logger.info("✅ Подключение к OpenAI API успешно установлено")
            logger.debug(f"Доступно моделей: {len(response.data)}")
            return True
        except ImportError:
            logger.warning("Библиотека openai не установлена - проверка подключения пропущена")
            return False
        except Exception as e:
            logger.error(f"❌ Ошибка подключения к OpenAI API: {e}")
            return False
