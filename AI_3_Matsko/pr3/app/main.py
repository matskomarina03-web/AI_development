"""Веб-рівень застосунку: сторінка зі зверненням і JSON-ендпоінт.

Цей файл не має знати ані про провайдера моделі, ані про те, як
складається запит до неї, — усе це лишається в `app/llm.py`. Тут
вирішується інше: що застосунок віддає клієнтові та з яким HTTP-статусом.

Запуск із папки pr3:

    uvicorn app.main:app --reload

Далі відкрийте http://127.0.0.1:8000
"""

import logging
import time
from logging.handlers import RotatingFileHandler
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

from . import llm

app = FastAPI(title="Помічник служби підтримки — ПР3")

INDEX_PAGE = Path(__file__).parent / "templates" / "index.html"
CONTEXT_FILE = Path(__file__).parent.parent / "context.md"
LOG_DIR = Path(__file__).parent.parent / "logs"
LOG_DIR.mkdir(exist_ok=True)

logger = logging.getLogger("pr3")
if not logger.handlers:
    handler = RotatingFileHandler(
        LOG_DIR / "app.log",
        maxBytes=1_000_000,
        backupCount=3,
        encoding="utf-8",
    )
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    logger.propagate = False


class Question(BaseModel):
    """Звернення користувача."""

    question: str


@app.middleware("http")
async def journal_requests(request: Request, call_next):
    """Записати результат HTTP-запиту без його вмісту."""
    started = time.perf_counter()
    try:
        response = await call_next(request)
    except Exception:
        logger.exception("request_failed method=%s path=%s", request.method, request.url.path)
        raise

    elapsed_ms = (time.perf_counter() - started) * 1000
    log = logger.warning if response.status_code >= 400 else logger.info
    log(
        "request_completed method=%s path=%s status=%s duration_ms=%.1f",
        request.method,
        request.url.path,
        response.status_code,
        elapsed_ms,
    )
    return response


def load_context() -> str:
    """Прочитати правила організації, на підставі яких відповідає модель."""
    if not CONTEXT_FILE.exists():
        raise HTTPException(status_code=500, detail="Файл context.md не знайдено")
    return CONTEXT_FILE.read_text(encoding="utf-8")


@app.get("/", response_class=HTMLResponse)
def index() -> str:
    """Віддати сторінку зі зверненням."""
    if not INDEX_PAGE.exists():
        raise HTTPException(status_code=500, detail="Файл index.html не знайдено")
    return INDEX_PAGE.read_text(encoding="utf-8")


@app.post("/api/ask")
def api_ask(payload: Question):
    """Повернути відповідь помічника у форматі JSON."""
    question = payload.question.strip()
    if not question:
        raise HTTPException(status_code=400, detail="Порожнє звернення")
    if len(question) > 1000:
        raise HTTPException(status_code=400, detail="Звернення надто довге")

    try:
        context = load_context()
        return llm.ask(question, context)
    except llm.LLMTimeoutError:
        raise HTTPException(status_code=504, detail="Таймаут звернення до сервісу") from None
    except llm.LLMRateLimitError:
        raise HTTPException(status_code=429, detail="Перевищено ліміт запитів до сервісу") from None
    except llm.LLMAuthError:
        logger.warning("model_auth_failed")
        raise HTTPException(status_code=401, detail="Невірний ключ або доступ до моделі заборонено") from None
    except llm.LLMInputError as exc:
        message = str(exc).lower()
        if "llm_base_url" in message or "llm_model" in message or "llm_api_key" in message or "налаштування" in message:
            raise HTTPException(status_code=500, detail="Не налаштовано підключення до моделі") from None
        raise HTTPException(status_code=400, detail="Некоректне звернення") from None
    except llm.LLMServiceError:
        raise HTTPException(status_code=503, detail="Помилка сервісу моделі") from None
    except HTTPException:
        raise
    except Exception:
        logger.exception("unhandled_api_error")
        raise HTTPException(status_code=500, detail="Внутрішня помилка застосунку") from None
