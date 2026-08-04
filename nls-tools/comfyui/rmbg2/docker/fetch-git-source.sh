#!/usr/bin/env bash
set -euo pipefail

destination=$1
commit=$2
primary=$3
mirror=${4:-}

rm -rf "${destination}"
mkdir -p "${destination}"
git -C "${destination}" init --quiet
for repository in "${mirror}" "${primary}"; do
  [[ -n "${repository}" ]] || continue
  if git -C "${destination}" fetch --quiet --depth 1 "${repository}" "${commit}"; then
    git -C "${destination}" checkout --quiet --detach FETCH_HEAD
    actual=$(git -C "${destination}" rev-parse HEAD)
    [[ "${actual}" == "${commit}" ]] || {
      echo "Repository ${repository} returned ${actual}, expected ${commit}." >&2
      exit 1
    }
    rm -rf "${destination}/.git"
    echo "Fetched ${repository}@${commit}"
    exit 0
  fi
  echo "Unable to fetch ${commit} from ${repository}; trying next source." >&2
done
echo "No repository source provided the required commit ${commit}." >&2
exit 1
