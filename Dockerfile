FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

COPY requirements.txt .
RUN pip install -r requirements.txt

COPY bot/ ./bot/
COPY webapp/ ./webapp/
COPY .env .env
COPY Price_by_KALYVAN.zip ./Price_by_KALYVAN.zip

EXPOSE 8080

CMD ["python", "-m", "bot.main"]
