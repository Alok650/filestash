FROM python:3.11-slim

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV DEBIAN_FRONTEND=noninteractive

WORKDIR /app

# Install system dependencies
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy project files
COPY . .

# Create necessary directories and set permissions
RUN mkdir -p media staticfiles data && \
    chmod -R 777 media staticfiles data

# Collect static files (requires a dummy SECRET_KEY if not in environment)
RUN DJANGO_SECRET_KEY=build-time-only-key python manage.py collectstatic --noinput

# Make start script executable
RUN chmod +x start.sh

EXPOSE 8000

CMD ["./start.sh"]