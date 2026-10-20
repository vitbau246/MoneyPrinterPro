#!/usr/bin/env sh

# If you could not download the model from the official site, you can use the mirror site.
# Just remove the comment of the following line .
# 如果你无法从官方网站下载模型，你可以使用镜像网站。
# 只需要移除下面一行的注释即可。

# export HF_ENDPOINT=https://hf-mirror.com

CURRENT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
export PYTHONPATH="$CURRENT_DIR${PYTHONPATH:+:$PYTHONPATH}"

# 0.0.0.0 只能表示“监听所有网卡”，不适合作为浏览器访问地址。
# macOS/Linux 下浏览器打开 http://0.0.0.0:8501 可能会经过代理或网关，
# 最终出现 502。默认绑定并打开 127.0.0.1，与 Windows 启动脚本保持一致。
MPT_WEBUI_HOST="${MPT_WEBUI_HOST:-127.0.0.1}"
MPT_WEBUI_PORT="${MPT_WEBUI_PORT:-8501}"

# Tự tạo .venv (Python 3.11+) và cài thư viện lần đầu / khi requirements.txt thay đổi,
# giống scripts/env.bat trên Windows.
PYTHON="$CURRENT_DIR/.venv/bin/python"
if [ ! -x "$PYTHON" ]; then
  BASE_PYTHON=""
  for candidate in python3 python3.14 python3.13 python3.12 python3.11; do
    if command -v "$candidate" >/dev/null 2>&1       && "$candidate" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)'; then
      BASE_PYTHON="$candidate"
      break
    fi
  done
  if [ -z "$BASE_PYTHON" ]; then
    echo "***** Python 3.11+ was not found. Install Python 3.11 and run this script again. *****"
    exit 1
  fi
  echo "***** Creating .venv with $BASE_PYTHON *****"
  "$BASE_PYTHON" -m venv "$CURRENT_DIR/.venv" || exit 1
fi

STAMP="$CURRENT_DIR/.venv/mpt-requirements.installed"
if ! cmp -s "$CURRENT_DIR/requirements.txt" "$STAMP"; then
  echo "***** Installing Python packages from requirements.txt *****"
  "$PYTHON" -m pip install -r "$CURRENT_DIR/requirements.txt" || exit 1
  cp "$CURRENT_DIR/requirements.txt" "$STAMP"
fi

if [ ! -f "$CURRENT_DIR/config.toml" ] && [ -f "$CURRENT_DIR/config.example.toml" ]; then
  cp "$CURRENT_DIR/config.example.toml" "$CURRENT_DIR/config.toml"
fi

export PYTHONIOENCODING=utf-8
set -- "$PYTHON" -m streamlit
find_port() { find_available_port "$PYTHON"; }

find_available_port() {
  WEBUI_HOST="$MPT_WEBUI_HOST" WEBUI_PORT="$MPT_WEBUI_PORT" "$@" - <<'PY' 2>/dev/null
import os
import socket
import sys

host = os.environ.get("WEBUI_HOST", "127.0.0.1")
preferred = int(os.environ.get("WEBUI_PORT", "8501"))
candidates = [preferred] + [port for port in range(8502, 8600) if port != preferred]

for port in candidates:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        try:
            sock.bind((host, port))
        except OSError:
            continue
        print(port)
        sys.exit(0)

sys.exit(1)
PY
}

# 用 Python 做端口探测，避免依赖 lsof/nc 在不同 macOS/Linux 发行版上的差异。
SELECTED_WEBUI_PORT=$(find_port)

if [ -z "$SELECTED_WEBUI_PORT" ]; then
  echo "***** No available WebUI port found in 8501-8599 for $MPT_WEBUI_HOST. *****"
  exit 1
fi

if [ "$SELECTED_WEBUI_PORT" != "$MPT_WEBUI_PORT" ]; then
  echo "***** Port $MPT_WEBUI_PORT is unavailable, using $SELECTED_WEBUI_PORT instead. *****"
fi

MPT_WEBUI_PORT="$SELECTED_WEBUI_PORT"

echo "***** WebUI address: http://$MPT_WEBUI_HOST:$MPT_WEBUI_PORT *****"
"$@" run "$CURRENT_DIR/webui/Main.py" \
  --server.address="$MPT_WEBUI_HOST" \
  --server.port="$MPT_WEBUI_PORT" \
  --browser.serverAddress="$MPT_WEBUI_HOST" \
  --browser.gatherUsageStats=False \
  --client.toolbarMode=minimal \
  --logger.hideWelcomeMessage=True \
  --server.showEmailPrompt=False \
  --server.enableCORS=True
