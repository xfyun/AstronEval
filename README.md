# astroneval

Skill 评测插件 for Claude Code。

引导用户对本地 Skill 进行自动化评测，支持单 Skill 验证、多 Skill 横评、多模型横评、运行框架横评等场景。

## 功能

- **快速测试单个 Skill**：验证 Skill 在指定模型下的执行效果
- **多 Skill 横评**：对比多个同类 Skill 的表现差异
- **多模型横评**：同一 Skill 在不同模型驱动下的效果对比
- **运行框架横评**：同一 Skill 在不同运行框架下的表现对比

## 安装

通过 Claude Code 插件市场安装：

```bash
claude plugins install astroneval
```

或本地开发测试：

```bash
claude --plugin-dir /path/to/skill-evaluation-plugin
```

## 使用方式

### 自动触发

在对话中提到以下内容时自动激活：

- "评测 skill"
- "提交 skill 评测"
- "跑 skill 评测"

### 斜杠命令

```
/skill-evaluation
```

## 评测流程

插件采用 4 阶段流水线引导用户完成评测：

1. **确认评测场景** — 鉴权验证、意图分析、场景确认
2. **配置评测对象** — 选择 Skill、运行框架、驱动模型、评委模型
3. **准备评测数据** — 上传或自动合成评测集
4. **提交并查看报告** — 任务提交、轮询、结果展示

## 前置条件

- Python 3.8+
- Claude Code CLI