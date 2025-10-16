FROM python:3.13-alpine

RUN apk update && \
    # Для Alpine нужен пакет 'sqlite-libs'
    apk add sqlite-libs && \
    rm -rf /var/cache/apk/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

CMD ["python", "main.py"]
