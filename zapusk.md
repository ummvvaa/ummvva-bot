Вот команды по порядку.

**Запустить проект:**
```bash
docker compose up -d
docker compose -f evolution-compose.yml up -d
```
`-d` — в фоне, чтобы терминал остался свободным для логов.

Если менял код, `requirements.txt` или `.env` — пересобери образ:
```bash
docker compose up -d --build
```

**Смотреть логи (весь поток — бот + воркер):**
```bash
docker compose logs -f web worker
```
`-f` — живая прокрутка в реальном времени. Выход — `Ctrl+C` (контейнеры при этом продолжают работать).

---

Полезное рядом:

Проверить, что всё поднялось:
```bash
docker compose ps
```

Логи только одного сервиса:
```bash
docker compose logs -f worker
```

Перезапустить воркер (после изменений кода, чтобы Celery подхватил):
```bash
docker compose restart worker
```

Остановить проект:
```bash
docker compose down
```

Рабочий порядок для тестов: открой **два терминала** — в первом `docker compose up -d`, во втором сразу `docker compose logs -f web worker`. Дальше в админке (http://localhost:8000/admin/) или с телефона гоняешь сценарии, а во втором окне видишь весь поток: входящее → распознавание → заявка → отправка.