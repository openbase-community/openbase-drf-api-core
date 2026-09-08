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

**Field tests** are agent-driven, end-to-end tests that install the product clean-room in a VM and exercise production Openbase Cloud. A field test creates its throwaway user through the real product signup flow, receives the real allauth verification message through Resend's official testing-recipient mechanism, and completes normal email verification. It never uses a personal address or inbox.

### Guardrail: reserved testing namespace

Every lifecycle action requires an address matching `delivered+openbase-field-<slug>@resend.dev`, using an opaque run-specific slug. Each field test may generate a fresh address without changing deployment configuration. The `+` form is permitted only for this exact Resend testing-recipient contract; personal-provider addresses and every other plus-address are rejected.

### Real signup and verification

The field-test agent generates a strong ephemeral password locally, drives the normal signup UI with a fresh reserved Resend testing recipient, waits for the selected Cloud deployment to render and submit the verification message, and retrieves that exact message through an authenticated Resend CLI profile. The active/default profile is acceptable; a separate field-test-specific profile is not required. The Resend credential remains in secure CLI storage: never pass an API key through `--api-key`, command arguments, reports, or logs.

Use message metadata to select only the exact recipient created after the run began, then retrieve that message by its id:

```bash
resend emails list --profile <field-test-profile> --limit 100 --json
resend emails get --profile <field-test-profile> <message-id> --json
```

The agent follows the confirmation URL from the returned HTML/text through the tested app/browser surface so allauth performs the real verification transition. Verification URLs are bearer credentials: never copy one into an RMOT, report, Slack message, shell history, or test log. If the scoped Resend profile is unavailable or no exact post-start message arrives, the field test is blocked; never fall back to a human inbox or mark the address verified out of band.

### Lifecycle command

`field_test_account` deliberately cannot create or verify a user. It only performs guarded cleanup and optional local paid entitlement around the real signup flow:

```bash
python manage.py field_test_account --destroy delivered+openbase-field-20260901-a7f3@resend.dev
python manage.py field_test_account --mock-payment delivered+openbase-field-20260901-a7f3@resend.dev
```

Typical field-test flow:

1. Confirm the exact Resend testing recipient is allowlisted, record the run start time, and run `field_test_account --destroy EMAIL` to clear a prior account if the address is being reused.
2. Drive real signup, retrieve the exact post-start Resend message, and complete real allauth verification through the product.
3. Run `field_test_account --mock-payment EMAIL` only after verification when paid features are in scope.
4. Run the product test, then always finish with `field_test_account --destroy EMAIL`.

Run the lifecycle command locally with `uv run python manage.py field_test_account …`, and against a deployed Openbase Cloud app with `openbase run`:

```bash
openbase run -a <app> python manage.py field_test_account \
  --destroy delivered+openbase-field-20260901-a7f3@resend.dev
```

### Safety contract

- Exact allowlist and Resend-recipient guards run before account reads/writes and again against fetched users. Staff and superuser accounts are always refused.
- User creation, password validation, mandatory verification, email template rendering, Resend submission, and allauth confirmation all run through their normal production paths.
- Destruction reuses the canonical account-deletion path (`user.delete()`, the same cascade as `users.views.DeleteUserView`), so owned data is cleaned exactly like a real account deletion.
- `--mock-payment` requires an already verified email and only writes a local `payment.Subscription` row; it makes no payment-provider call.
- A dedicated delivery canary may separately test receipt by a real mailbox provider. Core field tests use Resend's testing recipient and never a personal inbox.

The consolidated field-testing skill and testing-tiers spec live in the
`openbase-coder-workspace` repo.
