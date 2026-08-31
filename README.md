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
clean-room in a VM and exercise production Openbase Cloud. Core product field
tests use a reserved throwaway user, never a personal address, personal inbox,
or plus-address. The `field_test_account` management command provisions that
user directly as verified without invoking signup or sending email.

### Guardrail: environment allowlist

Every action requires normalized exact membership in the comma-separated
`FIELD_TEST_ALLOWED_EMAILS` environment variable. Empty or unset denies all.
Allowlisting alone is insufficient: the address must also use an
`openbase-field-<slug>` local-part on `example.com`, `example.net`,
`example.org`, or a `.test`/`.invalid` domain. Personal-provider domains,
ordinary deliverable domains, and plus-addressing are categorically rejected
even if allowlisted.

```bash
export FIELD_TEST_ALLOWED_EMAILS="openbase-field-20260831@example.com"
```

### Provisioning and credential lifecycle

`--provision` reads the password only from `FIELD_TEST_ACCOUNT_PASSWORD` in the
task environment. There is no password argument, and the JSON result never
contains the password. Configure it as a temporary, write-only app secret using
a secret-input path that does not place its value in shell history or process
arguments (for example, the Openbase Cloud dashboard). Remove the secret after
the run account has been destroyed. Do not put it in tracked files.

With both variables present in the deployed app environment:

```bash
python manage.py field_test_account --provision openbase-field-20260831@example.com
# -> {"action":"provision","email":"openbase-field-20260831@example.com",
#     "user_id":123,"created":true,"verified":true,
#     "is_staff":false,"is_superuser":false}

python manage.py field_test_account --mock-payment openbase-field-20260831@example.com
python manage.py field_test_account --destroy openbase-field-20260831@example.com
```

Typical field-test flow:

1. `field_test_account --provision EMAIL` creates or refreshes the verified,
   active, nonstaff account and rotates its password from the environment.
2. `field_test_account --mock-payment EMAIL` grants local paid entitlement when
   the test needs paid features.
3. Run the core product test, then `field_test_account --destroy EMAIL` and
   remove the temporary password secret.

Run it locally with `uv run python manage.py field_test_account …`, and against
a deployed Openbase Cloud app with `openbase run`:

```bash
openbase run -a <app> python manage.py field_test_account \
  --provision openbase-field-20260831@example.com
```

### Safety contract

- Exact allowlist and reserved-identity guards run before account reads/writes
  and again against fetched users. Provisioning refuses staff/superuser and
  allauth email-ownership collisions.
- Provisioning creates the verified `EmailAddress`, auth token, and local
  account records directly. It does not invoke signup, email, Resend, Stripe, or
  other network paths. The Resend backend independently filters every reserved
  domain accepted by this command before provider invocation.
- Destruction reuses the canonical account-deletion path (`user.delete()`, the
  same cascade as `users.views.DeleteUserView`), so owned data is cleaned
  exactly like a real account deletion.
- `--mock-payment` only ever writes a local `payment.Subscription` row; it makes
  no payment-provider calls and is exclusively for field-test accounts.
- Email-delivery or onboarding-email tests are a separate, explicitly
  authorized test class with their own isolated recipient infrastructure. They
  never reuse a core field-test account or any personal inbox.

The consolidated field-testing skill and testing-tiers spec live in the
`openbase-coder-workspace` repo.
