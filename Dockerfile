FROM python:3.11-slim

WORKDIR /app

# Install cron + system deps
RUN apt-get update && apt-get install -y cron && rm -rf /var/lib/apt/lists/*

# Install Python deps
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Install Playwright Chromium
RUN playwright install chromium && playwright install-deps chromium

# Copy all app files
COPY server.py .
COPY monitor.py .
COPY index.html .

# Create default state files
RUN echo "[]" > monitor_log.json && echo "0" > fail_count.txt

# Add cron job: every 5 min Mon-Fri, NPT 11:00-15:00 = UTC 05:15-09:15
RUN echo "*/5 5-9 * * 1-5 cd /app && python monitor.py >> /var/log/monitor_cron.log 2>&1" \
    | crontab -

EXPOSE 8000

# Start both cron and uvicorn
CMD cron && uvicorn server:app --host 0.0.0.0 --port 8000