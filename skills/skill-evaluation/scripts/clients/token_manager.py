# -*- coding: utf-8 -*-
"""
Token 管理器模块

负责从 auth_file 读取 token，懒加载检查过期。
"""
from typing import Optional

from utils.constants import ERR_REMOTE_AUTH_EXPIRED
from utils.errors import AuthExpiredError
from files.file_utils import load_json
from utils.datetime_utils import is_expired


class TokenManager:
    """
    Token 管理器 - 懒加载检查 token 有效性

    D-05: 负责从 auth_file 读取 token，懒加载检查过期
    D-06: 请求时检查 token 有效性，无效时提示重新授权
    """

    def __init__(self, auth_file: str):
        self.auth_file = auth_file
        self._token: Optional[str] = None
        self._expires_at: Optional[str] = None
        self._loaded = False

    def get_token(self) -> str:
        """获取有效 token，懒加载并检查过期"""
        if not self._loaded:
            self._load_token()
        if self._is_expired():
            raise AuthExpiredError("Token 已过期，请重新授权")
        return self._token

    def _load_token(self):
        """从 auth_file 加载 token"""
        result = load_json(self.auth_file)
        if not result.get("success"):
            raise FileNotFoundError(f"鉴权文件不存在: {self.auth_file}")
        data = result.get("data", {})
        self._token = data.get("access_token")
        self._expires_at = data.get("expires_at")
        self._loaded = True
        if not self._token:
            raise ValueError("鉴权文件中未找到 access_token")

    def _is_expired(self) -> bool:
        """检查 token 是否过期"""
        if not self._expires_at:
            return True
        return is_expired(self._expires_at)