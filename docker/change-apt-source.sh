#!/usr/bin/env bash
set -e
echo "==> Switching APT source to Aliyun (HTTP)"
#删除 Debian 12 默认的 .sources（必须）
rm -f /etc/apt/sources.list.d/debian.sources
# 使用 HTTP 阿里云源
cat > /etc/apt/sources.list <<'EOF'
deb http://mirrors.aliyun.com/debian bookworm main contrib non-free non-free-firmware
deb http://mirrors.aliyun.com/debian bookworm-updates main contrib non-free non-free-firmware
deb http://mirrors.aliyun.com/debian bookworm-backports main contrib non-free non-free-firmware
deb http://mirrors.aliyun.com/debian-security bookworm-security main contrib non-free non-free-firmware
EOF
#更新索引
apt-get update
