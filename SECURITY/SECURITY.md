# Политика безопасности

## Защита от утечки чувствительных данных

Этот документ описывает меры безопасности, принятые в проекте для предотвращения утечки чувствительных данных.

### Файлы, которые НИКОГДА не должны попадать в Git

- `.env` и любые файлы `.env.*` (кроме `.env.example`)
- `*.pkl` - файлы индексов и метаданных
- `*.faiss` - FAISS векторные индексы
- `data/` - папка с данными (книги, индексы)
- `logs/` - логи приложения
- `*.log` - любые лог-файлы
- `*.db`, `*.sqlite`, `*.dump` - базы данных и дампы
- `*_local.py`, `*_dev.py`, `*_secret.py` - локальные конфигурации

### Многоуровневая защита

#### 1. `.gitignore`
Все чувствительные файлы и папки добавлены в `.gitignore`.

#### 2. `.cursorrules`
AI-ассистент настроен на автоматическое предупреждение при попытке коммита чувствительных файлов.

#### 3. Pre-commit hooks
Автоматические проверки перед каждым коммитом:
- Проверка на наличие `.env` файлов
- Проверка на секреты и токены (detect-secrets)
- Проверка размера файлов
- Проверка на чувствительные расширения файлов

### Установка и настройка pre-commit hooks

```powershell
# Установка зависимостей
pip install -r ai_library_bot/requirements-dev.txt

# Установка pre-commit hooks
pre-commit install

# Ручной запуск проверок
pre-commit run --all-files
```

### Что делать, если секрет попал в репозиторий

1. **Немедленно** отозвать скомпрометированный ключ/токен
2. Удалить файл из истории Git (требует force push):
   ```bash
   git filter-branch --force --index-filter \
     "git rm --cached --ignore-unmatch путь/к/файлу" \
     --prune-empty --tag-name-filter cat -- --all
   ```
3. Уведомить команду о компрометации
4. Создать новый ключ/токен

### Использование переменных окружения

Все чувствительные данные должны храниться в `.env` файле:

1. Скопируйте `.env.example` в `.env`:
   ```powershell
   Copy-Item ai_library_bot\.env.example ai_library_bot\.env
   ```

2. Заполните реальными значениями (никогда не коммитьте `.env`!)

3. Используйте переменные окружения в коде через `os.getenv()` или `python-dotenv`

### Проверка перед коммитом

Перед каждым коммитом проверяйте:

```powershell
# Проверка статуса Git
git status

# Проверка изменённых файлов
git diff --cached --name-only

# Убедитесь, что нет .env файлов
git diff --cached --name-only | Select-String -Pattern "\.env$"
```

### Дополнительные ресурсы

- [GitHub Secrets Scanning](https://docs.github.com/en/code-security/secret-scanning)
- [OWASP Secrets Management](https://cheatsheetseries.owasp.org/cheatsheets/Secrets_Management_Cheat_Sheet.html)

