#!/bin/bash
# memory-guard.sh - M1 Pro 16GB memory protection
# Warns when system memory is low to prevent OOM during agent orchestration
MEM_PRESSURE=$(memory_pressure 2>/dev/null | grep "System-wide memory free percentage" | awk '{print $NF}' | tr -d '%')
if [[ -n "$MEM_PRESSURE" && "$MEM_PRESSURE" -lt 10 ]]; then
  echo "Warning: System memory critically low (${MEM_PRESSURE}% free). Consider reducing concurrent agents." >&2
fi
exit 0
