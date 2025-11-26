# Установка зависимостей

## Команды для установки

### 1. Перейти в корневую директорию проекта
```powershell
cd "G:\Mój dysk\Programming\Librarian"
```

### 2. Создать виртуальное окружение в корневой директории (если ещё не создано)
```powershell
python -m venv .venv
```

**Примечание:** Виртуальное окружение будет в `G:\Mój dysk\Programming\Librarian\.venv`, а проект в `ai_library_bot/`. Это нормально и будет работать.

### 3. Активировать виртуальное окружение

**Вариант А (рекомендуется):** Использовать активацию через cmd
```powershell
.venv\Scripts\activate.bat
```

**Вариант Б:** Временно изменить политику выполнения PowerShell (только для текущей сессии)
```powershell
Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope Process
.venv\Scripts\Activate.ps1
```

**Вариант В:** Использовать Python напрямую без активации (всегда указывать полный путь)
```powershell
# Вместо: python ...
# Использовать: .venv\Scripts\python.exe ...
```

### 4. Обновить pip
```powershell
.venv\Scripts\python.exe -m pip install --upgrade pip
```

### 5. Перейти в директорию проекта и установить основные зависимости
```powershell
cd ai_library_bot
..\..venv\Scripts\python.exe -m pip install --upgrade pip
..\..venv\Scripts\python.exe -m pip install -r requirements.txt
```

**Или из корневой директории:**
```powershell
cd "G:\Mój dysk\Programming\Librarian"
.venv\Scripts\python.exe -m pip install --upgrade pip
.venv\Scripts\python.exe -m pip install -r ai_library_bot\requirements.txt
```

### 6. Установить зависимости для разработки (опционально)
```powershell
# Из корневой директории
.venv\Scripts\python.exe -m pip install -r ai_library_bot\requirements-dev.txt
```

**Примечание:** 
- Виртуальное окружение находится в `G:\Mój dysk\Programming\Librarian\.venv`
- Проект находится в `G:\Mój dysk\Programming\Librarian\ai_library_bot\`
- Всегда используйте полный путь `.venv\Scripts\python.exe` из корневой директории или относительный путь `..\..venv\Scripts\python.exe` из директории проекта

## Проверка установки

После установки проверьте, что всё установлено:
```powershell
# Из корневой директории
cd "G:\Mój dysk\Programming\Librarian"
.venv\Scripts\python.exe -c "import sys; sys.path.insert(0, 'ai_library_bot'); from src.config import Config; print('✓ Config загружен успешно')"
```

**Или из директории проекта:**
```powershell
cd "G:\Mój dysk\Programming\Librarian\ai_library_bot"
..\..venv\Scripts\python.exe -c "from src.config import Config; print('✓ Config загружен успешно')"
```

## Структура директорий

```
G:\Mój dysk\Programming\Librarian\
├── .venv\                    ← Виртуальное окружение (здесь)
└── ai_library_bot\           ← Проект (здесь)
    ├── src\
    ├── tests\
    ├── requirements.txt
    └── ...
```

**Это нормальная структура!** Виртуальное окружение может быть в родительской директории.

