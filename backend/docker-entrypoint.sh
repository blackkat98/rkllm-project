#!/bin/sh
set -e

# wait for Postgres, then apply migrations
python - <<'EOF'
import asyncio, os, sys, time
import asyncpg

url = os.environ.get("DATABASE_URL", "").replace("postgresql+asyncpg://", "postgresql://")
if not url.startswith("postgresql://"):
    sys.exit(0)
for i in range(60):
    try:
        async def ping():
            conn = await asyncpg.connect(url)
            await conn.close()
        asyncio.run(ping())
        break
    except Exception as e:
        print(f"waiting for database ({e.__class__.__name__})...", flush=True)
        time.sleep(1)
else:
    sys.exit("database not reachable")
EOF

alembic upgrade head

# exactly ONE worker process: it owns the NPU and the single loaded model
exec uvicorn app.main:app --host 0.0.0.0 --port "${BACKEND_PORT:-8000}" --workers 1 \
     --proxy-headers --forwarded-allow-ips='*' "$@"
