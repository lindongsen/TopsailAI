#!/bin/bash
# Author: DawsonLin
# Email: lin_dongsen@126.com
# Created: 2026-04-15
# Purpose:

min=1
max=10
random_number=$((RANDOM % (max - min + 1) + min))
echo ${random_number}

sleep ${random_number}

exit 0
