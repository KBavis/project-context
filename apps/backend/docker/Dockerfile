# builder stage
FROM python:3.12-slim AS builder

ENV PYTHONDONTWRITEBYTECODE=1  

WORKDIR /build 

# copy relevant corporate certs so pip can fetch dependencies over TLS-intercepting corporate networks
COPY docker/certs/ /usr/local/share/ca-certificates/

# install Debian helper for reading everything in `ca-certificates/` and generating a single bundle (ca-certificates.crt) 
RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates \
    && update-ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# point pip at system CA bundle (which includes corporate certs)
ENV PIP_CERT=/etc/ssl/certs/ca-certificates.crt \
    SSL_CERT_FILE=/etc/ssl/certs/ca-certificates.crt \
    REQUESTS_CA_BUNDLE=/etc/ssl/certs/ca-certificates.crt

COPY requirements.txt . 

# use docker buildkit to cache deps locally and reduce build times
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install --no-cache-dir --no-warn-script-location --user --root-user-action=ignore -r requirements.txt

# production stage 
FROM python:3.12-slim AS production

ENV PYTHONDONTWRITEBYTECODE=1

WORKDIR /app

# copy corporate certs again (required for runtime HTTP calls)
COPY docker/certs/ /usr/local/share/ca-certificates/

# install libGL, tesseract, Docker CLI, ca-certificates, and Node.js
RUN apt-get update && apt-get install -y \
    libgl1 \
    libglib2.0-0 \
    tesseract-ocr \
    git \
    curl \
    ca-certificates \
    gnupg \
    && update-ca-certificates \
    && curl -fsSL https://download.docker.com/linux/debian/gpg | gpg --dearmor -o /usr/share/keyrings/docker-archive-keyring.gpg \
    && echo "deb [arch=$(dpkg --print-architecture) signed-by=/usr/share/keyrings/docker-archive-keyring.gpg] https://download.docker.com/linux/debian $(. /etc/os-release && echo "$VERSION_CODENAME") stable" | tee /etc/apt/sources.list.d/docker.list > /dev/null \
    && curl -fsSL https://deb.nodesource.com/setup_20.x | bash - \
    && apt-get update && apt-get install -y \
    docker-ce-cli \
    nodejs \
    && rm -rf /var/lib/apt/lists/*

# point python at system CA bundle (which includes corporate certs)
ENV SSL_CERT_FILE=/etc/ssl/certs/ca-certificates.crt \
    REQUESTS_CA_BUNDLE=/etc/ssl/certs/ca-certificates.crt

# copy Python packages from builder stage
COPY --from=builder /root/.local /root/.local 

COPY . /app

# Configure git identity required for cherry-pick and other write operations
RUN git config --global user.email "contextualized@app.local" && \
    git config --global user.name "Contextualized"

EXPOSE 8000

CMD ["python3", "-m", "app.main"]