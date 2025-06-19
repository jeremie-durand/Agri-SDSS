#!/bin/bash
# Convertit un chemin Windows en chemin Linux pour WSL (Windows Subsystem for Linux)


# Vérifie si un argument est donné
if [ -z "$1" ]; then
  echo "Usage: $0 <chemin_windows>"
  echo "Exemple : $0 'C:/Users/18195/OneDrive - USherbrooke/Bureau/MOS_data/SIIGSOL-100m/corg_fr_siigsol'"
  exit 1
fi

WIN_PATH="$1"

# Conversion :
# - Lettre de lecteur (ex: C:) en /mnt/c
# - Remplacement des backslashs \ par slash /
# - Gestion des espaces dans le chemin (garde tel quel)

LINUX_PATH=$(echo "$WIN_PATH" | sed -E 's|^([A-Za-z]):|/mnt/\L\1|' | sed 's|\\|/|g')

# Message de fin de script
echo "Le chemin Linux correspondant est : $LINUX_PATH"
read -p "You can now copy the mounted path - Press [Enter] to exit..."