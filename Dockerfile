FROM python:3.11-slim

WORKDIR /app

# Install deps
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy source
COPY agent/       ./agent/
COPY ui/          ./ui/
COPY main.py      ./main.py
COPY .env.example ./.env.example

# Railway/Render set $PORT at runtime
EXPOSE 8000

# Start server — use $PORT if set (Railway/Render), otherwise 8000
CMD ["sh", "-c", "uvicorn ui.api:app --host 0.0.0.0 --port ${PORT:-8000} --timeout-keep-alive 75"]

