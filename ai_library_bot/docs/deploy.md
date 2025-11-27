# Инструкции по развёртыванию ai_library_bot в production

Этот документ описывает, как подготовить и развернуть бота в production окружении.

## Предварительные требования

- Сервер с Linux (Ubuntu 20.04+ рекомендуется)
- Python 3.11 или выше
- Минимум 2 ГБ RAM
- Минимум 10 ГБ свободного места на диске
- Доступ к интернету для загрузки зависимостей

## Шаг 1: Подготовка сервера

### Обновление системы

```bash
sudo apt update
sudo apt upgrade -y
```

### Установка Python и необходимых инструментов

```bash
sudo apt install -y python3.11 python3.11-venv python3-pip git
```

## Шаг 2: Создание пользователя для бота

Рекомендуется создать отдельного пользователя для запуска бота:

```bash
sudo useradd -m -s /bin/bash ai_library_bot
sudo su - ai_library_bot
```

## Шаг 3: Клонирование репозитория

```bash
cd ~
git clone <URL_РЕПОЗИТОРИЯ> ai_library_bot
cd ai_library_bot/ai_library_bot
```

## Шаг 4: Настройка виртуального окружения

```bash
python3.11 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
```

**Важно:** В production НЕ устанавливайте `requirements-dev.txt` (только для разработки).

## Шаг 5: Настройка переменных окружения

Создайте файл `.env` в корне проекта:

```bash
nano .env
```

Заполните следующие переменные:

```env
# Обязательные переменные
TG_TOKEN=ваш_токен_telegram_бота
OPENAI_API_KEY=ваш_ключ_openai

# Опциональные переменные (можно оставить значения по умолчанию)
FAISS_PATH=./data/index.faiss
CACHE_BACKEND=memory
LOG_LEVEL=INFO

# Для production рекомендуется использовать Redis для кэша
# CACHE_BACKEND=redis
# REDIS_HOST=localhost
# REDIS_PORT=6379
# REDIS_DB=0
```

**Безопасность:**
- Никогда не коммитьте файл `.env` в Git
- Используйте сильные пароли и токены
- Ограничьте доступ к файлу `.env`:

```bash
chmod 600 .env
```

## Шаг 6: Подготовка данных

Создайте необходимые директории:

```bash
mkdir -p data/books
mkdir -p logs
```

Поместите книги в `data/books/` или загрузите их через ingestion.

## Шаг 7: Загрузка книг в индекс

```bash
source .venv/bin/activate
python -m src.main ingest --folder data/books
```

Этот процесс может занять время в зависимости от количества и размера книг.

## Шаг 8: Настройка systemd service (рекомендуется)

Создайте файл сервиса для автоматического запуска бота:

```bash
sudo nano /etc/systemd/system/ai-library-bot.service
```

Содержимое файла:

```ini
[Unit]
Description=AI Library Bot
After=network.target

[Service]
Type=simple
User=ai_library_bot
WorkingDirectory=/home/ai_library_bot/ai_library_bot/ai_library_bot
Environment="PATH=/home/ai_library_bot/ai_library_bot/ai_library_bot/.venv/bin"
ExecStart=/home/ai_library_bot/ai_library_bot/ai_library_bot/.venv/bin/python -m src.main run
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

**Важно:** Замените пути на актуальные для вашего сервера.

Активация сервиса:

```bash
sudo systemctl daemon-reload
sudo systemctl enable ai-library-bot
sudo systemctl start ai-library-bot
```

Проверка статуса:

```bash
sudo systemctl status ai-library-bot
```

Просмотр логов:

```bash
sudo journalctl -u ai-library-bot -f
```

## Шаг 9: Настройка резервного копирования

### Резервное копирование FAISS индекса

Создайте скрипт для резервного копирования:

```bash
nano ~/backup_index.sh
```

Содержимое:

```bash
#!/bin/bash
BACKUP_DIR="/home/ai_library_bot/backups"
DATE=$(date +%Y%m%d_%H%M%S)
mkdir -p $BACKUP_DIR
cp data/index.faiss $BACKUP_DIR/index_$DATE.faiss
# Удаляем старые бэкапы (старше 7 дней)
find $BACKUP_DIR -name "index_*.faiss" -mtime +7 -delete
```

Сделайте скрипт исполняемым:

```bash
chmod +x ~/backup_index.sh
```

Настройте cron для автоматического резервного копирования (каждый день в 3:00):

```bash
crontab -e
```

Добавьте строку:

```
0 3 * * * /home/ai_library_bot/backup_index.sh
```

## Шаг 10: Мониторинг

### Проверка использования ресурсов

```bash
# Использование памяти
free -h

# Использование диска
df -h

# Процессы бота
ps aux | grep python
```

### Логи

Логи сохраняются в `logs/` директории. Для просмотра:

```bash
tail -f logs/ai_library_bot.log
```

## Шаг 11: Обновление бота

При обновлении кода:

```bash
cd ~/ai_library_bot/ai_library_bot
git pull
source .venv/bin/activate
pip install -r requirements.txt
sudo systemctl restart ai-library-bot
```

## Безопасность

### Firewall

Настройте firewall для ограничения доступа:

```bash
sudo ufw allow 22/tcp  # SSH
sudo ufw enable
```

### SSL/TLS

Если бот использует webhook (вместо polling), настройте SSL сертификат.

### Ограничение доступа к файлам

```bash
chmod 700 data/
chmod 600 .env
chmod 644 logs/*.log
```

## Масштабирование

### Использование Redis для кэша

В production рекомендуется использовать Redis вместо in-memory кэша:

1. Установите Redis:

```bash
sudo apt install redis-server
sudo systemctl enable redis-server
sudo systemctl start redis-server
```

2. Обновите `.env`:

```env
CACHE_BACKEND=redis
REDIS_HOST=localhost
REDIS_PORT=6379
REDIS_DB=0
```

### Горизонтальное масштабирование

Для масштабирования на несколько серверов:
- Используйте общий Redis для кэша
- Используйте общий FAISS индекс (через сетевую файловую систему или объектное хранилище)
- Настройте load balancer для распределения нагрузки

## Откат (Rollback)

Если что-то пошло не так:

1. Остановите сервис:

```bash
sudo systemctl stop ai-library-bot
```

2. Восстановите предыдущую версию:

```bash
cd ~/ai_library_bot/ai_library_bot
git checkout <предыдущий_коммит>
source .venv/bin/activate
pip install -r requirements.txt
```

3. Восстановите индекс из бэкапа (если необходимо):

```bash
cp ~/backups/index_YYYYMMDD_HHMMSS.faiss data/index.faiss
```

4. Запустите сервис:

```bash
sudo systemctl start ai-library-bot
```

## Поддержка

При возникновении проблем:
1. Проверьте логи: `logs/ai_library_bot.log`
2. Проверьте статус сервиса: `sudo systemctl status ai-library-bot`
3. Проверьте системные логи: `sudo journalctl -u ai-library-bot -n 100`

## Дополнительные ресурсы

- Инструкции по локальному запуску: `docs/run_local.md`
- Операционные процедуры: `docs/ops.md` (будет создан на Шаге 9)
- Метрики и мониторинг: `docs/metrics.md`






