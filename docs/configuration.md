# Local settings

## Create the local settings file

From the project folder, copy the example if `.env` does not already exist. Keep your existing
`.env` if you have set up the app before.

```sh
test -f .env || cp .env.example .env
```

For a new `.env`, generate four secret keys using `openssl` in your terminal.

```sh
for key in SESSION ACTIVATION RATE_LIMIT AUDIT; do
  printf 'REVIEW_%s_HMAC_KEY=%s\n' "$key" "$(openssl rand -hex 32)"
done
```

Open `.env` in a text editor and replace the four lines with `HMAC_KEY` in their names with the four
printed lines. Keep these keys private and keep the same settings file between runs. The keys are
separate from the password you use on the sign-in page. The example already sets the database
address and points to the fictional dataset.

## Settings you might change later

| Setting | What it controls |
| --- | --- |
| `REVIEW_DATASET_PATH` | The SQLite file with the cases you want to load. [Import example](dataset.md) |
| `REVIEW_DATABASE_URL` | Where the app connects to PostgreSQL. |
| `REVIEW_MIGRATION_DATABASE_URL` | Which database `make migrate` updates. |
| `REVIEW_SOURCE_RENDER_ARTIFACT_ROOT` | Where the app saves prepared documents. The local default is `var/source_render`. |
| `REVIEW_ALLOWED_ORIGINS` and `REVIEW_ALLOWED_HOSTS` | The addresses allowed to reach the app. |
| `REVIEW_APP_BASE_URL` | The address in invitation and password reset links. |
| `REVIEW_EMAIL_MODE` | Where account messages go. `file` saves them in `var/email_outbox/` by default. |

The API uses port `8780`. Open `http://localhost:5273` to sign in. Docker runs PostgreSQL
on port `57432` by default.

## Hosting reference

The local settings are for trying the app on your computer. If you configure a hosted installation,
use `REVIEW_ENVIRONMENT=production`, HTTPS, secure cookies, persistent storage, separate migration
and app database credentials, and an SMTP sender. In production, you can create an administrator
with `python -m review_platform.bootstrap` after running migrations. The demo seed command is
available in development and test environments.

Back up PostgreSQL and the prepared document folder together.
