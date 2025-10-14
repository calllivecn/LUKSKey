#!/bin/sh
# 30remotekey.sh - dracut hook to fetch LUKS key from LAN multicast or prompt user
# Behavior: run lan-multicast-key in background (writes to tmp file).
# Simultaneously prompt user to type passphrase. First party to acquire lock wins.

# Helper: read kernel cmdline option
get_cmdline_opt() {
    # usage: get_cmdline_opt name
    awk -v k="$1" 'BEGIN{FS=" "}{for(i=1;i<=NF;i++){ if($i ~ ("^"k"=")){split($i,a,"="); print a[2]; exit }}}' /proc/cmdline 2>/dev/null
}

# Parameters (can come from kernel cmdline)
MCAST="$(get_cmdline_opt remotekey_mcast)"
PORT="$(get_cmdline_opt remotekey_port)"
PSKHEX="$(get_cmdline_opt remotekey_psk)"
DEV="$(get_cmdline_opt remotekey_dev)"
NAME="$(get_cmdline_opt remotekey_name)"
GLOBAL_TIMEOUT="$(get_cmdline_opt remotekey_timeout)"  # total seconds to wait
PROMPT_TIMEOUT="$(get_cmdline_opt remotekey_prompt_timeout)" # seconds for prompt read

: ${MCAST:=ff05::1234}
: ${PORT:=50000}
: ${PSKHEX:=}
: ${DEV:=}
: ${NAME:=cryptroot}
: ${GLOBAL_TIMEOUT:=60}
: ${PROMPT_TIMEOUT:=30}

if [ -z "$DEV" ]; then
  echo "remotekey: no remotekey_dev specified, skipping" > /dev/console
  exit 0
fi

# Paths
RUN_DIR="/run"
TMPFILE="$RUN_DIR/remote-key.$$"
FINALKEY="$RUN_DIR/remote-key"
LOCKDIR="$RUN_DIR/remote-key.lock"

# ensure run dir exists
mkdir -p "$RUN_DIR"
umask 077

# cleanup helper
_cleanup() {
  [ -n "$LISTENER_PID" ] && kill "$LISTENER_PID" 2>/dev/null || true
  [ -f "$TMPFILE" ] && rm -f "$TMPFILE"
}
trap '_cleanup' EXIT INT TERM

# Start network listener in background writing to TMPFILE.
# Assume lan-multicast-key writes key to stdout; adjust if your binary has --outfile option.
echo "remotekey: starting lan-multicast-key (mcast=$MCAST port=$PORT timeout=$GLOBAL_TIMEOUT)" > /dev/console
# if your binary supports flags, change below accordingly
/usr/sbin/lan-multicast-key --mcast "$MCAST" --port "$PORT" --psk "$PSKHEX" --timeout "$GLOBAL_TIMEOUT" > "$TMPFILE" 2>/dev/null &
LISTENER_PID=$!

# set deadline
NOW=$(date +%s)
DEADLINE=$((NOW + GLOBAL_TIMEOUT))

# main loop: check for incoming network key OR prompt user
while : ; do
  # 1) check if listener produced a file
  if [ -s "$TMPFILE" ]; then
    # attempt to acquire lock (mkdir is atomic; only one will succeed)
    if mkdir "$LOCKDIR" 2>/dev/null; then
      # atomically claim the key
      chmod 600 "$TMPFILE"
      mv "$TMPFILE" "$FINALKEY"
      echo "remotekey: network key received and claimed" > /dev/console
      break
    else
      # someone else claimed
      echo "remotekey: network key arrived but lock taken" > /dev/console
      # cleanup and check if FINALKEY exists
      rm -f "$TMPFILE"
    fi
  fi

  # 2) If lock already exists, stop
  if [ -d "$LOCKDIR" ] && [ -s "$FINALKEY" ]; then
    echo "remotekey: final key already present" > /dev/console
    break
  fi

  # 3) check timeout
  NOW=$(date +%s)
  if [ "$NOW" -ge "$DEADLINE" ]; then
    echo "remotekey: timed out after ${GLOBAL_TIMEOUT}s, no key found" > /dev/console
    break
  fi

  # 4) prompt user with remaining time (non-blocking prompt with timeout)
  REM=$((DEADLINE - NOW))
  # give only up to PROMPT_TIMEOUT for this prompt
  if [ "$REM" -gt "$PROMPT_TIMEOUT" ]; then
    READT="$PROMPT_TIMEOUT"
  else
    READT="$REM"
  fi

  # show a prompt on console
  printf "\nEnter LUKS passphrase (will be used if no network key arrives in %s s): " "$READT" > /dev/console

  # disable local echo on console (careful: some initramfs lack stty; fallback if needed)
  if command -v stty >/dev/null 2>&1; then
    # open /dev/console for reading user input
    exec 3</dev/console
    stty -echo <&3 2>/dev/null
    # read with timeout
    if read -r -t "$READT" PASS <&3; then
      stty echo <&3 2>/dev/null
      echo "" > /dev/console  # newline after input
      # try to claim lock
      if mkdir "$LOCKDIR" 2>/dev/null; then
        # write passphrase to FINALKEY (no newline trimming safety: cryptsetup will accept)
        printf "%s" "$PASS" > "$FINALKEY"
        chmod 600 "$FINALKEY"
        echo "remotekey: user passphrase claimed" > /dev/console
        # kill listener (we don't need it anymore)
        kill "$LISTENER_PID" 2>/dev/null || true
        break
      else
        echo "remotekey: someone else provided key meanwhile" > /dev/console
        # continue loop to check file
      fi
    else
      # timed out without input
      stty echo <&3 2>/dev/null
      echo "" > /dev/console
      # continue to loop and check network file again
    fi
    # close fd 3
    exec 3<&-
  else
    # no stty available; fallback: blocking read with timeout using dd (less ideal)
    printf "\n(typing disabled: no stty) waiting %s s for input...\n" "$READT" > /dev/console
    sleep "$READT"
  fi

  # small sleep to avoid busy loop
  sleep 1
done

# after loop: if we have key, try to open LUKS
if [ -s "$FINALKEY" ]; then
  echo "remotekey: attempting cryptsetup luksOpen $DEV $NAME" > /dev/console
  # try unlocking
  if cryptsetup luksOpen "$DEV" "$NAME" --key-file="$FINALKEY"; then
    echo "remotekey: luksOpen succeeded" > /dev/console
    # clean key and lock (but keep mapper open)
    shred -u "$FINALKEY" 2>/dev/null || rm -f "$FINALKEY"
    rmdir "$LOCKDIR" 2>/dev/null || true
    exit 0
  else
    echo "remotekey: luksOpen failed" > /dev/console
    # remove final key and lock so other methods (manual shell) can try
    rm -f "$FINALKEY" 2>/dev/null || true
    rmdir "$LOCKDIR" 2>/dev/null || true
    # optionally drop to shell or continue to next unlock method
    # we will fall through and allow initramfs to continue (or reveal shell if rd.shell)
    exit 1
  fi
else
  echo "remotekey: no key obtained" > /dev/console
  exit 2
fi

