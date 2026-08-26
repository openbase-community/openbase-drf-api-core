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

`~/.openbase/deployments/<deployment-name>/deployment.toml`

Each deployment picks its own stack name and the app package(s) to install on
top of the backbone via `--app-requirement`. The example below uses the stack
name `openbase-api-core` and installs `openbase-cloud-api` as one example
consuming app; substitute your own stack name and app requirement(s).

If that stack's metadata does not exist yet, initialize it before building or applying:

```bash
openbase-deploy init-stack <stack-name> \
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
openbase-deploy build openbase-api-core --app-dir .
OPENBASE_DEPLOY_DB_PASSWORD='...' openbase-deploy apply openbase-api-core --auto-approve
CLOUDFLARE_API_TOKEN='...' openbase-deploy cloudflare-setup openbase-api-core
openbase-deploy deploy openbase-api-core
```

For operator-managed app config, use SSM-backed metadata:

```bash
openbase-deploy config set openbase-api-core STRIPE_SECRET_KEY
openbase-deploy config unset openbase-api-core STRIPE_SECRET_KEY
```

Do not commit generated tfvars, local deployment metadata, or secret values.

## Field-test users

**Field tests** are agent-driven, end-to-end tests that install the product
clean-room in a VM and run through real signup/usage flows against production
Openbase Cloud. Each run needs a fresh user, but real inboxes are scarce, so
field-test users live under reserved `example.com` identities managed by the
`field_test_user` management command.

### Reserved-identity contract

Every field-test user has an email matching exactly:

```
^field-test-[a-z0-9-]+@example\.com$
```

`example.com` is one of the domains the Resend email backend filters (see
`config/email.py` `is_filtered_email_address`), so these users send and receive
**zero** real mail and carry no deliverability/spam-score risk. Because they can
never receive verification or payment email, the command provisions those
directly:

- The primary email is marked **verified** (django-allauth `EmailAddress`).
- Paid entitlement is **faked with a local `payment.Subscription` row only** —
  no Stripe checkout, subscription, or charge is ever created. This is
  exclusively for field-test users; never point it at a real account.

### Usage

The command has three mutually exclusive actions, each taking a `SLUG`, and
emits a single line of JSON to stdout so the field-test harness can consume the
email, generated password, and user id:

```bash
# Create field-test-<slug>@example.com (fails if it already exists).
python manage.py field_test_user --create ci-run-42
# -> {"action": "create", "email": "field-test-ci-run-42@example.com",
#     "user_id": 123, "password": "…", "verified": true, "entitled": true}

# Destroy (idempotent no-op if absent). Cascade-cleans owned data.
python manage.py field_test_user --destroy ci-run-42

# Destroy-if-exists then create — a guaranteed-fresh user.
python manage.py field_test_user --recycle ci-run-42
```

Run it locally with `uv run python manage.py field_test_user …`, and against a
deployed Openbase Cloud app with the CLI's exec convention:

```bash
openbase run -a <app> python manage.py field_test_user --recycle ci-run-42
```

### Safety contract

- The email pattern above is the primary contract **and** the guardrail: the
  command refuses — loudly, before any write — to destroy or modify any user
  whose email does not match it (realistic near-misses like
  `field-test-x@example.com.evil.com` or `gabe@openbase.cloud` are rejected).
- Destruction reuses the canonical account-deletion path (`user.delete()`, the
  same cascade as `users.views.DeleteUserView`), so owned data is cleaned
  exactly like a real account deletion — no hand-rolled partial delete.

The consolidated field-testing skill and testing-tiers spec live in a parallel
change on the `field-testing-taxonomy` branch of the `openbase-coder-workspace`
repo.
