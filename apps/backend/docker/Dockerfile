# builder stage
FROM python:3.12-slim AS builder

ENV PYTHONDONTWRITEBYTECODE=1  

WORKDIR /build 

COPY requirements.txt . 

# user docker buildkit to cache deps locally and reduce build times
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install --no-cache-dir --no-warn-script-location --user --root-user-action=ignore -r requirements.txt

# production stage 
FROM python:3.12-slim AS production

ENV PYTHONDONTWRITEBYTECODE=1

WORKDIR /app

# install libGL, tesseract, Docker CLI, and Node.js
RUN apt-get update && apt-get install -y \
    libgl1 \
    libglib2.0-0 \
    tesseract-ocr \
    git \
    curl \
    ca-certificates \
    gnupg \
    && curl -fsSL https://download.docker.com/linux/debian/gpg | gpg --dearmor -o /usr/share/keyrings/docker-archive-keyring.gpg \
    && echo "deb [arch=$(dpkg --print-architecture) signed-by=/usr/share/keyrings/docker-archive-keyring.gpg] https://download.docker.com/linux/debian $(. /etc/os-release && echo "$VERSION_CODENAME") stable" | tee /etc/apt/sources.list.d/docker.list > /dev/null \
    && curl -fsSL https://deb.nodesource.com/setup_20.x | bash - \
    && apt-get update && apt-get install -y \
    docker-ce-cli \
    nodejs \
    && rm -rf /var/lib/apt/lists/*


# copy Python packages from builder stage
COPY --from=builder /root/.local /root/.local 

COPY . /app

EXPOSE 8000

CMD ["python3", "-m", "app.main"]