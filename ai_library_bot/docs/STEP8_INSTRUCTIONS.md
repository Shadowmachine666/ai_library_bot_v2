# Подробные инструкции для Шага 8

## Важно: Работа с виртуальным окружением

Так как автоматическая активация виртуального окружения отключена в Cursor, используйте один из следующих способов:

## Способ 1: Использование оператора вызова `&` (рекомендуется)

```powershell
# Переходим в директорию проекта
cd ai_library_bot

# Проверка ruff
& "..\..venv\Scripts\python.exe" -m ruff check .

# Проверка black
& "..\..venv\Scripts\python.exe" -m black . --check

# Проверка mypy
& "..\..venv\Scripts\python.exe" -m mypy src/

# Запуск тестов
& "..\..venv\Scripts\python.exe" -m pytest tests/ -v --tb=short
```

## Способ 2: Использование Join-Path (альтернатива)

```powershell
cd ai_library_bot
$python = Join-Path (Get-Location).Parent.Parent ".venv\Scripts\python.exe"
& $python -m ruff check .
& $python -m black . --check
& $python -m mypy src/
& $python -m pytest tests/ -v --tb=short
```

## Способ 3: Активация через .bat файл (самый простой)

```powershell
# Из корневой директории проекта
cd "G:\Mój dysk\Programming\Librarian"

# Активация виртуального окружения
.venv\Scripts\activate.bat

# Теперь можно использовать python напрямую
cd ai_library_bot
python -m ruff check .
python -m black . --check
python -m mypy src/
python -m pytest tests/ -v --tb=short
```

## Способ 4: Использование полного пути (если другие не работают)

```powershell
cd ai_library_bot
$pythonPath = "G:\Mój dysk\Programming\Librarian\.venv\Scripts\python.exe"
& $pythonPath -m ruff check .
& $pythonPath -m black . --check
& $pythonPath -m mypy src/
& $pythonPath -m pytest tests/ -v --tb=short
```

## Рекомендация

**Используйте Способ 3** (активация через .bat) - это самый простой и надёжный способ.




