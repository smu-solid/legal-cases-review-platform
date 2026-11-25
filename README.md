# Review Platform

Review Platform helps teams check information extracted from court judgments. An administrator assigns
cases, reviewers check the values against the judgment, and adjudicators compare the reviews and
record decisions. The demo comes with 12 fictional cases and their documents.

## Run the demo on your computer

### What to install first

- **Docker with Compose** runs the PostgreSQL database. [Docker installation guide](https://docs.docker.com/compose/install/)
- **`uv`** sets up Python and the backend packages. [uv installation guide](https://docs.astral.sh/uv/getting-started/installation/)
- **Node.js 24** includes `npm`. Select version 24 on the [Node.js download page](https://nodejs.org/en/download).
- **`make`** runs the project shortcuts. If `make --version` fails, run `xcode-select --install`
  on macOS or `sudo apt install make` on Ubuntu or Debian.

Start Docker and open a Bash or Zsh terminal in the downloaded project folder. Docker runs the
database. You start the API and the web app in separate terminals.

### 1. Install dependencies and create your settings file

```sh
uv sync --locked --all-extras
npm --prefix apps/web ci
```

`uv sync` downloads Python 3.12 if needed and installs the backend packages. `npm ci` uses the
Node.js and `npm` you installed to set up the frontend packages.

Follow [Create the local settings file](docs/configuration.md#create-the-local-settings-file) to
create `.env` and fill in the four secret keys. Keep that file for later runs.

### 2. Start the database and load the fictional cases

```sh
docker compose -p review_platform_oss up -d --wait postgres
make migrate
REVIEW_DEMO_PASSWORD='replace-this-with-your-own-password' make demo
```

Replace the example password with one of your choice of at least 12 characters. The first command
downloads the PostgreSQL image if needed and waits for the database to be ready. You can skip a
separate PostgreSQL installation. `make migrate` creates the app's tables, and `make demo` loads the
cases and creates the demo accounts. Look for `Demo ready: 12 cases` before moving on.

### 3. Start the app and sign in

In one terminal, from the project folder, run `make api-run`. In a second terminal in the same
folder, run `make web-run`. Open [http://localhost:5273](http://localhost:5273) in Chrome or another
Chromium browser and sign in as `admin@example.test`. Use `localhost` as shown in the link.

The four accounts start with the password you chose in step 2.

| Email | Role |
| --- | --- |
| `admin@example.test` | Administrator and adjudicator |
| `reviewer1@example.test` | First reviewer |
| `reviewer2@example.test` | Second reviewer |
| `adjudicator@example.test` | Adjudicator |

Follow [Complete your first review](docs/user-guide.md) to assign one case, submit both reviews and
record the final decisions.

## Stop and start again

Press Ctrl+C in the API and web terminals. To stop PostgreSQL as well, run
`docker compose -p review_platform_oss stop postgres`. Your saved work stays in the database volume.
Keep `.env` and `var/source_render` with your local setup. On your next visit, start Docker and run the
three startup commands below, using a separate terminal for the last one.

```sh
docker compose -p review_platform_oss up -d --wait postgres
make api-run
```

```sh
make web-run
```

Run `make migrate` when a code update adds database changes. Running `make demo` again keeps the
existing accounts, passwords and reviews.

## If something gets stuck

| What you see | What to check |
| --- | --- |
| Docker cannot be reached | Open Docker and wait for it to start, then rerun the database command. |
| Database connection refused | Check `docker compose -p review_platform_oss ps postgres`. Wait until PostgreSQL is `healthy`, then retry the failed command. |
| Port already in use | Stop the other process using port `57432` (database), `8780` (API) or `5273` (web app), then restart the affected step. |
| Page opens but sign-in fails | Check that both terminals are running and visit `http://localhost:5273/health/ready`. If it shows `unavailable`, check PostgreSQL and run `make migrate`. If it shows `ready`, check the email and the password first used to initialize the account. |
| Reviewer sees no cases | In the admin account, open the campaign and check that you selected the reviewer and clicked **Publish assignments**. |

## Where the data lives

| Location | What it holds |
| --- | --- |
| `fixtures/demo.sqlite` | The fictional cases, document HTML and evidence supplied to the app. The app reads this file without editing it. |
| PostgreSQL | Accounts, campaigns, assignments, drafts, submitted reviews and decisions. |
| `var/source_render` | The prepared document files shown in the local app. |

## Guides

- [Complete your first review](docs/user-guide.md)
- [Import your own case](docs/dataset.md)
- [Local settings](docs/configuration.md)
- [Architecture](docs/architecture.md)
- [Testing and contributing](CONTRIBUTING.md)
