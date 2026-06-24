# -*- coding: utf-8 -*-
"""
认证服务客户端模块

用于与 OAuth2 认证服务交互：
- 无 Bearer Token 注入（认证服务本身不需要）
- 处理认证服务特定的响应格式
"""
import logging
from typing import Dict, Any

import requests

from .http_client import BaseHttpClient
from utils.constants import DEFAULT_TIMEOUT, MAX_RETRIES, RETRY_BACKOFF_FACTOR

logger = logging.getLogger(__name__)


class AuthClient(BaseHttpClient):
    """
    认证服务客户端

    用于与 OAuth2 认证服务交互：
    - 无 Bearer Token 注入（认证服务本身不需要）
    - 处理认证服务特定的响应格式
    """

    def __init__(
        self,
        base_url: str = "",
        timeout: int = DEFAULT_TIMEOUT,
        max_retries: int = MAX_RETRIES,
        retry_backoff_factor: float = RETRY_BACKOFF_FACTOR,
        verify_ssl: bool = False
    ):
        """
        初始化认证客户端

        Args:
            base_url: 认证服务基础 URL（可选，可使用完整 URL 请求）
            timeout: 请求超时时间（秒）
            max_retries: 最大重试次数
            retry_backoff_factor: 重试退避因子
            verify_ssl: 是否验证 SSL 证书
        """
        super().__init__(
            base_url=base_url,
            timeout=timeout,
            max_retries=max_retries,
            retry_backoff_factor=retry_backoff_factor,
            verify_ssl=verify_ssl
        )

    def _handle_response(self, response: requests.Response) -> Dict[str, Any]:
        """
        处理认证服务响应

        认证服务响应格式（多种）：
        1. 标准格式: {"code": 0, "message": "success", "data": {...}}
        2. OAuth2错误格式: {"error": "...", "error_description": "..."}
        3. 纯文本错误

        修复：先解析响应体获取业务错误信息，再处理HTTP状态码
        """
        # 先尝试解析响应体（无论HTTP状态码如何）
        try:
            result = response.json()
        except ValueError:
            # JSON解析失败，可能是纯文本错误
            text = response.text
            if text:
                # 返回文本作为错误信息
                return {"code": response.status_code, "message": text, "data": None}
            # 无响应体时，使用HTTP状态码判断
            response.raise_for_status()
            return {}

        # 处理标准格式 {"code": 0, "message": "", "data": {}}
        if "code" in result:
            if result.get("code") != 0:
                # 返回完整错误信息（包含code和message）
                return result
            return result.get("data", result)

        # 处理OAuth2错误格式 {"error": "...", "error_description": "..."}
        if "error" in result:
            return {
                "code": response.status_code,
                "message": result.get("error_description", result.get("error")),
                "error": result.get("error"),
                "data": None
            }

        # 无code字段时，防御性检查HTTP状态码
        if response.status_code >= 400:
            response.raise_for_status()

        return result

    def request_full_url(
        self,
        method: str,
        url: str,
        **kwargs
    ) -> Dict[str, Any]:
        """
        使用完整 URL 发送请求（不拼接 base_url）

        适用于认证服务的端点 URL 是完整路径的场景

        Args:
            method: HTTP 方法
            url: 完整 URL
            **kwargs: 其他参数

        Returns:
            响应数据
        """
        return self.request(method, url, full_url=True, **kwargs)