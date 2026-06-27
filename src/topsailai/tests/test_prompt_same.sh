#!/bin/bash

set -e

TMP_PATH="/tmp/topsailai.$(date +%Y-%m-%d).prompt"
echo "${TMP_PATH}"

write_prompt() {
  _file=$1
  echo > "${_file}"
  topsailai_agent_call_instruction -i /agent.system_prompt >> "${_file}"
  topsailai_agent_call_instruction -i /agent.tool_prompt >> "${_file}"
}

write_prompt "${TMP_PATH}"

for count in {1..100}; do
  echo "${count}"
  sleep 1
  write_prompt "${TMP_PATH}.1" && diff "${TMP_PATH}" "${TMP_PATH}.1" && continue;
  echo Failed
  exit 1
done

echo OK
exit 0
