# Deploy Review Platform on Google Cloud

Google Cloud is one example of where you can host Review Platform. You can deploy the app on any suitable host. This guide describes how we deployed the Review Platform on Google Cloud so you can use that setup as a reference.

## 1. Prepare a Google Cloud project

Create or select a project, enable billing, and choose a region. The person setting up the deployment needs permission to configure these services.

| Google Cloud service | What it does |
| --- | --- |
| Cloud Run | Runs the web app, the API, and one-time jobs |
| Cloud SQL for PostgreSQL | Stores accounts, campaigns, reviews, and adjudication decisions |
| Cloud Storage | Keeps the HTML judgments shown in **Document** view |
| Artifact Registry | Stores packaged versions of the web app and API |
| Secret Manager | Keeps database passwords, email credentials, and private keys |
| Identity-Aware Proxy (IAP) | Controls who can open the site with a Google account |
| Cloud Build | Builds and releases a specific version of the app |

Cloud SQL and storage can incur charges while the app is idle. A budget alert can notify you as spending rises. [Set up a budget alert](https://docs.cloud.google.com/billing/docs/how-to/budgets)

## 2. Set up PostgreSQL and judgment storage

| What Review Platform saves | Where it’s stored in this deployment |
| --- | --- |
| Accounts, cases available for review, campaigns, saved answers, and adjudication decisions | PostgreSQL, hosted on Cloud SQL |
| The HTML judgments that reviewers/adjudicators can view | A private Cloud Storage bucket |

Use one database login for the running app to read and save work, and a separate login for the setup job to create or update tables. [Connect Cloud Run to PostgreSQL](https://docs.cloud.google.com/sql/docs/postgres/connect-run)

Create the bucket with **Public access prevention** enabled. [Create a Cloud Storage bucket](https://docs.cloud.google.com/storage/docs/creating-buckets)

Updating the app leaves the judgment files in the bucket. Keep each new version connected to the same bucket so reviewers can still open judgments from earlier campaigns.

## 3. Package the web app and API

The deployment uses two container images. An image is a packaged version of the software that Cloud Run can start.

- The **web image** contains the browser interface and nginx. nginx serves the web pages and sends `/api/` requests to the API.
- The **API image** contains the application logic. The same image also runs one-time jobs such as database setup.

The files below were used for the deployment described in this guide. **They are not included in this repository.** Before deploying, prepare your own configuration files for these tasks and fill in your Google Cloud project settings. You can use the filenames below or choose your own.

| Example file | What it does |
| --- | --- |
| `Dockerfile.api` | Packages the Python API |
| `Dockerfile.ui` | Builds the web app and packages it with nginx |
| `apps/web/deploy/nginx/default.conf.template` | Tells nginx how to serve the web app and forward API requests |
| `deploy/cloud-run/review-app.service.yaml` | Tells Cloud Run how to start and connect the two containers |

Artifact Registry stores both images. Each image is tagged with the Git commit used to build it, so you can trace a running version back to the code. [Push images to Artifact Registry](https://docs.cloud.google.com/artifact-registry/docs/docker/pushing-and-pulling)

## 4. Set up the database tables and deploy the app

1. Run a **Cloud Run job** to create or update the database tables. The release stops if this job fails.
2. Deploy one Cloud Run service with both containers. The web container receives requests from the browser and forwards API requests inside the service. Users open one HTTPS address for the whole app.
3. Give the API access to the passwords and keys it needs in Secret Manager. Set the app’s address so invitation emails link to the correct site.
4. Open `/health/ready` on the deployed app to confirm that the API can connect to PostgreSQL and that the database tables are up to date.

[Deploy two containers in one Cloud Run service](https://docs.cloud.google.com/run/docs/deploying#sidecars) · [Run a Cloud Run job](https://docs.cloud.google.com/run/docs/execute/jobs) · [Use secrets with Cloud Run](https://docs.cloud.google.com/run/docs/configuring/services/secrets)

## 5. Set up sign-in and user access

Enable Google IAP on the Cloud Run service and grant access to the Google accounts or groups that need to open the site. Inside Review Platform, app roles control who can administer campaigns, review cases, or adjudicate.

With IAP enabled, users first sign in with Google to reach the site, then sign in with their Review Platform account. Configure your email provider so invitations and password reset links can reach them. [Set up IAP on Cloud Run](https://docs.cloud.google.com/run/docs/securing/identity-aware-proxy-cloud-run)

## 6. Prepare and load cases

Before you create a campaign, load the cases you want people to review. For each case, supply **the judgment, the fields you’ve already extracted, and the passages that support those fields**. For example, to review a judgment date, supply the date you extracted and the line in the judgment where it appears.

### Try your own cases locally

1. Open `demo.sqlite` or follow the example in the dataset guide to see how the judgment, fields, and evidence are supplied together.
2. Prepare a SQLite file with the cases you want to try. Your original case data can stay wherever you already store it.
3. In your `.env` file, set `REVIEW_DATASET_PATH` to the path of your SQLite file.
4. From the project folder, run the command below using your chosen demo password. Restart the API afterward so it picks up the new file path.

   ```sh
   REVIEW_DEMO_PASSWORD='your-demo-password' make demo
   ```

5. Sign in as a demo admin and open **Create campaign**. Your imported cases should now be available to select. [Follow the local case import walkthrough](dataset.md)

### Load cases into an app hosted on Google Cloud

The Google Cloud deployment used a separate **Cloud Run job** to load cases. Before the first import, set up a job that can handle these three steps.

1. **Read your prepared cases.** Give the job access to the database or files containing the judgments, extracted fields, and evidence.
2. **Add the cases to Review Platform.** Connect the job to the same Cloud SQL database the app uses. The job must save the cases to the pool that admins select from when creating campaigns.
3. **Save the judgment files.** Give the job write access to the storage where Review Platform keeps the HTML documents.

Once the job is configured, run it from **Cloud Run → Jobs**, then check its logs for the number of cases loaded. Sign in to Review Platform and create a campaign with one of those cases to check that the judgment and extracted fields are visible. [Run a Cloud Run job](https://docs.cloud.google.com/run/docs/execute/jobs)

## 7. Release updates and look after the app

GitHub Actions checks proposed changes. A separately approved Cloud Build release builds the images, updates the database tables, and deploys the new version. You can also build and release from a local copy of the project.

- **Before an update**, back up PostgreSQL and the judgment files.
- **After an update**, check `/health/ready`, sign in, and open a judgment from an existing campaign.
- **If an update fails**, check the job and service logs in Google Cloud. Before switching Cloud Run back to an earlier version, check that it can still use the updated database.
- **If a judgment won’t open**, check that the API can still read the saved HTML file.

[Connect a repository to Cloud Build](https://docs.cloud.google.com/run/docs/continuous-deployment) · [Roll back a Cloud Run release](https://docs.cloud.google.com/run/docs/rollouts-rollbacks-traffic-migration)
