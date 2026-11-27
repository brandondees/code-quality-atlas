#!/bin/sh
# Writes the operator's event file, then runs the existing CLI.
# Fly secrets are already in the environment. This script does not print
# the environment and does not put those values on the command line.
#
# With ATLAS_HOLD_SECONDS set, the Machine stays up after the CLI exits so
# the operator can copy /home/atlas/out off its disk. Stopping a Machine
# resets its root filesystem, and starting it again reruns this command.
set -eu
umask 077
if [ -n "${ATLAS_EVENT_JSON:-}" ]; then
  printf '%s\n' "$ATLAS_EVENT_JSON" > /home/atlas/event.json
fi

hold="${ATLAS_HOLD_SECONDS:-}"
if [ -z "$hold" ]; then
  exec python -m atlas_reviewer "$@"
fi
case "$hold" in
  *[!0-9]*)
    echo "atlas-reviewer: ATLAS_HOLD_SECONDS must be a whole number of seconds" >&2
    exit 2
    ;;
esac

out=/home/atlas/out
mkdir -p "$out"
child=
signalled=0
# `fly machine stop` sends SIGINT. Passing a stop on lets the CLI's finally
# blocks delete the runner Sprite before the process exits. It goes on as
# SIGTERM: sh starts the CLI with SIGINT ignored, and until the CLI has
# installed its handler, SIGTERM ends it before it has created anything.
trap 'signalled=1; [ -z "$child" ] || kill -TERM "$child" 2>/dev/null || :' INT TERM
python -m atlas_reviewer "$@" &
child=$!
if [ "$signalled" -eq 1 ]; then
  kill -TERM "$child" 2>/dev/null || :
fi
while :; do
  if wait "$child"; then status=0; else status=$?; fi
  # A trapped signal ends `wait` early, above 128, while the CLI still runs.
  if [ "$status" -le 128 ] || ! kill -0 "$child" 2>/dev/null; then
    break
  fi
done
trap 'exit "$status"' INT TERM

printf '%s\n' "$status" > "$out/exit-code.tmp"
mv "$out/exit-code.tmp" "$out/exit-code"
if [ "$signalled" -eq 1 ]; then
  exit "$status"
fi
echo "atlas-reviewer: review exited $status; holding ${hold}s so $out can be copied" >&2
sleep "$hold" > /dev/null 2>&1 &
sleeper=$!
trap 'kill "$sleeper" 2>/dev/null || :; exit "$status"' INT TERM
wait "$sleeper" || :
exit "$status"
