# Container image: one small, non-root image, and a check that keeps it so

A three-stage Dockerfile for a FastAPI API that also serves its built React web app from the same
origin, and a check that fails when a later edit makes the image unsafe or large.

## How to call it

1. Copy `Dockerfile.template` to your project root as `Dockerfile`. Keep a `.dockerignore` that
   leaves out `.git`, `.env`, `node_modules`, `.venv` and build output.
2. Build it: `docker build -t myapp .`
3. Keep it honest in CI or a test:

```python
from pathlib import Path

from toolkit.container_image.core import problems


def test_the_dockerfile_stays_safe() -> None:
    assert problems(Path("Dockerfile").read_text()) == []
```

or `python -m toolkit.container_image.core Dockerfile` (exit 1, one line per problem).

## What the template does

- **Stage 1, `web`:** installs the web dependencies from the lockfile and builds the web app.
- **Stage 2, `python`:** installs the Python dependencies with uv from `uv.lock`, into a virtual
  environment, without the dev tools.
- **Stage 3, `runtime`:** copies only that environment, the code and the built web app. It runs as
  a system user with a fixed uid, has a `HEALTHCHECK` on the liveness probe, and has no compiler,
  no Node and no uv.
- Base images come through a `REGISTRY` build argument, so a network that cannot reach Docker Hub
  can build from a mirror.

## What the check refuses

- a single stage, because the build tools would ship in the image;
- a base image with no pinned tag, or tagged `latest`;
- an `ARG` or `ENV` whose name says it is a secret, because build arguments and environment values
  can be read from the image's history;
- `ADD` from a URL (download in a `RUN` with a checksum instead);
- copying a `.env` file;
- a final stage that runs as root, or has no `HEALTHCHECK`.

A secret the build itself needs, such as a certificate authority for a network that re-signs
HTTPS, goes in as a BuildKit secret mount (`RUN --mount=type=secret,id=...`), which never lands in
a layer.

## When lifting, change

The `COPY` lines to your own folders; the app module in `CMD`; the health path in `HEALTHCHECK`;
the pinned versions of Node, Python, pnpm and uv.

Needs: Docker with BuildKit; the check needs only the standard library. Tests:
`toolkit/container_image/tests/`.
