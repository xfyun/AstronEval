# CLAUDE.md

## 项目概述

astroneval 是一个 Claude Code 插件，用于对本地 Skill 进行自动化评测。插件通过对话式交互引导用户完成评测配置、数据准备和报告查看。

## 技术栈

- **插件框架**: Claude Code Plugin（`.claude-plugin/plugin.json`）
- **技能定义**: Markdown 文档（SKILL.md + 阶段文档）
- **后端脚本**: Python 3.8+（`scripts/` 目录）
- **鉴权平台**: 讯飞开放平台 OAuth（`base_url: https://maas.xfyun.cn`）
- **许可证**: Apache 2.0

## 项目结构

```
.claude-plugin/plugin.json       → 插件元数据（name, version, description）
skills/skill-evaluation/
  SKILL.md                       → 技能入口，定义触发条件和流程概览
  eval-init.md                   → 阶段1：鉴权 + 意图识别 + 场景确认
  eval-build.md                  → 阶段2：选择 Skill / 运行框架 / 驱动模型 / 评委模型
  eval-set.md                    → 阶段3：评测集上传或自动合成 + 预览确认
  eval-execute.md                → 阶段4：提交任务 + 轮询 + 报告展示
  processes/                     → 子流程（场景检测、Skill选择、模型选择、数据集准备/预览）
  references/                    → 规范文档（输出行为、进度展示、脚本定义、场景说明、中间产物）
  scripts/
    eval_skill.py                → 主入口脚本，所有子命令通过此文件调用
    eval_auth.py                 → 鉴权辅助
    clients/                     → API 客户端（HTTP、OAuth、Token 管理）
    files/                       → 文件处理（streaming、file_utils）
    utils/                       → 工具函数（常量、错误、日期、keypoint prompts）
    cfg/                         → 配置文件（eval-auth.cfg、eval-server.cfg）
```

## 关键约定

### 插件行为

- 所有用户交互使用中文
- 禁用 `AskUserQuestion` 工具，使用 Markdown 编号表格作为交互方式
- 技术实现细节（脚本命令、JSON 字段、内部 ID）不向用户暴露
- 鉴权、搜索、打包、上传、轮询等操作全程静默执行

### 脚本调用

所有 Python 脚本通过统一入口调用：

```bash
python3 "skills/skill-evaluation/scripts/eval_skill.py" <subcommand> [options]
```

子命令分类：鉴权（check-token, login）、Skill 管理（search-skill, download-skill, package）、模型管理（models, build-models）、评测集（convert-excel, upload-dataset, datamaker）、任务管理（submit, status, summary, artifacts）。

### 运行时产物

评测会话产物存放在工作目录的 `.eval/` 下：

```
{work-dir}/.eval/
  auth.json                      → OAuth Token
  {session-id}/
    eval-runtimes.json           → 运行框架配置
    eval-models.json             → 驱动模型列表
    eval-judge.json              → 评委模型配置
    eval-dataset.json            → 评测集数据
    eval-dataset-meta.json       → 评测集元信息（含 dataset-id）
    eval-task.json               → 任务信息（含 task-id）
    eval-result.json             → 评测结果
```

## 开发指南

### 本地测试

```bash
claude --plugin-dir /path/to/skill-evaluation-plugin
```

然后在对话中输入 `/skill-evaluation` 或描述评测意图触发。

### 修改技能流程

- 阶段文档（eval-init/build/set/execute.md）定义每个阶段的任务和步骤
- `processes/` 下的子流程文档被阶段文档引用
- `references/` 下的规范文档定义全局约束

### 修改脚本

- `eval_skill.py` 是 CLI 入口，使用 argparse 注册子命令
- `clients/` 封装 HTTP 和 OAuth 逻辑
- 新增子命令后需同步更新 `references/脚本定义.md`

### 插件验证

```bash
npx claude-plugin-validator ./skill-evaluation-plugin
```

## 注意事项

- `.eval/` 目录已在 `.gitignore` 中，不要提交用户的评测产物
- `scripts/cfg/` 中的配置文件包含 OAuth client_id，属于公开信息，可提交
- 修改 SKILL.md 的 `allowed-tools` 时需确保脚本执行权限匹配
