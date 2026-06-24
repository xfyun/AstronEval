# -*- coding: utf-8 -*-
"""
基础 HTTP 客户端模块

提供统一的 HTTP 请求处理：
- 自动重试（连接超时、读取超时、瞬态故障）
- 超时控制
- 连接池管理
- SSL 证书验证控制
- 分级日志

子类可覆写：
- _inject_auth(): 注入认证信息
- _handle_response(): 处理响应
"""
import time
import logging
import requests
from typing import Optional, Dict, Any
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

from utils.constants import (
    DEFAULT_TIMEOUT,
    MAX_RETRIES,
    RETRY_BACKOFF_FACTOR,
    ERR_NETWORK_RETRY_EXHAUSTED,
)
from utils.errors import (
    NetworkError,
    NetworkTimeoutError,
    NetworkConnectionError,
)

logger = logging.getLogger(__name__)


class BaseHttpClient:
    """
    基础 HTTP 客户端

    提供统一的 HTTP 请求处理：
    - 自动重试（连接超时、读取超时、瞬态故障）
    - 超时控制
    - 连接池管理
    - SSL 证书验证控制
    - 分级日志

    子类可覆写：
    - _inject_auth(): 注入认证信息
    - _handle_response(): 处理响应
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
        初始化基础 HTTP 客户端

        Args:
            base_url: 服务基础 URL（可选，可使用完整 URL 请求）
            timeout: 请求超时时间（秒）
            max_retries: 最大重试次数
            retry_backoff_factor: 重试退避因子
            verify_ssl: 是否验证 SSL 证书
        """
        self.base_url = base_url.rstrip('/') if base_url else ""
        self.timeout = timeout
        self.max_retries = max_retries
        self.retry_backoff_factor = retry_backoff_factor
        self.verify_ssl = verify_ssl
        self.session = self._create_session()

    def _create_session(self) -> requests.Session:
        """创建带重试配置的 Session"""
        session = requests.Session()

        # 配置重试策略
        # 重试条件：连接超时、读取超时、连接错误、瞬态 HTTP 错误
        retry = Retry(
            total=self.max_retries,
            backoff_factor=self.retry_backoff_factor,
            status_forcelist=[429, 500, 502, 503, 504],  # 瞬态故障
            allowed_methods=["HEAD", "GET", "OPTIONS", "POST", "PUT", "DELETE", "PATCH"],
            raise_on_status=False,
        )

        adapter = HTTPAdapter(max_retries=retry)
        session.mount("https://", adapter)
        session.mount("http://", adapter)

        return session

    def _inject_auth(self, headers: Dict[str, str]) -> Dict[str, str]:
        """
        注入认证信息（子类覆写）

        Args:
            headers: 现有请求头

        Returns:
            注入认证信息后的请求头
        """
        return headers

    def _handle_response(self, response: requests.Response) -> Dict[str, Any]:
        """
        处理响应（子类可覆写）

        Args:
            response: HTTP 响应对象

        Returns:
            解析后的响应数据
        """
        response.raise_for_status()
        return response.json()

    def request(
        self,
        method: str,
        url_or_endpoint: str,
        full_url: bool = False,
        **kwargs
    ) -> Dict[str, Any]:
        """
        发送 HTTP 请求

        Args:
            method: HTTP 方法（GET, POST, etc.）
            url_or_endpoint: URL 或端点路径
            full_url: 是否为完整 URL（True 则不拼接 base_url）
            **kwargs: 传递给 requests 的其他参数

        Returns:
            解析后的响应数据
        """
        # 构建 URL
        if full_url:
            url = url_or_endpoint
        else:
            url = f"{self.base_url}{url_or_endpoint}"

        # 设置默认参数
        kwargs.setdefault("timeout", self.timeout)
        kwargs.setdefault("verify", self.verify_ssl)

        # 处理请求头
        headers = kwargs.pop("headers", {})
        headers.setdefault("Content-Type", "application/json")
        headers = self._inject_auth(headers)
        kwargs["headers"] = headers

        start = time.time()
        try:
            resp = self.session.request(method, url, **kwargs)
            elapsed = time.time() - start
            logger.info(f"{method} {url} -> {resp.status_code} ({elapsed:.2f}s)")
            return self._handle_response(resp)

        except requests.Timeout as e:
            logger.error(f"{method} {url} -> TIMEOUT")
            raise NetworkTimeoutError(f"请求超时: {url}", original_error=e)

        except requests.ConnectionError as e:
            logger.error(f"{method} {url} -> CONNECTION_ERROR")
            raise NetworkConnectionError(f"连接失败: {url}", original_error=e)

        except requests.exceptions.RetryError as e:
            logger.error(f"{method} {url} -> RETRY_EXHAUSTED")
            raise NetworkError(
                f"重试耗尽: {url}",
                original_error=e,
                code=ERR_NETWORK_RETRY_EXHAUSTED
            )

    def get(self, url_or_endpoint: str, **kwargs) -> Dict[str, Any]:
        """发送 GET 请求"""
        return self.request("GET", url_or_endpoint, **kwargs)

    def post(self, url_or_endpoint: str, **kwargs) -> Dict[str, Any]:
        """发送 POST 请求"""
        return self.request("POST", url_or_endpoint, **kwargs)

    def put(self, url_or_endpoint: str, **kwargs) -> Dict[str, Any]:
        """发送 PUT 请求"""
        return self.request("PUT", url_or_endpoint, **kwargs)

    def delete(self, url_or_endpoint: str, **kwargs) -> Dict[str, Any]:
        """发送 DELETE 请求"""
        return self.request("DELETE", url_or_endpoint, **kwargs)