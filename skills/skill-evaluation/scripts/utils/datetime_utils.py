# -*- coding: utf-8 -*-
"""
时间处理工具函数
提供 ISO 格式时间解析和过期检查功能
"""
from datetime import datetime
from typing import Optional


def parse_iso_datetime(dt_str: str) -> Optional[datetime]:
    """
    解析 ISO 格式时间字符串，支持带时区和不带时区格式

    Args:
        dt_str: ISO 格式时间字符串

    Returns:
        datetime 对象，解析失败返回 None

    Examples:
        >>> parse_iso_datetime("2024-01-15T10:30:00")
        datetime(2024, 1, 15, 10, 30, 0)
        >>> parse_iso_datetime("2024-01-15T10:30:00Z")
        datetime(2024, 1, 15, 10, 30, 0, tzinfo=timezone.utc)
        >>> parse_iso_datetime("2024-01-15T10:30:00+08:00")
        datetime(2024, 1, 15, 10, 30, 0, tzinfo=timezone(timedelta(hours=8)))
    """
    try:
        # Python 3.7+ 支持 datetime.fromisoformat
        if '+' in dt_str or dt_str.endswith('Z'):
            return datetime.fromisoformat(dt_str.replace('Z', '+00:00'))
        return datetime.fromisoformat(dt_str)
    except ValueError:
        return None


def is_expired(expires_at: str) -> bool:
    """
    检查过期时间是否已过期

    Args:
        expires_at: ISO 格式的过期时间字符串

    Returns:
        True 表示已过期或无法解析，False 表示未过期

    Examples:
        >>> is_expired("2020-01-01T00:00:00")  # 过去时间
        True
        >>> is_expired("2099-12-31T23:59:59")  # 未来时间
        False
    """
    expire_time = parse_iso_datetime(expires_at)
    if expire_time is None:
        return True

    now = datetime.now()
    if expire_time.tzinfo:
        now = now.astimezone()
    return now >= expire_time