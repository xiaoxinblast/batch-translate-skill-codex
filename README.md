# batch-translate-skill-codex

日→中 批量翻译工作流的 **Codex 适配版**：mqxliff/xliff/docx/xlsx/txt → 分批翻译 → 逐批校对 → 程序化 QA → AI QA 复核 → 写回，全自动循环。

Reasonix 版请使用 [batch-translate-skill](https://github.com/xiaoxinblast/batch-translate-skill)；本仓库是 Codex 版（技能目录结构、元数据与工具调用方式均已按 Codex 规范调整）。

## 安装

### 方式一：skill-installer

```bash
python ~/.codex/skills/.system/skill-installer/scripts/install-skill-from-github.py \
  --repo xiaoxinblast/batch-translate-skill-codex \
  --path batch-translate
python ~/.codex/skills/batch-translate/scripts/install_roles.py
```

skill 已自带四个子代理角色资源；第二条命令只同步这四个受管角色，不会删除 `~/.codex/agents/` 中的其他文件。

安装后重启 Codex（或新开对话）即可生效。

### 方式二：手动复制

把主技能目录复制到 `~/.codex/skills/`，角色文件复制到 `~/.codex/agents/`：

```powershell
$skills = "$HOME\.codex\skills"
$agents = "$HOME\.codex\agents"
New-Item -ItemType Directory -Force -Path $agents | Out-Null
Copy-Item -Recurse -Force batch-translate -Destination $skills
python "$skills\batch-translate\scripts\install_roles.py" --destination $agents
```

## 工具包

首次触发主技能时会自动从 [xiaoxinblast/batch-translate](https://github.com/xiaoxinblast/batch-translate) 安装工具包；也可手动安装：

```powershell
git clone https://github.com/xiaoxinblast/batch-translate.git batch_translate
python -m pip install -r batch_translate/requirements.txt
New-Item -ItemType Directory -Force batch_translate\data, batch_translate\exports | Out-Null
```

## 使用

在 Codex 中说：

> 开始批量翻译

技能自动完成：安装工具包 → 扫描项目文件 → 编译风格指南/术语库 → 全量语境分析 → 分批翻译 → 逐批校对 → 程序化 QA → QA 代理复核 → 写回。

## 组成

| 类型 | 名称 | 职责 |
|------|------|------|
| 技能 | `batch-translate` | 主流程编排（安装工具包、扫描、初始化、循环调度） |
| 角色 | `context-analyzer`（`agents/context-analyzer.toml`） | 全量语境分析，识别文档分段与术语缺口 |
| 角色 | `translator`（`agents/translator.toml`） | 日→中翻译，按风格指南产出自然中文 |
| 角色 | `trans-reviewer`（`agents/trans-reviewer.toml`） | 硬性错误检查 + 语言润色 |
| 角色 | `qa-reviewer`（`agents/qa-reviewer.toml`） | 复核程序化 QA finding，修正真错并记录误报 |

> 四个子代理由 Codex 自定义角色（`~/.codex/agents/*.toml`）替代了此前的同名技能，角色文件内含各自的 `developer_instructions` 与模型分工说明。
> 当前分工为 `context-analyzer = gpt-5.6-luna / max`、`qa-reviewer = gpt-5.6-luna / max`，翻译与校对为 `gpt-5.6-terra / max`。

当前会话具备原生角色 spawn 能力时，无论宿主终端是独立 CLI、VS Code、Desktop 还是 IDE，都使用原生编排：父代理依次执行 `agent-attempt`、等待子代理完成、`agent-complete` 和 `promote`。等待超时只表示本次轮询没有新事件，不能据此中断或重试运行中的子代理；原生接口明确报告 terminal failure 后才可复用原 attempt 重试。缺少原生 spawn、等待结果无效或工具路由异常时，应停止并报告，不使用 shell 或其他角色替代。

项目级 QA 提案只允许机器可执行规则。父代理必须把完整提案按固定列名 `规则名｜严重级别｜机器检查说明｜参数/阈值｜证据` 展示给用户；人工审校、主观质量判断和未决问题不得进入提案。

所有临时任务、agent attempt、报告和 scratch 文件统一写入项目工具包的 `batch_translate/_temp/`。`exports/` 保存批次任务、结果、receipt 和验证记录等持久产物。清理必须先 `temp audit`，再逐项核对后显式使用 `temp cleanup --apply`；不得整体处理项目根 `_temp/`。

## 兼容性

- Python 3.10+
- skill workflow protocol 10
- 工具包 `batch-translate` 10.x；自动更新前会验证 GitHub origin，更新后会验证协议
