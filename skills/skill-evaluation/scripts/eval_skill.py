#!/usr/bin/env python3
"""云端 Skill 评测脚本：封装提交/状态查询/产物获取接口"""
import argparse
import json
import re
import sys
import time
import zipfile
from pathlib import Path

import requests

# eval_skill.py 现在位于 scripts/ 目录内，直接将当前目录加入 sys.path
_SCRIPTS_DIR = Path(__file__).parent
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

from clients import ApiClient, TokenManager  # noqa: E402
from utils.errors import EvalError, ApiError, AuthExpiredError  # noqa: E402


TERMINAL_STATES = {"Succeeded", "Failed", "Cancelled"}
DEFAULT_AUTH_FILE = "./.eval/auth.json"


def load_config(config_path: str) -> dict:
    cfg = {}
    with open(config_path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if ":" in line:
                k, _, v = line.partition(":")
                cfg[k.strip()] = v.strip().strip('"')
    return cfg


def load_models(models_path: str) -> dict:
    with open(models_path, encoding="utf-8") as f:
        return json.load(f)


# ============================================================================
# 鉴权辅助：所有平台业务接口统一通过 ApiClient 注入 Bearer Token
# ============================================================================

def _resolve_auth_file(args) -> str:
    """从 args 中解析 auth-file 路径，未提供则使用默认值。"""
    return getattr(args, "auth_file", None) or DEFAULT_AUTH_FILE


def _make_client(cfg: dict, auth_file: str) -> ApiClient:
    """构建已注入 Bearer Token 的 API 客户端。

    Token 通过 TokenManager 从 auth.json 懒加载，过期或缺失时抛 AuthExpiredError。
    同时注入 x-consumer-username 请求头。
    """
    base_url = cfg.get("base_url", "").rstrip("/")
    token_manager = TokenManager(auth_file)
    return ApiClient(token_manager, base_url, config_path="cfg/eval-server.cfg")


def _bearer_headers(auth_file: str) -> dict:
    """获取含 Authorization 和 x-consumer-username 的请求头，用于 multipart 文件上传。

    multipart 请求不能复用 ApiClient（其强制 Content-Type=application/json，
    会破坏 requests 自动生成的 multipart 边界），因此单独取 token 自行构造。
    """
    token = TokenManager(auth_file).get_token()
    headers = {"Authorization": f"Bearer {token}"}

    # 加载 username 配置
    config_path = Path(__file__).parent / "cfg" / "eval-server.cfg"
    if config_path.exists():
        cfg = load_config(str(config_path))
        if cfg.get("username"):
            headers["x-consumer-username"] = cfg["username"]

    return headers


def _print_error_and_exit(e: Exception, *, exit_code: int = 1):
    """统一打印错误并退出。EvalError 透传 code/message。"""
    if isinstance(e, EvalError):
        payload = {"success": False, "code": e.code, "message": e.message}
    else:
        payload = {"success": False, "message": str(e)}
    print(json.dumps(payload, ensure_ascii=False))
    sys.exit(exit_code)


# ============================================================================
# 登录鉴权（阶段 1）
# ============================================================================

def _check_token(auth_file: str) -> dict:
    """检查本地 Token 是否有效，返回 {status, access_token?, expires_at?}"""
    from datetime import datetime
    p = Path(auth_file)
    if not p.exists():
        return {"status": "not_found"}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {"status": "invalid"}

    access_token = data.get("access_token", "")
    expires_at = data.get("expires_at", "")
    if not access_token:
        return {"status": "invalid"}
    if expires_at:
        try:
            if datetime.now().astimezone() >= datetime.fromisoformat(expires_at):
                return {"status": "expired"}
        except Exception:
            return {"status": "invalid"}
    return {"status": "valid", "access_token": access_token, "expires_at": expires_at}


def cmd_login(args):
    """
    检查或刷新鉴权 Token。

    - 若 Token 有效，直接返回
    - 若无效，调用 scripts/eval_auth.py 完成 OAuth2 登录（支持自动回调和手动 OOB 两种模式）
    """
    auth_file = args.auth_file
    scripts_dir = Path(__file__).parent

    if not args.force:
        check = _check_token(auth_file)
        if check["status"] == "valid":
            print(json.dumps({"status": "valid",
                              "access_token": check["access_token"],
                              "expires_at": check["expires_at"]}, ensure_ascii=False))
            return

    # Token 无效，调用鉴权脚本
    auth_script = scripts_dir / "eval_auth.py"
    auth_cfg = scripts_dir / "cfg" / "eval-auth.cfg"

    cmd = [
        sys.executable, str(auth_script),
        "login",
        "--config", str(auth_cfg),
        "--output", auth_file,
    ]
    if args.mode:
        cmd += ["--mode", args.mode]
    if args.port:
        cmd += ["--port", str(args.port)]

    import subprocess
    result = subprocess.run(cmd, capture_output=False)
    sys.exit(result.returncode)


def cmd_token(args):
    """
    用授权码换取 Token 并保存到 auth.json。

    当 login 返回 manual_url 时，用户访问链接获取授权码后，
    调用此命令完成登录。
    """
    auth_file = args.auth_file
    scripts_dir = Path(__file__).parent

    auth_script = scripts_dir / "eval_auth.py"
    auth_cfg = scripts_dir / "cfg" / "eval-auth.cfg"

    cmd = [
        sys.executable, str(auth_script),
        "token",
        "--config", str(auth_cfg),
        "--output", auth_file,
        "--code", args.code,
        "--state_token", args.state_token,
    ]

    import subprocess
    result = subprocess.run(cmd, capture_output=False)
    sys.exit(result.returncode)


def cmd_check_token(args):
    """仅检查 Token 有效性，不触发登录。

    退出码：始终 0。Token 状态通过 stdout 的 JSON `status` 字段传达，调用方据此分支处理。
    这样 `not_found` / `invalid` / `expired` 都是预期状态，不污染 Bash 工具的错误流。
    """
    check = _check_token(args.auth_file)
    print(json.dumps(check, ensure_ascii=False))
    sys.exit(0)


# ============================================================================
# 检查评测集字段完整性（阶段 3）
# ============================================================================

def cmd_check_dataset(args):
    """
    检查评测集是否缺少 category 或 keypoint 字段值。

    返回：
    - needs_completion: true 表示需要补全（缺少字段或存在空值）
    - missing_fields: 缺少的字段列表
    - empty_count: 存在空值的样例数量
    """
    dataset_path = Path(args.dataset)
    if not dataset_path.exists():
        print(json.dumps({"success": False, "message": f"文件不存在: {dataset_path}"}, ensure_ascii=False))
        sys.exit(1)

    try:
        data = json.loads(dataset_path.read_text(encoding="utf-8"))
        if not isinstance(data, list):
            # 支持多种嵌套格式：items 或 cases
            data = data.get("items") or data.get("cases") or []
    except Exception as e:
        print(json.dumps({"success": False, "message": f"解析失败: {e}"}, ensure_ascii=False))
        sys.exit(1)

    if not data:
        print(json.dumps({"success": True, "needs_completion": False, "total": 0}, ensure_ascii=False))
        return

    total = len(data)
    has_category = all("category" in case for case in data)
    has_keypoint = all("keypoint" in case for case in data)

    # 检查是否存在空值
    empty_category = sum(1 for case in data if not case.get("category", "").strip())
    empty_keypoint = sum(1 for case in data if not case.get("keypoint", "").strip())

    missing_fields = []
    if not has_category or empty_category > 0:
        missing_fields.append("category")
    if not has_keypoint or empty_keypoint > 0:
        missing_fields.append("keypoint")

    needs_completion = bool(missing_fields)

    print(json.dumps({
        "success": True,
        "needs_completion": needs_completion,
        "missing_fields": missing_fields,
        "empty_category_count": empty_category,
        "empty_keypoint_count": empty_keypoint,
        "total": total,
    }, ensure_ascii=False))


# ============================================================================
# 获取云端模型列表（阶段 2）
# ============================================================================

def cmd_models(args):
    """
    获取评测平台推荐模型列表（限时免费）。

    调用 /eval/api/v1/recommend/models，使用 Bearer Token 鉴权。
    将 data.limited_free[] 扁平化为统一的模型列表，每条携带
    source/recommend_model_id/usage 等字段，供后续筛选和任务提交使用。
    """
    cfg = load_config(args.config)
    auth_file = _resolve_auth_file(args)

    params = {}
    if args.scene:
        params["scene"] = args.scene
    if args.usage:
        params["usage"] = args.usage

    try:
        client = _make_client(cfg, auth_file)
        payload = client.get("/eval/api/v1/recommend/models", params=params) or {}

        models = []
        for m in payload.get("limited_free", []) or []:
            models.append({
                "source": "limited_free",
                "recommend_model_id": str(m.get("id", "")),
                "name": m.get("name", ""),
                "display_name": m.get("display_name", ""),
                "description": m.get("description", ""),
                "type": m.get("type", ""),
                "model": m.get("model", ""),
                "usage": m.get("usage", ""),
                "scene": m.get("scene", ""),
                "recommend_type": m.get("recommend_type", ""),
                "concurrency": m.get("concurrency", 0),
                "expires_at": m.get("expires_at", ""),
            })

        result = {
            "success": True,
            "has_limited_free": payload.get("has_limited_free", False),
            "models": models,
        }

        if args.output:
            output_path = Path(args.output)
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")

        print(json.dumps(result, ensure_ascii=False))

    except Exception as e:
        _print_error_and_exit(e)


# ============================================================================
# 打包并上传 Skill（阶段 2）
# ============================================================================

def cmd_package(args):
    """打包 Skill 目录为 zip 并上传，返回 URL。

    三种输入模式（互斥）：
    - `--skill-dir <dir>`：单个 Skill 目录，按目录名打包
    - `--skill-dir <dir> --extra-skills <dir1,dir2,...>`：父 Skill + 协同 Skill，合成一个 zip
    - `--skill-zip <path>`：已打好的 zip 包（云端下载或用户提供），直接上传
    """
    zip_path: Path
    skill_name: str
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    if args.skill_zip:
        src_zip = Path(args.skill_zip)
        if not src_zip.exists():
            print(json.dumps({"success": False, "message": f"zip 文件不存在: {src_zip}"}, ensure_ascii=False))
            sys.exit(1)
        skill_name = src_zip.stem
        zip_path = src_zip if src_zip.parent.resolve() == output_dir.resolve() else output_dir / src_zip.name
        if zip_path != src_zip:
            zip_path.write_bytes(src_zip.read_bytes())
    else:
        skill_dir = Path(args.skill_dir)
        if not skill_dir.exists():
            print(json.dumps({"success": False, "message": f"Skill 目录不存在: {args.skill_dir}"}, ensure_ascii=False))
            sys.exit(1)
        if not (skill_dir / "SKILL.md").exists():
            print(json.dumps({"success": False, "message": f"未找到 SKILL.md: {skill_dir / 'SKILL.md'}"}, ensure_ascii=False))
            sys.exit(1)

        skill_name = skill_dir.name
        extra_dirs = []
        if args.extra_skills:
            for raw in args.extra_skills.split(","):
                raw = raw.strip()
                if not raw:
                    continue
                d = Path(raw)
                if not d.exists():
                    print(json.dumps({"success": False, "message": f"协同 Skill 目录不存在: {raw}"}, ensure_ascii=False))
                    sys.exit(1)
                if not (d / "SKILL.md").exists():
                    print(json.dumps({"success": False, "message": f"协同 Skill 缺少 SKILL.md: {d}"}, ensure_ascii=False))
                    sys.exit(1)
                extra_dirs.append(d)

        zip_path = output_dir / f"{skill_name}.zip"
        included_names = {skill_dir.name}
        with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zf:
            for src in [skill_dir, *extra_dirs]:
                if src.name in included_names and src is not skill_dir:
                    continue
                included_names.add(src.name)
                for file_path in src.rglob('*'):
                    if file_path.is_file():
                        arcname = Path(src.name) / file_path.relative_to(src)
                        zf.write(file_path, arcname)

    # 上传
    cfg = load_config(args.config)
    base_url = cfg.get("base_url", "").rstrip("/")
    auth_file = _resolve_auth_file(args)

    try:
        with open(zip_path, "rb") as f:
            files = {"file": f}
            data_form = {"path": "skills/"}
            resp = requests.post(
                f"{base_url}/eval/api/v1/skill/eval-resource/file",
                headers=_bearer_headers(auth_file),
                files=files,
                data=data_form,
                timeout=60,
                verify=False,
            )
            resp.raise_for_status()
            data = resp.json()
    except Exception as e:
        _print_error_and_exit(e)

    if data.get("code") != 0:
        print(json.dumps({"success": False, "code": data.get("code"), "message": data.get("message")}, ensure_ascii=False))
        sys.exit(1)

    file_data = data.get("data", {})
    if not file_data or not file_data.get("downloadUrl"):
        print(json.dumps({"success": False, "message": "上传失败: 未返回下载地址"}, ensure_ascii=False))
        sys.exit(1)

    result = {
        "success": True,
        "skill_name": skill_name,
        "zip_path": str(zip_path),
        "url": file_data["downloadUrl"]
    }
    print(json.dumps(result, ensure_ascii=False))


# ============================================================================
# 会话管理（阶段 1）
# ============================================================================

def cmd_session(args):
    """创建或查找评测会话目录"""
    eval_dir = Path(args.work_dir) / ".eval"
    eval_dir.mkdir(parents=True, exist_ok=True)

    if args.action == "create":
        timestamp = time.strftime("%Y%m%d_%H%M%S")
        skill_name = (args.skill_name or "").strip()
        session_id = f"{timestamp}_{skill_name}" if skill_name else timestamp
        session_dir = eval_dir / session_id
        session_dir.mkdir(parents=True, exist_ok=True)

        _update_task(args.work_dir, session_id,
                     skill_name=skill_name,
                     status="configuring",
                     submitted_at=time.strftime("%Y-%m-%d %H:%M:%S"),
                     task_id="",
                     models=[],
                     session_dir=str(session_dir))

        result = {"session_id": session_id, "session_dir": str(session_dir)}
        print(json.dumps(result, ensure_ascii=False))

    elif args.action == "list":
        sessions = [d.name for d in eval_dir.iterdir() if d.is_dir() and not d.name.startswith(".")]
        result = {"sessions": sessions}
        print(json.dumps(result, ensure_ascii=False))


# ============================================================================
# 自定义模型管理（阶段 2）
# ============================================================================

def cmd_custom_models(args):
    """读写 custom-models.json"""
    custom_models_file = Path(args.work_dir) / ".eval" / "custom-models.json"

    if args.action == "read":
        if custom_models_file.exists():
            with open(custom_models_file, encoding="utf-8") as f:
                data = json.load(f)
        else:
            data = []
        if args.usage:
            data = [m for m in data if m.get("usage") == args.usage]
        print(json.dumps(data, ensure_ascii=False))

    elif args.action == "add":
        models = []
        if custom_models_file.exists():
            with open(custom_models_file, encoding="utf-8") as f:
                models = json.load(f)

        new_model = {
            "model": args.model_id,
            "api_key": args.api_key,
            "api_url": args.api_url,
            "usage": args.usage,
        }
        existing = next((i for i, m in enumerate(models)
                         if m.get("model") == args.model_id and m.get("usage") == args.usage), None)
        if existing is not None:
            models[existing] = new_model
            added = False
        else:
            models.append(new_model)
            added = True

        custom_models_file.parent.mkdir(parents=True, exist_ok=True)
        with open(custom_models_file, "w", encoding="utf-8") as f:
            json.dump(models, f, ensure_ascii=False, indent=2)

        print(json.dumps({"success": True, "added": added, "total": len(models)}, ensure_ascii=False))


# ============================================================================
# 用户角色管理（阶段 2）
# ============================================================================

def cmd_user_profile(args):
    """读写 user-profile.json"""
    profile_file = Path(args.work_dir) / ".eval" / "user-profile.json"

    if args.action == "read":
        if profile_file.exists():
            with open(profile_file, encoding="utf-8") as f:
                data = json.load(f)
            print(json.dumps(data, ensure_ascii=False))
        else:
            print(json.dumps({"role": None}, ensure_ascii=False))

    elif args.action == "write":
        profile_data = {"role": args.role}
        profile_file.parent.mkdir(parents=True, exist_ok=True)
        with open(profile_file, "w", encoding="utf-8") as f:
            json.dump(profile_data, f, ensure_ascii=False, indent=2)

        print(json.dumps({"success": True}, ensure_ascii=False))


# ============================================================================
# 构建运行框架配置文件（阶段 2）
# ============================================================================

def cmd_build_runtimes(args):
    """
    构建运行框架配置（eval-runtimes.json）。

    接收运行框架类型列表，生成对应的配置文件。
    """
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    # 解析运行框架类型
    runtime_types = [r.strip() for r in args.runtimes.split(",") if r.strip()]
    if not runtime_types:
        runtime_types = ["claude-code"]  # 默认值

    runtimes_list = [{"type": rt} for rt in runtime_types]
    runtimes_path = output_dir / "eval-runtimes.json"
    runtimes_path.write_text(json.dumps(runtimes_list, ensure_ascii=False, indent=2), encoding="utf-8")

    print(json.dumps({
        "success": True,
        "runtimes": str(runtimes_path),
        "runtime_count": len(runtimes_list),
    }, ensure_ascii=False))


# ============================================================================
# 构建模型配置文件（阶段 2）
# ============================================================================

def cmd_build_models(args):
    """
    构建评委配置（eval-judge.json）和待评测模型配置（eval-models.json）。

    接收完整模型对象（JSON），按来源生成对应的提交体：
    - `limited_free` 云端推荐模型 → `{source, recommend_model_id}`
    - `custom` 自定义模型 → `{type, api_key, api_url, model, concurrency}`
    """
    def _build_entry(entry: dict) -> dict:
        source = entry.get("source", "custom")
        if source == "limited_free":
            return {
                "source": "limited_free",
                "recommend_model_id": entry.get("recommend_model_id", ""),
            }
        return {
            "type": "api-anthropic",
            "api_key": entry.get("api_key", ""),
            "api_url": entry.get("api_url", ""),
            "model": entry.get("model", ""),
            "concurrency": 1,
        }

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    try:
        judge_obj = json.loads(args.judge_json)
    except Exception as e:
        print(json.dumps({"success": False, "message": f"--judge-json 解析失败: {e}"}, ensure_ascii=False))
        sys.exit(1)

    try:
        models_obj = json.loads(args.models_json)
        if not isinstance(models_obj, list):
            models_obj = [models_obj]
    except Exception as e:
        print(json.dumps({"success": False, "message": f"--models-json 解析失败: {e}"}, ensure_ascii=False))
        sys.exit(1)

    judge_entry = _build_entry(judge_obj)
    judge_path = output_dir / "eval-judge.json"
    judge_path.write_text(json.dumps(judge_entry, ensure_ascii=False, indent=2), encoding="utf-8")

    models_list = [_build_entry(m) for m in models_obj]
    models_path = output_dir / "eval-models.json"
    models_path.write_text(json.dumps(models_list, ensure_ascii=False, indent=2), encoding="utf-8")

    work_dir = getattr(args, "work_dir", "") or ""
    session_id = getattr(args, "session_id", "") or ""
    if not session_id and work_dir:
        try:
            rel = output_dir.resolve().relative_to((Path(work_dir) / ".eval").resolve())
            session_id = rel.parts[0]
        except Exception:
            pass
    if work_dir and session_id:
        model_names = []
        for m in models_obj:
            if not isinstance(m, dict):
                continue
            name = m.get("display_name") or m.get("model") or m.get("recommend_model_id") or ""
            if name:
                model_names.append(name)
        _update_task(work_dir, session_id, models=model_names)

    print(json.dumps({
        "success": True,
        "judge": str(judge_path),
        "models": str(models_path),
        "model_count": len(models_list),
    }, ensure_ascii=False))


# ============================================================================
# 断点续做（阶段 1）
# ============================================================================

def cmd_resume(args):
    """查找未完成的评测会话"""
    eval_dir = Path(args.work_dir) / ".eval"
    if not eval_dir.exists():
        print(json.dumps({"sessions": []}, ensure_ascii=False))
        return

    incomplete_sessions = []
    for session_dir in eval_dir.iterdir():
        if not session_dir.is_dir() or session_dir.name.startswith("."):
            continue

        task_file = session_dir / "eval-task.json"
        result_file = session_dir / "eval-result.json"

        # 有 task 但没有 result，说明未完成
        if task_file.exists() and not result_file.exists():
            with open(task_file, encoding="utf-8") as f:
                task_data = json.load(f)
            incomplete_sessions.append({
                "session_id": session_dir.name,
                "session_dir": str(session_dir),
                "task_id": task_data.get("task_id")
            })

    print(json.dumps({"sessions": incomplete_sessions}, ensure_ascii=False))


# ============================================================================
# 历史评测任务列表
# ============================================================================

SESSION_ID_RE = re.compile(r"^\d{8}_\d{6}(_[A-Za-z0-9_-]+)?$")


def _load_json(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _tasks_file(work_dir: str) -> Path:
    return Path(work_dir) / ".eval" / "tasks.json"


def _update_task(work_dir: str, session_id: str, **fields):
    """在 tasks.json 中更新或插入指定 session_id 的记录。"""
    if not work_dir:
        return
    tf = _tasks_file(work_dir)
    tasks = []
    if tf.exists():
        try:
            tasks = json.loads(tf.read_text(encoding="utf-8"))
            if not isinstance(tasks, list):
                tasks = []
        except Exception:
            tasks = []

    for t in tasks:
        if t.get("session_id") == session_id:
            t.update(fields)
            break
    else:
        entry = {"session_id": session_id}
        entry.update(fields)
        tasks.insert(0, entry)

    tf.parent.mkdir(parents=True, exist_ok=True)
    tf.write_text(json.dumps(tasks, ensure_ascii=False, indent=2), encoding="utf-8")


def _session_models(session_dir: Path) -> list:
    """从 eval-models.json 提取模型标识，便于展示"""
    data = _load_json(session_dir / "eval-models.json")
    if not isinstance(data, list):
        return []
    names = []
    for m in data:
        if not isinstance(m, dict):
            continue
        name = m.get("model") or m.get("recommend_model_id") or ""
        if name:
            names.append(name)
    return names


def _session_status(session_dir: Path) -> tuple:
    """返回 (status, task_id, progress)。状态取值：
    - Succeeded / Failed / Cancelled：来自 eval-result.json
    - Running：有 eval-task.json 无 eval-result.json
    - Pending：连 eval-task.json 也没有（仅创建了会话目录）
    """
    task_file = session_dir / "eval-task.json"
    result_file = session_dir / "eval-result.json"

    task_id = ""
    task_data = _load_json(task_file) if task_file.exists() else None
    if isinstance(task_data, dict):
        task_id = task_data.get("task_id", "")

    if result_file.exists():
        result_data = _load_json(result_file)
        if isinstance(result_data, dict):
            status = result_data.get("status") or "Succeeded"
            progress = result_data.get("progress", "")
        else:
            status = "Succeeded"
            progress = ""
        return status, task_id, progress

    if task_file.exists():
        return "Running", task_id, ""

    return "Pending", task_id, ""


def cmd_recent_tasks(args):
    """列出最近的评测会话（按 session_id 倒序）。

    优先读取 tasks.json 状态文件；若不存在则回退到扫描会话目录。
    """
    eval_dir = Path(args.work_dir) / ".eval"
    tf = _tasks_file(args.work_dir)

    if tf.exists():
        try:
            tasks = json.loads(tf.read_text(encoding="utf-8"))
            if isinstance(tasks, list):
                tasks.sort(key=lambda s: s.get("session_id", ""), reverse=True)
                if args.limit > 0:
                    tasks = tasks[: args.limit]
                print(json.dumps({"tasks": tasks}, ensure_ascii=False))
                return
        except Exception:
            pass

    # 回退：扫描文件系统
    if not eval_dir.exists():
        print(json.dumps({"tasks": []}, ensure_ascii=False))
        return

    sessions = []
    for session_dir in eval_dir.iterdir():
        if not session_dir.is_dir():
            continue
        if not SESSION_ID_RE.match(session_dir.name):
            continue

        status, task_id, progress = _session_status(session_dir)
        submitted_at = ""
        skill_name = ""
        dir_name = session_dir.name
        ts_part = dir_name[:15]  # YYYYMMDD_HHMMSS
        if len(dir_name) > 16:
            skill_name = dir_name[16:]
        try:
            submitted_at = time.strftime(
                "%Y-%m-%d %H:%M:%S",
                time.strptime(ts_part, "%Y%m%d_%H%M%S"),
            )
        except ValueError:
            pass

        sessions.append({
            "session_id": session_dir.name,
            "session_dir": str(session_dir),
            "submitted_at": submitted_at,
            "status": status,
            "task_id": task_id,
            "progress": progress,
            "skill_name": skill_name,
            "models": _session_models(session_dir),
        })

    sessions.sort(key=lambda s: s["session_id"], reverse=True)
    if args.limit > 0:
        sessions = sessions[: args.limit]

    print(json.dumps({"tasks": sessions}, ensure_ascii=False))


# ============================================================================
# 搜索 / 下载 Skill（阶段 2 任务 1）
# ============================================================================

CLOUD_SKILL_URL = "https://wry-manatee-359.convex.site/api/v1/download?slug={slug}"

LOCAL_SEARCH_MAX_DEPTH = 4
LOCAL_SEARCH_SKIP_DIRS = {
    ".git", ".hg", ".svn", ".idea", ".vscode", ".eval",
    "node_modules", "__pycache__", ".venv", "venv", "env",
    "dist", "build", "target", "out", ".next", ".cache",
    "AppData", "OneDrive", "Library", ".npm", ".gradle", ".m2",
}


def _search_local_skill(name: str, work_dir: Path) -> list:
    """在 work_dir 和 ~/.claude/skills 下查找 SKILL.md 同名 Skill 目录。

    手动遍历 + 深度剪枝，避免 rglob 把整个家目录扫穿。
    """
    candidates = []
    seen_path = set()

    raw_roots = [work_dir, Path.home() / ".claude" / "skills"]
    resolved_roots = []
    seen_root = set()
    for root in raw_roots:
        if not root.exists():
            continue
        try:
            rkey = str(root.resolve())
        except OSError:
            continue
        if rkey in seen_root:
            continue
        seen_root.add(rkey)
        resolved_roots.append(root)

    def walk(current: Path, depth: int):
        if depth > LOCAL_SEARCH_MAX_DEPTH:
            return
        try:
            entries = list(current.iterdir())
        except (PermissionError, OSError):
            return

        for entry in entries:
            try:
                if entry.is_file():
                    if entry.name == "SKILL.md" and current.name == name:
                        resolved = str(current.resolve())
                        if resolved not in seen_path:
                            seen_path.add(resolved)
                            candidates.append({"source": "local", "name": name, "path": resolved})
                    continue
                if not entry.is_dir():
                    continue
            except OSError:
                continue

            ename = entry.name
            if ename.startswith(".") and ename not in {".claude"}:
                if ename not in LOCAL_SEARCH_SKIP_DIRS:
                    continue
            if ename in LOCAL_SEARCH_SKIP_DIRS:
                continue
            walk(entry, depth + 1)

    for root in resolved_roots:
        walk(root, 0)

    return candidates


def _probe_cloud_skill(name: str) -> dict:
    """探测云端是否存在该 Skill。HEAD 命中 200 + zip 视为存在。"""
    url = CLOUD_SKILL_URL.format(slug=name)
    try:
        resp = requests.head(url, allow_redirects=True, timeout=15)
    except Exception as e:
        return {"available": False, "error": str(e)}
    if resp.status_code != 200:
        return {"available": False, "status": resp.status_code}
    content_type = resp.headers.get("content-type", "")
    if "zip" not in content_type.lower():
        return {"available": False, "status": resp.status_code, "content_type": content_type}
    return {
        "available": True,
        "url": url,
        "size": int(resp.headers.get("content-length", "0") or "0"),
    }


def cmd_search_skill(args):
    """按名称搜索 Skill：本地 + 云端，汇总返回。"""
    work_dir = Path(args.work_dir)
    local = _search_local_skill(args.name, work_dir)

    results = list(local)
    cloud = _probe_cloud_skill(args.name)
    if cloud.get("available"):
        results.append({
            "source": "cloud",
            "name": args.name,
            "url": cloud["url"],
            "size": cloud.get("size", 0),
        })

    print(json.dumps({
        "name": args.name,
        "results": results,
        "local_count": len(local),
        "cloud_available": cloud.get("available", False),
    }, ensure_ascii=False))


def cmd_download_skill(args):
    """从云端按 slug 下载 skill zip 到 output_dir。"""
    url = CLOUD_SKILL_URL.format(slug=args.slug)
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    zip_path = output_dir / f"{args.slug}.zip"

    try:
        resp = requests.get(url, stream=True, timeout=60)
    except Exception as e:
        print(json.dumps({"success": False, "message": f"下载失败: {e}"}, ensure_ascii=False))
        sys.exit(1)

    if resp.status_code != 200:
        body = resp.text[:200] if resp.text else ""
        print(json.dumps({"success": False, "status": resp.status_code,
                          "message": f"云端无此 Skill（slug={args.slug}）: {body}"}, ensure_ascii=False))
        sys.exit(1)

    with open(zip_path, "wb") as f:
        for chunk in resp.iter_content(8192):
            if chunk:
                f.write(chunk)

    print(json.dumps({"success": True, "slug": args.slug, "zip_path": str(zip_path)}, ensure_ascii=False))


# ============================================================================
# 上传 skill zip 包
# ============================================================================

def cmd_upload(args):
    cfg = load_config(args.config)
    base_url = cfg.get("base_url", "").rstrip("/")
    auth_file = _resolve_auth_file(args)

    try:
        with open(args.file, "rb") as f:
            files = {"file": f}
            data_form = {"path": "skills/"}
            resp = requests.post(
                f"{base_url}/eval/api/v1/skill/eval-resource/file",
                headers=_bearer_headers(auth_file),
                files=files,
                data=data_form,
                timeout=60,
                verify=False,
            )
            resp.raise_for_status()
            data = resp.json()
    except Exception as e:
        _print_error_and_exit(e)

    if data.get("code") != 0:
        print(json.dumps({"success": False, "code": data.get("code"), "message": data.get("message")}, ensure_ascii=False))
        sys.exit(1)

    file_data = data.get("data", {})
    if not file_data or not file_data.get("downloadUrl"):
        print(json.dumps({"success": False, "message": "上传失败: 未返回下载地址"}, ensure_ascii=False))
        sys.exit(1)

    output = {"url": file_data["downloadUrl"]}
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(output, ensure_ascii=False))


# ============================================================================
# 上传单个评测资源文件（filelist 中的资源文件）
# ============================================================================

def cmd_upload_resource(args):
    """上传评测资源文件，返回 downloadUrl"""
    cfg = load_config(args.config)
    base_url = cfg.get("base_url", "").rstrip("/")
    auth_file = _resolve_auth_file(args)

    file_path = Path(args.file)
    if not file_path.exists():
        print(json.dumps({"success": False, "message": f"文件不存在: {args.file}"}, ensure_ascii=False))
        sys.exit(1)

    remote_path = args.path if args.path else ""

    try:
        with open(file_path, "rb") as f:
            files = {"file": (file_path.name, f)}
            data_form = {}
            if remote_path:
                data_form["path"] = remote_path
            resp = requests.post(
                f"{base_url}/eval/api/v1/skill/eval-resource/file",
                headers=_bearer_headers(auth_file),
                files=files,
                data=data_form,
                timeout=120,
                verify=False,
            )
            resp.raise_for_status()
            data = resp.json()
    except Exception as e:
        _print_error_and_exit(e)

    if data.get("code") != 0:
        print(json.dumps({"success": False, "code": data.get("code"), "message": data.get("message")}, ensure_ascii=False))
        sys.exit(1)

    file_data = data.get("data", {})
    if not file_data or not file_data.get("downloadUrl"):
        print(json.dumps({"success": False, "message": "上传失败: 未返回下载地址"}, ensure_ascii=False))
        sys.exit(1)

    output = {
        "success": True,
        "local_path": str(file_path.resolve()),
        "remote_path": file_data.get("path", ""),
        "download_url": file_data["downloadUrl"],
    }
    print(json.dumps(output, ensure_ascii=False))


# ============================================================================
# 上传评测集（从 JSON 文件）
# ============================================================================

def cmd_upload_dataset(args):
    """将评测集 JSON 文件中的条目批量上传到平台"""
    cfg = load_config(args.config)
    auth_file = _resolve_auth_file(args)

    with open(args.dataset, encoding="utf-8") as f:
        payload = json.load(f)

    if args.dataset_id:
        payload["dataset_id"] = args.dataset_id

    try:
        client = _make_client(cfg, auth_file)
        data = client.post("/eval/api/v1/skill/dataset", json=payload, timeout=60) or {}
    except Exception as e:
        _print_error_and_exit(e)

    result = {
        "success": True,
        "dataset_id": data["dataset_id"],
        "received": data["received"],
    }

    if args.output:
        output_path = Path(args.output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")

    print(json.dumps(result, ensure_ascii=False))


# ============================================================================
# 提交数据合成任务
# ============================================================================

def cmd_datamaker(args):
    """提交数据合成任务，根据 skill 自动生成评测集"""
    cfg = load_config(args.config)
    auth_file = _resolve_auth_file(args)

    skill_names = [n.strip() for n in args.skill_names.split(",") if n.strip()]
    skill_urls = [u.strip() for u in args.skill_urls.split(",") if u.strip()]

    if not skill_names:
        print(json.dumps({"success": False, "message": "--skill-names 不能为空"}, ensure_ascii=False))
        sys.exit(1)

    if len(skill_names) != len(skill_urls):
        print(json.dumps({
            "success": False,
            "message": f"--skill-names 数量({len(skill_names)})与 --skill-urls 数量({len(skill_urls)})不一致",
        }, ensure_ascii=False))
        sys.exit(1)

    payload = {
        "skills": [{"name": n, "url": u} for n, u in zip(skill_names, skill_urls)],
    }
    if args.dataset_id:
        payload["dataset_id"] = args.dataset_id

    try:
        client = _make_client(cfg, auth_file)
        data = client.post("/eval/api/v1/skill/datamaker", json=payload) or {}
    except Exception as e:
        _print_error_and_exit(e)

    result = {"datamaker_id": data["id"]}

    if args.output:
        output_path = Path(args.output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")

    print(json.dumps(result, ensure_ascii=False))


# ============================================================================
# 查询数据合成任务状态
# ============================================================================

def cmd_datamaker_status(args):
    """查询数据合成任务状态，可轮询直到完成"""
    cfg = load_config(args.config)
    auth_file = _resolve_auth_file(args)

    try:
        client = _make_client(cfg, auth_file)
    except Exception as e:
        _print_error_and_exit(e)

    start = time.time()
    while True:
        elapsed = time.time() - start
        if elapsed > args.timeout:
            print(json.dumps({"id": args.id, "status": "Timeout", "error": f"轮询超时（{args.timeout}秒）"}, ensure_ascii=False))
            sys.exit(1)

        try:
            task = client.get(f"/eval/api/v1/skill/datamaker/{args.id}") or {}
        except Exception as e:
            _print_error_and_exit(e)

        status = task.get("status")
        progress = task.get("progress", "0")

        if status in TERMINAL_STATES:
            result = {"id": args.id, "status": status, "progress": progress}
            if task.get("artifacts"):
                result["artifacts"] = task["artifacts"]
                for artifact in task["artifacts"]:
                    if artifact.get("type") == "dataset":
                        result["dataset_id"] = artifact.get("dataset_id")
                        break

            if args.output:
                output_path = Path(args.output)
                output_path.parent.mkdir(parents=True, exist_ok=True)
                output_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")

            print(json.dumps(result, ensure_ascii=False))
            return

        print(json.dumps({"id": args.id, "status": status, "progress": progress,
                          "elapsed": int(elapsed), "message": f"数据合成中，{args.interval}秒后再次查询..."},
                         ensure_ascii=False), flush=True)

        if not args.poll:
            break

        time.sleep(args.interval)


# ============================================================================
# 提交评测任务（标准模式，需指定 dataset_id）
# ============================================================================

def cmd_submit(args):
    cfg = load_config(args.config)
    auth_file = _resolve_auth_file(args)

    # 读取 eval-models.json（列表格式）
    models_data = load_models(args.models)
    if isinstance(models_data, list):
        models = models_data
    else:
        models = models_data.get("models", [])

    # 读取 eval-judge.json（可选，优先于 models 文件中内嵌的 judge）
    judge = None
    if args.judge and Path(args.judge).exists():
        with open(args.judge, encoding="utf-8") as f:
            judge = json.load(f)
    elif isinstance(models_data, dict):
        judge = models_data.get("judge")

    # 构建 skills[]：name 必填，url 与 name 一一对齐
    skill_names = [n.strip() for n in args.skill_names.split(",") if n.strip()]
    skill_urls = [u.strip() for u in args.skill_urls.split(",") if u.strip()] if args.skill_urls else []
    if not skill_names:
        print(json.dumps({"success": False, "message": "--skill-names 不能为空"}, ensure_ascii=False))
        sys.exit(1)
    if skill_urls and len(skill_urls) != len(skill_names):
        print(json.dumps({
            "success": False,
            "message": f"--skill-names 数量({len(skill_names)})与 --skill-urls 数量({len(skill_urls)})不一致",
        }, ensure_ascii=False))
        sys.exit(1)
    skills_payload = []
    for i, name in enumerate(skill_names):
        item = {"name": name}
        if i < len(skill_urls):
            item["url"] = skill_urls[i]
        skills_payload.append(item)

    # 构建 runtimes：从 --runtime 参数获取，支持逗号分隔的多个框架
    runtime_str = args.runtime or "claude-code"
    runtime_types = [r.strip() for r in runtime_str.split(",") if r.strip()]
    runtimes_payload = [{"type": rt} for rt in runtime_types]

    payload = {
        "dataset_id": args.dataset_id,
        "models": models,
        "runtimes": runtimes_payload,
        "skills": skills_payload,
    }
    if judge:
        payload["judge"] = judge

    try:
        client = _make_client(cfg, auth_file)
        task = client.post("/eval/api/v1/skill/eval", json=payload) or {}
    except Exception as e:
        _print_error_and_exit(e)

    result = {"task_id": task["id"], "status": "Pending", "runtimes": runtimes_payload}

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")

    # 从 output 路径推断 session_id（output 通常是 {work-dir}/.eval/{session-id}/eval-task.json）
    work_dir = getattr(args, "work_dir", "") or ""
    session_id = getattr(args, "session_id", "") or ""
    if not session_id and work_dir:
        try:
            rel = output_path.relative_to(Path(work_dir) / ".eval")
            session_id = rel.parts[0]
        except Exception:
            pass
    if session_id and work_dir:
        models_data = _load_json(Path(args.models)) if args.models else None
        model_names = []
        if isinstance(models_data, list):
            for m in models_data:
                name = m.get("model") or m.get("recommend_model_id") or ""
                if name:
                    model_names.append(name)
        _update_task(work_dir, session_id,
                     status="running",
                     task_id=task["id"],
                     models=model_names)

    print(json.dumps(result, ensure_ascii=False))


# ============================================================================
# 查询任务状态
# ============================================================================

def query_status(client: ApiClient, task_id: str) -> dict:
    return client.get(f"/eval/api/v1/skill/tasks/{task_id}") or {}


def cmd_status(args):
    cfg = load_config(args.config)
    auth_file = _resolve_auth_file(args)

    try:
        client = _make_client(cfg, auth_file)
    except Exception as e:
        _print_error_and_exit(e)

    start = time.time()
    while True:
        elapsed = time.time() - start
        if elapsed > args.timeout:
            print(json.dumps({"task_id": args.task_id, "status": "Timeout", "error": f"轮询超时（{args.timeout}秒）"}, ensure_ascii=False))
            sys.exit(1)

        try:
            task = query_status(client, args.task_id)
        except Exception as e:
            print(json.dumps({"success": False, "message": str(e)}, ensure_ascii=False))
            sys.exit(1)

        status = task.get("status")
        progress = task.get("progress", "0")

        if status in TERMINAL_STATES:
            result = {"task_id": args.task_id, "status": status, "progress": progress}
            if task.get("artifacts"):
                result["artifacts"] = task["artifacts"]

            output_path = Path(args.output)
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")

            # 更新 tasks.json 状态
            work_dir = getattr(args, "work_dir", "") or ""
            session_id = getattr(args, "session_id", "") or ""
            if not session_id and work_dir:
                try:
                    rel = output_path.relative_to(Path(work_dir) / ".eval")
                    session_id = rel.parts[0]
                except Exception:
                    pass
            if session_id and work_dir:
                _update_task(work_dir, session_id,
                             status=status.lower(),
                             task_id=args.task_id,
                             progress=progress)

            print(json.dumps(result, ensure_ascii=False))
            return

        # 轮询中间态：实时更新 tasks.json 中的 progress
        work_dir = getattr(args, "work_dir", "") or ""
        session_id = getattr(args, "session_id", "") or ""
        if not session_id and work_dir:
            try:
                rel = Path(args.output).relative_to(Path(work_dir) / ".eval")
                session_id = rel.parts[0]
            except Exception:
                pass
        if session_id and work_dir:
            _update_task(work_dir, session_id,
                         status=status.lower(),
                         task_id=args.task_id,
                         progress=progress)

        print(json.dumps({"task_id": args.task_id, "status": status, "progress": progress,
                          "elapsed": int(elapsed), "message": f"任务执行中，{args.interval}秒后再次查询..."}, ensure_ascii=False), flush=True)

        if not args.poll:
            break

        time.sleep(args.interval)


# ============================================================================
# 打印评测结果摘要
# ============================================================================

def _fmt_rate(rate):
    return f"{rate * 100:.1f}%" if rate is not None else "N/A"


def cmd_summary(args):
    result_path = Path(args.result)
    if not result_path.exists():
        print(f"错误: 结果文件不存在: {result_path}", file=sys.stderr)
        sys.exit(1)

    result = json.loads(result_path.read_text(encoding="utf-8"))

    # 优先从参数获取 platform_url，其次从 artifacts 提取
    platform_url = args.platform_url or ""
    report_file_url = ""
    for artifact in result.get("artifacts", []):
        t = artifact.get("type", "")
        if t == "report_render_url" and not platform_url:
            platform_url = artifact.get("url", "")
        elif t == "report_file" and not report_file_url:
            report_file_url = artifact.get("url", "")

    # 下载报告 JSON
    report = None
    if report_file_url:
        try:
            if report_file_url.startswith("file://"):
                import urllib.request
                with urllib.request.urlopen(report_file_url) as f:
                    report = json.loads(f.read().decode("utf-8"))
            else:
                resp = requests.get(report_file_url, timeout=60)
                resp.raise_for_status()
                report = resp.json()
        except Exception as e:
            print(f"警告: 下载报告文件失败: {e}", file=sys.stderr)

    if report is None:
        # 无法下载报告，仅展示链接
        print("评测完成！")
        if platform_url:
            print(f"\n在线报告：{platform_url}")
        return

    # 解析 views
    views = {v["view_id"]: v for v in report.get("views", [])}

    print("=" * 50)
    print("评测结果摘要")
    print("=" * 50)

    # 运行框架信息
    runtimes = result.get("runtimes", [])
    if runtimes:
        runtime_names = [r.get("type", "unknown") for r in runtimes]
        print(f"\n运行框架：{', '.join(runtime_names)}")

    # 总体统计
    overall = views.get("overall")
    if overall and overall.get("records"):
        r = overall["records"][0]
        total = r.get("case_count", 0)
        passed = r.get("passed_count", 0)
        failed = r.get("failed_count", 0)
        error = r.get("error_count", 0)
        evaluated = r.get("evaluated_case_count", 0)
        rate = r.get("pass_rate")
        avg_dur = r.get("avg_duration_seconds")
        avg_in = r.get("avg_input_tokens")
        avg_out = r.get("avg_output_tokens")

        print(f"\n总体通过率：{_fmt_rate(rate)}  （{passed}/{evaluated} 通过，{failed} 失败，{error} 异常，共 {total} 条）")
        if avg_dur is not None and evaluated > 0:
            total_dur = avg_dur * evaluated
            if total_dur >= 60:
                print(f"执行总耗时：{total_dur / 60:.1f} 分钟")
            else:
                print(f"执行总耗时：{total_dur:.1f} 秒")
        if avg_in is not None:
            print(f"平均输入 Token：{int(avg_in):,}")
        if avg_out is not None:
            print(f"平均输出 Token：{int(avg_out):,}")

    # 分类统计
    by_cat = views.get("by_category")
    if by_cat and by_cat.get("records"):
        print("\n分类通过率：")
        max_cat_len = max(len(r.get("category") or "") for r in by_cat["records"])
        for r in by_cat["records"]:
            cat = (r.get("category") or "（未分类）").ljust(max_cat_len)
            passed = r.get("passed_count", 0)
            failed = r.get("failed_count", 0)
            error = r.get("error_count", 0)
            evaluated = r.get("evaluated_case_count", 0)
            rate = r.get("pass_rate")
            print(f"  {cat}  {_fmt_rate(rate).rjust(6)}  {passed}/{evaluated} 通过，{failed} 失败，{error} 异常")

    print()
    if platform_url:
        print(f"在线报告：{platform_url}")
        print("（可在线查看完整评测详情、用例明细和评判原因）")
    else:
        print("提示：如需查看完整报告，请访问评测平台在线报告页面。")


# ============================================================================
# 获取评测结果产物
# ============================================================================

def cmd_artifacts(args):
    cfg = load_config(args.config)
    auth_file = _resolve_auth_file(args)

    params = {}
    if args.type:
        params["type"] = args.type

    try:
        client = _make_client(cfg, auth_file)
        data = client.get(
            f"/eval/api/v1/skill/tasks/{args.task_id}/artifacts",
            params=params,
        )
    except Exception as e:
        _print_error_and_exit(e)

    print(json.dumps({"artifacts": data or []}, ensure_ascii=False))


# ============================================================================
# 列出评测集样例
# ============================================================================

def _truncate(s: str, max_len: int) -> str:
    s = s or ""
    return s if len(s) <= max_len else s[:max_len - 1] + "…"


def _print_table(items: list, total: int, offset: int):
    start = offset + 1
    end = offset + len(items)
    print(f"共 {total} 条样例，显示第 {start}-{end} 条：\n")
    col_widths = [4, 12, 62, 14, 42, 8]
    headers = ["#", "case_id", "question", "category", "keypoint", "filelist"]
    sep = "  ".join("-" * w for w in col_widths)
    header_row = "  ".join(h.ljust(w) for h, w in zip(headers, col_widths))
    print(header_row)
    print(sep)
    for i, item in enumerate(items, start=start):
        row = [
            str(i).rjust(col_widths[0]),
            _truncate(item.get("case_id", ""), col_widths[1]).ljust(col_widths[1]),
            _truncate(item.get("question", ""), col_widths[2]).ljust(col_widths[2]),
            _truncate(item.get("category", ""), col_widths[3]).ljust(col_widths[3]),
            _truncate(item.get("keypoint", ""), col_widths[4]).ljust(col_widths[4]),
            str(len(item.get("filelist") or [])).rjust(col_widths[5]),
        ]
        print("  ".join(row))


def cmd_list_dataset(args):
    cfg = load_config(args.config)
    auth_file = _resolve_auth_file(args)
    endpoint = f"/eval/api/v1/skill/dataset/{args.dataset_id}"

    try:
        client = _make_client(cfg, auth_file)

        if args.all:
            all_items, offset, total = [], 0, None
            d = {}
            while True:
                d = client.get(endpoint, params={"offset": offset, "limit": 500}) or {}
                total = d["total"]
                all_items.extend(d["items"])
                if len(all_items) >= total:
                    break
                offset += 500
            result = {"dataset_id": args.dataset_id, "name": d.get("name", ""), "total": total, "items": all_items}
        else:
            result = client.get(endpoint, params={"offset": args.offset, "limit": args.limit}) or {}
    except Exception as e:
        _print_error_and_exit(e)

    if args.output:
        output_path = Path(args.output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")

    if args.format == "json":
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        _print_table(result["items"], result["total"], 0 if args.all else args.offset)


# ============================================================================
# 编辑/覆盖更新评测集样例
# ============================================================================

def cmd_edit_dataset(args):
    cfg = load_config(args.config)
    auth_file = _resolve_auth_file(args)

    with open(args.items, encoding="utf-8") as f:
        raw = json.load(f)

    if isinstance(raw, list):
        items = raw
    elif isinstance(raw, dict) and "items" in raw:
        items = raw["items"]
    else:
        print(json.dumps({"success": False, "message": "--items 文件应为 JSON 数组或含 items 字段的对象"}, ensure_ascii=False))
        sys.exit(1)

    # 分批提交（每批最多 500 条）
    batch_size = 500
    total_received = 0
    last_dataset_id = args.dataset_id
    try:
        client = _make_client(cfg, auth_file)
        for i in range(0, len(items), batch_size):
            batch = items[i:i + batch_size]
            payload = {"dataset_id": args.dataset_id, "items": batch}
            data = client.post("/eval/api/v1/skill/dataset", json=payload, timeout=60) or {}
            total_received += data["received"]
            last_dataset_id = data["dataset_id"]
    except Exception as e:
        _print_error_and_exit(e)

    result = {"success": True, "dataset_id": last_dataset_id, "received": total_received}

    if args.output:
        output_path = Path(args.output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")

    print(json.dumps(result, ensure_ascii=False))


# ============================================================================
# 删除评测集 Case
# ============================================================================

def cmd_delete_cases(args):
    cfg = load_config(args.config)
    auth_file = _resolve_auth_file(args)

    case_ids = list(args.case_ids) if args.case_ids else []
    if args.case_ids_file:
        with open(args.case_ids_file, encoding="utf-8") as f:
            case_ids.extend(json.load(f))

    if not case_ids:
        print(json.dumps({"success": False, "message": "未提供任何 case_id"}, ensure_ascii=False))
        sys.exit(1)

    try:
        client = _make_client(cfg, auth_file)
        data = client.delete(
            f"/eval/api/v1/skill/dataset/{args.dataset_id}/cases",
            json={"case_ids": case_ids},
        ) or {}
    except Exception as e:
        _print_error_and_exit(e)

    result = {"success": True, "deleted": data["deleted"]}

    if args.output:
        output_path = Path(args.output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")

    print(json.dumps(result, ensure_ascii=False))


# ============================================================================
# Excel 转评测集 JSON
# ============================================================================

def _upload_file(base_url: str, auth_file: str, local_path: str, remote_dir: str) -> str:
    """上传单个文件，返回 download_url"""
    file_path = Path(local_path)
    if not file_path.exists():
        raise FileNotFoundError(f"文件不存在: {local_path}")
    with open(file_path, "rb") as f:
        resp = requests.post(
            f"{base_url}/eval/api/v1/skill/eval-resource/file",
            headers=_bearer_headers(auth_file),
            files={"file": (file_path.name, f)},
            data={"path": remote_dir} if remote_dir else {},
            timeout=120,
            verify=False,
        )
    resp.raise_for_status()
    data = resp.json()
    if data.get("code") != 0:
        raise RuntimeError(f"上传失败: {data.get('message')}")
    url = data.get("data", {}).get("downloadUrl")
    if not url:
        raise RuntimeError("上传失败: 未返回下载地址")
    return url


def cmd_convert_excel(args):
    try:
        import pandas as pd
    except ImportError:
        print(json.dumps({"success": False, "message": "缺少依赖：pip install pandas openpyxl"}, ensure_ascii=False))
        sys.exit(1)

    df = pd.read_excel(args.file)

    # 验证 question
    if "question" not in df.columns or df["question"].isnull().any() or (df["question"].astype(str).str.strip() == "").any():
        missing = df.index[df["question"].isnull() | (df["question"].astype(str).str.strip() == "")].tolist()
        print(json.dumps({"success": False, "message": f"question 不能为空，问题行（0-indexed）：{missing}"}, ensure_ascii=False))
        sys.exit(1)

    # 自动生成 case_id
    if "case_id" not in df.columns:
        df["case_id"] = [f"case-{i+1:03d}" for i in range(len(df))]
    else:
        mask = df["case_id"].isnull() | (df["case_id"].astype(str).str.strip() == "")
        for i in df.index[mask].tolist():
            df.at[i, "case_id"] = f"case-{i+1:03d}"

    # 如果需要上传 filelist，加载配置
    upload_cfg = None
    upload_auth_file = None
    if args.config:
        upload_cfg = load_config(args.config)
        upload_auth_file = _resolve_auth_file(args)

    items = []
    for _, row in df.iterrows():
        item = {
            "case_id": str(row["case_id"]).strip(),
            "question": str(row["question"]).strip(),
            "category": str(row["category"]).strip() if "category" in df.columns and pd.notna(row.get("category")) else "",
            "keypoint": str(row["keypoint"]).strip() if "keypoint" in df.columns and pd.notna(row.get("keypoint")) else "",
            "filelist": [],
        }
        if "filelist" in df.columns and pd.notna(row.get("filelist")) and str(row["filelist"]).strip():
            local_paths = [p.strip() for p in str(row["filelist"]).split(",") if p.strip()]
            if upload_cfg:
                base_url = upload_cfg.get("base_url", "").rstrip("/")
                uploaded = []
                for lp in local_paths:
                    url = _upload_file(base_url, upload_auth_file, lp, "skills/docs/")
                    uploaded.append({"url": url, "relative_path": f"skills/docs/{Path(lp).name}"})
                    print(json.dumps({"uploading": lp, "url": url}, ensure_ascii=False), file=sys.stderr)
                item["filelist"] = uploaded
            else:
                item["filelist"] = local_paths
        items.append(item)

    result = {"items": items}
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")

    has_empty_keypoint = any(not item["keypoint"] for item in items)
    print(json.dumps({
        "success": True,
        "total": len(items),
        "output": str(output_path),
        "has_empty_keypoint": has_empty_keypoint,
    }, ensure_ascii=False))


# ============================================================================
# CLI 入口
# ============================================================================

def _add_auth_file_arg(p: argparse.ArgumentParser) -> None:
    """为调用平台 API 的子命令统一附加 --auth-file 参数。"""
    p.add_argument(
        "--auth-file",
        default=DEFAULT_AUTH_FILE,
        help=f"鉴权 Token 缓存路径（默认 {DEFAULT_AUTH_FILE}），将注入 Authorization: Bearer 头",
    )


def main():
    parser = argparse.ArgumentParser(description="云端 Skill 评测")
    sub = parser.add_subparsers(dest="command", required=True)

    # login
    p = sub.add_parser("login", help="检查或刷新鉴权 Token（Token 无效时触发 OAuth2 登录）")
    p.add_argument("--auth-file", default="./.eval/auth.json", help="鉴权文件路径")
    p.add_argument("--force", action="store_true", help="强制重新登录")
    p.add_argument("--mode", choices=["auto", "manual"], default=None,
                   help="登录模式：auto（自动回调）或 manual（手动 OOB），默认自动选择")
    p.add_argument("--port", type=int, default=None, help="回调模式端口（默认 51943）")
    p.set_defaults(func=cmd_login)

    # token（用授权码换取 Token）
    p = sub.add_parser("token", help="用授权码换取 Token 并保存")
    p.add_argument("--auth-file", default="./.eval/auth.json", help="鉴权文件路径")
    p.add_argument("--code", required=True, help="用户输入的授权码")
    p.add_argument("--state-token", required=True, help="login 返回的 state_token")
    p.set_defaults(func=cmd_token)

    # check-token
    p = sub.add_parser("check-token", help="仅检查 Token 有效性，不触发登录")
    p.add_argument("--auth-file", default="./.eval/auth.json", help="鉴权文件路径")
    p.set_defaults(func=cmd_check_token)

    # check-dataset
    p = sub.add_parser("check-dataset", help="检查评测集字段完整性")
    p.add_argument("--dataset", required=True, help="评测集 JSON 文件路径")
    p.set_defaults(func=cmd_check_dataset)

    # models
    p = sub.add_parser("models", help="获取评测平台推荐模型列表（限时免费）")
    p.add_argument("--config", required=True, help="服务配置文件（提供 base_url）")
    p.add_argument("--scene", default="skill", help="评测场景过滤：skill 或 code，默认 skill")
    p.add_argument("--usage", default="", help="模型用途过滤：judge 或 candidate（可选）")
    p.add_argument("--output", default="", help="结果输出文件（可选）")
    _add_auth_file_arg(p)
    p.set_defaults(func=cmd_models)

    # package
    p = sub.add_parser("package", help="打包并上传 Skill")
    p.add_argument("--config", required=True, help="服务配置文件")
    p.add_argument("--skill-dir", default="", help="Skill 目录路径（与 --skill-zip 互斥）")
    p.add_argument("--extra-skills", default="", help="协同 Skill 目录列表（逗号分隔），与 --skill-dir 合成一个 zip")
    p.add_argument("--skill-zip", default="", help="已打好的 Skill zip 包（与 --skill-dir 互斥）")
    p.add_argument("--output-dir", required=True, help="输出目录（存放 zip 包）")
    _add_auth_file_arg(p)
    p.set_defaults(func=cmd_package)

    # session
    p = sub.add_parser("session", help="会话管理")
    p.add_argument("--work-dir", default=".", help="工作目录")
    p.add_argument("--action", choices=["create", "list"], required=True, help="操作类型")
    p.add_argument("--skill-name", default="", help="Skill 名称（用于 create）")
    p.set_defaults(func=cmd_session)

    # custom-models
    p = sub.add_parser("custom-models", help="自定义模型管理")
    p.add_argument("--work-dir", default=".", help="工作目录")
    p.add_argument("--action", choices=["read", "add"], required=True, help="操作类型")
    p.add_argument("--model-id", default="", help="模型名称（用于 add）")
    p.add_argument("--api-key", default="", help="API Key（用于 add）")
    p.add_argument("--api-url", default="", help="API URL（用于 add）")
    p.add_argument("--usage", default="", help="模型用途：candidate 或 judge")
    p.set_defaults(func=cmd_custom_models)

    # user-profile
    p = sub.add_parser("user-profile", help="用户角色管理")
    p.add_argument("--work-dir", default=".", help="工作目录")
    p.add_argument("--action", choices=["read", "write"], required=True, help="操作类型")
    p.add_argument("--role", default="", help="用户角色（用于 write）")
    p.set_defaults(func=cmd_user_profile)

    # resume
    p = sub.add_parser("resume", help="查找未完成的评测会话")
    p.add_argument("--work-dir", default=".", help="工作目录")
    p.set_defaults(func=cmd_resume)

    # recent-tasks
    p = sub.add_parser("recent-tasks", help="列出最近的评测会话（含状态、模型、提交时间）")
    p.add_argument("--work-dir", default=".", help="工作目录")
    p.add_argument("--limit", type=int, default=5, help="返回条数上限（默认 5，<=0 表示全部）")
    p.set_defaults(func=cmd_recent_tasks)

    # search-skill
    p = sub.add_parser("search-skill", help="按名称搜索 Skill（本地 + 云端）")
    p.add_argument("--name", required=True, help="Skill 名称")
    p.add_argument("--work-dir", default=".", help="工作目录（本地搜索范围之一）")
    p.set_defaults(func=cmd_search_skill)

    # download-skill
    p = sub.add_parser("download-skill", help="按 slug 从云端下载 Skill zip")
    p.add_argument("--slug", required=True, help="云端 Skill slug（一般等于 Skill 名称）")
    p.add_argument("--output-dir", required=True, help="zip 输出目录")
    p.set_defaults(func=cmd_download_skill)

    # build-runtimes
    p = sub.add_parser("build-runtimes", help="构建运行框架配置")
    p.add_argument("--output-dir", required=True, help="输出目录（通常是 session 目录）")
    p.add_argument("--runtimes", default="claude-code", help="运行框架类型，多个以逗号分隔（默认 claude-code）")
    p.set_defaults(func=cmd_build_runtimes)

    # build-models
    p = sub.add_parser("build-models", help="构建评委配置和待评测模型配置")
    p.add_argument("--output-dir", required=True, help="输出目录（通常是 session 目录）")
    p.add_argument("--judge-json", required=True, help="评委模型对象（JSON 字符串）")
    p.add_argument("--models-json", required=True, help="待评测模型对象数组（JSON 字符串）")
    p.add_argument("--work-dir", default="", help="工作目录（用于更新 tasks.json，可选）")
    p.add_argument("--session-id", default="", help="会话 ID（缺省时按 output-dir 推断）")
    p.set_defaults(func=cmd_build_models)

    # upload
    p = sub.add_parser("upload", help="上传 skill zip 包")
    p.add_argument("--config", required=True, help="服务配置文件")
    p.add_argument("--file", required=True, help="skill zip 包路径")
    p.add_argument("--output", default="./.eval/upload-result.json", help="上传结果输出文件（内部使用）")
    _add_auth_file_arg(p)
    p.set_defaults(func=cmd_upload)

    # upload-resource
    p = sub.add_parser("upload-resource", help="上传单个评测资源文件（用于 filelist）")
    p.add_argument("--config", required=True, help="服务配置文件")
    p.add_argument("--file", required=True, help="本地文件绝对路径")
    p.add_argument("--path", default="", help="远端目标路径（可选）")
    _add_auth_file_arg(p)
    p.set_defaults(func=cmd_upload_resource)

    # upload-dataset
    p = sub.add_parser("upload-dataset", help="上传评测集（JSON 格式）")
    p.add_argument("--config", required=True, help="服务配置文件")
    p.add_argument("--dataset", required=True, help="评测集 JSON 文件路径")
    p.add_argument("--dataset-id", default="", help="评测集 ID（可选，不传时服务端自动生成）")
    p.add_argument("--output", default="", help="结果输出文件（可选）")
    _add_auth_file_arg(p)
    p.set_defaults(func=cmd_upload_dataset)

    # datamaker
    p = sub.add_parser("datamaker", help="提交数据合成任务")
    p.add_argument("--config", required=True, help="服务配置文件")
    p.add_argument("--skill-names", required=True, help="skill 名称，多个以逗号分隔（顺序与 --skill-urls 对齐）")
    p.add_argument("--skill-urls", required=True, help="skill zip 包 URL，多个以逗号分隔（顺序与 --skill-names 对齐）")
    p.add_argument("--dataset-id", default="", help="评测集 ID（可选）")
    p.add_argument("--output", default="", help="结果输出文件（可选）")
    _add_auth_file_arg(p)
    p.set_defaults(func=cmd_datamaker)

    # datamaker-status
    p = sub.add_parser("datamaker-status", help="查询数据合成任务状态")
    p.add_argument("--config", required=True, help="服务配置文件")
    p.add_argument("--id", required=True, help="数据合成任务 ID")
    p.add_argument("--output", default="", help="结果输出文件（可选）")
    p.add_argument("--poll", action="store_true", help="启用轮询模式")
    p.add_argument("--interval", type=int, default=30, help="轮询间隔（秒）")
    p.add_argument("--timeout", type=int, default=3600, help="轮询超时（秒）")
    _add_auth_file_arg(p)
    p.set_defaults(func=cmd_datamaker_status)

    # submit
    p = sub.add_parser("submit", help="提交评测任务")
    p.add_argument("--config", required=True, help="服务配置文件")
    p.add_argument("--skill-names", required=True, help="skill 名称，多个以逗号分隔（顺序与 --skill-urls 对齐）")
    p.add_argument("--skill-urls", default="", help="skill zip 包 URL，多个以逗号分隔（顺序与 --skill-names 对齐，可为空）")
    p.add_argument("--dataset-id", required=True, help="评测集 ID")
    p.add_argument("--models", required=True, help="模型配置 JSON 文件（eval-models.json）")
    p.add_argument("--judge", default="", help="评委配置 JSON 文件（eval-judge.json，可选）")
    p.add_argument("--runtime", default="claude-code", help="运行框架类型，多个以逗号分隔（默认 claude-code）")
    p.add_argument("--output", required=True, help="任务元信息输出文件（通常是 {session-dir}/eval-task.json）")
    p.add_argument("--work-dir", default="", help="工作目录（用于更新 tasks.json，可选）")
    _add_auth_file_arg(p)
    p.set_defaults(func=cmd_submit)

    # status
    p = sub.add_parser("status", help="查询任务状态")
    p.add_argument("--config", required=True, help="服务配置文件")
    p.add_argument("--task-id", required=True, help="任务 ID")
    p.add_argument("--output", required=True, help="结果输出文件（通常是 {session-dir}/eval-result.json）")
    p.add_argument("--poll", action="store_true", help="启用轮询模式")
    p.add_argument("--interval", type=int, default=30, help="轮询间隔（秒）")
    p.add_argument("--timeout", type=int, default=3600, help="轮询超时（秒）")
    p.add_argument("--work-dir", default="", help="工作目录（用于更新 tasks.json，可选）")
    _add_auth_file_arg(p)
    p.set_defaults(func=cmd_status)

    # artifacts
    p = sub.add_parser("artifacts", help="获取评测结果产物")
    p.add_argument("--config", required=True, help="服务配置文件")
    p.add_argument("--task-id", required=True, help="任务 ID")
    p.add_argument("--type", default="", help="产物类型过滤：report_file 或 report_render_url")
    _add_auth_file_arg(p)
    p.set_defaults(func=cmd_artifacts)

    # list-dataset
    p = sub.add_parser("list-dataset", help="列出评测集样例")
    p.add_argument("--config", required=True, help="服务配置文件")
    p.add_argument("--dataset-id", required=True, help="评测集 ID")
    p.add_argument("--offset", type=int, default=0, help="起始偏移量（默认 0）")
    p.add_argument("--limit", type=int, default=20, help="每页条数（默认 20，最大 500）")
    p.add_argument("--all", action="store_true", help="一次性拉取全部样例（分批请求）")
    p.add_argument("--output", default="", help="将完整结果保存为 JSON 文件（可选）")
    p.add_argument("--format", choices=["table", "json"], default="table", help="输出格式（默认 table）")
    _add_auth_file_arg(p)
    p.set_defaults(func=cmd_list_dataset)

    # edit-dataset
    p = sub.add_parser("edit-dataset", help="覆盖更新评测集样例（通过 case_id）")
    p.add_argument("--config", required=True, help="服务配置文件")
    p.add_argument("--dataset-id", required=True, help="评测集 ID")
    p.add_argument("--items", required=True, help="待更新的 items JSON 文件（数组格式）")
    p.add_argument("--output", default="", help="结果输出文件（可选）")
    _add_auth_file_arg(p)
    p.set_defaults(func=cmd_edit_dataset)

    # delete-cases
    p = sub.add_parser("delete-cases", help="删除指定评测集 case")
    p.add_argument("--config", required=True, help="服务配置文件")
    p.add_argument("--dataset-id", required=True, help="评测集 ID")
    p.add_argument("--case-ids", nargs="+", default=[], help="要删除的 case_id 列表（命令行传入）")
    p.add_argument("--case-ids-file", default="", help="要删除的 case_id 列表文件（JSON 数组）")
    p.add_argument("--output", default="", help="结果输出文件（可选）")
    _add_auth_file_arg(p)
    p.set_defaults(func=cmd_delete_cases)

    # summary
    p = sub.add_parser("summary", help="解析评测结果并打印通过率摘要")
    p.add_argument("--result", required=True, help="eval-result.json 路径（含 artifacts 字段）")
    p.add_argument("--platform_url", default="", help="在线报告链接（可选，优先于 artifacts 中的链接）")
    p.set_defaults(func=cmd_summary)

    # convert-excel
    p = sub.add_parser("convert-excel", help="将 Excel 评测集转换为 JSON 格式")
    p.add_argument("--file", required=True, help="Excel 文件路径（.xlsx）")
    p.add_argument("--output", required=True, help="输出 JSON 文件路径")
    p.add_argument("--config", default="", help="服务配置文件；提供后会自动上传 filelist 并替换为下载链接")
    _add_auth_file_arg(p)
    p.set_defaults(func=cmd_convert_excel)

    args = parser.parse_args()

    # 为所有调用平台 API 的子命令统一注入 --auth-file 默认值（若未声明）
    if not hasattr(args, "auth_file") or getattr(args, "auth_file", None) is None:
        args.auth_file = DEFAULT_AUTH_FILE

    try:
        args.func(args)
    except Exception as e:
        print(f"错误: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
