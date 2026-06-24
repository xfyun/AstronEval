# -*- coding: utf-8 -*-
"""
常量定义模块
集中管理超时、默认值、错误码等
"""

# ============================================================================
# 超时配置（秒）
# ============================================================================
DEFAULT_TIMEOUT = 30           # HTTP 请求默认超时
DEFAULT_TOKEN_EXPIRY = 7200    # Token 默认过期时间（2小时）
DEFAULT_POLL_INTERVAL = 30     # 任务轮询间隔
DEFAULT_POLL_TIMEOUT = 3600    # 任务轮询总超时（1小时）

# ============================================================================
# 重试配置
# ============================================================================
MAX_RETRIES = 3
RETRY_BACKOFF_FACTOR = 1.0

# ============================================================================
# 错误码定义
# ============================================================================
# 错误码范围说明：
# - 脚本本地错误码: 1000-4999
# - 远程服务错误码: 10000-99999（透传，不修改）

# 文件相关错误 (1000-1999)
ERR_FILE_NOT_FOUND = 1001
ERR_FILE_ENCODING = 1002
ERR_FILE_PARSE = 1003

# 配置相关错误 (2000-2999)
ERR_CONFIG_INVALID = 2001
ERR_CONFIG_MISSING = 2002

# 网络相关错误 (3000-3999)
ERR_NETWORK_TIMEOUT = 3001
ERR_NETWORK_CONNECTION = 3002
ERR_NETWORK_RETRY_EXHAUSTED = 3003

# 数据相关错误 (4000-4999)
ERR_DATA_INVALID = 4001
ERR_DATA_MISSING_FIELD = 4002

# 远程服务错误码（透传，仅作参考）
# 认证服务错误码: 10000-19999
ERR_REMOTE_AUTH_EXPIRED = 10002  # Token 过期
ERR_REMOTE_DEFAULT = 10001       # 未知远程错误

# ============================================================================
# 默认路径
# ============================================================================
# 注意：这些路径相对于 scripts/ 目录
DEFAULT_AUTH_CONFIG = "cfg/eval-auth.cfg"
DEFAULT_SERVER_CONFIG = "cfg/eval-server.cfg"
DEFAULT_AUTH_CACHE = "./.eval/auth.json"

# ============================================================================
# OAuth 配置
# ============================================================================
OOB_REDIRECT = "urn:ietf:wg:oauth:2.0:oob"

# OAuth2 回调配置（loopback 模式）
DEFAULT_CALLBACK_HOST = "127.0.0.1"
DEFAULT_CALLBACK_PORT = 51943
DEFAULT_CALLBACK_PATH = "/callback"
DEFAULT_CALLBACK_TIMEOUT = 120  # 秒

# ============================================================================
# 任务状态
# ============================================================================
TERMINAL_STATES = {"Succeeded", "Failed", "Cancelled"}

# ============================================================================
# 维度配置
# ============================================================================
VALID_DIMENSION_TYPES = {"llm-score", "llm-judge", "builtin"}
BUILTIN_FUNCTIONS = {"BLEU", "ROUGE", "BERTScore", "COMET", "TER", "Cosine"}

# ============================================================================
# 评测集字段映射
# ============================================================================
FIELD_PATTERNS = {
    # 必填字段
    'question': ['question', 'prompt', 'input', 'query', '问题', '提问', '用户问题'],
    'answer': ['answer', 'response', 'output', 'reply', '回答', '回复', '模型回复'],
    'model': ['model', 'model_name', 'model_id', 'llm', 'llm_name', '模型', '模型名称', '大模型', '大语言模型'],
    'case_id': ['case_id', 'caseid', '用例id', '用例ID'],
    # 可选字段
    'system': ['system', 'system_prompt', '系统提示', '系统提示词'],
    'context': ['context', '上下文'],
    'category': ['category', 'type', '分类', '类别'],
    'reference': ['reference', 'ref', 'gold', '参考答案', '标准答案'],
    'keypoint': ['keypoint', 'keypoints', '关键点', '评测点', '评估点'],
}

# 特殊处理：'id' 字段需精确匹配到 case_id，避免 seq_id、user_id 误匹配
CASE_ID_EXACT_MATCH = ['id']

REQUIRED_FIELDS = ['question', 'answer', 'model', 'case_id']
OPTIONAL_FIELDS = ['system', 'context', 'category', 'reference', 'keypoint', 'metainfo']