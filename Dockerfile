FROM python:3.11-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PORT=8000

# Copy application files
COPY requirements.txt /app/
RUN pip install --no-cache-dir -r requirements.txt || true

COPY . /app

RUN chmod +x /app/cellar

EXPOSE 8000

CMD ["python3", "-m", "wine_agent.server"]
