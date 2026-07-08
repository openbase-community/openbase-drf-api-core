FROM public.ecr.aws/docker/library/python:3.14-slim

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
RUN apt-get update && apt-get install -y bash ffmpeg curl postgresql-client git awscli

COPY nocache.txt /tmp/nocache.txt

WORKDIR /app
COPY . /app
COPY private_github_repos.txt /tmp/private_github_repos.txt

RUN --mount=type=secret,id=gh_pat \
    --mount=type=secret,id=openbase_platform_github_token \
    GH_PAT="$(cat /run/secrets/gh_pat 2>/dev/null || true)" && \
    OPENBASE_PLATFORM_GITHUB_TOKEN="$(cat /run/secrets/openbase_platform_github_token 2>/dev/null || true)" && \
    if [ -n "${OPENBASE_PLATFORM_GITHUB_TOKEN}" ]; then \
        git config --global url."https://x-access-token:${OPENBASE_PLATFORM_GITHUB_TOKEN}@github.com/openbase-community/".insteadOf "https://github.com/openbase-community/"; \
    fi && \
    if [ -n "${GH_PAT}" ]; then \
        git config --global url."https://x-access-token:${GH_PAT}@github.com/".insteadOf "https://github.com/"; \
    fi && \
    uv sync --frozen --no-dev --no-editable && \
    uv pip install --python /app/.venv/bin/python . && \
    if [ -n "${OPENBASE_PLATFORM_GITHUB_TOKEN}" ]; then \
        git config --global --unset url."https://x-access-token:${OPENBASE_PLATFORM_GITHUB_TOKEN}@github.com/openbase-community/".insteadOf; \
    fi && \
    if [ -n "${GH_PAT}" ]; then \
        git config --global --unset url."https://x-access-token:${GH_PAT}@github.com/".insteadOf; \
    fi

# Private repos are installed one-per-RUN (sed -n '1p', '2p', ...) on purpose:
# each repo gets its own Docker layer so editing or bumping one private
# requirement only busts that repo's cached layer, not all of them. This
# repetition is intentional and must not be collapsed into a single loop.
RUN --mount=type=secret,id=gh_pat \
    --mount=type=secret,id=openbase_platform_github_token \
    GH_PAT="$(cat /run/secrets/gh_pat 2>/dev/null || true)" && \
    OPENBASE_PLATFORM_GITHUB_TOKEN="$(cat /run/secrets/openbase_platform_github_token 2>/dev/null || true)" && \
    if [ -n "${OPENBASE_PLATFORM_GITHUB_TOKEN}" ]; then \
        git config --global url."https://x-access-token:${OPENBASE_PLATFORM_GITHUB_TOKEN}@github.com/openbase-community/".insteadOf "https://github.com/openbase-community/"; \
    fi && \
    if [ -n "${GH_PAT}" ]; then \
        git config --global url."https://x-access-token:${GH_PAT}@github.com/".insteadOf "https://github.com/"; \
    fi && \
    if [ -s /tmp/private_github_repos.txt ]; then \
        sed -n '1p' /tmp/private_github_repos.txt | xargs -r uv pip install --python /app/.venv/bin/python; \
    fi && \
    if [ -n "${OPENBASE_PLATFORM_GITHUB_TOKEN}" ]; then \
        git config --global --unset url."https://x-access-token:${OPENBASE_PLATFORM_GITHUB_TOKEN}@github.com/openbase-community/".insteadOf; \
    fi && \
    if [ -n "${GH_PAT}" ]; then \
        git config --global --unset url."https://x-access-token:${GH_PAT}@github.com/".insteadOf; \
    fi

RUN --mount=type=secret,id=gh_pat \
    --mount=type=secret,id=openbase_platform_github_token \
    GH_PAT="$(cat /run/secrets/gh_pat 2>/dev/null || true)" && \
    OPENBASE_PLATFORM_GITHUB_TOKEN="$(cat /run/secrets/openbase_platform_github_token 2>/dev/null || true)" && \
    if [ -n "${OPENBASE_PLATFORM_GITHUB_TOKEN}" ]; then \
        git config --global url."https://x-access-token:${OPENBASE_PLATFORM_GITHUB_TOKEN}@github.com/openbase-community/".insteadOf "https://github.com/openbase-community/"; \
    fi && \
    if [ -n "${GH_PAT}" ]; then \
        git config --global url."https://x-access-token:${GH_PAT}@github.com/".insteadOf "https://github.com/"; \
    fi && \
    if [ -s /tmp/private_github_repos.txt ]; then \
        sed -n '2p' /tmp/private_github_repos.txt | xargs -r uv pip install --python /app/.venv/bin/python; \
    fi && \
    if [ -n "${OPENBASE_PLATFORM_GITHUB_TOKEN}" ]; then \
        git config --global --unset url."https://x-access-token:${OPENBASE_PLATFORM_GITHUB_TOKEN}@github.com/openbase-community/".insteadOf; \
    fi && \
    if [ -n "${GH_PAT}" ]; then \
        git config --global --unset url."https://x-access-token:${GH_PAT}@github.com/".insteadOf; \
    fi

RUN --mount=type=secret,id=gh_pat \
    --mount=type=secret,id=openbase_platform_github_token \
    GH_PAT="$(cat /run/secrets/gh_pat 2>/dev/null || true)" && \
    OPENBASE_PLATFORM_GITHUB_TOKEN="$(cat /run/secrets/openbase_platform_github_token 2>/dev/null || true)" && \
    if [ -n "${OPENBASE_PLATFORM_GITHUB_TOKEN}" ]; then \
        git config --global url."https://x-access-token:${OPENBASE_PLATFORM_GITHUB_TOKEN}@github.com/openbase-community/".insteadOf "https://github.com/openbase-community/"; \
    fi && \
    if [ -n "${GH_PAT}" ]; then \
        git config --global url."https://x-access-token:${GH_PAT}@github.com/".insteadOf "https://github.com/"; \
    fi && \
    if [ -s /tmp/private_github_repos.txt ]; then \
        sed -n '3p' /tmp/private_github_repos.txt | xargs -r uv pip install --python /app/.venv/bin/python; \
    fi && \
    if [ -n "${OPENBASE_PLATFORM_GITHUB_TOKEN}" ]; then \
        git config --global --unset url."https://x-access-token:${OPENBASE_PLATFORM_GITHUB_TOKEN}@github.com/openbase-community/".insteadOf; \
    fi && \
    if [ -n "${GH_PAT}" ]; then \
        git config --global --unset url."https://x-access-token:${GH_PAT}@github.com/".insteadOf; \
    fi

RUN --mount=type=secret,id=gh_pat \
    --mount=type=secret,id=openbase_platform_github_token \
    GH_PAT="$(cat /run/secrets/gh_pat 2>/dev/null || true)" && \
    OPENBASE_PLATFORM_GITHUB_TOKEN="$(cat /run/secrets/openbase_platform_github_token 2>/dev/null || true)" && \
    if [ -n "${OPENBASE_PLATFORM_GITHUB_TOKEN}" ]; then \
        git config --global url."https://x-access-token:${OPENBASE_PLATFORM_GITHUB_TOKEN}@github.com/openbase-community/".insteadOf "https://github.com/openbase-community/"; \
    fi && \
    if [ -n "${GH_PAT}" ]; then \
        git config --global url."https://x-access-token:${GH_PAT}@github.com/".insteadOf "https://github.com/"; \
    fi && \
    if [ -s /tmp/private_github_repos.txt ]; then \
        sed -n '4p' /tmp/private_github_repos.txt | xargs -r uv pip install --python /app/.venv/bin/python; \
    fi && \
    if [ -n "${OPENBASE_PLATFORM_GITHUB_TOKEN}" ]; then \
        git config --global --unset url."https://x-access-token:${OPENBASE_PLATFORM_GITHUB_TOKEN}@github.com/openbase-community/".insteadOf; \
    fi && \
    if [ -n "${GH_PAT}" ]; then \
        git config --global --unset url."https://x-access-token:${GH_PAT}@github.com/".insteadOf; \
    fi

RUN --mount=type=secret,id=gh_pat \
    --mount=type=secret,id=openbase_platform_github_token \
    GH_PAT="$(cat /run/secrets/gh_pat 2>/dev/null || true)" && \
    OPENBASE_PLATFORM_GITHUB_TOKEN="$(cat /run/secrets/openbase_platform_github_token 2>/dev/null || true)" && \
    if [ -n "${OPENBASE_PLATFORM_GITHUB_TOKEN}" ]; then \
        git config --global url."https://x-access-token:${OPENBASE_PLATFORM_GITHUB_TOKEN}@github.com/openbase-community/".insteadOf "https://github.com/openbase-community/"; \
    fi && \
    if [ -n "${GH_PAT}" ]; then \
        git config --global url."https://x-access-token:${GH_PAT}@github.com/".insteadOf "https://github.com/"; \
    fi && \
    if [ -s /tmp/private_github_repos.txt ]; then \
        sed -n '5p' /tmp/private_github_repos.txt | xargs -r uv pip install --python /app/.venv/bin/python; \
    fi && \
    if [ -n "${OPENBASE_PLATFORM_GITHUB_TOKEN}" ]; then \
        git config --global --unset url."https://x-access-token:${OPENBASE_PLATFORM_GITHUB_TOKEN}@github.com/openbase-community/".insteadOf; \
    fi && \
    if [ -n "${GH_PAT}" ]; then \
        git config --global --unset url."https://x-access-token:${GH_PAT}@github.com/".insteadOf; \
    fi

RUN --mount=type=secret,id=gh_pat \
    --mount=type=secret,id=openbase_platform_github_token \
    GH_PAT="$(cat /run/secrets/gh_pat 2>/dev/null || true)" && \
    OPENBASE_PLATFORM_GITHUB_TOKEN="$(cat /run/secrets/openbase_platform_github_token 2>/dev/null || true)" && \
    if [ -n "${OPENBASE_PLATFORM_GITHUB_TOKEN}" ]; then \
        git config --global url."https://x-access-token:${OPENBASE_PLATFORM_GITHUB_TOKEN}@github.com/openbase-community/".insteadOf "https://github.com/openbase-community/"; \
    fi && \
    if [ -n "${GH_PAT}" ]; then \
        git config --global url."https://x-access-token:${GH_PAT}@github.com/".insteadOf "https://github.com/"; \
    fi && \
    if [ -s /tmp/private_github_repos.txt ]; then \
        sed -n '6p' /tmp/private_github_repos.txt | xargs -r uv pip install --python /app/.venv/bin/python; \
    fi && \
    if [ -n "${OPENBASE_PLATFORM_GITHUB_TOKEN}" ]; then \
        git config --global --unset url."https://x-access-token:${OPENBASE_PLATFORM_GITHUB_TOKEN}@github.com/openbase-community/".insteadOf; \
    fi && \
    if [ -n "${GH_PAT}" ]; then \
        git config --global --unset url."https://x-access-token:${GH_PAT}@github.com/".insteadOf; \
    fi

RUN --mount=type=secret,id=gh_pat \
    --mount=type=secret,id=openbase_platform_github_token \
    GH_PAT="$(cat /run/secrets/gh_pat 2>/dev/null || true)" && \
    OPENBASE_PLATFORM_GITHUB_TOKEN="$(cat /run/secrets/openbase_platform_github_token 2>/dev/null || true)" && \
    if [ -n "${OPENBASE_PLATFORM_GITHUB_TOKEN}" ]; then \
        git config --global url."https://x-access-token:${OPENBASE_PLATFORM_GITHUB_TOKEN}@github.com/openbase-community/".insteadOf "https://github.com/openbase-community/"; \
    fi && \
    if [ -n "${GH_PAT}" ]; then \
        git config --global url."https://x-access-token:${GH_PAT}@github.com/".insteadOf "https://github.com/"; \
    fi && \
    if [ -s /tmp/private_github_repos.txt ]; then \
        sed -n '7p' /tmp/private_github_repos.txt | xargs -r uv pip install --python /app/.venv/bin/python; \
    fi && \
    if [ -n "${OPENBASE_PLATFORM_GITHUB_TOKEN}" ]; then \
        git config --global --unset url."https://x-access-token:${OPENBASE_PLATFORM_GITHUB_TOKEN}@github.com/openbase-community/".insteadOf; \
    fi && \
    if [ -n "${GH_PAT}" ]; then \
        git config --global --unset url."https://x-access-token:${GH_PAT}@github.com/".insteadOf; \
    fi

RUN --mount=type=secret,id=gh_pat \
    --mount=type=secret,id=openbase_platform_github_token \
    GH_PAT="$(cat /run/secrets/gh_pat 2>/dev/null || true)" && \
    OPENBASE_PLATFORM_GITHUB_TOKEN="$(cat /run/secrets/openbase_platform_github_token 2>/dev/null || true)" && \
    if [ -n "${OPENBASE_PLATFORM_GITHUB_TOKEN}" ]; then \
        git config --global url."https://x-access-token:${OPENBASE_PLATFORM_GITHUB_TOKEN}@github.com/openbase-community/".insteadOf "https://github.com/openbase-community/"; \
    fi && \
    if [ -n "${GH_PAT}" ]; then \
        git config --global url."https://x-access-token:${GH_PAT}@github.com/".insteadOf "https://github.com/"; \
    fi && \
    if [ -s /tmp/private_github_repos.txt ]; then \
        sed -n '8p' /tmp/private_github_repos.txt | xargs -r uv pip install --python /app/.venv/bin/python; \
    fi && \
    if [ -n "${OPENBASE_PLATFORM_GITHUB_TOKEN}" ]; then \
        git config --global --unset url."https://x-access-token:${OPENBASE_PLATFORM_GITHUB_TOKEN}@github.com/openbase-community/".insteadOf; \
    fi && \
    if [ -n "${GH_PAT}" ]; then \
        git config --global --unset url."https://x-access-token:${GH_PAT}@github.com/".insteadOf; \
    fi

RUN --mount=type=secret,id=gh_pat \
    --mount=type=secret,id=openbase_platform_github_token \
    GH_PAT="$(cat /run/secrets/gh_pat 2>/dev/null || true)" && \
    OPENBASE_PLATFORM_GITHUB_TOKEN="$(cat /run/secrets/openbase_platform_github_token 2>/dev/null || true)" && \
    if [ -n "${OPENBASE_PLATFORM_GITHUB_TOKEN}" ]; then \
        git config --global url."https://x-access-token:${OPENBASE_PLATFORM_GITHUB_TOKEN}@github.com/openbase-community/".insteadOf "https://github.com/openbase-community/"; \
    fi && \
    if [ -n "${GH_PAT}" ]; then \
        git config --global url."https://x-access-token:${GH_PAT}@github.com/".insteadOf "https://github.com/"; \
    fi && \
    if [ -s /tmp/private_github_repos.txt ]; then \
        sed -n '9p' /tmp/private_github_repos.txt | xargs -r uv pip install --python /app/.venv/bin/python; \
    fi && \
    if [ -n "${OPENBASE_PLATFORM_GITHUB_TOKEN}" ]; then \
        git config --global --unset url."https://x-access-token:${OPENBASE_PLATFORM_GITHUB_TOKEN}@github.com/openbase-community/".insteadOf; \
    fi && \
    if [ -n "${GH_PAT}" ]; then \
        git config --global --unset url."https://x-access-token:${GH_PAT}@github.com/".insteadOf; \
    fi

# Creates a non-root user with an explicit UID and adds permission to access the /app folder
# For more info, please refer to https://aka.ms/vscode-docker-python-configure-containers
RUN adduser -u 5678 --disabled-password --gecos "" appuser && chown -R appuser /app
USER appuser
