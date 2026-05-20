FROM python:3.14-slim

COPY --from=ghcr.io/astral-sh/uv:0.9.4 /uv /uvx /bin/

EXPOSE 8000

# Keeps Python from generating .pyc files in the container
ENV PYTHONDONTWRITEBYTECODE=1

# Turns off buffering for easier container logging
ENV PYTHONUNBUFFERED=1
ENV UV_PROJECT_ENVIRONMENT=/app/.venv
ENV UV_LINK_MODE=copy
ENV PATH="/app/.venv/bin:${PATH}"

# Install requirements
RUN apt-get update && apt-get install -y bash ffmpeg curl postgresql-client git

COPY nocache.txt /tmp/nocache.txt

WORKDIR /app
COPY . /app
COPY private_github_repos.txt /tmp/private_github_repos.txt

RUN --mount=type=secret,id=gh_pat \
    GH_PAT="$(cat /run/secrets/gh_pat 2>/dev/null || true)" && \
    if [ -n "${GH_PAT}" ]; then \
        git config --global url."https://${GH_PAT}:x-oauth-basic@github.com/".insteadOf "https://github.com/"; \
    fi && \
    uv sync --frozen --no-dev --no-editable && \
    uv pip install --python /app/.venv/bin/python . && \
    if [ -s /tmp/private_github_repos.txt ]; then \
        uv pip install --python /app/.venv/bin/python -r /tmp/private_github_repos.txt; \
    fi && \
    if [ -n "${GH_PAT}" ]; then \
        git config --global --unset url."https://${GH_PAT}:x-oauth-basic@github.com/".insteadOf; \
    fi

# Creates a non-root user with an explicit UID and adds permission to access the /app folder
# For more info, please refer to https://aka.ms/vscode-docker-python-configure-containers
RUN adduser -u 5678 --disabled-password --gecos "" appuser && chown -R appuser /app
USER appuser
