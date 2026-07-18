FROM python:3.12-slim

WORKDIR /app

COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY backend/ ./backend/
COPY frontend/ ./frontend/

EXPOSE 8010

CMD ["uvicorn", "app:app", "--app-dir", "backend", "--host", "0.0.0.0", "--port", "8010"]
