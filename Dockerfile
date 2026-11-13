# atlas_reviewer controller image. One-off Fly Machine, no public port.
# Base: python:3.12.16-slim-bookworm manifest list, registry-1.docker.io
# Docker-Content-Digest on 2026-11-10. The builder selects its own platform
# from this list (linux/amd64 inside it is
# sha256:0f086103b026048cc50cb5da25ec435c023c5241a83fc44daea593377abc61c4).
FROM python:3.12.16-slim-bookworm@sha256:935c3c5b12357a7e10caa9c1e6ca5692344d97cf229832ef584be2cec9fc03df

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONPATH=/opt/atlas \
    HOME=/home/atlas \
    ATLAS_REVIEWER_STATE_DIR=/home/atlas/.atlas-reviewer-state

RUN useradd --create-home --uid 10001 --shell /bin/false atlas

# requirements.txt is the repo's hashed pip-compile lock, dev tools included.
# There is no separate runtime lock. --require-hashes matches CI.
COPY requirements.txt /tmp/requirements.txt
RUN pip install --require-hashes --only-binary=:all: -r /tmp/requirements.txt \
    && rm /tmp/requirements.txt

COPY atlas_reviewer/*.py /opt/atlas/atlas_reviewer/
COPY atlas_reviewer/fixtures/eval-references /opt/atlas/atlas_reviewer/fixtures/eval-references
COPY collapsed/skills/reviewing-a-change/SKILL.md /opt/atlas/collapsed/skills/reviewing-a-change/SKILL.md
COPY collapsed/skills/reviewing-a-change/reference/lenses /opt/atlas/collapsed/skills/reviewing-a-change/reference/lenses
COPY skills/choosing-review-lenses/SKILL.md /opt/atlas/skills/choosing-review-lenses/SKILL.md
COPY atlas_reviewer/docker-entrypoint.sh /usr/local/bin/atlas-reviewer
RUN chmod 755 /usr/local/bin/atlas-reviewer

# Root only long enough for the entrypoint to chown the state volume.
# The entrypoint then continues as uid 10001.
WORKDIR /home/atlas

ENTRYPOINT ["/usr/local/bin/atlas-reviewer"]
CMD ["--help"]
