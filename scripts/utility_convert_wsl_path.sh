#!/bin/bash
# Convert a Windows path to a Linux path for WSL2


# Arguments check
if [ -z "$1" ]; then
  echo "Usage: $0 <windows_path>"
  echo "Example: $0 'C:/Users/username/OneDrive/Documents/MOS_data/SIIGSOL-100m/corg_fr_siigsol'"
  exit 1
fi

WIN_PATH="$1"

# Convert drive letter and backslashes to WSL2 mount path
LINUX_PATH=$(echo "$WIN_PATH" | sed -E 's|^([A-Za-z]):|/mnt/\L\1|' | sed 's|\\|/|g')

echo "Equivalent Linux path: $LINUX_PATH"
read -p "You can now copy the mounted path - Press [Enter] to exit..."