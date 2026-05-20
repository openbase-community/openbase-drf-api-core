# API Core

This repo provides the backbone of all Django webapps/APIs. It is a framework that these webapps/APIs fit into and can rely on, with a shared `settings.py` file, logic regarding users, contact, and email. To add functionality, you can install "app packages", which are pip packages containing one or more Django apps that will automatically have their URLs and models imported.

## Local Setup

Use the workspace-level setup script for a full local install:

`./scripts/setup`

For coding agents or other unattended environments, use:

`./scripts/setup --non-interactive`

Non-interactive setup behavior:

- Requires the workspace `.env` file to already exist and exits immediately if it does not.
- Creates or updates the default development superuser without prompting.
- Defaults to `test@example.com` / `test` for the development superuser.
- Allows overriding the default superuser with `DEV_SUPERUSER_EMAIL` and `DEV_SUPERUSER_PASSWORD`.
- Skips Google OAuth setup if credentials are not provided.
- Allows providing Google OAuth credentials through `GOOGLE_OAUTH_CREDENTIALS_JSON`.

## Production Deployment

Use the sibling `deploy` repo and the `openbase-deploy` CLI for AWS/Terraform/ECS deployment. This repo keeps only local development scripts under `scripts/`.

Deployment metadata is stored outside the repo at:

`~/.openbase/deployments/<stack-name>/<environment>/deployment.toml`

If that file does not exist for `openbase-api-core`, initialize it before building or applying:

```bash
openbase-deploy init-stack openbase-api-core prod \
  --web-hostname api.example.com \
  --web-hostname app.example.com \
  --cdn-hostname assets.example.com \
  --web-command "/app/.venv/bin/gunicorn config.asgi:application --log-file - -k uvicorn.workers.UvicornWorker --bind 0.0.0.0:8000" \
  --worker-command "/app/.venv/bin/taskiq worker --log-level=INFO --max-threadpool-threads=2 config.taskiq_config:broker config.taskiq_tasks" \
  --deploy-command "/app/.venv/bin/python manage.py migrate" \
  --app-requirement git+https://github.com/openbase-community/openbase-cloud-api
```

The `openbase-deploy` stack shape is always web + worker, but the deploy one-off command is app-specific metadata. For this Django app it is usually migrations; it is not hard-coded into the deploy tool.

Repeat `--web-hostname` and `--cdn-hostname` for every domain that should point at the same server. Use `openbase-deploy domains add` to add aliases later, then run `apply` and `cloudflare-setup`.

Typical flow:

```bash
openbase-deploy build openbase-api-core prod --app-dir .
OPENBASE_DEPLOY_DB_PASSWORD='...' openbase-deploy apply openbase-api-core prod --auto-approve
CLOUDFLARE_API_TOKEN='...' openbase-deploy cloudflare-setup openbase-api-core prod
openbase-deploy deploy openbase-api-core prod
```

For operator-managed app config, use SSM-backed metadata:

```bash
openbase-deploy config set openbase-api-core prod STRIPE_SECRET_KEY
openbase-deploy config unset openbase-api-core prod STRIPE_SECRET_KEY
```

Do not commit generated tfvars, local deployment metadata, or secret values.
