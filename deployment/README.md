# Deployment

Two configurations, one image. The `Dockerfile` at the repository root builds a
single image and the entrypoint picks the role, so every service below is the
same image with a different command.

```
deployment/
  local/       docker-compose.yml            throwaway values inline, no env file
  production/  docker-compose.yml            single DigitalOcean Droplet
               .env.production.example       copy to .env.production and fill in
```

Driven from the root `Makefile`; nothing here is wired into CI. The env decides
*where* the work happens: `local` runs containers on this machine, `production`
rsyncs the working tree to the Droplet and runs every docker command there over
SSH. Same targets either way.

```bash
make deploy-help                # every target
make deploy env=local           # build + up + migrate + seed, here
make deploy env=production      # sync + the same four, on the Droplet
```

The Droplet is addressed by the `guru-backend` SSH alias and `/opt/guru-core`;
override with `ssh_host=` / `remote_dir=` if it moves.

## local

Builds from the working tree and publishes the API on 8000, the catalog
service on 8001, and PostgreSQL / Redis on **5433 / 6380** — the offset ports
keep them clear of whatever is already running on 5432 / 6379. Data lives in
named volumes; `docker compose down -v` is the reset button.

`ALLOW_FAKE_LOGIN=1` and `LLM_ADAPTER=fake` are set here so `make deploy-smoke`
runs without Google credentials or an LLM provider.

## production

Single Droplet, no reverse proxy and no TLS: there is no domain yet, so the API
publishes straight onto the public interface and is reached at
`http://<droplet-ip>:8000`. PostgreSQL, Redis and the catalog service stay on
the internal compose network and are never published.

State is in bind mounts under `deployment/production/data/` (`postgres`, `redis`,
`storage`) rather than named volumes, so it sits where you can back it up and a
stray `down -v` cannot take it with it.

First run, all from your own checkout:

```bash
cp deployment/production/.env.production.example deployment/production/.env.production
$EDITOR deployment/production/.env.production   # PUBLIC_BASE_URL + every secret
make deploy-bootstrap env=production            # install docker, open the firewall
make deploy env=production
curl http://<droplet-ip>:8000/health
```

Redeploy: `make deploy env=production` again. The sync uses `--delete` so the
Droplet mirrors your tree, with `deployment/*/data` excluded — that is the live
database and must never be touched by the sync.

`.env.production` is gitignored, so it is copied by a second, explicit rsync
rather than riding along with the tree.

Because the API is plain HTTP on the open internet, open only 22 and 8000 in the
Droplet firewall, and treat the traffic as readable in transit until a domain and
TLS terminator go in front of it.
