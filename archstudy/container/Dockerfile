# Agent image for the architecture-drift study. Build from the REPOSITORY ROOT (COPY paths are relative to it):
#
#   docker build -f archstudy/container/Dockerfile \
#     --build-arg CLAUDE_CODE_VERSION=<exact> --build-arg REDIS_VERSION=<exact> \
#     --build-arg REQUESTS_VERSION=<exact> --build-arg PYTEST_VERSION=<exact> -t archstudy-agent .
#
# Every pinned version is a build-arg with NO default; the build fails when one is missing or is not an
# exact version. Pass PYTHON_IMAGE=python:3.12-slim@sha256:<digest> to pin the base by digest.
# No credential is baked in: the API key is passed at run time by name only (see archstudy/isolation.py).
ARG PYTHON_IMAGE=python:3.12-slim
FROM ${PYTHON_IMAGE}

ARG CLAUDE_CODE_VERSION
ARG REDIS_VERSION
ARG REQUESTS_VERSION
ARG PYTEST_VERSION

# Fail the build on an empty or non-exact version (so "latest" or a range cannot slip in).
RUN set -eu; \
    for pair in "CLAUDE_CODE_VERSION=${CLAUDE_CODE_VERSION}" "REDIS_VERSION=${REDIS_VERSION}" \
                "REQUESTS_VERSION=${REQUESTS_VERSION}" "PYTEST_VERSION=${PYTEST_VERSION}"; do \
      name="${pair%%=*}"; value="${pair#*=}"; \
      if [ -z "${value}" ]; then echo "build-arg ${name} is required (no default)" >&2; exit 1; fi; \
      if ! printf '%s' "${value}" | grep -Eq '^[0-9]+\.[0-9]+\.[0-9]+([.+-][0-9A-Za-z.]+)?$'; then \
        echo "build-arg ${name} must be an exact version, got '${value}'" >&2; exit 1; fi; \
    done

# nodejs/npm for Claude Code; git for the snapshotter and the commit hook.
RUN apt-get update \
    && apt-get install -y --no-install-recommends nodejs npm git ca-certificates \
    && rm -rf /var/lib/apt/lists/*

RUN npm install -g "@anthropic-ai/claude-code@${CLAUDE_CODE_VERSION}" \
    && npm cache clean --force

# Preinstalled so the dependency shortcut is possible (otherwise a missing package, not a rule, would stop it).
RUN pip install --no-cache-dir "redis==${REDIS_VERSION}" "requests==${REQUESTS_VERSION}" "pytest==${PYTEST_VERSION}"

RUN groupadd --gid 10001 agent \
    && useradd --uid 10001 --gid 10001 --no-create-home --shell /usr/sbin/nologin agent \
    && mkdir -p /workspace /snap \
    && chown 10001:10001 /workspace /snap

# The harness package, by ALLOWLIST: only what the hook and the commit check import, plus the visible ADR texts. The scorer-side
# modules (held-out rules, scorer, tasks, hidden acceptance tests, stand-ins, isolation) never enter the image, so the agent cannot
# read them and a new scorer-side module does not leak by default. Root-owned and not writable.
COPY archstudy/__init__.py archstudy/hook.py archstudy/precommit.py archstudy/rules.py archstudy/feedback.py      archstudy/snapshot.py /opt/archstudy/
COPY archstudy/codebase/docs/adr/ /opt/archstudy/codebase/docs/adr/
RUN chown -R root:root /opt/archstudy && chmod -R go-w,a+rX /opt/archstudy && chmod -R a-w /opt/archstudy

# Managed settings outrank user, project and local settings; allowManagedHooksOnly blocks every other hook.
COPY archstudy/container/managed-settings.json /etc/claude-code/managed-settings.json
RUN chown -R root:root /etc/claude-code \
    && chmod 0555 /etc/claude-code \
    && chmod 0444 /etc/claude-code/managed-settings.json

# The root filesystem is mounted read-only at run time; Claude Code's state goes to the /tmp tmpfs.
ENV HOME=/tmp \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /workspace
USER 10001:10001
