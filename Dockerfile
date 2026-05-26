FROM python:3.11-slim

WORKDIR /app

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy app files
COPY server.py .
COPY index.html .

# monitor_log.json and fail_count.txt will be volume-mounted or
# fetched from the repo — Railway will have them from the repo clone
# Create empty defaults so the app starts clean if files are missing
RUN echo "[]" > monitor_log.json && echo "0" > fail_count.txt

EXPOSE 8000

CMD ["uvicorn", "server:app", "--host", "0.0.0.0", "--port", "8000"]