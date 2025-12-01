"""Точка входа для ai_library_bot.

Поддерживает команды:
- ingest: загрузка книг в индекс
- run: запуск Telegram бота
- rebuild-index: восстановление FAISS индекса из метаданных (если индекс поврежден)
"""

import argparse
import asyncio
import sys
from pathlib import Path

from src.config import Config
from src.ingest_service import ingest_books, _rebuild_index_from_metadata
from src.telegram_bot import run_bot
from src.utils import setup_logger

logger = setup_logger(__name__)


def main() -> None:
    """Главная функция для запуска приложения."""
    parser = argparse.ArgumentParser(
        description="AI Library Bot - RAG-based Telegram bot for answering questions from uploaded books"
    )
    subparsers = parser.add_subparsers(dest="command", help="Доступные команды")

    # Команда ingest
    ingest_parser = subparsers.add_parser("ingest", help="Загрузить книги в индекс")
    ingest_parser.add_argument(
        "--folder",
        type=str,
        default="./data/books",
        help="Путь к папке с книгами (по умолчанию: ./data/books)",
    )
    ingest_parser.add_argument(
        "--force",
        action="store_true",
        help="Принудительно переиндексировать все файлы, даже если они не изменились",
    )

    # Команда run
    run_parser = subparsers.add_parser("run", help="Запустить Telegram бота")

    # Команда rebuild-index
    rebuild_parser = subparsers.add_parser(
        "rebuild-index",
        help="Восстановить FAISS индекс из метаданных (если индекс поврежден)"
    )

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(1)

    # Валидация конфигурации
    if not Config.validate():
        logger.error("Ошибка конфигурации. Проверьте переменные окружения.")
        sys.exit(1)

    try:
        if args.command == "ingest":
            asyncio.run(ingest_books(str(Path(args.folder)), force=args.force))
        elif args.command == "run":
            asyncio.run(run_bot())
        elif args.command == "rebuild-index":
            logger.info("🔄 Запуск восстановления индекса из метаданных...")
            success, message = asyncio.run(_rebuild_index_from_metadata())
            if success:
                logger.info(f"✅ {message}")
                sys.exit(0)
            else:
                logger.error(f"❌ {message}")
                sys.exit(1)
        else:
            parser.print_help()
            sys.exit(1)
    except KeyboardInterrupt:
        logger.info("Получен сигнал прерывания. Завершение работы...")
        sys.exit(0)
    except Exception as e:
        logger.error(f"Критическая ошибка: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()




