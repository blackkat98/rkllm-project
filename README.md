# RKLLM Chat

A self-hosted, multi-user chat app (in the style of ChatGPT, Gemini and Claude) that runs LLMs on the
**Rockchip RK3588 NPU** of an **Orange Pi 5+** (librkllmrt **1.2.0**).

> This project is inspired by [thanhtantran/rkllm_api_bundle](https://github.com/thanhtantran/rkllm_api_bundle).
> Its RKLLM ctypes binding, prompt templates, runtime library and frequency script were the starting point
> for this backend (see [What changed](#what-changed-compared-with-rkllm_api_bundle)).

```
browser ──► web (Caddy: Nuxt SPA + reverse proxy) ──► backend (FastAPI, 1 process) ──► NPU (librkllmrt.so)
                                                          │
                                                          └──► Postgres (users, chats, messages, models)
```

| Folder | What |
|---|---|
| `backend/` | FastAPI, SQLAlchemy 2 (async), Alembic, ctypes binding for librkllmrt 1.2.0, NPU worker, memory |
| `backend/models/` | put your `.rkllm` files here (mounted read-only, never baked into the image) |
| `frontend/` | Nuxt 4 + Nuxt UI 4 SPA, served by Caddy |
| `deploy/` | `compose.yml` (Orange Pi, behind the shared Caddy on the `proxy` network), `Caddyfile.host`, `compose.dev.yml` (PC, mock engine), `.env.example`, systemd unit |

## Features

- **Login**: JWT in httpOnly cookies, refresh tokens, "log out everywhere", login throttling.
  The first admin is created from `.env`. Admins create accounts; open sign-up can be switched on.
- **Chats are saved**: sidebar grouped Today / Yesterday / 7 days / 30 days, search (titles and messages),
  pin, rename, archive, delete, and auto-generated titles.
- **Choose a model per chat** in the composer. It shows which model is already on the NPU and which needs
  loading. You can switch models mid-chat.
- **Streaming**, with live status: *waiting for NPU (2 ahead)*, *loading model*, *condensing memory*.
  Stop button. Regenerate. Edit a message and resend.
- Replies keep generating if you close the tab, and a reloaded page reattaches to the stream.
- Markdown with syntax-highlighted code and copy buttons. Reasoning models (DeepSeek-R1, Qwen3) show a
  collapsible *Thought process* block.
- Settings: theme, custom instructions, default model, password, API keys.
- Admin: models, users, instance settings (global system prompt, sign-up, auto titles).
- **OpenAI-compatible API** (`/v1/chat/completions`, `/v1/models`) with per-user API keys, the same
  endpoints `rkllm_api_bundle/server.py` offered. Requests share the NPU queue with chats.

## Conversation memory: yes, models remember

A model itself has no memory, so the backend provides it in three tiers:

1. **Replay (always on).** Every message is stored. Each turn rebuilds the prompt from the saved
   history using the model's chat template, so a chat reopened days later, after a restart, or with a
   different model continues with full context.
2. **Rolling summary.** When the history would pass ~70% of the context window (4096 tokens by default),
   the oldest turns are summarized by the model into a running summary, which then goes into the
   system prompt. The newest 6 messages are always kept verbatim. The chat header shows a *memory* badge
   when this has happened.
3. **NPU KV-cache fast path.** If you continue the chat that the NPU processed last, only your new message
   is sent (`keep_history=1`), so the model doesn't re-read the whole conversation and answers start
   much sooner. Answers produced this way show a ⚡ *cached* tag. Any other job in between (another chat,
   a title, a regenerate) clears the cache and the next turn falls back to tier 1, which is slower to
   start but gives the same result.

## Models: ≤2B parameters on the 8 GB board

The NPU uses system RAM, and w8a8 needs about 1 GB per 1B parameters. **Only one model is resident at a
time**: switching models unloads the old one first, which takes a few seconds.

The `.rkllm` format can't report its parameter count, so the 2B limit is enforced with measurable proxies:

1. **File size cap** (`MAX_MODEL_FILE_GB=2.8`): larger files are marked *Too large* and can't be enabled.
2. **Filename hint** (e.g. `1.5B`): shown to admins, with a warning above 2B, but never decisive.
3. **Measured RAM on first load** (`MAX_MODEL_RAM_MB=3000`): over the limit, the model is unloaded,
   disabled, and flagged.

Models are listed by scanning the folder (at startup and with **Admin → Models → Rescan**), saved in
the database, and **start disabled** until an admin enables them. An optional `models.yaml` in the models
folder pre-fills names, templates and sampling (see `deploy/models.example.yaml`).

Good choices: Qwen2.5 1.5B Instruct, Qwen3 1.7B, DeepSeek-R1-Distill-Qwen 1.5B, Gemma 3 1B, Llama 3.2 1B.
They must be converted for **RK3588 with toolkit/runtime 1.2.0**, e.g. from
<https://huggingface.co/thanhtantran>.

> Sampling settings (temperature, top-p, …) are applied when the model loads (RKLLM sets them at init).
> Changing them in Admin reloads the model on its next use.

## Deploy on the Orange Pi 5+

Prerequisites on the Pi (Rockchip BSP kernel, e.g. Orange Pi OS / Ubuntu Rockchip / Armbian vendor):

```bash
sudo cat /sys/kernel/debug/rknpu/version   # needs RKNPU driver >= 0.9.8
ls /dev/dri /dev/dma_heap                  # NPU render node + DMA heaps
curl -fsSL https://get.docker.com | sh      # Docker + compose plugin
```

Then:

```bash
git clone <this repo> rkllm-chat && cd rkllm-chat
cp /path/to/*.rkllm backend/models/              # or set MODELS_DIR in deploy/.env
cp deploy/.env.example deploy/.env && nano deploy/.env   # set the passwords + JWT_SECRET (openssl rand -hex 32)
cd deploy && docker compose up -d --build
docker compose logs -f backend                   # expect "model scan: N added"
```

The app **never uses port 80 or 443**. It follows the Pi's existing setup (`~/prj/caddy`, same as n8n and
nam-nuxt-room). The web container binds **`127.0.0.1:${WEB_PORT}`** (default 8090), so it's reachable from
the Pi itself (the Cloudflare tunnel) but not from the LAN. It also joins the external `proxy` network,
where the shared Caddy reaches it as `rkllm-web:${WEB_PORT}`. The backend (`BACKEND_PORT`, default 8000)
is only on the app's internal network.

1. **Cloudflare.** The tunnel is token-managed, so add the hostname in the dashboard:
   Zero Trust → Networks → Tunnels → your tunnel → Public hostnames → `rkllm-chat.blackkat.bond` →
   HTTP → `localhost:8090`.
2. **Caddy.** Add the block from `deploy/Caddyfile.host` to `~/prj/caddy/Caddyfile`, above the catch-all
   `:80` block, like the other sites:

   ```caddy
   http://rkllm-chat.blackkat.bond {
   	reverse_proxy rkllm-web:8090 {
   		header_up X-Forwarded-For {http.request.header.CF-Connecting-IP}
   		flush_interval -1          # required: stream tokens immediately
   	}
   }
   ```

   Then reload it: `cd ~/prj/caddy && docker compose exec caddy caddy reload --config /etc/caddy/Caddyfile`

Keep `COOKIE_SECURE=true`, since Cloudflare serves the site over HTTPS. The app must sit at the root of a
(sub)domain, not on a sub-path. If you change `WEB_PORT`, change it in the Caddy block too.

Open the site, log in as the admin from `.env`, then go to **Admin → Models**, enable a model, and
start chatting. The first message loads the model onto the NPU; the backend log shows `rkllm init ok`.
Watch the NPU work with `sudo cat /sys/kernel/debug/rknpu/load`.

**Max performance (optional, recommended).** Pin NPU/CPU/DDR frequencies at boot, as the original server
did on every start:

```bash
sudo cp deploy/fix_freq_rk3588.sh /usr/local/bin/ && sudo chmod +x /usr/local/bin/fix_freq_rk3588.sh
sudo cp deploy/rkllm-freq.service /etc/systemd/system/
sudo systemctl daemon-reload && sudo systemctl enable --now rkllm-freq
```

### How the container reaches the NPU

`deploy/compose.yml` passes `/dev/dri` (the RKNPU DRM node) and `/dev/dma_heap` into the backend
container (verified on the Pi: `renderD129` is the RKNPU node, driver 0.9.8). It also sets `security_opt: systempaths=unconfined`, so the runtime can read the device tree,
which Docker hides by default. `librkllmrt.so` 1.2.0 is baked into the image (`backend/lib/`). If
`rkllm_init` fails on your kernel, the fallback is `privileged: true`, commented in the compose file. A
missing `/dev/dma_heap` on older kernels just means removing that line.

### Building from Windows instead of on the Pi

```bash
docker buildx build --platform linux/arm64 -t rkllm-chat-backend:latest --load backend
docker buildx build --platform linux/arm64 -t rkllm-chat-web:latest --load frontend
docker save rkllm-chat-backend:latest rkllm-chat-web:latest | gzip > rkllm-chat.tar.gz
# copy to the Pi, then:  docker load < rkllm-chat.tar.gz && docker compose up -d   (no --build)
```

## Develop on a PC (no NPU)

```bash
docker compose -f deploy/compose.dev.yml up --build     # full app on http://localhost:8090, API on :8000
                                                        # (override with WEB_PORT / BACKEND_PORT)
# login: admin / admin12345. A mock engine streams fake answers; two placeholder models
# in deploy/dev-models are enabled.

cd frontend && npm install && npm run dev                # hot-reload UI on :3000, proxies /api to BACKEND_PORT
```

Backend tests (run in a container, no local Python needed):

```bash
cd backend
docker run --rm -v "$PWD:/w" -w /w -e UV_PROJECT_ENVIRONMENT=/tmp/venv \
  ghcr.io/astral-sh/uv:0.8-python3.12-bookworm-slim sh -c "uv sync --frozen && uv run pytest -q"
```

Schema changes: edit `backend/app/models/*`, then
`uv run alembic revision --autogenerate -m "..."`. Migrations run automatically when the backend
container starts.

## Configuration (backend env)

| Variable | Default | |
|---|---|---|
| `DATABASE_URL` | – | `postgresql+asyncpg://…` |
| `JWT_SECRET` | – | long random string |
| `ADMIN_USERNAME` / `ADMIN_EMAIL` / `ADMIN_PASSWORD` | – | first admin, created once |
| `COOKIE_SECURE` | `true` in compose | Secure cookies (site served over HTTPS by Cloudflare) |
| `BACKEND_PORT` / `WEB_PORT` | `8000` / `8090` | container ports; only `WEB_PORT` is published, on 127.0.0.1 |
| `RKLLM_ENGINE` | `rkllm` | `mock` for development |
| `MODELS_DIR` | `/models` | inside the container |
| `MAX_MODEL_FILE_GB` / `MAX_MODEL_RAM_MB` | `2.8` / `3000` | ≤2B policy |
| `IDLE_UNLOAD_MINUTES` | `0` | free RAM when idle |
| `KV_FAST_PATH` | `true` | memory tier 3 |
| `SUMMARY_TRIGGER_RATIO` / `KEEP_RECENT_MESSAGES` | `0.70` / `6` | memory tier 2 |
| `RKLLM_CPU_MASK` / `RKLLM_CPU_NUM` | big cores 4–7 / `4` | CPU threads used by the runtime |

## What changed compared with rkllm_api_bundle

- The ctypes binding no longer uses globals. It decodes split UTF-8 correctly, adds `rkllm_abort` (stop)
  and `rkllm_clear_kv_cache`, and disables the runtime's built-in chat template so the backend controls
  prompts.
- Template fixes: DeepSeek special tokens use `▁`, not a space. Plain Qwen uses ChatML instead of the
  DeepSeek format. Gemma has no system role. Llama 3 headers added.
- One NPU worker with a fair queue replaces "server busy, try again later".
- Flask was replaced by FastAPI, and the frequency script moved to a host systemd unit.
