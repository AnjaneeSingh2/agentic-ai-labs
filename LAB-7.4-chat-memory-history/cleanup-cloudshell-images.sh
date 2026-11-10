#!/usr/bin/env bash
# LAB 7.4 – Step 10: free Cloud Shell disk space by removing local container images.
#
# Usage: bash cleanup-cloudshell-images.sh
#
# Removes untagged build leftovers, then offers to remove local copies of tagged images
# (one prompt per image). Pushed images stay in OCIR; only the local copies are deleted.
# The fnproject base images are always kept because fn deploy needs them.
set -uo pipefail

echo "Before: $(df -h "$HOME" | awk 'NR==2 {print $3" used, "$4" free ("$5")"}')"

# If the disk is completely full, Podman cannot rewrite its index files.
# Temporarily move ~/.cache to /tmp to make room; it is moved back at the end.
moved_cache=0
if [ "$(df -Pk "$HOME" | awk 'NR==2 {print $4}')" -lt 5120 ] && [ -d "$HOME/.cache" ]; then
  mv "$HOME/.cache" /tmp/home-cache-backup && moved_cache=1
  echo "Disk was full: moved ~/.cache to /tmp/home-cache-backup for now."
fi

echo "Removing untagged images..."
docker image prune -f

echo
docker images
echo
docker images --format '{{.Repository}}:{{.Tag}}' | grep -v '^<none>' | grep -v 'fnproject/' | while read -r img; do
  read -r -p "Remove local copy of $img? [y/N] " ans < /dev/tty
  if [ "${ans,,}" = "y" ]; then docker rmi "$img"; fi
done

docker image prune -f >/dev/null 2>&1

if [ "$moved_cache" = 1 ]; then
  mv /tmp/home-cache-backup "$HOME/.cache" && echo "Moved ~/.cache back."
fi

echo "After:  $(df -h "$HOME" | awk 'NR==2 {print $3" used, "$4" free ("$5")"}')"
