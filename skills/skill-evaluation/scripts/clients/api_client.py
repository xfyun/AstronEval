# -*- coding: utf-8 -*-
"""
评测服务 API 客户端模块

继承 BaseHttpClient，添加 Bearer Token 注入和 x-consumer-username 请求头
"""
import logging
from pathlib import Path
from typing import Dict, Any, Optional

import requests

from .http_client import BaseHttpClient
from utils.constants import DEFAULT_TIMEOUT, DEFAULT_SERVER_CONFIG
from utils.errors import (
    AuthExpiredError,
    ApiError,
)
from .token_manager import TokenManager
from files.file_utils import load_config_kv

logger = logging.getLogger(__name__)


# ============================================================================
# 评测服务 API 客户端
# ============================================================================

class ApiClient(BaseHttpClient):
    """
    评测服务 API 客户端

    继承 BaseHttpClient，添加：
    - Bearer Token 认证注入
    - x-consumer-username 请求头
    - 评测服务特定的响应处理
    - Token 过期检测

    D-05: RequestBuilder 负责构建请求、注入 header、处理响应
    D-08: 只重试瞬态故障: 502, 503, 504
    D-09: 3 次重试 + 指数退避 (1s, 2s, 4s)
    D-10: 透传远程服务错误，保留原 code
    D-12: 简洁日志 - URL + 方法 + 状态码 + 耗时
    D-13: 分级日志 - INFO/WARNING/ERROR
    """

    def __init__(
        self,
        token_manager: TokenManager,
        base_url: str,
        timeout: int = DEFAULT_TIMEOUT,
        config_path: Optional[str] = None
    ):
        """
        初始化评测服务客户端

        Args:
            token_manager: Token 管理器
            base_url: 评测服务基础 URL
            timeout: 请求超时时间（秒）
            config_path: 配置文件路径（用于读取 username）
        """
        # 保存 token_manager
        self.token_manager = token_manager

        # 加载配置获取 username
        self._username: Optional[str] = None
        if config_path:
            self._load_username(config_path)

        # 调用父类初始化
        super().__init__(
            base_url=base_url,
            timeout=timeout,
            verify_ssl=False  # 跳过SSL验证（部分服务器证书异常）
        )

    def _load_username(self, config_path: str):
        """从配置文件加载 username"""
        # 解析相对路径
        p = Path(config_path)
        if not p.is_absolute():
            # config_path 相对于 skill-evaluation 根目录
            # __file__ 在 scripts/clients/api_client.py，所以 parent.parent.parent 是根目录
            p = Path(__file__).parent.parent.parent / config_path

        result = load_config_kv(str(p))
        if result.get("success") and result.get("data"):
            self._username = result["data"].get("username")

    def _inject_auth(self, headers: Dict[str, str]) -> Dict[str, str]:
        """注入 Bearer Token 认证和 x-consumer-username"""
        token = self.token_manager.get_token()
        headers["Authorization"] = f"Bearer {token}"
        if self._username:
            headers["x-consumer-username"] = self._username
        return headers

    def _handle_response(self, response: requests.Response) -> Dict[str, Any]:
        """
        处理评测服务响应

        D-10: 透传远程错误码和消息

        修复：先解析响应体获取业务错误码，再处理HTTP状态码
        支持多种响应格式：
        1. 标准格式: {"code": 0, "message": "success", "data": {...}}
        2. OAuth2错误格式: {"error": "...", "error_description": "..."}
        """
        # 先尝试解析响应体（无论HTTP状态码如何）
        try:
            result = response.json()
        except ValueError:
            # JSON解析失败时，使用HTTP状态码判断
            if response.status_code == 401:
                raise AuthExpiredError("Token 已过期，请重新授权")
            response.raise_for_status()
            return {}

        # 检查认证过期 (code=10002 或 OAuth2格式)
        if result.get('code') == 10002:
            raise AuthExpiredError("Token 已过期，请重新授权")

        # 处理OAuth2错误格式 {"error": "...", "error_description": "..."}
        if "error" in result and "code" not in result:
            # HTTP 401 认证错误抛出 AuthExpiredError
            if response.status_code == 401:
                raise AuthExpiredError(result.get('error_description', 'Token 已过期，请重新授权'))
            # 其他错误抛出 ApiError，使用 HTTP 状态码作为错误码
            raise ApiError(
                message=result.get('error_description', result.get('error', 'Unknown error')),
                code=response.status_code,
                data={"error": result.get('error')}
            )

        # 透传业务错误码（优先于HTTP状态码）
        if result.get('code') != 0:
            raise ApiError(
                message=result.get('message', 'Unknown error'),
                code=result.get('code'),
                data=result.get('data')
            )

        # 业务成功时，防御性检查HTTP状态码
        if response.status_code >= 400:
            response.raise_for_status()

        return result.get('data', {})

    def get_models(self) -> list:
        """获取可用推理模型名称列表

        Returns:
            模型名称列表，如 ["deepseek-r1", "gpt-4", "claude-3"]
        """
        response = self.get("/open/api/v1/models")
        return response.get("models", [])

    def get_models_detail(self) -> list:
        """获取可用推理模型详情列表

        调用 /open/api/v1/models 接口，返回完整的模型信息。

        Returns:
            模型信息列表，每项包含:
            - name: 模型名称
            - description: 模型描述
            - model: 模型服务标识
            - id: 模型ID（用于填充 metainfo.infer_model_id）
        """
        response = self.get("/open/api/v1/models")
        # response 是 data 数组
        models = response if isinstance(response, list) else []
        # 确保 id 字段为字符串类型
        for m in models:
            if "id" in m and not isinstance(m["id"], str):
                m["id"] = str(m["id"])
        return models