# Операционные процедуры (OPS) для ai_library_bot

Этот документ описывает операционные процедуры для управления и поддержки бота в production окружении.

## Содержание

1. [Логирование](#логирование)
2. [Восстановление FAISS индекса](#восстановление-faiss-индекса)
3. [Откат индекса](#откат-индекса)
4. [Отключение ingestion](#отключение-ingestion)
5. [Rollback сценарии](#rollback-сценарии)
6. [Мониторинг](#мониторинг)

---

## Логирование

### Где находятся логи

Логи сохраняются в директории `logs/` относительно корня проекта.

**Локальная разработка:**
```
ai_library_bot/logs/
```

**Production (systemd):**
```
/home/ai_library_bot/ai_library_bot/logs/
```

### Структура логов

Логи сохраняются в файлы с именами вида:
- `ai_library_bot_YYYY-MM-DD.log` - основной лог файл
- Логи ротируются ежедневно

### Уровни логирования

Уровень логирования настраивается через переменную окружения `LOG_LEVEL` в файле `.env`:

```env
LOG_LEVEL=INFO  # DEBUG, INFO, WARNING, ERROR
```

### Просмотр логов

**В реальном времени:**
```bash
# Локально
tail -f logs/ai_library_bot_*.log

# Production (systemd)
sudo journalctl -u ai-library-bot -f
```

**Поиск ошибок:**
```bash
grep -i error logs/ai_library_bot_*.log
grep -i exception logs/ai_library_bot_*.log
```

**Последние 100 строк:**
```bash
tail -n 100 logs/ai_library_bot_*.log
```

### Ротация логов

Рекомендуется настроить автоматическую ротацию логов через `logrotate`:

```bash
# /etc/logrotate.d/ai-library-bot
/home/ai_library_bot/ai_library_bot/logs/*.log {
    daily
    rotate 7
    compress
    delaycompress
    missingok
    notifempty
    create 0644 ai_library_bot ai_library_bot
}
```

---

## Восстановление FAISS индекса

### Где находится индекс

FAISS индекс сохраняется в файл, указанный в переменной окружения `FAISS_PATH`:

```env
FAISS_PATH=./data/index.faiss
```

**Локально:**
```
ai_library_bot/data/index.faiss
```

**Production:**
```
/home/ai_library_bot/ai_library_bot/data/index.faiss
```

### Восстановление из резервной копии

Если у вас есть резервная копия индекса:

```bash
# 1. Остановите бота
sudo systemctl stop ai-library-bot

# 2. Создайте резервную копию текущего индекса (на всякий случай)
cp data/index.faiss data/index.faiss.backup_$(date +%Y%m%d_%H%M%S)

# 3. Восстановите индекс из бэкапа
cp /path/to/backup/index_YYYYMMDD_HHMMSS.faiss data/index.faiss

# 4. Проверьте права доступа
chmod 644 data/index.faiss
chown ai_library_bot:ai_library_bot data/index.faiss

# 5. Запустите бота
sudo systemctl start ai-library-bot

# 6. Проверьте логи
sudo journalctl -u ai-library-bot -n 50
```

### Пересоздание индекса с нуля

Если индекс повреждён и нет резервной копии:

```bash
# 1. Остановите бота
sudo systemctl stop ai-library-bot

# 2. Удалите повреждённый индекс
rm data/index.faiss

# 3. Пересоздайте индекс из книг
cd ai_library_bot
source .venv/bin/activate
python -m src.main ingest --folder data/books

# 4. Запустите бота
sudo systemctl start ai-library-bot
```

**Внимание:** Пересоздание индекса может занять значительное время в зависимости от количества и размера книг.

---

## Откат индекса

### Откат к предыдущей версии индекса

Если после обновления индекса возникли проблемы:

```bash
# 1. Остановите бота
sudo systemctl stop ai-library-bot

# 2. Найдите нужную версию индекса в бэкапах
ls -lh ~/backups/index_*.faiss

# 3. Откатитесь к предыдущей версии
cp ~/backups/index_YYYYMMDD_HHMMSS.faiss data/index.faiss

# 4. Запустите бота
sudo systemctl start ai-library-bot

# 5. Проверьте работу
sudo journalctl -u ai-library-bot -f
```

### Откат к последнему рабочему состоянию

```bash
# 1. Остановите бота
sudo systemctl stop ai-library-bot

# 2. Найдите последний бэкап (самый новый)
LATEST_BACKUP=$(ls -t ~/backups/index_*.faiss | head -1)

# 3. Восстановите индекс
cp "$LATEST_BACKUP" data/index.faiss

# 4. Запустите бота
sudo systemctl start ai-library-bot
```

---

## Отключение ingestion

### Временное отключение ingestion

Если нужно временно остановить обработку новых книг:

**Вариант 1: Переименовать директорию с книгами**

```bash
# Переименуйте директорию, чтобы бот не видел новые файлы
mv data/books data/books.disabled

# Создайте пустую директорию
mkdir data/books
```

**Вариант 2: Удалить все файлы из директории**

```bash
# Переместите файлы во временную директорию
mkdir -p data/books_backup
mv data/books/* data/books_backup/
```

**Вариант 3: Использовать переменную окружения (если реализовано)**

```bash
# В .env файле
INGESTION_ENABLED=false
```

### Постоянное отключение ingestion

Если ingestion больше не нужен:

1. Удалите или закомментируйте код, отвечающий за автоматическую обработку книг
2. Удалите cron job или systemd timer, если они настроены
3. Удалите директорию `data/books/` (опционально)

### Включение ingestion обратно

```bash
# Верните файлы на место
mv data/books.disabled data/books

# Или восстановите из бэкапа
mv data/books_backup/* data/books/
```

---

## Rollback сценарии

### Сценарий 1: Откат после неудачного обновления кода

**Ситуация:** После обновления кода бот перестал работать.

**Действия:**

```bash
# 1. Остановите бота
sudo systemctl stop ai-library-bot

# 2. Откатитесь к предыдущей версии кода
cd ~/ai_library_bot/ai_library_bot
git log --oneline -10  # Найдите нужный коммит
git checkout <предыдущий_рабочий_коммит>

# 3. Восстановите зависимости (если нужно)
source .venv/bin/activate
pip install -r requirements.txt

# 4. Восстановите индекс из бэкапа (если нужно)
cp ~/backups/index_YYYYMMDD_HHMMSS.faiss data/index.faiss

# 5. Запустите бота
sudo systemctl start ai-library-bot

# 6. Проверьте логи
sudo journalctl -u ai-library-bot -f
```

### Сценарий 2: Откат после повреждения индекса

**Ситуация:** FAISS индекс повреждён, бот не может найти информацию.

**Действия:**

```bash
# 1. Остановите бота
sudo systemctl stop ai-library-bot

# 2. Создайте резервную копию повреждённого индекса (для анализа)
cp data/index.faiss data/index.faiss.corrupted_$(date +%Y%m%d_%H%M%S)

# 3. Восстановите последний рабочий индекс
LATEST_BACKUP=$(ls -t ~/backups/index_*.faiss | head -1)
cp "$LATEST_BACKUP" data/index.faiss

# 4. Запустите бота
sudo systemctl start ai-library-bot

# 5. Проверьте работу
# Отправьте тестовый запрос боту и проверьте ответ
```

### Сценарий 3: Откат после проблем с зависимостями

**Ситуация:** После обновления зависимостей возникли ошибки.

**Действия:**

```bash
# 1. Остановите бота
sudo systemctl stop ai-library-bot

# 2. Откатитесь к предыдущей версии зависимостей
cd ~/ai_library_bot/ai_library_bot
source .venv/bin/activate

# 3. Удалите текущие зависимости
pip freeze > current_requirements.txt
pip uninstall -r current_requirements.txt -y

# 4. Восстановите зависимости из requirements.txt
pip install -r requirements.txt

# 5. Или используйте конкретные версии из requirements.txt
pip install -r requirements.txt --force-reinstall

# 6. Запустите бота
sudo systemctl start ai-library-bot
```

### Сценарий 4: Полный откат системы

**Ситуация:** Требуется полный откат к предыдущему состоянию.

**Действия:**

```bash
# 1. Остановите бота
sudo systemctl stop ai-library-bot

# 2. Откатите код
cd ~/ai_library_bot/ai_library_bot
git checkout <предыдущий_коммит>

# 3. Восстановите зависимости
source .venv/bin/activate
pip install -r requirements.txt

# 4. Восстановите индекс
LATEST_BACKUP=$(ls -t ~/backups/index_*.faiss | head -1)
cp "$LATEST_BACKUP" data/index.faiss

# 5. Восстановите конфигурацию (если нужно)
cp ~/backups/.env.backup .env

# 6. Запустите бота
sudo systemctl start ai-library-bot

# 7. Проверьте работу
sudo journalctl -u ai-library-bot -f
```

---

## Мониторинг

### Ключевые метрики для отслеживания

1. **Доступность бота**
   - Проверяйте, что бот отвечает на команды
   - Мониторьте логи на наличие ошибок

2. **Размер индекса**
   ```bash
   ls -lh data/index.faiss
   ```

3. **Использование памяти**
   ```bash
   ps aux | grep python | grep ai_library_bot
   ```

4. **Количество обработанных запросов**
   ```bash
   grep "Запрос от пользователя" logs/ai_library_bot_*.log | wc -l
   ```

5. **Ошибки в логах**
   ```bash
   grep -i error logs/ai_library_bot_*.log | tail -20
   ```

### Автоматический мониторинг (рекомендуется)

Настройте мониторинг через:
- **Prometheus + Grafana** - для метрик
- **Sentry** - для отслеживания ошибок
- **Uptime monitoring** - для проверки доступности

### Алерты

Настройте алерты на:
- Отсутствие ответов от бота более 5 минут
- Критические ошибки в логах
- Превышение использования памяти
- Отсутствие новых запросов (если ожидается активность)

---

## Полезные команды

### Проверка статуса бота

```bash
# Статус systemd сервиса
sudo systemctl status ai-library-bot

# Проверка процесса
ps aux | grep python | grep ai_library_bot

# Проверка портов (если используется webhook)
netstat -tulpn | grep python
```

### Очистка логов

```bash
# Удалить логи старше 30 дней
find logs/ -name "*.log" -mtime +30 -delete

# Очистить текущий лог (осторожно!)
> logs/ai_library_bot_$(date +%Y-%m-%d).log
```

### Проверка индекса

```bash
# Размер индекса
du -h data/index.faiss

# Проверка целостности (если есть утилита)
# python -m src.utils.check_index
```

---

## Контакты и поддержка

При возникновении критических проблем:
1. Проверьте логи: `logs/ai_library_bot_*.log`
2. Проверьте статус сервиса: `sudo systemctl status ai-library-bot`
3. Восстановите из последнего бэкапа
4. Если проблема не решается - создайте issue в репозитории

---

## Дополнительные ресурсы

- Инструкции по локальному запуску: `docs/run_local.md`
- Инструкции по развёртыванию: `docs/deploy.md`
- Метрики и мониторинг: `docs/metrics.md`





