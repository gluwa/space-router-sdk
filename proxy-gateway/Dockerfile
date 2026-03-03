FROM python:3.12-slim

WORKDIR /app

# Install Tailscale for private mesh networking to Home Nodes
RUN apt-get update && \
    apt-get install -y curl && \
    curl -fsSL https://tailscale.com/install.sh | sh && \
    apt-get clean && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8080
EXPOSE 8081

CMD ["sh", "start.sh"]
