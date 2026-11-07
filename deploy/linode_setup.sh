#!/usr/bin/env bash
# One-time Linode setup. Run as root from the laptop:
#   ssh -i C:\Users\Douglas\.ssh\prch_linode root@<IPv4> "bash -s" < deploy/linode_setup.sh
# Then test `ssh prch` and run linode_harden_ssh.sh, which turns off password and root login.
set -euo pipefail

. /etc/os-release
echo "== $PRETTY_NAME"
free -m
echo "cores: $(nproc)"
df -h /
ss -tlnp

case "$ID:$VERSION_ID" in
  ubuntu:22.04|ubuntu:24.04|debian:12) ;;
  *) echo "STOP: unsupported OS $ID $VERSION_ID"; exit 1 ;;
esac
if ss -tln | grep -qE ':(80|443)[[:space:]]'; then
  echo "STOP: port 80 or 443 is already in use on this machine"
  exit 1
fi

# Deploy user: key-only (no password), passwordless sudo, same keys as root.
id prch >/dev/null 2>&1 || adduser --disabled-password --gecos "" prch
echo "prch ALL=(ALL) NOPASSWD:ALL" > /etc/sudoers.d/90-prch
chmod 440 /etc/sudoers.d/90-prch
install -d -m 700 -o prch -g prch /home/prch/.ssh
install -m 600 -o prch -g prch /root/.ssh/authorized_keys /home/prch/.ssh/authorized_keys

# Docker Engine + compose plugin from Docker's apt repository.
export DEBIAN_FRONTEND=noninteractive
apt-get update
apt-get install -y ca-certificates curl ufw gettext-base unattended-upgrades
install -m 0755 -d /etc/apt/keyrings
curl -fsSL "https://download.docker.com/linux/$ID/gpg" -o /etc/apt/keyrings/docker.asc
chmod a+r /etc/apt/keyrings/docker.asc
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/$ID $VERSION_CODENAME stable" \
  > /etc/apt/sources.list.d/docker.list
apt-get update
apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
usermod -aG docker prch

# Firewall. Docker-published ports bypass ufw, which is why docker-compose.yml publishes
# nothing private.
ufw default deny incoming
ufw default allow outgoing
ufw allow 22/tcp
ufw allow 80/tcp
ufw allow 443/tcp
ufw allow 7100:7119/tcp
ufw --force enable

# 2 GB swap so Postgres is not OOM-killed under a spike. Not extra capacity.
if ! swapon --show | grep -q /swapfile; then
  fallocate -l 2G /swapfile
  chmod 600 /swapfile
  mkswap /swapfile
  swapon /swapfile
  grep -q '^/swapfile' /etc/fstab || echo '/swapfile none swap sw 0 0' >> /etc/fstab
fi
echo 'vm.swappiness=10' > /etc/sysctl.d/99-prch.conf
sysctl -p /etc/sysctl.d/99-prch.conf

dpkg-reconfigure -f noninteractive unattended-upgrades

mkdir -p /opt/prch/backups /opt/prch/incoming
chown -R prch:prch /opt/prch
echo "== done; now test: ssh prch \"docker run --rm hello-world\""
