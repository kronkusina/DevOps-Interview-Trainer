# DevOps Interview Trainer

Интерактивный тренажёр для подготовки к DevOps-собеседованиям. Можно пройти полное mock-интервью, выбрать одну или несколько тем, отвечать на уточняющие вопросы AI и разбирать результаты по темам.

## Возможности

- 136+ вопросов по Linux, Docker, Kubernetes, CI/CD, сетям, security, Terraform, Ansible и AWS;
- фильтры по уровню, темам и типу: теория, практика, сценарии из публичных interview reports;
- два формата ответа: «Живое интервью» с уточняющими вопросами AI и «Быстрый прогон»;
- генерация короткого нового вопроса через AI по выбранным фильтрам;
- эталонный ответ, сильные стороны и зоны роста после ответа;
- навигация назад/далее в рамках тренировки, итоги по темам, светлая и тёмная темы.

## Быстрый запуск в Docker

Нужны [Docker Desktop](https://www.docker.com/products/docker-desktop/) и Docker Compose.

```bash
git clone <URL_ВАШЕГО_РЕПОЗИТОРИЯ>
cd devops-trainer
cp .env.example .env
```

Откройте `.env` и укажите ключ Groq:

```dotenv
GROQ_API_KEY=gsk_ваш_ключ_здесь
GROQ_MODEL=openai/gpt-oss-120b
```

Затем запустите приложение:

```bash
docker compose up --build -d
```

Откройте http://localhost:8000. Для просмотра логов используйте `docker compose logs -f trainer`, для остановки — `docker compose down`.

> Не используйте `docker compose down -v`, если хотите сохранить историю ответов и сгенерированные AI-вопросы: эта команда удаляет SQLite volume.

## Где получить Groq API key

1. Зарегистрируйтесь или войдите в [Groq Console](https://console.groq.com/).
2. Откройте раздел [API Keys](https://console.groq.com/keys) и создайте ключ для своего проекта.
3. Скопируйте ключ в локальный файл `.env` в переменную `GROQ_API_KEY`.
4. Перезапустите контейнер: `docker compose up --build -d`.

Ключ нужен для оценки ответов, уточняющих вопросов и кнопки генерации AI-вопроса. Базу статических вопросов можно просматривать без него, но AI-функции работать не будут. Groq рекомендует передавать ключ через переменную окружения, а не добавлять его в исходный код. Подробнее — в [официальном Quickstart Groq](https://console.groq.com/docs/quickstart).

## Безопасность ключа

- Никогда не коммитьте `.env` и не публикуйте ключ в issue, скриншотах или логах.
- `.env` добавлен в `.gitignore`; в репозиторий попадает только безопасный шаблон `.env.example`.
- Если ключ уже попал в публичный репозиторий, немедленно отзовите его в Groq Console и создайте новый.

## Локальный запуск без Docker

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r app/requirements.txt
export GROQ_API_KEY=gsk_ваш_ключ_здесь
uvicorn app.main:app --reload --port 8000
```

## Источники вопросов

Вопросы разделены на `theory`, `practical` и `real_interview`. Часть тем адаптирована по публичной базе [Speedrun IT DevOps Questions](https://speedrunit.ru/questions/devops/), а сценарии из публичных interview reports нормализованы для единого формата тренажёра. Формулировки не выдаются за дословные вопросы конкретных компаний.

## Структура проекта

```text
app/main.py              FastAPI API и SQLite-миграция
app/questions_seed.json  Стартовая база вопросов
app/static/              Интерфейс приложения
docker-compose.yml       Запуск в Docker
```
