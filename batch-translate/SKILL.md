---
name: batch-translate
description: "批量翻译工作流（Codex 适配版 v5）。支持 mqxliff/docx/xlsx/txt → 分批翻译 → 逐批校对 → 写回，全自动循环。混合文件原生支持 + 独立验证脚本 + 绝对路径 + UTF-8 规范；Windows 默认 PowerShell。"
---

# batch-translate — 批量翻译工作流

> 已从 Reasonix 迁移至 Codex：`run_skill`/`ask`/`write_file` 已按 Codex 等价流程改写；shell 命令按当前环境执行（Windows 默认 PowerShell）。

## 触发条件

用户表达要批量翻译文件时触发本 skill。如：
- "开始批量翻译"
- "批量翻译这个文件"
- "继续翻译下一批"

## 阶段〇：安装/更新工具包

> ⚠️ **强制步骤**：每次触发本 skill 必须首先执行，不可跳过。

### 情况 A：`batch_translate/` 不存在

Bash：

```bash
git clone https://github.com/xiaoxinblast/batch-translate.git batch_translate
python -m pip install -r batch_translate/requirements.txt
mkdir -p batch_translate/data batch_translate/exports
```

PowerShell（Windows 默认）：

```powershell
git clone https://github.com/xiaoxinblast/batch-translate.git batch_translate
python -m pip install -r batch_translate/requirements.txt
New-Item -ItemType Directory -Force batch_translate\data, batch_translate\exports | Out-Null
```

目录结构（按源文件 stem 分组）：
- `data/<stem>/_working_*, batch_state.json` ← 每个源文件独立
- `exports/<stem>/_batch_NNN_*.json` ← 每个源文件独立
- `data/tm_memory.json, term_base.xlsx, style_guide.txt` ← 共享

### 情况 B：`batch_translate/` 已存在

**必须检查并更新到最新版本**：

Bash：

```bash
cd batch_translate
if [ ! -d .git ]; then
  cd .. && rm -rf batch_translate
  git clone https://github.com/xiaoxinblast/batch-translate.git batch_translate
  python -m pip install -r batch_translate/requirements.txt
else
  git fetch origin && git merge origin/main --ff-only 2>/dev/null || git reset --hard origin/main
fi
mkdir -p data exports
cd ..
```

PowerShell（Windows 默认）：

```powershell
Set-Location batch_translate
if (-not (Test-Path .git)) {
  Set-Location ..
  Remove-Item -Recurse -Force batch_translate
  git clone https://github.com/xiaoxinblast/batch-translate.git batch_translate
  python -m pip install -r batch_translate/requirements.txt
} else {
  git fetch origin
  git merge origin/main --ff-only
  if ($LASTEXITCODE -ne 0) { git reset --hard origin/main }
}
New-Item -ItemType Directory -Force data, exports | Out-Null
Set-Location ..
```

确认 `batch.py` 可执行且依赖已安装后，进入阶段〇.五。

## 阶段〇.五：项目文件扫描

> ⚠️ **强制步骤**：必须在阶段一之前执行。

### 1. 列出根目录
```bash
ls -la
```

### 2. 多维度 Glob 扫描

- 术语类：`**/*术语*` `**/*用語*` `**/*term*` `**/*glossary*` `**/*词汇*`
- 风格指南类：`**/*翻译指南*` `**/*翻訳*` `**/*方針*` `**/*style*guide*` `**/*ローカライズ*` `**/*本地化*`
- 翻译记忆类：`**/*tm*` `**/*memory*` `**/*翻译记忆*`
- 前作/参考类：`**/*前作*` `**/*master*` `**/*マスター*`

### 3. 评估找到的文件

列出所有找到的文件，标注大小，**同时检查 `batch_translate/data/` 下是否已有编译版**。

**优先级判断原则**：
- `batch_translate/data/` 下的已有编译版优先于项目原始文档
- 根目录文件优先于子目录文件
- 行数/大小大的优先于小的
- `.xlsx` 多 sheet 优先于单 sheet
- 文件修改时间新的优先于旧的

### 4. 确认参考文件来源

> ⚠️ **强制步骤**：扫描后、生成任何文件前，必须询问用户。
> 
> **例外**：若用户触发本 skill 时已明确指定术语库/TM/风格指南来源，跳过 ask 直接使用用户指定值。

向用户展示扫描结果，然后直接向用户提问（可多选），依次询问风格指南、术语库、翻译记忆来源。

> ⚠️ 若用户选择"从源文件导入已有译文"，必须提醒：
> "源文件中已有的译文可能已过时。导入后需逐条核对。"

## 阶段一：项目初始化

若 `batch_translate/data/<stem>/batch_state.json` 不存在，则尚未初始化。

### 1. 生成风格指南 → `batch_translate/data/style_guide.txt`

> ⚠️ **强制步骤**：必须在 init 之前完成。

- 用 python heredoc：`python << 'PYEOF' ... PYEOF`，输出重定向到文件后读取内容核验
- 必须包含：弯引号规范、破折号/省略号规范、日中翻译注意事项（正反示例各至少一个）
- **必须用文件写入工具（Codex 中为 apply_patch）将风格指南写入文件**

### 2. 生成术语库 → `batch_translate/data/term_base.xlsx`

- ⚠️ 读取参考文件时必须读取全部行，禁止截断
- 自适应识别列结构
- 以 xlsx 三列格式写入：`原文(ja) | 译文(zh) | 注释`

### 3. 创建翻译记忆

根据用户选择创建或导入 TM。

### 4. 运行 init

```bash
python batch_translate/batch.py init <源文件> \
  --batch-chars 3000 --context-size 5 \
  --terms batch_translate/data/term_base.xlsx \
  --tm batch_translate/data/tm_memory.json \
  --style-guide batch_translate/data/style_guide.txt
```

PowerShell（Windows 默认，单行写法）：

```powershell
python batch_translate/batch.py init <源文件> --batch-chars 3000 --context-size 5 --terms batch_translate/data/term_base.xlsx --tm batch_translate/data/tm_memory.json --style-guide batch_translate/data/style_guide.txt
```

### 4.5. 模式判定

> ⚠️ **强制步骤**。init 已自动检测并打印（如 `🔀 混合文件: 511/1491 条已有译文`）。

- **全部有译文 = 总数** → `batch.py next --review`（跳过翻译，直接校对）
- **混合 / 全部无译文** → `batch.py next`（translate 模式自动锁定已有译文，只翻译空条目）

> `batch.py next` 会自动从 `_working.json` 中检测已有 `target`，注入为 `locked=true`。无需外部手动脚本。

### 5. 全量语境分析

> ⚠️ **强制步骤**。

启动 `context-analyzer` 子代理角色（角色文件：`~/.codex/agents/context-analyzer.toml`）。返回后确认报告完整，写入 `batch_state.json` 的 `document_summary` 字段。

### 6. 术语缺口核查（只读）

若语境分析报告含「疑似术语库未覆盖的专名」清单，核查术语库是否已存在。**不询问用户、不写入术语库、不阻塞流程**。

## 阶段二：自动循环

反复执行以下步骤直到全部批次完成。

### Step 1: 获取当前批

```bash
python batch_translate/batch.py next        # 普通/混合文件（自动锁定已有译文）
python batch_translate/batch.py next --review  # 全译文文件（跳过翻译）
```

### Step 2: 翻译（仅 translate 模式）

启动 `translator` 子代理角色（角色文件：`~/.codex/agents/translator.toml`）。任务参数中必须使用**绝对路径**指定输入输出文件（从 `batch_state.json` 的 `stem` 推导）。

- locked=true 的条目：保留 target 不变，**严禁对译文进行任何改动**（这些是100%匹配的已交付译文）
- locked=false 的条目：从零翻译

### Step 3: 生成校对文件（仅 translate 模式）

```bash
python batch_translate/batch.py review _batch_NNN_translated.json
```

### Step 4: 校对（共用）

启动 `trans-reviewer` 子代理角色（角色文件：`~/.codex/agents/trans-reviewer.toml`）。任务参数中必须使用**绝对路径**。

> locked=true 的条目**严禁修改**——校对时同样遵循此规则。

### Step 4.5: 机制化验证校对 JSON

```bash
python batch_translate/scripts/verify_batch.py --stem <stem>
```

> 脚本内置 UTF-8 输出，无 GBK 编码问题；可连续调用不会被 loop guard 拦截。

**分级处理**：
- `RESULT: PASS (...)` exit 0 → 进入 Step 5
- `FATAL:` 非 0 退出码 → 退回 Step 4 重跑
- `WARNING:` + `PASS with warnings` → 退回 Step 4 修正后重跑

### Step 5: 提交并推进

```bash
python batch_translate/batch.py submit _batch_NNN_reviewed.json
```

submit 内部自动执行 write + TM 积累 + 重新 parse + 生成下一批 JSON（自动注入 locked 条目）。提交后回到 Step 1。

### 完成

全部批次完成后，`batch.py submit` 自动清理状态文件。告知用户完成。

## Shell 命令规范

- **所有 Python 脚本默认在开头加 UTF-8 输出**：`import sys; sys.stdout.reconfigure(encoding="utf-8")`（Windows 优先用此方法）
- **独立 `.py` 脚本文件**优先于 heredoc（避免 GBK 编码和 loop guard 问题），如 `batch_translate/scripts/verify_batch.py`
- **含中文/emoji 输出时**：优先使用独立脚本文件
- **pip**：用 `python -m pip install` 而非 `pip install`

## 子代理角色（Codex）

三个子代理已从技能改为 Codex 自定义角色，角色文件位于 `~/.codex/agents/`（个人级）：

- `context-analyzer.toml`：指定 `deepseek-v4-flash`，快速全量语境分析
- `translator.toml`：不指定 model（继承主模型），文件内保留原 pro 分工说明与启用注释
- `trans-reviewer.toml`：不指定 model（继承主模型），文件内保留原 pro 分工说明与启用注释

三个角色均设置 `model_reasoning_effort = "max"`（沿用 Reasonix 原分工）。

DeepSeek Responses API 目前仅支持 `deepseek-v4-flash`；待支持 pro 后可按角色文件内注释启用。
