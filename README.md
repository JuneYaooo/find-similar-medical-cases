<div align="center">

# Find Similar Medical Cases

**把相似医学病例检索做成可复现、可核验、有来源边界的 Agent Skill。**

装进 Codex 后，可以直接用自然语言描述一个已经去标识化的临床表现，让 Agent 从 PubMed、Europe PMC、OpenAlex、Crossref、中文文献入口、专科病例库和可选微信渠道中检索、扩展、去重并比较相似病例。

[![GitHub stars](https://img.shields.io/github/stars/JuneYaooo/find-similar-medical-cases?style=flat)](https://github.com/JuneYaooo/find-similar-medical-cases/stargazers)
[![CI](https://github.com/JuneYaooo/find-similar-medical-cases/actions/workflows/ci.yml/badge.svg)](https://github.com/JuneYaooo/find-similar-medical-cases/actions/workflows/ci.yml)
[![Agent Skill](https://img.shields.io/badge/Agent-Skill-orange.svg)](./SKILL.md)
[![Python 3.10+](https://img.shields.io/badge/Python-3.10%2B-blue.svg)](https://www.python.org/)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](./LICENSE)

</div>

> **安全提示**：本项目不是诊断或治疗工具。相似病例只能用于文献回顾和生成临床假设，不能单独确定诊断、药物因果关系、治疗适用性或个体预后。发送外部查询前必须移除患者身份信息。

---

## 能做什么

- **多路线检索**：把一个病例拆成高精度、表现优先、诊断/鉴别、宽泛同义词和检查/治疗等独立查询族。
- **多来源发现**：默认查询 PubMed、Europe PMC 和 OpenAlex；按需用 Crossref 补充 DOI 与出版商元数据。
- **相似与引文扩展**：对已验证种子执行 PubMed Similar Articles，以及 OpenAlex 参考文献、前向引用和相关文献扩展。
- **中文与专科补漏**：生成 CNKI、万方、维普、SinoMed、CMCR、病例期刊和专科教学病例库的浏览器检索计划。
- **可选微信检索**：支持用户提供的公众号文章、人工搜索，以及有明确费用上限的 TikHub 付费通道。
- **跨来源去重**：联合 DOI、PMID、PMCID、标题、年份和第一作者；稳定标识冲突时不会仅凭同标题合并。
- **病例级比较**：分开列出相同点、重要差异和未知信息，不把“疾病名称相同”直接当作临床相似。
- **证据分层**：明确区分题录、摘要、可访问全文、本次实际检查的证据、教学病例和社会化来源。
- **覆盖审计**：记录查询式、来源、时间、结果数、边际新增候选、失败原因、停止条件和剩余盲区。

## 适合哪些场景

| 场景 | 适合程度 | 说明 |
| --- | --- | --- |
| 罕见病或非典型表现的相似病例检索 | 很适合 | 多查询族和引文扩展有助于减少单一关键词漏检。 |
| 药物不良反应或治疗反应类病例 | 很适合 | 可加入药物、机制、检查和结局分支。 |
| 影像、病理、眼科等专科教学病例 | 适合 | 可补充专科病例库，并与论文来源分开报告。 |
| 中文病例报告、医案和病例讨论 | 适合 | 提供中文数据库与站点检索入口，访问权限需用户自行具备。 |
| 微信公众号病例线索 | 有条件适合 | 作为二级发现来源，需追溯原始论文或机构来源。 |
| 系统综述或正式循证评价 | 只能辅助 | 本 Skill 不替代注册方案、双人筛选、偏倚评价和正式系统综述流程。 |
| 个人诊断、处方或治疗决策 | 不适合 | 病例相似性不能直接证明当前患者的诊断或治疗适用性。 |

## 安装

### 让 Agent 帮你安装

把下面这段话发给 Codex：

```text
帮我安装 find-similar-medical-cases skill：
https://github.com/JuneYaooo/find-similar-medical-cases
```

安装完成后，重新启动 Codex 或开启新会话，让 Skill 元数据重新加载。

### 手动安装

需要 Python 3.10 或更高版本。核心检索脚本只使用 Python 标准库。

```bash
mkdir -p "${CODEX_HOME:-$HOME/.codex}/skills"
git clone https://github.com/JuneYaooo/find-similar-medical-cases.git \
  "${CODEX_HOME:-$HOME/.codex}/skills/find-similar-medical-cases"
```

如果已经克隆到其他目录，可以创建符号链接：

```bash
ln -s /absolute/path/to/find-similar-medical-cases \
  "${CODEX_HOME:-$HOME/.codex}/skills/find-similar-medical-cases"
```

## 使用示例

使用前先删除姓名、联系方式、病历号、精确地址、精确日期和不必要的罕见身份组合。

```text
用 find-similar-medical-cases 帮我找相似病例：
成年患者使用泊沙康唑后出现高血压、低钾、代谢性碱中毒、低肾素和低醛固酮。
```

```text
帮我找“青年女性、反复低钾、高血压、代谢性碱中毒”的病例报告。
不要先假设诊断，同时覆盖原发性醛固酮增多症、肾血管性高血压和表观盐皮质激素过多。
```

```text
找与这个罕见病理组合相似的病例，并从最接近的论文继续查参考文献、引用它的论文和 PubMed Similar Articles。
```

```text
除了英文论文，再补充中文病例报告和相关专科教学病例；把论文、教学病例和微信线索分开列出。
```

```text
只做一个快速初筛，不要称为完整检索；告诉我哪些数据库还没有查。
```

## 它如何工作

```text
去标识化病例
  → 病例指纹与多查询族
  → PubMed / Europe PMC / OpenAlex / 可选 Crossref
  → 中文、专科与可选微信补漏
  → DOI / PMID / PMCID / 书目信息联合去重
  → PubMed Similar + 引文图扩展
  → 临床特征比较与证据核验
  → 来源分层报告、覆盖审计和停止说明
```

项目不会把“搜到很多结果”写成“找到了所有病例”。未发表病例、数据库收录延迟、订阅限制、术语差异和封闭平台，使绝对完整性无法被证明。

## 来源与能力边界

| 来源 | 接入方式 | 默认使用 | 证据角色 |
| --- | --- | ---: | --- |
| PubMed | NCBI 官方 API | 是 | 医学文献主干、标识符和摘要核验。 |
| Europe PMC | 官方 API | 是 | 医学文献主干、摘要和开放全文线索。 |
| OpenAlex | 第三方学术 API | 是 | 广泛发现、引用和相关文献扩展，临床事实需回原始来源核验。 |
| Crossref | 官方 DOI 元数据 API | 否 | DOI 与出版商元数据补充，不作为临床证据。 |
| CNKI、万方、维普、SinoMed、CMCR | 浏览器或授权入口 | 按需 | 中文病例与题录发现，不绕过登录或订阅。 |
| 专科病例库、病例期刊和出版商 | 浏览器 | 按需 | 原始论文或明确标注的教学病例。 |
| 微信公众号 | 用户链接、人工搜索或 TikHub | 按需 | 二级线索；追溯原始来源后再支持临床事实。 |

“实时查询”只表示请求时查询了来源当前索引，不代表索引没有出版延迟，也不代表可以发现未发表或不可访问的病例。

## 输出内容

一次完整报告应包含：

1. 去标识化病例指纹和实际使用的查询变体。
2. 每个来源的检索方式、时间、命中数、新增候选数、失败和访问限制。
3. 最接近病例的标题、年份、标识符、链接、相似点、重要差异和证据范围。
4. 论文、教学病例、中文题录和社会化来源的分组结果。
5. 候选、重复、纳入、近似但不匹配和排除数量。
6. 停止原因、未检索渠道、全文缺失和其他不确定性。
7. 关键临床陈述对应的 claim-to-source 证据账本。
8. 医疗安全说明。

`clinical_similarity`、`retrieval_confidence`、`source_quality` 和 `citation_support` 始终分开，不合并成一个含义不清的总分。

<details>
<summary><strong>命令行高级使用</strong></summary>

### 综合检索计划

复制模板并替换为去标识化事实：

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

### 快速单查询

```bash
python3 scripts/search_cases.py \
  --query 'de-identified English clinical concepts' \
  --sources pubmed,europepmc,openalex \
  --limit 10 \
  --pretty
```

Crossref 为可选元数据来源：

```bash
python3 scripts/search_cases.py \
  --query 'rare disease presentation' \
  --sources crossref \
  --limit 10 \
  --pretty
```

### 扩展已验证种子

```bash
python3 scripts/expand_related_cases.py \
  --doi '10.xxxx/xxxxx' \
  --providers pubmed,openalex \
  --directions related,references,citations \
  --limit-per-direction 20 \
  --pretty
```

### 生成浏览器补漏计划

```bash
python3 scripts/build_browser_searches.py \
  --query '去标识化中文关键词' \
  --pretty
```

### TikHub 费用预览

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

</details>

## 可选环境变量

| 变量 | 用途 |
| --- | --- |
| `NCBI_EMAIL` | NCBI 负责任使用标识。 |
| `NCBI_API_KEY` | 提高 NCBI 速率额度。 |
| `OPENALEX_EMAIL` | OpenAlex polite-pool 标识（服务支持时）。 |
| `OPENALEX_API_KEY` | OpenAlex 当前政策要求时使用。 |
| `CROSSREF_EMAIL` | Crossref polite-pool 标识。 |
| `TIKHUB_API_KEY` | TikHub 付费调用，只从环境读取。 |
| `TIKHUB_BASE_URL` | TikHub API 区域端点。 |

不要把 API Key 放进 prompt、命令参数、查询计划、Git 提交、Issue 或日志。

## 项目验证

```bash
python3 scripts/validate_project.py
python3 -m unittest discover -s tests -v
```

项目验证器会检查 Skill frontmatter、目录名、`agents/openai.yaml`、相对链接、JSON 和 Python 语法。GitHub Actions 会在 Python 3.10 和 3.13 上运行格式检查、项目验证、单元测试和命令入口检查。测试不会调用付费服务。

## 项目结构

```text
find-similar-medical-cases/
├── SKILL.md                         # Agent 工作流与输出契约
├── agents/openai.yaml               # Codex 展示与默认调用提示
├── references/                      # 来源路由、检索协议、架构和查询模板
├── scripts/                         # 检索、扩展、浏览器计划、微信连接器和验证器
├── tests/                           # 无付费调用的自动化回归测试
└── .github/workflows/ci.yml         # Python 3.10 / 3.13 CI
```

完整工作流见 [SKILL.md](./SKILL.md)，来源路由见 [references/sources.md](./references/sources.md)，架构边界见 [references/technical-architecture.md](./references/technical-architecture.md)。

## 安全与隐私

- 外部检索前必须去除姓名、电话、邮箱、身份证件、病历号、精确地址和精确日期。
- 不要直接把未去标识化病历、住院记录或检查单粘贴进查询。
- API 或网页失败必须显示为失败、受限或未检索，不能改写成“0 个病例”。
- 不绕过登录、订阅、CAPTCHA、robots 规则或平台访问控制。
- 可访问全文不等于本次已经检查全文，也不等于拥有复制或再发布许可。
- 真实患者的诊断和治疗必须由合格医疗专业人员结合完整病史、检查和当地规范判断。

## 许可证

[MIT License](./LICENSE)
