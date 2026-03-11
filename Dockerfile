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

# Expose dashboard port (Railway/Render inject $PORT at runtime)
EXPOSE 8000

# Start the dashboard — $PORT is set by Railway/Render, fallback 8000
CMD ["sh", "-c", "uvicorn ui.api:app --host 0.0.0.0 --port ${PORT:-8000}"]
