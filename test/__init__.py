# Unit test package for test
"""
Test không được chạm vào môi trường thật.

Trước khi module test nào nạp ``app``, gói này trỏ config.toml và thư mục storage
sang một thư mục tạm riêng cho lần chạy:

- config.toml tạm được app.config chép từ config.example.toml, nên không có khoá
  API hay token thật, test không thể gọi dịch vụ bằng tài khoản của người dùng;
- storage tạm chứa cache tìm clip, task, file tạm... thay cho storage thật;
- MPT_TESTING=1 bật khoá an toàn trong app.config: save_config từ chối ghi vào
  config.toml thật nếu có test trỏ ngược về đó.

Thư mục tạm bị xoá khi tiến trình test kết thúc. Chạy test qua gói này:
``python -m unittest discover -s test -t .`` hoặc ``pytest test``. Chạy thẳng
``python test/services/test_x.py`` thì bỏ qua bước cô lập.
"""

import atexit
import os
import shutil
import sys
import tempfile

if "app.config.config" in sys.modules:
    raise RuntimeError(
        "app.config was imported before the test package isolated config.toml and "
        "storage; run tests with `python -m unittest discover -s test -t .` or "
        "`pytest test`."
    )

_ISOLATED_ROOT = tempfile.mkdtemp(prefix="mpt-test-")
os.environ["MPT_TESTING"] = "1"
os.environ["MPT_CONFIG_FILE"] = os.path.join(_ISOLATED_ROOT, "config.toml")
os.environ["MPT_STORAGE_DIR"] = os.path.join(_ISOLATED_ROOT, "storage")
atexit.register(shutil.rmtree, _ISOLATED_ROOT, ignore_errors=True)
