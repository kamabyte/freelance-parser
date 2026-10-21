# Deploying to a server

The bot runs as a Docker container from `ghcr.io/kamabyte/freelance-parser`. GitHub
Actions builds the image on every push to `main`. Below is an example for **Dokploy**;
any other way to run a container (`docker run`, Compose) works too.

    push to main ──► GitHub Actions ──► ghcr.io/kamabyte/freelance-parser:{sha-…, latest}
                                                    │
                                       Dokploy ── Deploy ──► container

## What the bot needs

| | |
|---|---|
| Ports, domain | none: long polling to `api.telegram.org`, RSS from `fl.ru` |
| Volume | `/data`, owned by uid `10001`: `parser.db` (seen projects, your decisions, the `/start` chat). Optionally your own `config.yaml` / `profile.md`, which override the ones in the image |
| Variables | `TELEGRAM_BOT_TOKEN`, `ANTHROPIC_API_KEY`; optionally `TELEGRAM_CHAT_ID`, `TELEGRAM_TOPIC_ID` — see `.env.example` |
| Resources | 1 CPU and 512 MB is plenty |
| Instances | **exactly one**: two processes on one Telegram token fight each other (`Conflict: terminated by other getUpdates`) and would both send every alert |
| Health | the image has a `HEALTHCHECK`: the container turns `unhealthy` if no feed poll finished for 10 minutes |

## Without Dokploy

```bash
docker run -d --name freelance-parser --restart unless-stopped \
  --env-file .env -v freelance-parser-data:/data \
  ghcr.io/kamabyte/freelance-parser:latest
```

## Setting up in Dokploy

1. The image is built: the `image` workflow is green in Actions, and Packages lists
   `freelance-parser`.
2. Create the data directory on the server for the uid the bot runs as:

   ```bash
   sudo install -d -o 10001 -g 10001 -m 750 /srv/freelance-parser/data
   ```

   To keep history from a previous install, copy its `data/parser.db` in there (same owner).
3. Dokploy → project → **Create Service → Application**, e.g. `freelance-parser`.
4. **General → Provider: Docker.** Image `ghcr.io/kamabyte/freelance-parser:latest`
   (or your fork). For a private image — Registry `ghcr.io` with a `read:packages` token.
5. **Environment** — the variables from the table above. Never commit their values.
6. **Advanced → Mounts:** bind mount, host path `/srv/freelance-parser/data`, mount path `/data`.
7. **Advanced → Resources:** CPU limit 1, memory limit 512 MB.
8. No domain.
9. **Deploy.** If the bot already runs elsewhere on this token, stop it there first.
10. Check: the application logs show `Application started` and then
    `poll: N fetched, …` every 90 seconds; `/stats` in Telegram answers.

The first poll on an empty DB treats every project in the feeds as new, so with
`score_threshold: 0` expect a burst of alerts.

## Updating

From your Mac, in one command, via the Dokploy API:
[`deploy/dokploy/deploy.sh`](deploy/dokploy/deploy.sh) waits for the commit's image in
Actions, points the application at the `sha-<commit>` image, presses Deploy and waits
for `Application started` in the bot logs — meaning Telegram accepted the token.
GitHub never reaches your servers, and Actions holds no secrets.

    git push && deploy/dokploy/deploy.sh   # origin/main
    deploy/dokploy/deploy.sh <commit>      # pin / roll back to <commit>

A push alone deploys nothing. At the end the script prints the command to roll back
to the previous commit.

An install is a file `deploy/dokploy/targets/<name>.env` (the folder is gitignored);
with several, the script deploys them in turn, `-t <name>` picks one:

    DOKPLOY_URL=http://dokploy.example.lan   # Dokploy on your LAN, or
    DOKPLOY_SSH=root@203.0.113.10            # via an ssh tunnel to its localhost:3000
    PROJECT=<project> APP=<application>      # the application in Dokploy
    # KEYCHAIN=dokploy-api-<name> — the default

A Dokploy without TLS on a public address — only via `DOKPLOY_SSH`: otherwise the
API key travels over the internet in plain text.

API key — Dokploy → Settings → Profile → API/CLI, into the macOS Keychain:
`security add-generic-password -U -a "$USER" -s dokploy-api-<name> -w`.

By hand: push → Actions builds `sha-<commit>` → in Dokploy, the application's
General → image `…:sha-<commit>` → **Deploy**. A specific tag, not `latest`: that
way Dokploy is sure to pull the new image. Rollback — the previous tag and Deploy.

## Common problems

| Symptom | Cause |
|---|---|
| `Conflict: terminated by other getUpdates request` | two instances on one token: an old install is still running, or more than one replica |
| `sqlite3.OperationalError: unable to open database file` | `/data` isn't writable by uid `10001`: `chown -R 10001:10001` the host directory |
| `TELEGRAM_BOT_TOKEN is not set` at startup | the variable is missing in Environment |
| Alerts arrive, but the draft says `ANTHROPIC_API_KEY не задан` | the variable is missing in Environment |
| `poll: N fetched — no target yet` | no chat yet: send `/start` in the target chat/topic, or set `TELEGRAM_CHAT_ID` |
| `pull access denied` on Deploy | the image is private, and Dokploy has no `ghcr.io` registry selected or the token lacks `read:packages` |
