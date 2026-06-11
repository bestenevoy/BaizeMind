#!/bin/bash
# Milvus Standalone 安装脚本
# 适用于 Ubuntu / Debian / CentOS

set -e

echo "=== Milvus Standalone Setup ==="

MILVUS_VERSION="2.4.0"
INSTALL_DIR="$HOME/milvus"

if command -v milvus &>/dev/null; then
    echo "Milvus is already installed."
    milvus --version 2>/dev/null || true

    if pgrep -f "milvus run" &>/dev/null; then
        echo "Milvus is already running."
    else
        echo "Starting Milvus..."
        nohup milvus run standalone > /tmp/milvus.log 2>&1 &
        sleep 3
        echo "Milvus started. Check logs: tail -f /tmp/milvus.log"
    fi
    exit 0
fi

echo "Downloading Milvus Standalone v${MILVUS_VERSION}..."

mkdir -p "$INSTALL_DIR" && cd "$INSTALL_DIR"

ARCH=$(uname -m)
if [ "$ARCH" = "x86_64" ]; then
    ARCH="amd64"
elif [ "$ARCH" = "aarch64" ]; then
    ARCH="arm64"
fi

OS=$(uname -s | tr '[:upper:]' '[:lower:]')
MILVUS_TAR="milvus-standalone-${OS}-${ARCH}.tar.gz"
MILVUS_URL="https://github.com/milvus-io/milvus/releases/download/v${MILVUS_VERSION}/${MILVUS_TAR}"

wget -q --show-progress "$MILVUS_URL" -O "$MILVUS_TAR" || {
    echo "Download failed. Trying apt install..."
    if command -v apt-get &>/dev/null; then
        sudo apt-get update && sudo apt-get install -y milvus
    elif command -v yum &>/dev/null; then
        sudo yum install -y milvus
    else
        echo "Please install Milvus manually: https://milvus.io/docs/install_standalone.md"
        exit 1
    fi
}

if [ -f "$MILVUS_TAR" ] && command -v tar &>/dev/null; then
    tar xzf "$MILVUS_TAR"
    echo "Extracted to $INSTALL_DIR"
fi

echo ""
echo "=== Milvus installation complete ==="
echo ""
echo "To start Milvus:"
echo "  milvus run standalone"
echo ""
echo "To check connection with Python:"
echo "  python -c 'from pymilvus import connections; connections.connect(\"default\", host=\"127.0.0.1\", port=\"19530\"); print(\"Connected!\")'"
