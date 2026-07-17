FROM python:3.12-slim

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .
EXPOSE 8000
# Shell form so ${PORT} expands — Railway injects PORT at runtime and expects
# the app to bind to it; falls back to 8000 for local `docker run`.
CMD uvicorn backend.main:app --host 0.0.0.0 --port ${PORT:-8000}
