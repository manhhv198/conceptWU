# Use official Playwright image (includes Python & Browsers)
FROM mcr.microsoft.com/playwright/python:v1.40.0-jammy

# Install system dependencies
# fonts-liberation, fontconfig etc. are good for rendering text in screenshots if needed
# local-locales for timezone maybe?
RUN apt-get update && apt-get install -y \
    fonts-liberation \
    fontconfig \
    && rm -rf /var/lib/apt/lists/*

# Set timezone to Vietnam (optional but good for logs)
ENV TZ=Asia/Ho_Chi_Minh
RUN ln -snf /usr/share/zoneinfo/$TZ /etc/localtime && echo $TZ > /etc/timezone

WORKDIR /app

# Copy requirements
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy all application code
COPY . .

# Set environment variable to ensure output buffering is off
ENV PYTHONUNBUFFERED=True

# WORKDIR is /app, but Cloud Run filesystem is read-only except /tmp
# Strategy: We can run scripts from /app, but they must write to /tmp.
# We change WORKDIR to /tmp so relative writes go there.
# BUT we need to make sure python can find the scripts in /app.
ENV PYTHONPATH=/app

WORKDIR /tmp

# Entrypoint
# We run the cloud_runner.py which is located in /app (via PYTHONPATH or absolute path)
CMD ["python", "/app/cloud_runner.py"]
