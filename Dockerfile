FROM python:3.11-slim
WORKDIR /app

# System deps: fonts for PDF unicode (Polish/German/Spanish chars), build tools
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        fontconfig \
        fonts-dejavu-core \
        fonts-liberation \
    && fc-cache -fv \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
RUN chmod +x scripts/docker-entrypoint.sh
EXPOSE 8008
ENTRYPOINT ["./scripts/docker-entrypoint.sh"]
