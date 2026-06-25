# astroneval

Claude Code 插件：Skill 自动化评测。

引导用户通过对话完成从配置到出报告的全流程，支持多种评测场景。

## 评测场景

| 场景 | 说明 | Skill 数量 | 驱动模型数量 | 运行时 Agent 数量 |
|------|------|:----------:|:------------:|:------------:|
| 快速效果验证 | 验证单个 Skill 在指定模型下的执行效果 | 1 | 1 | 1 |
| 同类 Skill 横评 | 对比多个功能相似 Skill 的表现差异 | 多个 | 1 | 1 |
| 驱动模型横评 | 同一 Skill 在不同模型驱动下的效果对比 | 1 | 多个 | 1 |
| Skill 版本对比 | 同一 Skill 不同版本的 A/B 测试 | 多个 | 1 | 1 |
| 运行框架横评 | 同一 Skill 在不同运行框架下的表现对比 | 1 | 1 | 多个 |

## 安装

### Claude Code

通过 GitHub 仓库安装（推荐）

```bash
# 注册 marketplace
claude plugins marketplace add https://github.com/xfyun/AstronEval.git

# 安装插件
claude plugins install astroneval@AstronEval
```

通过 npm 安装

```bash
npx -y --registry=https://depend.iflytek.com/artifactory/api/npm/npm-repo astron-eval@0.4.21
```

本地开发测试

```bash
claude --plugin-dir /path/to/skill-evaluation-plugin
```

### CodeX

通过 GitHub 仓库安装（推荐）

```bash
# 注册 marketplace
codex plugin marketplace add https://github.com/xfyun/AstronEval.git

# 安装插件
codex plugin install astroneval@AstronEval
```

通过 npm 安装

```bash
npx -y --registry=https://depend.iflytek.com/artifactory/api/npm/npm-repo astron-eval@0.4.21 --codex
```

### OpenClaw

> OpenClaw暂不支持当前的插件形式，只能安装裸技能。

通过 npm 安装

```bash
npx -y --registry=https://depend.iflytek.com/artifactory/api/npm/npm-repo astron-eval@0.4.21 --openclaw
```

通过 clawHub 安装

```bash
openclaw skills install @njuxumq/skill-evaluation
```

## 使用

### 命令触发

| 平台 | 触发命令 |
|------|----------|
| Claude Code | `/astroneval:skill-evaluation` |
| CodeX | `@skill-evaluation` |
| OpenClaw | `/skill_evaluation` |

### 自然语言触发

在对话中描述评测意图即可自动激活（所有平台通用）：

- "评测下 xxx Skill"
- "对比 skill-A 和 skill-B"
- "哪个模型驱动 xxx 效果更好"
- "xxx Skill 在 claude-code 和 openclaw 上对比一下"

## 评测流程

```
描述评测意图 → 确认场景 → 选择 Skill / 模型 / 框架 → 准备评测数据 → 提交并查看报告
```

| 阶段 | 内容 |
|------|------|
| 1. 初始化 | 鉴权验证 → 意图识别 → 场景确认 |
| 2. 构建配置 | 选择 Skill → 选择运行框架 → 选择驱动模型 → 选择评委模型 |
| 3. 数据准备 | 上传自定义评测集 或 平台自动合成 → 预览确认 |
| 4. 执行评测 | 确认任务摘要 → 云端执行 → 查看评分报告 |

整个过程以对话方式推进，技术细节（鉴权、打包上传、任务轮询等）在后台自动完成。

## 前置条件

- Python 3.8+
- Claude Code CLI
- 讯飞开放平台账号（首次使用时引导登录）

## 项目结构

```
.claude-plugin/
  plugin.json          # 插件元信息
skills/skill-evaluation/
  SKILL.md             # 技能入口定义
  eval-init.md         # 阶段1：初始化
  eval-build.md        # 阶段2：构建配置
  eval-set.md          # 阶段3：数据准备
  eval-execute.md      # 阶段4：执行评测
  processes/           # 子流程文档
  references/          # 参考规范
  scripts/             # Python 脚本（鉴权、API 调用、评测集处理）
```

## 许可证

Apache License 2.0
