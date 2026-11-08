# Run background jobs

Jobs live in Postgres, in procrastinate's tables, so the API and the worker need nothing else. The API defers a job, and a worker picks it up, runs it, and retries it if it fails.

| Job | Runs | Does |
|---|---|---|
| `send_welcome_email` | After each registration | Sends a welcome email through `EmailSender`, with up to 5 attempts |
| `delete_expired_rows` | Hourly, at 7 past | Removes expired sessions, idempotency keys, and rate-limit windows |

Run a worker with `make worker` on your machine, or the `worker` service in Compose. In production, run the image with the `worker` command.

## Add a job

1. Write an async function in `src/app/jobs.py`, decorated with `@queue.task(name="...")`. Give it JSON-serializable arguments, such as IDs, not objects.
2. Defer it from a route with `await my_job.defer_async(user_id=str(user.id))`.
3. For a schedule, add `@queue.periodic(cron="...")` above the task, and accept a `timestamp: int` argument.
4. Test it through a real worker, as `tests/integration/test_jobs.py` does.

Make every job safe to run twice, because a worker can crash after doing the work but before marking the job done. Use `queueing_lock` to keep only one copy of a job waiting.

## Send real email

`LogEmailSender` only logs. Write a class with the same `send` method that calls your provider, and set `jobs.sender` to it at startup. Keep the provider's API key in an environment variable on the worker.

## Inspect the queue

```sh
uv run --env-file .env procrastinate --app=app.jobs.queue shell
```

Jobs that fail every attempt stay in `procrastinate_jobs` with the status `failed`, so you can find and retry them.
