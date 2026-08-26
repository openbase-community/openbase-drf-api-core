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

## Field-test accounts

**Field tests** are agent-driven, end-to-end tests that install the product
clean-room in a VM and run through the *real* signup/usage flows against
production Openbase Cloud. So that signup and email verification are exercised
for real, a field test uses a real, designated account whose verification mail
lands in a Gabe-controlled inbox the testing agent can read.

Use **plus-addressing** to get unlimited distinct real signup addresses into one
inbox: `you+ci-run-42@gmail.com`, `you+ci-run-43@gmail.com`, … all deliver to
`you@gmail.com`, and each is a distinct account from Openbase's point of view.

The `field_test_account` management command does the two things the product's own
flows cannot safely do around a run. It never creates users and never mocks
email verification — those happen for real through the product.

### Guardrail: environment allowlist

The command refuses to touch any email that is not in an explicit allowlist read
from the `FIELD_TEST_ALLOWED_EMAILS` environment variable (comma-separated). If
that variable is empty or unset, the allowlist is empty and the command refuses
everything. A real customer can never be destroyed or mutated unless an operator
has deliberately listed their exact email.

```bash
export FIELD_TEST_ALLOWED_EMAILS="you+ci-run-42@gmail.com,you+ci-run-43@gmail.com"
```

### Usage

Both operations take an `EMAIL` and emit a single line of JSON to stdout for the
field-test harness:

```bash
# Pre-test: delete the designated user so the test can sign up from scratch.
python manage.py field_test_account --destroy you+ci-run-42@gmail.com
# -> {"action": "destroy", "email": "you+ci-run-42@gmail.com",
#     "destroyed": true, "user_id": 123}

# Mid-test, AFTER the real signup + real email verification: grant paid
# entitlement with a LOCAL payment.Subscription row (no Stripe charge).
python manage.py field_test_account --mock-payment you+ci-run-42@gmail.com
# -> {"action": "mock-payment", "email": "you+ci-run-42@gmail.com",
#     "user_id": 124, "entitled": true, "subscription_created": true}
```

Typical field-test flow:

1. `field_test_account --destroy EMAIL` (clear any prior account).
2. The test signs up as `EMAIL` for real through the product; the verification
   email arrives in the controlled inbox and the agent reads it to complete
   verification.
3. `field_test_account --mock-payment EMAIL` (grant paid entitlement so the test
   can exercise paid features).

Run it locally with `uv run python manage.py field_test_account …`, and against
a deployed Openbase Cloud app with the CLI's exec convention (the
`FIELD_TEST_ALLOWED_EMAILS` config var must be set on the app):

```bash
openbase run -a <app> python manage.py field_test_account --destroy you+ci-run-42@gmail.com
```

### Safety contract

- Only emails in `FIELD_TEST_ALLOWED_EMAILS` can be touched; the guardrail runs
  before any read/write and again against the fetched user's stored email.
  Realistic near-misses (`you+ci-run-42@gmail.com.evil.com`, a bare
  `you@gmail.com`, an unlisted `+tag`) are refused.
- Destruction reuses the canonical account-deletion path (`user.delete()`, the
  same cascade as `users.views.DeleteUserView`), so owned data is cleaned
  exactly like a real account deletion.
- `--mock-payment` only ever writes a local `payment.Subscription` row; it makes
  no payment-provider calls and is exclusively for field-test accounts.

The consolidated field-testing skill and testing-tiers spec live in the
`openbase-coder-workspace` repo.
