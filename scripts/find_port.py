"""In ra cong TCP trong 8501-8599 con bind duoc tren host (uu tien cong MPT_WEBUI_PORT)."""
import os
import socket
import sys

host = os.environ.get("MPT_WEBUI_HOST", "127.0.0.1")
try:
    preferred = int(os.environ.get("MPT_WEBUI_PORT", "8501"))
except ValueError:
    preferred = 8501

try:
    address = socket.gethostbyname(host)
except OSError:
    sys.exit(1)

for port in [preferred] + [p for p in range(8502, 8600) if p != preferred]:
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        sock.bind((address, port))
    except OSError:
        continue
    finally:
        sock.close()
    print(port)
    sys.exit(0)
sys.exit(1)
