#!/usr/bin/env bash
# Run only after `ssh prch` works:  ssh prch "sudo bash -s" < deploy/linode_harden_ssh.sh
# The file is 00-* because sshd keeps the FIRST value it reads and cloud images ship a
# 50-cloud-init.conf that turns password login back on.
set -euo pipefail
cat > /etc/ssh/sshd_config.d/00-prch.conf <<'EOF'
PasswordAuthentication no
KbdInteractiveAuthentication no
PermitRootLogin no
EOF
sshd -t
systemctl restart ssh
echo "== sshd: key-only, no root login"
