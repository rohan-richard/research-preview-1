# Rumi API

The REST service behind the Rumi iOS and web clients. It keeps patient data in Postgres. The AIService chat server keeps chat, voice, and memory. The spec is the "Rumi API Spec" Claude Doc.

This first cut covers Layer 1 (Auth), Layer 2 (User), Layer 3 (EHR, through Fasten Connect), Layer 4 (Visits and logging), Layer 5 (Journeys and habits), Layer 7 (Push), Layer 9 (Care plan), Layer 11 (Today), Layer 12 (Content library), and the shared pieces they need: the job queue, the chat-server outbox, the S3 file store, file uploads, the audit log, `Idempotency-Key` on every creating POST, and the hourly cleanup.

## Run it

1. Start Postgres: `docker compose up -d`
2. Copy `.env.example` to `.env`, then fill in the values. `JWT_SECRET` must be at least 32 characters.
3. Install the packages: `uv sync`
4. Create the tables: `uv run alembic upgrade head`
5. Start the API: `uv run uvicorn app.main:app --reload`
6. Start the worker in a second terminal: `uv run python -m app.worker`

The API listens on http://localhost:8000. Open http://localhost:8000/docs for the route list.

## Tests

`uv run pytest`

The tests need the Postgres from step 1. They use a database named `rumi_test` and create it if it does not exist. Google, Apple, the chat server, S3, and Fasten are replaced by fakes, so the tests run offline.

## Layout

| Path | Holds |
| --- | --- |
| `app/auth.py` | Sign-in, refresh, sign-out, `/v1/auth/me`, and the access-token check that every other route uses |
| `app/providers.py` | Checks a Google or Apple ID token against the provider's public keys |
| `app/tokens.py` | Mints and reads our access tokens. Makes and hashes refresh tokens |
| `app/me.py` | Profile, onboarding, preferences, notifications, consents, exports, and account delete |
| `app/visits.py` | Appointments, the visit prep for each one, and the discussion guide |
| `app/ehr.py` | Health-system connections through Fasten, the Fasten webhook and widget page, the record routes, and the import jobs. `rebuild_records` makes the record tables again from the raw FHIR |
| `app/fhir_map.py` | Turns one FHIR R4 resource into the columns of its record table. Pure functions, no database |
| `app/logs.py` | Patient logs: readings, symptoms, medicines taken, meals, activity, and notes. Also the chart series |
| `app/files.py` | Upload links, download links, and the delete for patient files |
| `app/journeys.py` | Journeys, their habits and support plans, the Today list, and daily check-ins |
| `app/care_plans.py` | Care plans from the EHR, read-only, and the route that turns a goal into a journey. `import_care_plan` creates one |
| `app/content.py` | Currents pieces and progress, the meal and activity library, symptom lists, and the glossary |
| `app/push.py` | Push devices, the notification list, and the chat-server nudge webhook |
| `app/notifications.py` | Makes the scheduled notifications from habits and visits, applies the send rules, and sends them. The worker calls `tick` once a minute |
| `app/push_send.py` | Sends one payload to one device: Web Push with VAPID, or APNs over HTTP/2 with a JWT |
| `app/audit.py` | Writes one `audit_log` row for each change to patient data, and for each list read of clinical data |
| `app/idempotency.py` | The `Idempotency-Key` check that every creating POST uses |
| `app/maintenance.py` | The hourly cleanup: old idempotency keys, deleted logs and files, and old exports |
| `app/today.py` | `GET /v1/today`: the next visit, the latest numbers, the habits due, and what needs the patient |
| `app/content_seed.py` | Loads `content/*.json` into `content_items`: `python -m app.content_seed`. Safe to run again |
| `app/chat_server.py` | Calls the chat server's `/onboardPerson` and keeps the outbox of pending syncs |
| `app/jobs.py` | The job queue (exports, deletes) and the outbox worker loop |
| `app/worker.py` | The process that runs the queue, the notification tick, and the hourly cleanup: `python -m app.worker` |
| `app/storage.py` | Puts export files in S3, signs upload and download links, and checks or removes an object. Without `S3_BUCKET`, it keeps export files on disk and signs a link to `GET /v1/files/local/...` |
| `app/models.py` | The tables |
| `alembic/versions` | Migrations. Make a new one with `uv run alembic revision --autogenerate -m "..."` |

## How the pieces fit

- Every route except sign-in and refresh needs `Authorization: Bearer <access_token>`. The server reads the user from the token and checks that the session is not ended.
- The access token is an HS256 JWT with `sub`, `sid`, and `exp`. It lives 15 minutes. The refresh token is a random string. The server stores only its SHA-256 hash and rotates it on every refresh.
- On the web, the refresh token travels in the `rumi_refresh` cookie. On iOS, it travels in the body.
- Exports and account deletes run in the worker. `POST /v1/me/exports` adds a job, the worker writes the file to S3, and `GET /v1/me/exports/{id}` returns a signed link that works for 24 hours. After 24 hours the cleanup marks the export `expired` and the link is no longer offered. Add a bucket lifecycle rule to remove old export files. With no `S3_BUCKET`, the file goes to `LOCAL_FILES_DIR` and the link is a signed `GET /v1/files/local/{key}` on this API. An account delete also asks the chat server to remove the person through the outbox (`POST /deletePerson`). A 404 from the chat server counts as done.
- Layer 4: `PUT .../prep` takes `If-Match` with the last `updated_at` and answers 409 with the newer prep when another device saved first. A deleted log keeps `deleted_at` for 24 hours so `POST /v1/logs/{id}/restore` can bring it back. The cleanup removes it after that.
- Every POST that creates something takes an optional `Idempotency-Key` header: logs, appointments, guide items, journeys, habits, the journey from a care-plan goal, exports, push devices, and files. A retry with the same key returns the stored body with the stored status instead of a second row. Only a success is stored. A key belongs to one user and one route, so the same key on another route answers 400. Keys last 24 hours.
- Files: `POST /v1/files` makes a row and returns a signed S3 PUT link that works for 15 minutes. The client uploads straight to that link with the content type it sent. The limit is 20 MB. `GET /v1/files/{id}` returns a signed download link that works for 10 minutes. The first GET after the upload checks that the object is in S3 and marks the file `ready`. Before that it answers 409 `file_not_ready`. `DELETE` hides the file at once and tries to remove the object. The cleanup removes the object and the row a day later.
- The audit log (`audit_log`) only grows. The routes write one row for each create, update, and delete of patient data, and one `read` row for `GET /v1/logs`, `GET /v1/appointments`, `GET /v1/care-plans`, and `GET /v1/journeys`. The worker writes a row with actor `system` when it runs an export or an account delete. Each row holds the actor, whose data it is, the table, the row id, and the client IP (the first `X-Forwarded-For` value, else the connection address). There is no read route for it.
- Once an hour the worker removes idempotency keys older than 24 hours, hard-deletes logs that were deleted more than 24 hours ago, removes the S3 object and the row for files deleted more than 24 hours ago, and marks exports requested more than 24 hours ago as `expired`.
- When onboarding completes, the server calls the chat server's `/onboardPerson` at once. If that call fails, or when a synced profile field changes later, the server adds a row to `chat_server_outbox` and the worker retries with backoff.
- Layer 12: content is the same for every user and lives in `content_items`. Each content response carries an `ETag`, and a request with the same `If-None-Match` gets a 304. Only Currents progress belongs to one user. Seed content comes from `content/*.json`. Run `uv run python -m app.content_seed` after `alembic upgrade head`.
- Layer 9: care plans come from the EHR sync (Layer 3). `rebuild_records` turns each CarePlan resource, and the Goal resources it points to, into a care plan with `care_plans.import_care_plan`, and a goal keeps its journey across a re-import. The patient reads them and can turn a goal into a journey. A goal holds one journey at most, so a second try answers 409 `journey_exists`. Deleting the journey frees the goal.
- Layer 7: a client registers its browser subscription or APNs token with `POST /v1/push/devices`. The same endpoint or token twice updates one row, and it moves to whoever is signed in on that device. The worker makes `notifications` rows for habit reminders (today, at `reminder_time`), visit reminders (1 day and 2 hours before), and visit-prep reminders (2 days before, when the prep is not reviewed). The `idempotency_key` stops duplicates, and a rescheduled visit moves its rows. Just before a send, the worker checks the push channel and category, quiet hours (a reminder moves to the end of them, a nudge is skipped), the 2-a-day and 8-a-week limits (visit reminders are exempt), paused AI or a paused habit, and that the visit or habit still exists (`stale`). A Web Push 404 or 410, an APNs 410, or 5 failures in a row turns a device off. The chat server posts nudges to `/v1/integrations/chat-server/nudge` with the `X-Rumi-Webhook-Secret` header. Refill and records reminders are not built yet.
- Layer 3: the client opens `GET /v1/integrations/fasten/stitch` (no token) in a web view. The Fasten widget on that page lets the patient sign in to a health system, then posts the `org_connection_id` back to the app. `POST /v1/ehr/connections` needs the `health_records` consent. It saves the connection, reads its scope and consent expiry from Fasten, and queues an `ehr_export` job that asks Fasten for a record export. Fasten posts `patient.ehi_export_success` to `/v1/integrations/fasten/webhook` with the Standard Webhooks signature headers. The route checks the signature, saves the event once by its id, queues an `ehr_webhook` job, and answers 200 at once. That job downloads the NDJSON files, saves each FHIR resource in `fhir_resources` by (connection, type, id), sets `removed_at` on resources that the export no longer has, and rebuilds the record tables from the live rows. The record tables (`conditions`, `allergies`, `medications`, `medication_fills`, `lab_reports`, `lab_results`, `encounters`, `care_team_members`) are read-only copies, so a mapping fix only needs `ehr.rebuild_records`. Immunization, Procedure, DocumentReference, Coverage, and Patient stay raw only. `GET /v1/ehr/immunizations`, `/procedures`, and `/documents` map the live raw rows when they are read. `GET /v1/ehr/patient` gives the name, birth date, gender, place, and phone from the newest Patient resource, so the app can fill in onboarding. `POST /v1/ehr/connections/{id}/sync` starts a new export and answers 409 `sync_in_progress` while one runs. The hourly cleanup starts a new export for each connected system that last synced more than 24 hours ago. `DELETE` marks the connection `revoked` and keeps the records. `?delete_data=true` also removes the raw rows, and the record rows go with them. A failed export or a revoked authorization from Fasten moves the connection to `error` or `revoked`. An export that cannot be requested or downloaded marks that sync job `failed` and the patient can start another one.
- Layer 11: `GET /v1/today` has no table. It reads the next visit from Layer 4, the newest live blood pressure, glucose, and weight logs, the habits due from Layer 5, and builds `needs_you` in a fixed order: a visit within 7 days with an unreviewed prep, unfinished onboarding, and the `ai_chat` consent when it is off.
- Layer 5: the Today list and the week in a journey use the patient's local date from `profiles.timezone` (UTC when unset). The week starts on Monday. One check-in per habit per day: a second `PUT` on the same date replaces the first, and `DELETE` undoes it. Each check-in keeps a copy of the support plan as it was that day. Pausing a journey pauses its habits, and resuming it brings them back. A deleted habit leaves every list but keeps its check-ins.

## Settings

| Variable | What it is |
| --- | --- |
| `DATABASE_URL` | Postgres connection string |
| `JWT_SECRET` | Signs access tokens. 32 characters or more |
| `GOOGLE_CLIENT_IDS` | OAuth client IDs that may sign in, comma-separated |
| `APPLE_CLIENT_IDS` | The iOS bundle ID and the web Services ID, comma-separated |
| `CORS_ORIGINS` | Web origins that may call the API with cookies, comma-separated |
| `CHAT_SERVER_URL` | Chat server base URL with its API prefix, for example `https://chat.example.com/chat` |
| `CHAT_SERVER_API_KEY` | The `rumi-chat` tenant key |
| `S3_BUCKET` | Bucket for export files and patient uploads. AWS credentials come from the usual `AWS_*` variables or the instance role |
| `LOCAL_FILES_DIR` | Folder for export files when `S3_BUCKET` is empty. Default `var/files` in the api folder |
| `API_BASE_URL` | The address of this API in the local download links. Default `http://localhost:8000` |
| `VAPID_PUBLIC_KEY` | Web Push public key, base64url. `GET /v1/push/web-key` gives it to the browser |
| `VAPID_PRIVATE_KEY` | Web Push private key, base64url |
| `VAPID_SUBJECT` | Contact for the push services, for example `mailto:ops@example.com` |
| `APNS_KEY_ID` | Key ID of the APNs auth key |
| `APNS_TEAM_ID` | Apple team ID |
| `APNS_PRIVATE_KEY` | The `.p8` file contents. Write `\n` for each line break |
| `APNS_BUNDLE_ID` | The iOS app bundle ID, sent as `apns-topic` |
| `APNS_USE_SANDBOX` | `true` sends every APNs push to the sandbox host. Default `false`: a device registered as `sandbox` still goes there |
| `CHAT_SERVER_WEBHOOK_SECRET` | Shared secret the chat server sends in `X-Rumi-Webhook-Secret`. Unset means the webhook answers 401 |
| `FASTEN_PUBLIC_ID` | The Fasten Connect public id (`public_test_...` or `public_live_...`). The stitch page shows it to the browser. Unset means the page answers 404 |
| `FASTEN_PRIVATE_KEY` | The Fasten Connect private key. HTTP Basic password on every server call to Fasten. Never sent to a client |
| `FASTEN_WEBHOOK_SECRET` | Signs the webhooks from Fasten (Standard Webhooks). Test and live have different secrets. Unset means the webhook answers 401 |
| `FASTEN_API_URL` | Fasten API base URL. Default `https://api.connect.fastenhealth.com/v1` |
