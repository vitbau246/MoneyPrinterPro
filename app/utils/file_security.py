import os


def _is_lexically_within(base_dir: str, path: str) -> bool:
    """只比较规范化后的字符串，判断 path 是否位于 base_dir 内，不访问文件系统。"""

    base = os.path.normcase(base_dir)
    try:
        return os.path.commonpath([base, os.path.normcase(path)]) == base
    except ValueError:
        # 不同盘符、UNC 与本地路径混用时 commonpath 会抛出 ValueError。
        return False


def resolve_path_within_directory(
    base_dir: str,
    unsafe_path: str,
    *,
    require_file: bool = True,
) -> str:
    # 用户传入的路径可能是文件名、相对路径、绝对路径，也可能夹带 `../`。
    # 这里统一解析成真实路径，并用 commonpath 判断它是否仍在允许目录内。
    # 这样比简单判断字符串前缀可靠，可以覆盖符号链接、重复分隔符、相对路径
    # 等场景，适用于上传目录、素材目录、任务产物目录这类白名单目录。
    if not unsafe_path:
        raise ValueError("empty path is not allowed")

    base_dir_real = os.path.realpath(base_dir)
    candidate_path = unsafe_path
    if not os.path.isabs(candidate_path):
        candidate_path = os.path.join(base_dir_real, candidate_path)

    # realpath 在 Windows 上会真正打开路径：`\\host\share\x` 这类 UNC 路径会
    # 因此向外部主机发起 SMB 连接并泄露 NTLM 哈希，即使随后 commonpath 会拒绝
    # 它。所以先做不访问文件系统的纯字符串检查，明显越界的路径直接拒绝。
    lexical_path = os.path.abspath(candidate_path)
    allowed_bases = (os.path.abspath(base_dir), base_dir_real)
    if not any(_is_lexically_within(base, lexical_path) for base in allowed_bases):
        raise ValueError("path is outside the allowed directory")

    resolved_path = os.path.realpath(candidate_path)
    try:
        common_path = os.path.commonpath([base_dir_real, resolved_path])
    except ValueError as exc:
        # Windows 下不同盘符会触发 ValueError，这类路径一定不属于允许目录。
        raise ValueError("path is outside the allowed directory") from exc

    if common_path != base_dir_real:
        raise ValueError("path is outside the allowed directory")

    if require_file and not os.path.isfile(resolved_path):
        raise ValueError("file does not exist")

    return resolved_path
