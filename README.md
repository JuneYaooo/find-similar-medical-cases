# Find Similar Medical Cases

一个可公开安装的 Codex Skill，用可复现、来源分层的方式检索、扩展、核验和比较相似医学病例。

它不是诊断工具。相似病例只能帮助文献回顾和生成临床假设，不能单独确定诊断、因果关系、治疗适用性或个体预后。

## 能力范围

| 模块 | 当前实现 | 说明 |
|---|---|---|
| 医学文献主检索 | PubMed、Europe PMC | 官方 API，默认执行 |
| 学术发现 | OpenAlex | 第三方学术 API，默认执行后再回原始来源核验 |
| DOI 元数据补充 | Crossref | 可选，不作为临床证据 |
| 综合查询计划 | 多查询族、并发执行、覆盖审计 | 记录查询、命中、失败和边际新增候选 |
| 相似/引文扩展 | PubMed Similar Articles、OpenAlex | 支持相关文献、参考文献和前向引用 |
| 中文与专科来源 | CNKI、万方、维普、SinoMed、CMCR、专科病例库 | 生成来源标记的浏览器检索计划，不绕过访问控制 |
| 微信文章 | 用户链接、人工搜索、TikHub | TikHub 为可选付费通道，默认先 dry-run 估算费用 |
| 安全与证据 | 去标识化检查、来源质量分层、输出契约 | 明确区分题录、摘要、全文、教学病例和社会化来源 |

“实时”表示请求时查询了来源的当前索引，不代表索引没有收录延迟，也不表示能找到未发表、订阅受限或封闭平台中的全部病例。

## 安装

需要 Python 3.10 或更高版本；核心脚本只使用 Python 标准库。

直接安装到 Codex Skills 目录：

```bash
mkdir -p "${CODEX_HOME:-$HOME/.codex}/skills"
git clone https://github.com/JuneYaooo/find-similar-medical-cases.git \
  "${CODEX_HOME:-$HOME/.codex}/skills/find-similar-medical-cases"
```

如果已经克隆到其他位置，可以创建符号链接：

```bash
ln -s /absolute/path/to/find-similar-medical-cases \
  "${CODEX_HOME:-$HOME/.codex}/skills/find-similar-medical-cases"
```

重新启动 Codex 或开启新会话后，使用：

```text
Use $find-similar-medical-cases to find cases similar to this de-identified presentation: ...
```

## 快速验证

在仓库根目录运行：

```bash
python3 scripts/validate_project.py
python3 -m unittest discover -s tests -v
```

验证器会检查 Skill frontmatter、目录名、`agents/openai.yaml`、相对链接、JSON 和 Python 语法；测试不调用付费服务。

## 命令行使用

复制模板并替换为去标识化信息：

```bash
cp references/search-plan-template.json /tmp/case-search-plan.json
python3 scripts/run_search_plan.py \
  --plan /tmp/case-search-plan.json \
  --mode comprehensive \
  --limit 20 \
  --max-api-searches 30 \
  --workers 4 \
  --pretty
```

快速单查询：

```bash
python3 scripts/search_cases.py \
  --query 'de-identified English clinical concepts' \
  --sources pubmed,europepmc,openalex \
  --limit 10 \
  --pretty
```

Crossref 是可选元数据来源：

```bash
python3 scripts/search_cases.py \
  --query 'rare disease presentation' \
  --sources crossref \
  --limit 10 \
  --pretty
```

扩展已验证种子：

```bash
python3 scripts/expand_related_cases.py \
  --doi '10.xxxx/xxxxx' \
  --providers pubmed,openalex \
  --directions related,references,citations \
  --limit-per-direction 20 \
  --pretty
```

生成中文、期刊、专科和微信浏览器检索入口：

```bash
python3 scripts/build_browser_searches.py \
  --query '去标识化中文关键词' \
  --pretty
```

TikHub 付费调用前必须先查看预算：

```bash
python3 scripts/search_wechat_tikhub.py \
  --dry-run \
  --max-calls 6 \
  --pretty \
  collect \
  --query '去标识化关键词' \
  --pages 1 \
  --details 5
```

只有在确认当前价格、获得付费检索授权并设置 `TIKHUB_API_KEY` 后，才移除 `--dry-run`。

## 可选环境变量

| 变量 | 用途 |
|---|---|
| `NCBI_EMAIL` | NCBI 负责任使用标识 |
| `NCBI_API_KEY` | 提高 NCBI 速率额度 |
| `OPENALEX_EMAIL` | OpenAlex polite-pool 标识（服务支持时） |
| `OPENALEX_API_KEY` | OpenAlex 当前政策要求时使用 |
| `CROSSREF_EMAIL` | Crossref polite-pool 标识 |
| `TIKHUB_API_KEY` | TikHub 付费调用，只从环境读取 |
| `TIKHUB_BASE_URL` | TikHub API 区域端点 |

不要把患者标识信息或 API Key 放进查询计划、命令参数、提交、Issue 或日志。

## 检索与证据原则

- 发送外部查询前移除姓名、联系方式、病历号、精确地址、精确日期和不必要的罕见识别组合。
- 分开报告 `retrieval_confidence`、`clinical_similarity`、`source_quality` 和 `citation_support`。
- 题录记录、摘要、开放全文、教学病例和微信文章不得混成一个无标签置信分数。
- DOI/PMID/PMCID/标题用于出版物去重；疑似重复患者仍需人工复核。
- API 或网页失败必须显示为失败、受限或未检索，不能改写成“0 个病例”。
- 不绕过登录、订阅、CAPTCHA、robots 规则或平台访问控制。

完整工作流见 [SKILL.md](SKILL.md)，来源路由见 [references/sources.md](references/sources.md)，架构边界见 [references/technical-architecture.md](references/technical-architecture.md)。

## 许可证

[MIT License](LICENSE)
