# builder stage
FROM python:3.12-slim AS builder

ENV PYTHONDONTWRITEBYTECODE=1  

WORKDIR /build 

COPY requirements.txt . 

RUN pip install --no-cache-dir --no-warn-script-location --user --root-user-action=ignore -r requirements.txt

# production stage 
FROM python:3.12-slim AS production

ENV PYTHONDONTWRITEBYTECODE=1

WORKDIR /app

# copy Python packages from builder stage
COPY --from=builder /root/.local /root/.local 

COPY . /app

EXPOSE 8000

CMD ["python3", "-m", "app.main"]