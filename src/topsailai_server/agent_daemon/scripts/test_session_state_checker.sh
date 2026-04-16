#!/bin/bash
# Author: DawsonLin
# Email: lin_dongsen@126.com
# Created: 2026-04-15
# Purpose:

STATUS_PROCESSING="processing"
STATUS_IDLE="idle"

min=1
max=10
random_number=$((RANDOM % (max - min + 1) + min))

sleep 0.${random_number}

if [ ${random_number} -gt 5 ]; then
  echo ${STATUS_IDLE}
else
  echo ${STATUS_PROCESSING}
fi

[ ${random_number} -lt 3 ] && exit ${random_number}

exit 0
