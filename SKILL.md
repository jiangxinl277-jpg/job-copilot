---
name: job-copilot
description: 把岗位 JD 变成结构化需求，评估简历证据覆盖度，并自动生成一页 A4 定制简历的求职工作流。适用于"按 JD 改简历""这条岗位值不值得投""批量筛岗位"三类任务。
metadata:
  short-description: JD 抓取 → 要求抽取 → 证据匹配 → 一页简历 → 版式校验 → 投递台账
---

# Job Copilot

把一份岗位 JD 或一张岗位表，变成"投不投、怎么投、投哪版"的确定动作。

## 何时使用

- 用户给了一个 JD / 招聘链接，要判断匹配度或改简历
- 用户给了一张岗位表（飞书、Excel、导出 CSV），要筛出能投的岗位
- 用户要针对某家公司生成一版简历，并且必须是一页

## 六步流水线

| 步 | 做什么 | 脚本 | 产出 |
| --- | --- | --- | --- |
| ① | 文本化：公开页 / 文件 / 粘贴 / 截图 OCR | `scripts/fetch_page.js`、`scripts/ocr_image.py`、`scripts/extract_jd.py` | `data/raw/*.txt` |
| ② | 要求抽取：关键词、学历、城市、截止、质量 | `scripts/extract_jd.py` | `data/jd_*.json` |
| ③ | 证据匹配：命中 / 弱证据 / 缺口 | `scripts/match_evidence.py` | `output/match_*.md` |
| ④ | 简历生成：按命中权重重排条目 | `scripts/build_resume.py` | `output/定制简历_*.docx` |
| ⑤ | 版式校验：页高 ≤ 268mm | `scripts/check_layout.py` | PASS / FAIL |
| ⑥ | 投递台账 | `scripts/ledger.py` | `data/applications.csv` |

一键跑完 ③–⑥：

```bash
python3 scripts/run_all.py --jd data/jd_ey.json --tag ey
```

## 批量模式（客户给一张岗位 Excel）

```bash
# 1) 解析候选人的简历（docx / pdf / txt 都行）
python3 scripts/parse_resume.py --input resume.docx --out data/resume_profile.json

# 2) 岗位表 → 打分排名（--deep N 抓前 N 个 JD，--resumes N 生成前 N 版简历）
python3 scripts/batch_score.py --excel data/jobs.xlsx \
    --resume data/resume_profile.json --out output/岗位匹配排名.xlsx \
    --deep 6 --resumes 5
```

批量打分规则（缺一条就会排出一堆"前端工程师"）：

1. **硬过滤**：学历含本科、届次含 2026、截止未过
2. **分档**：金融业 / 银行 = A 档；非金融但岗位含财务职能 = B 档（-15 分）；其余排除
3. **词权重**：债券/审计/估值 3 分，数据/分析/团队 0.5–0.8 分
4. **核心词缺口惩罚**：岗位要求精算/核保/理赔等而简历没有 → 每条 -12
5. **覆盖度折扣**：可匹配词权重不足 8 分时按比例打折，避免"一个词命中就 100"
6. **技术岗排除**：工程师/开发/算法岗直接排除；混合岗位行封顶 55

## 站点适配器

| 适配器 | 站点 | 现状 |
| --- | --- | --- |
| `adapters/citic.js` | careers.citics.com | 岗位名可抓；点"详情"跳登录 → `needs_login` |
| `adapters/hotjob.js` | *.hotjob.cn（北森） | iframe 内岗位清单可抓；详情需登录/交互 → `needs_login_or_paste` |
| `scripts/fetch_page.js` | 通用公开页 | 直接取 innerText |

适配器统一输出 `summary.json`，`status` 取 `ok / thin / needs_login / needs_paste`。
**不要**为了"有产出"而把导航栏当 JD —— 质量闸门比抓取量重要。

## 截图 OCR（macOS Vision）

截图 / 照片里的 JD 用系统 Vision 识别，离线、中文准确率高，不用 Tesseract：

```bash
python3 scripts/ocr_image.py --out data/raw shot1.png shot2.jpg
```

- 引擎：PyObjC 调 macOS Vision（`scripts/ocr_vision_py.py`），装在 skill 内的 `.venv`
- 首次安装：`uv venv .venv --python <python3.12>` + `uv pip install --python .venv/bin/python pyobjc-framework-Vision pyobjc-framework-Quartz`
- **必须非沙箱执行**：沙箱会拦住 Vision 的 CVPixelBuffer 分配（报 `Failed to create CVPixelBuffer`），在 Codex 里跑这一步需要一次授权
- 实测：772 字的 JD 渲染成图后识别出 770 字，关键词全部命中

## 事实与排版分离

`data/profile.json` 是唯一事实来源（只有本人素材）。`build_resume.py` 只做筛选与排序，
不新增、不改写任何事实；新内容必须先由用户确认后写进 profile。

## 匹配判定（决定"投不投"）

`match_evidence.py` 三条规则，刻意从严：

| 判定 | 条件 | 面试含义 |
| --- | --- | --- |
| ✅ 强命中 | 关键词或其同义词**真的出现在经历文本里** | 可以直接讲，有例子 |
| ⚠️ 弱证据 | 没有原词，但能力标签重叠，或只在技能区出现 | 要准备"能力迁移"的说法 |
| ❌ 缺口 | 完全没有 | 别硬讲 |

分数 = (强命中 + 0.5×弱证据) / 关键词总数 × 100。

两条维护规则（血泪教训）：

1. **短词要收紧成词组**：`咨询` 会匹配到"客户**咨询**记录"，必须改成
   `咨询顾问 / 管理咨询 / 咨询服务`，否则 EY 这种岗位会假命中。
2. **独立能力必须独立标签**：`反洗钱 / KYC / AML` 不能挂在 `compliance` 上，
   否则做过授信核对就会被算成"懂反洗钱"。

改动词表后跑自检：

```bash
python3 scripts/selftest_matcher.py   # 10 条断言，必须 10/10
```

## 稳定性

- 页面抓不全 → `needs_paste`，不生成简历
- 简历超页 → 按标签得分删最弱条目后重渲染，直到 ≤ 268mm
- 每个岗位都落一行台账，避免重复投、漏投

## 已知限制

- BOSS / 猎聘等登录墙平台不做抓取，改由用户粘贴或导出
- 截图 OCR 依赖 macOS Vision + PyObjC venv，且不能在沙箱内运行（见上）
- JD 关键词映射是规则表（`match_evidence.py` 的 `KW2TAG`），长尾词需要补词表
