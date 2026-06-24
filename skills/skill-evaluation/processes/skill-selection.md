---
name: skill-selection
description: Use when in build phase and need to search, identify dependencies, package and upload skills for evaluation
---

# Skill 选择与上传流程

本流程定义如何根据用户选择的获取方式（搜索 / 给地址）完成 Skill 的搜索、依赖识别、打包、上传。

---

## 触发条件

- 阶段2 任务1 步骤2 触发
- 用户已选择获取方式，或上下文中已提供 Skill 名称/地址

---

## 分支 A：按名称搜索

### 步骤A1：询问 Skill 名称

| 评测对象数量 | 询问语句 |
|--------------|----------|
| 1 个 | `请提供要评测的 Skill 名称。` |
| 多个 | `请提供要评测的多个 Skill 名称（逗号分隔，至少 2 个）。` |

### 步骤A2：执行搜索

后台静默执行搜索（同时查本地 + 云端）：

```bash
{python-cmd} "$CLAUDE_PLUGIN_ROOT/skills/skill-evaluation/scripts/eval_skill.py" search-skill --name "{skill-name}" --work-dir "{work-dir}"
```

**JSON 解析注意**：搜索结果中本地路径字段（如 `path`）需经过 JSON 解析后再展示，**不要对路径字符串做任何二次处理**，否则 Windows 路径中的 `\\` 会被折叠为 `\`。

### 步骤A3：展示候选项

| 命中数量 | 输出格式 |
|----------|---------|
| 多条 | 合并展示并让用户选一个（见下方"多条结果"格式） |
| 仅一条 | 展示该结果并询问是否选用（见下方"仅一条结果"格式） |
| 零条 | 告知"本地与云端均未找到 Skill「{skill-name}」"，提示改用方式 2 或换名称 |

**多条结果**：

> 找到名称为「{skill-name}」的 Skill：
>
> | 选项 | 来源 | 位置 |
> |:----:|------|------|
> | 1 | 本地 | ~/.claude/skills/{skill-name} |
> | 2 | 云端 | https://clawhub.ai/ |
>
> 请选择（输入序号）：

**仅一条结果**：

> 找到名称为「{skill-name}」的 Skill：
>
> | 来源 | 位置 |
> |------|------|
> | {本地 / 云端} | {本地路径 或 https://clawhub.ai/} |
>
> 是否选用此 Skill？
>
> | 选项 | |
> |:----:|--|
> | 1 | 是，继续 |
> | 2 | 否，重新输入 Skill 名称 |

### 步骤A4：创建会话目录

用户选定 Skill 后，立即后台静默创建会话目录：

```bash
{python-cmd} "$CLAUDE_PLUGIN_ROOT/skills/skill-evaluation/scripts/eval_skill.py" session \
  --work-dir "{work-dir}" \
  --action create \
  --skill-name "{skill-name}"
```

会话目录命名规则：`YYYYMMDD_HHMMSS_{skill-name}`。后续所有中间文件均保存到此会话目录。

### 步骤A5：依赖识别（仅本地结果）

用户选定**本地**结果后，后台静默识别依赖（不向用户输出任何中间提示）：

- 读取该 Skill 目录里的 `SKILL.md` / `README.md` 等文档
- 结合上下文语义识别它是否调用、路由到、或依赖了其他 Skill
- 与 `~/.claude/skills/` 下的子目录名匹配，递归去重得到依赖列表

| 识别结果 | 处理 |
|----------|------|
| 无依赖 | **静默完成打包和上传，不向用户输出任何识别结论或过程提示**（如"xxx 无依赖，直接打包上传"、"未发现依赖 Skill"等开发态描述都禁止打印） |
| 有依赖且全部找到 | 向用户展示依赖列表询问是否一并打包（仅展示依赖项，不解释识别过程） |
| 有依赖但部分找不到 | 向用户展示已找到和未找到的依赖，提示重新选择待评测 Skill |

> ⚠️ **禁止暴露识别结论**：依赖识别是内部实现细节，"是否有依赖"本身就属于开发态信息。无依赖时跳过任何提示，直接进入打包；有依赖时也只列依赖名称，不描述识别行为。

**依赖全部找到时**，询问格式：

> 已识别「xxx」依赖以下 Skill：
>
> - skill-A
> - skill-B
>
> 是否一并打包？
>
> | 选项 | |
> |:----:|--|
> | 1 | 是 |
> | 2 | 否 |

**依赖部分找不到时**，询问格式：

> Skill「xxx」依赖以下 Skill：
>
> - skill-A（已找到）
> - skill-B（未找到）
>
> 依赖 Skill「skill-B」在本地与云端均未找到，无法完成打包。请重新选择待评测 Skill。

用户确认后，返回步骤 A1 重新询问 Skill 名称。

### 步骤A6：打包并上传

按用户确认结果后台静默打包上传：

**单目录打包上传**：
```bash
{python-cmd} "$CLAUDE_PLUGIN_ROOT/skills/skill-evaluation/scripts/eval_skill.py" package \
  --config "$CLAUDE_PLUGIN_ROOT/skills/skill-evaluation/scripts/cfg/eval-server.cfg" \
  --skill-dir "{target-skill-dir}" \
  --output-dir "{work-dir}/.eval/{session-id}"
```

**父 + 协同/依赖（合成单 zip）**：
```bash
{python-cmd} "$CLAUDE_PLUGIN_ROOT/skills/skill-evaluation/scripts/eval_skill.py" package \
  --config "$CLAUDE_PLUGIN_ROOT/skills/skill-evaluation/scripts/cfg/eval-server.cfg" \
  --skill-dir "{parent-skill-dir}" \
  --extra-skills "{dep-dir-1},{dep-dir-2}" \
  --output-dir "{work-dir}/.eval/{session-id}"
```

**直接上传已有 zip**（云端下载或用户提供）：
```bash
{python-cmd} "$CLAUDE_PLUGIN_ROOT/skills/skill-evaluation/scripts/eval_skill.py" package \
  --config "$CLAUDE_PLUGIN_ROOT/skills/skill-evaluation/scripts/cfg/eval-server.cfg" \
  --skill-zip "{skill-zip-path}" \
  --output-dir "{work-dir}/.eval/{session-id}"
```

| 场景 | 命令选择 |
|------|----------|
| 本地无依赖 / 用户拒绝合并依赖 | `package --skill-dir` |
| 本地有依赖且用户同意合并 | `package --skill-dir --extra-skills` |
| 云端结果 | 先 `download-skill` 下载到会话目录，再 `package --skill-zip` 上传 |

输出 `{skill-zip-url}`。多个评测对象时，每个对象各得一个 URL。

---

## 分支 B：提供 Skill 地址

### 步骤B1：询问地址

> 请提供 Skill 地址，多个用逗号分隔（**第一个为父 Skill**，其余将作为依赖一起打包）。
> 支持两种形式：
>
> - 本地路径：Skill 目录或 .zip 文件
> - 云端 URL：直接以 https:// 开头的 skill zip 链接

### 步骤B2：识别输入形式

| 输入形式 | 处理 |
|----------|------|
| 1 个本地目录 | 走分支 A 步骤A4-A6 |
| 多个本地目录 | 创建会话目录；第一个为父 Skill（识别依赖），其余作为用户指定的协同 Skill，合成**单个 zip** |
| 1 个 .zip 文件 | 创建会话目录；直接作为 Skill zip 上传，跳过依赖识别 |
| 1 个 https:// URL | 创建会话目录；先下载到本地，再上传，跳过依赖识别 |
| 多个项混合本地路径与 URL | 不支持，要求用户重新提供（统一为本地目录或单个 zip/URL） |

### 步骤B3：依赖识别规则

| 输入形式 | 依赖识别 |
|----------|----------|
| 本地目录 | 自动识别依赖（同分支 A 步骤A5），询问用户是否合并 |
| zip 文件 / 云端 URL | 跳过依赖识别，认为已自带依赖 |
| 多个本地目录 | 仅对第一个（父 Skill）识别依赖；其余目录作为协同 Skill 包含，不再递归扫描 |

### 步骤B4：打包并上传

同分支 A 步骤A6。

---

## 多评测对象处理

需要多个评测对象（横评 / 版本对比）时，对**每个评测对象**分别完成"步骤1～6"，得到一个 URL 列表与对应的名称列表。提交时同时传给后续 `submit --skill-names`（与 URL 顺序对齐）和 `submit --skill-urls`。

---

## 静默执行清单

下列动作必须全程静默，不向用户输出"正在 xxx"等中间提示：

- 搜索
- 下载
- 依赖识别
- 打包
- 上传

所有步骤全程静默，不向用户输出任何中间提示。

---

## 输出

| 变量 | 说明 |
|------|------|
| `{session-id}` | 会话目录名 |
| `{skill-zip-url}` | Skill zip 包 URL，多个时用逗号分隔 |
| `{skill-name}` | 选定的 Skill 名称（用于会话目录命名、摘要展示，以及 `submit --skill-names`）；多个时用逗号分隔，顺序需与 `{skill-zip-url}` 一一对齐 |
