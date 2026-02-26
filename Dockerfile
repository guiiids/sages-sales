

######## Deps: build wheels (cached) ########
FROM python:3.11-slim AS deps
WORKDIR /w
# Only needed if any deps compile; drop if all are manylinux wheels
RUN apt-get update && apt-get install -y --no-install-recommends build-essential \
  && rm -rf /var/lib/apt/lists/*
COPY requirements.txt .
RUN --mount=type=cache,target=/root/.cache/pip \
  pip install -U pip wheel setuptools && \
  pip wheel --prefer-binary -r requirements.txt -w /wheels

######## App: small, fast to push ########
FROM python:3.11-slim AS app
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends curl \
  && rm -rf /var/lib/apt/lists/*
COPY --from=deps /wheels /wheels
RUN pip install --no-cache-dir /wheels/* && rm -rf /wheels

# app files last for cache hits
COPY . .
RUN sed -i 's/\r$//' ./startup.sh && chmod +x ./startup.sh

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=5 \
  CMD curl -fsS "http://127.0.0.1:${PORT:-${WEBSITES_PORT:-8000}}/healthz" || exit 1
CMD ["./startup.sh","gunicorn","-c","gunicorn_config.py","run:app"]

######## Optional: debug target with SSH ########
FROM app AS debug-ssh
RUN apt-get update && apt-get install -y --no-install-recommends openssh-server \
  && rm -rf /var/lib/apt/lists/* \
  && mkdir -p /var/run/sshd \
  && echo 'PermitRootLogin yes' >> /etc/ssh/sshd_config \
  && echo 'Port 2222' >> /etc/ssh/sshd_config \
  && echo 'PasswordAuthentication yes' >> /etc/ssh/sshd_config \
  && echo 'root:root' | chpasswd