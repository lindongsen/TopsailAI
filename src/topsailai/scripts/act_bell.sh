#!/usr/bin/env bash
# act_bell.sh - Ring a bell once.
#
# The script plays a single short bell tone. When no usable audio route is
# available it falls back to the terminal bell character so the caller still
# receives one ring.

set -euo pipefail

# Get the absolute path of the script and its directory.
EXE_FILE=$(readlink -f "$0")
EXE_FOLDER=$(dirname "${EXE_FILE}")

# Switch to the script's directory so companion files resolve stably.
cd "${EXE_FOLDER}" || exit 1

SCRIPT_NAME=$(basename "${EXE_FILE}")
ENV_FILE="${EXE_FOLDER}/act_bell.env"

# Script-owned environment variables.
SOUND_CMD_ENV="TOPSAILAI_ACT_BELL_SOUND"

# Built-in ffplay tone: a short 880 Hz sine needs no display or audio files.
FFPLAY_TONE_ARGS=(-nodisp -autoexit -loglevel error -f lavfi -i sine=frequency=880:duration=0.3)

# log_warn prints a diagnostic message to stderr.
log_warn() {
  printf '%s: %s\n' "${SCRIPT_NAME}" "$*" >&2
}

# usage prints help information and exit status codes.
usage() {
  cat <<EOF
Usage: ${SCRIPT_NAME} [OPTIONS]

Ring a bell once. The script plays a single short tone through ffplay when an
audio route is available, otherwise it emits the terminal bell character.

Options:
  -h, --help    Show this help message and exit.

Environment:
  ${SOUND_CMD_ENV}
                Optional shell command that plays the bell sound. When unset,
                a built-in ffplay sine tone is used.

Exit status:
  0   The bell was rung (tone played or terminal bell emitted).
  1   Invalid usage.

Examples:
  ${SCRIPT_NAME}
  ${SOUND_CMD_ENV}="aplay /usr/share/sounds/bell.wav" ${SCRIPT_NAME}
EOF
}

# load_env loads companion configuration without overriding process values.
load_env() {
  local env_file="$1"
  [[ -f "${env_file}" ]] || return 0
  local line key value
  while IFS= read -r line || [[ -n "${line}" ]]; do
    line="${line#"${line%%[![:space:]]*}"}"
    [[ -z "${line}" || "${line}" == \#* ]] && continue
    key="${line%%=*}"
    value="${line#*=}"
    [[ "${key}" == "${line}" ]] && continue
    key="${key%"${key##*[![:space:]]}"}"
    # Process environment takes precedence over the companion file.
    if [[ -z "${!key+x}" ]]; then
      export "${key}=${value}"
    fi
  done < "${env_file}"
}

# alsa_playback_devices lists unique direct ALSA playback devices.
alsa_playback_devices() {
  local snd_dir="/dev/snd"
  local entry name rest card device
  [[ -d "${snd_dir}" ]] || return 0
  for entry in "${snd_dir}"/pcmC*D*p; do
    [[ -e "${entry}" ]] || continue
    name=$(basename "${entry}")
    rest="${name#pcmC}"
    card="${rest%%D*}"
    device="${rest#*D}"
    device="${device%p}"
    [[ "${card}" =~ ^[0-9]+$ && "${device}" =~ ^[0-9]+$ ]] || continue
    printf 'plughw:%s,%s\n' "${card}" "${device}"
  done
}

# play_ffplay plays one ffplay tone and rejects reported audio failures.
# ffplay can exit 0 even when audio initialization fails, so the exit code
# alone is not trustworthy; stderr error markers are inspected instead.
play_ffplay() {
  local device="$1"
  local stderr_output
  if [[ -n "${device}" ]]; then
    stderr_output=$(env SDL_AUDIODRIVER=alsa AUDIODEV="${device}" \
      ffplay "${FFPLAY_TONE_ARGS[@]}" 2>&1 >/dev/null) || true
  else
    stderr_output=$(ffplay "${FFPLAY_TONE_ARGS[@]}" 2>&1 >/dev/null) || true
  fi
  local lowered="${stderr_output,,}"
  local marker
  for marker in "couldn't open audio device" "audio open failed" \
    "failed to open file" "unable to open slave" "device or resource busy"; do
    if [[ "${lowered}" == *"${marker}"* ]]; then
      return 1
    fi
  done
  return 0
}

# ring_bell plays the configured sound command or falls back to the terminal bell.
ring_bell() {
  local sound_cmd="${!SOUND_CMD_ENV:-}"
  if [[ -n "${sound_cmd}" ]]; then
    local -a cmd_parts
    read -r -a cmd_parts <<< "${sound_cmd}"
    if command -v "${cmd_parts[0]}" >/dev/null 2>&1; then
      if "${cmd_parts[@]}" >/dev/null 2>&1; then
        return 0
      fi
      log_warn "sound command failed, falling back to terminal bell"
    else
      log_warn "sound command '${cmd_parts[0]}' not found, falling back to terminal bell"
    fi
    printf '\a'
    return 0
  fi

  # No explicit command: try the default route, then direct ALSA devices.
  if play_ffplay ""; then
    return 0
  fi
  local device
  while IFS= read -r device; do
    if play_ffplay "${device}"; then
      return 0
    fi
  done < <(alsa_playback_devices)
  log_warn "no usable audio output found, falling back to terminal bell"
  printf '\a'
  return 0
}

# main parses arguments and rings the bell once.
main() {
  while [[ $# -gt 0 ]]; do
    case "$1" in
      -h|--help)
        usage
        return 0
        ;;
      *)
        log_warn "unknown argument: $1"
        usage >&2
        return 1
        ;;
    esac
  done

  load_env "${ENV_FILE}"
  ring_bell
  return 0
}

main "$@"
