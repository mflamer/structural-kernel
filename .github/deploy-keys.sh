#!/usr/bin/env bash
# Grant read-only access to the private design-library git dependencies
# (ndswood, aiscsteel, aciconcrete). Each repo has its OWN deploy key, so a
# single shared sshCommand won't do — we give each an SSH host alias mapped to
# its key and rewrite that repo's https URL to the alias. Keys come from the
# matching CI secrets in the environment.
set -euo pipefail

mkdir -p ~/.ssh
ssh-keyscan github.com >>~/.ssh/known_hosts 2>/dev/null

setup_key() {
  local name="$1" key="$2"
  printf '%s\n' "$key" >~/.ssh/"${name}"_key
  chmod 600 ~/.ssh/"${name}"_key
  cat >>~/.ssh/config <<EOF
Host github-${name}
  HostName github.com
  IdentityFile ~/.ssh/${name}_key
  IdentitiesOnly yes
EOF
  git config --global \
    url."git@github-${name}:mflamer/${name}".insteadOf \
    "https://github.com/mflamer/${name}"
}

setup_key ndswood "${NDSWOOD_DEPLOY_KEY}"
setup_key aiscsteel "${AISCSTEEL_DEPLOY_KEY}"
setup_key aciconcrete "${ACICONCRETE_DEPLOY_KEY}"
