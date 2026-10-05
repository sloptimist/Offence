FROM python:3.12-slim@sha256:02108f5d322dd89f1c9e552442c25acb0543dfdbc455693a5599624f20d9155d
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 PIP_NO_CACHE_DIR=1
WORKDIR /app
COPY requirements.lock ./
RUN pip install --no-cache-dir -r requirements.lock
COPY offence ./offence
RUN groupadd -g 10001 offence && useradd -u 10001 -g offence -M -s /usr/sbin/nologin offence \
    && mkdir /data && chown 10001:10001 /data
USER 10001:10001
EXPOSE 8080
VOLUME /data
CMD ["python", "-m", "offence.cli", "serve", "--data", "/data", "--host", "0.0.0.0", "--port", "8080"]
