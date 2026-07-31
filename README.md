# batch-translate-skill-codex

日→中 批量翻译工作流的 **Codex 适配版**：mqxliff/docx/xlsx/txt → 分批翻译 → 逐批校对 → 写回，全自动循环。

Reasonix 版请使用 [batch-translate-skill](https://github.com/xiaoxinblast/batch-translate-skill)；本仓库是 Codex 版（技能目录结构、元数据与工具调用方式均已按 Codex 规范调整）。

## 安装

### 方式一：skill-installer

```bash
python ~/.codex/skills/.system/skill-installer/scripts/install-skill-from-github.py \
  --repo xiaoxinblast/batch-translate-skill-codex \
  --path batch-translate context-analyzer translator trans-reviewer
```

安装后重启 Codex（或新开对话）即可生效。

### 方式二：手动复制

把四个技能目录复制到 `~/.codex/skills/`：

```powershell
$dst = "$HOME\.codex\skills"
Copy-Item -Recurse -Force batch-translate, context-analyzer, translator, trans-reviewer -Destination $dst
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

技能自动完成：安装工具包 → 扫描项目文件 → 编译风格指南/术语库 → 全量语境分析 → 分批翻译 → 逐批校对 → 写回。

## 技能组成

| 技能 | 职责 |
|------|------|
| `batch-translate` | 主流程编排（安装工具包、扫描、初始化、循环调度） |
| `context-analyzer` | 全量语境分析，识别文档分段与术语缺口 |
| `translator` | 日→中翻译，按风格指南产出自然中文 |
| `trans-reviewer` | 硬性错误检查 + 语言润色 |
