# -*- coding: utf-8 -*-
"""Author the 思解 competition deck pages inside the round-trip workspace.

Edits the five reused template pages in place (text only, every data-pptx-*
attribute preserved) and authors the new pages: p06/p07/p10 on the slide_04
skeleton, p08/p09 on the slide_03 skeleton. Pristine template SVGs are restored
from _pristine/ on every run, so the script is idempotent.
"""
from __future__ import annotations

import html
import re
import shutil
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

BASE = Path(__file__).resolve().parent
SVG = BASE / "authoring-svg-flat"

FONT = "Microsoft YaHei, sans-serif"
INK = "#1D1D1B"
SUB = "#5B5B5B"
RED = "#C00000"
BLUE = "#0070C0"
PANEL = "#F7F7F8"
LINE = "#D9D9D9"

TEXT_RE = re.compile(r"<text\b[^>]*>.*?</text>", re.S)


def esc(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def plain(inner: str) -> str:
    return html.unescape(re.sub(r"<[^>]+>", "", inner))


def _match(svg: str, old_plain: str, build, count: int, label: str) -> str:
    done = [0]

    def repl(m):
        el = m.group(0)
        open_tag = re.match(r"<text\b[^>]*>", el).group(0)
        inner = el[len(open_tag):-len("</text>")]
        if done[0] < count and plain(inner).strip() == old_plain.strip():
            done[0] += 1
            return build(open_tag)
        return el

    out = TEXT_RE.sub(repl, svg)
    if done[0] != count:
        raise SystemExit(f"{label}: matched {done[0]}/{count} for {old_plain!r}")
    return out


def replace_text(svg: str, old_plain: str, new_inner: str, count: int = 1) -> str:
    return _match(svg, old_plain, lambda tag: tag + new_inner + "</text>", count, "replace_text")


def drop_text(svg: str, old_plain: str, count: int = 1) -> str:
    return _match(svg, old_plain, lambda tag: "", count, "drop_text")


def replace_multiline(svg: str, old_plain: str, lines, leading: float) -> str:
    def build(open_tag: str) -> str:
        x = re.search(r'\bx="([^"]+)"', open_tag).group(1)
        body = esc(lines[0])
        for ln in lines[1:]:
            body += f'<tspan x="{x}" dy="{leading}">{esc(ln)}</tspan>'
        return open_tag + body + "</text>"

    return _match(svg, old_plain, build, 1, "replace_multiline")


def block_text(x, y, lines, fs=14, fill=INK, leading=None, bold=False):
    """One absolutely positioned <text> per line (PowerPoint keeps exact leading)."""
    leading = leading if leading is not None else round(fs * 1.55, 2)
    return "".join(text_el(x, y + i * leading, [ln], fs=fs, fill=fill, leading=leading, bold=bold)
                   for i, ln in enumerate(lines))


def text_el(x, y, lines, fs=14, fill=INK, leading=None, bold=False,
            anchor="start", family=FONT):
    leading = leading if leading is not None else round(fs * 1.55, 2)
    weight = ' font-weight="bold"' if bold else ""
    body = esc(lines[0])
    for ln in lines[1:]:
        body += f'<tspan x="{x}" dy="{leading}">{esc(ln)}</tspan>'
    return (f'<text x="{x}" y="{y}" text-anchor="{anchor}" xml:space="preserve" '
            f'font-family="{family}" font-size="{fs}" fill="{fill}"{weight}>'
            f'{body}</text>')


def panel(x, y, w, h, fill=PANEL, stroke=LINE, rx=12):
    return (f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="{rx}" '
            f'fill="{fill}" stroke="{stroke}" stroke-width="1" />')


def group(gid, bounds, *parts):
    b = " ".join(str(v) for v in bounds)
    return f'<g id="{gid}" data-pptx-bounds="{b}">{"".join(parts)}</g>'


def append_groups(svg: str, *groups: str) -> str:
    """Insert before the ROOT closing tag only (pages embed nested <svg>)."""
    head, sep, tail = svg.rpartition("</svg>")
    return head + "".join(groups) + sep + tail


def load(name: str) -> str:
    return (SVG / name).read_text(encoding="utf-8")


def save(name: str, svg: str) -> None:
    (SVG / name).write_text(svg, encoding="utf-8")


# ---------------------------------------------------------------- page 1
def page01() -> None:
    s = load("slide_01.svg")
    s = replace_text(s, "openJiuwen 创意大赛提交模板",
                     '<tspan>思解</tspan><tspan fill="#C00000"> SIJIE</tspan>')
    groups = group(
        "p01-subtitle", [28, 470, 760, 120],
        text_el(37, 508, ["让每一句结论都能被验证 · 可拒绝的科研证据链"], fs=24, fill=INK, leading=34),
        text_el(37, 556, ["openJiuwen 智能体创意大赛 · 初赛 · 科研赛道"], fs=16, fill=RED, leading=24),
    )
    save("slide_01.svg", append_groups(s, groups))


# ---------------------------------------------------------------- page 2
def page02() -> None:
    s = load("slide_02.svg")
    s = replace_text(s, "创意名称XXX", "<tspan>思解 · 可被验证的科研论文生成系统</tspan>")
    s = replace_text(s, " \t创意描述（必填）：（<500字）",
                     '<tspan>\t创意描述</tspan><tspan fill="#C00000" font-weight="bold">（必填）</tspan>')
    s = replace_text(s, "办公、Coding、科研、设备互联", "<tspan>科研赛道（论文生成与验证）</tspan>")
    s = drop_text(s, "<500字")
    s = drop_text(s, "面向什么用户，什么场景，解决什么痛点；用户有什么潜在需求；对用户或者垂直领域会产生什么样的影响")

    desc = [
        "「思解」把论文写作从「生成文字」升级为「生成可",
        "核验的证据链」。每条结论以声明卡（ClaimCard）为最",
        "小单位，必须绑定计算脚本哈希、产物哈希、数据条目、",
        "文献快照与定位符；经八步校验链（schema、execution、",
        "context、binding、values、citation、deviation、",
        "row_conflict）与六道 rail（引用、溯源、推理边界、",
        "合规、预算、HITL）逐项判定，任一环不成立即拒绝落账",
        "并返回冻结错误码。落账走唯一写入口 ledger-mcp 的",
        "append-only 账本：rawlog、artifacts、账本三写，WAL",
        "先行、row_id 幂等，支持双源对账、崩溃恢复与篡改检测。",
        "编排层基于 openJiuwen 与 WorkSwarm：11 个角色协作，",
        "六道门以 DeepAgentRail 扩展接入执行点，审计链复用",
        "EvidenceWriter。目标不是让 AI 写得更好看，而是让导师、",
        "审稿人与作者都能机器核验每一句结论的出处与计算过程。",
    ]
    scene = [
        "面向科研团队、期刊编辑与审稿人。",
        "· 从数据到论文：图表、统计与结论同源同哈希，",
        "  改一个数字即可定位要重跑哪一步。",
        "· 投稿前自检：引用是否在 MANIFEST、是否一手来源、",
        "  快照是否留存，逐条给出可核对结果。",
        "· 审稿回应：把「我认为」换成「这是证据链」，",
        "  审稿意见可被机器复核。",
        "痛点：LLM 写作不可验证、引用与数字对不上、复现",
        "成本高、责任不可追溯。",
        "影响：论文从「看起来对」变成「可被验证」；科研",
        "协作从「信任个人」转为「信任证据」。",
    ]
    groups = (
        group("p02-desc", [55, 172, 620, 344],
              block_text(64, 196, desc, fs=14.5, fill=INK, leading=23.6)),
        group("p02-scene", [705, 172, 545, 300],
              block_text(712, 196, scene, fs=14.5, fill=INK, leading=24.5)),
    )
    save("slide_02.svg", append_groups(s, *groups))


# ---------------------------------------------------------------- page 3
def page03() -> None:
    s = load("slide_03.svg")
    s = replace_text(s, "方案详情（必填）",
                     '<tspan>方案详情</tspan><tspan fill="#C00000" font-weight="bold">（必填）</tspan>')
    s = replace_text(s, "方案优势（可选）",
                     '<tspan>方案优势</tspan><tspan fill="#C00000" font-weight="bold">（差异）</tspan>')
    s = replace_text(s, "技术依赖（可选）",
                     '<tspan>技术依赖</tspan><tspan fill="#C00000" font-weight="bold">（复用）</tspan>')
    s = drop_text(s, "此方案的核心能力")
    s = drop_text(s, "若业内有类似场景或专利，方案的优势在哪")
    s = drop_text(s, "如果入选，方案如何打磨验证，简单分析下依赖哪些资源，预期的Demo形式")

    caps = [
        ("① 声明卡 schema 族", "六件 schema 把「结论」冻成可校验原子：ClaimCard 1.4.0 / ClaimRow 1.2.0"),
        ("② 八步校验链", "schema→execution→context→binding→values→citation→deviation→row_conflict"),
        ("③ 六道 rail", "CitationGate · Provenance · InferenceScope · Compliance · Budget · HITL"),
        ("④ 账本与双源对账", "append-only CLAIMS.jsonl + rawlog + artifacts，WAL 先行、row_id 幂等"),
        ("⑤ 十一角色编排", "coordinator→intake-curator→librarian→analyst→writing→reviewer 1/2/3→ac→auditor"),
        ("⑥ 七道门禁", "82 语义/规则 + 18 版本对偶 + 73 文档口径 + 76 行为 + 48 端到端 + 35 向量 + 2 组合"),
    ]
    cap_parts = []
    for i, (title, detail) in enumerate(caps):
        x = 45 if i < 3 else 655
        y = 182 + (i % 3) * 80
        cap_parts.append(group(f"p03-cap-{i+1}", [x - 6, y - 30, 580, 68],
                               text_el(x, y, [title], fs=15.5, fill=RED, leading=22, bold=True),
                               text_el(x, y + 21, [detail], fs=12.5, fill=INK, leading=19)))
    adv = [
        "· 不是「更会写」，而是「更会拒绝」：20 类冻结错误码逐环拦截",
        "· 结论可复现：脚本、产物、数据、快照全部内容寻址，重跑即复现",
        "· 可审计可追责：事件链 + 审计报告 + 双源对账，改一行即被发现",
        "· 真实数据端到端已跑通：48 项检查，含 20 条负例与两处崩溃注入",
    ]
    dep = [
        "· openjiuwen（agent-core）：DeepAgentRail、MCP、权限与 HITL 包",
        "· WorkSwarm harness：调度、十一角色、扩展装载与 MCP 注册",
        "· jsonschema 4.26.0 / Python 3.12+；本地目录或对象存储",
        "· Demo：run_gates.sh 七道门禁 + demo/run_e2e.py 端到端复跑",
    ]
    save("slide_03.svg", append_groups(
        s, *cap_parts,
        group("p03-adv", [45, 448, 575, 190], text_el(48, 482, adv, fs=12.5, fill=INK, leading=23)),
        group("p03-dep", [655, 448, 580, 190], text_el(658, 482, dep, fs=12.5, fill=INK, leading=23)),
    ))


# ---------------------------------------------------------------- page 4
def page04() -> None:
    s = load("slide_04.svg")
    s = replace_text(s, "DEMO或示意图（可选，有更好）", "<tspan>系统架构：八层 + 证据链</tspan>")
    s = drop_text(s, "最终构想效果示意图或DEMO•  什么时机、什么方式、什么界面 触发该功能•  用户怎么输入、怎么输出•  关键的用户路径")

    guide = [
        ("读图：一条声明怎么走完八层", RED, 15.5, True),
        ("① 输入契约层 Research Brief 冻结问题、数据、文献三档", INK, 13, False),
        ("② 流水线层 SwarmSkill 十一角色 + SwarmFlow 横切编排", INK, 13, False),
        ("③ 可信门层六道 rail 在上下文装配处拦截（执行点①）", INK, 13, False),
        ("④ ledger-mcp 是唯一写入口：八步校验后 WAL 先行落账", INK, 13, False),
        ("⑤ 证据链层 CLAIMS.jsonl append-only，永不压缩", INK, 13, False),
        ("⑥ 审计出口层 Auditor 双源对账：账本 × 原始日志 + 重放", INK, 13, False),
        ("⑦ 平台层 WorkSwarm harness 提供调度、MCP、权限、rails", INK, 13, False),
        ("", INK, 13, False),
        ("写路径：rawlog → artifacts → 账本（WAL 先行，row_id 幂等）", RED, 13, True),
        ("任何一环不成立即拒绝，返回冻结码而不是写入脏数据。", SUB, 12.5, False),
    ]
    parts = []
    y = 100
    for line, fill, fs, bold in guide:
        if line:
            parts.append(text_el(742, y, [line], fs=fs, fill=fill, leading=fs * 1.5, bold=bold))
        y += 36 if fs > 13 else 31
    groups = (
        group("p04-arch", [22, 88, 690, 558],
              '<image href="../images/arch.png" x="22" y="88" width="690" height="555" '
              'preserveAspectRatio="xMidYMid meet" />'),
        group("p04-caption", [30, 646, 690, 30],
              text_el(34, 668, ["图：v27 总体架构（八层）；八步链与六道 rail 在流水线层与 ledger-mcp 之间。"],
                      fs=11, fill=SUB, leading=15)),
        group("p04-guide", [730, 70, 530, 600], *parts),
    )
    save("slide_04.svg", append_groups(s, *groups))


# ---------------------------------------------------------------- page 5
def page05() -> None:
    s = load("slide_05.svg")
    s = replace_text(s, "附：赛题方向详细参考", "<tspan>生态能力利用：把作品长在 openJiuwen 上</tspan>")
    s = replace_text(s, "*示意方向仅做场景参考，不限定大家的想象力",
                     "<tspan fill=\"#FFFFFF\">四类平台原生扩展点 · 一行都不 fork harness core</tspan>")
    for old, new in zip(["办公赛道", "Coding赛道", "科研赛道", "设备互联赛道"],
                        ["生态扩展点", "工作流编排", "工具与协议", "基础设施复用"]):
        s = replace_text(s, old, f"<tspan>{new}</tspan>")

    line_sets = {
        "让智能体成为你的办公助手。围绕会议纪要、文档处理、流程自动化、数据报表、知识管理等场景，打造高效、精准、可靠的生产力工具":
            ["六道门与审计做成原生 Rail 扩展，", "挂在 openJiuwen 执行点，", "不改 harness 内核"],
        "让智能体成为你的开发搭档。覆盖代码生成、审查、Bug修复、自动化测试、项目脚手架等全研发链路，提升开发效率与代码质量":
            ["SwarmFlow 编排十一角色，", "声明卡生成前必须过门层，", "产出即证据"],
        "让智能体成为你的科研伙伴。从文献检索、实验设计到数据分析、论文写作，全方位辅助科研全流程，激发创新灵感":
            ["ledger-mcp 是唯一写入口，", "四件工具覆盖写入、", "干跑校验与双源对账"],
        "让智能体突破数字边界。跟硬件生态结合，实现人机/机机联动，将智能体的眼、手、脚实体化，打造虚实融合新体验":
            ["审计链、内容寻址、权限与", "HITL 直接复用平台件，", "只把规范化换成 JCS"],
    }
    for old, lines in line_sets.items():
        s = replace_multiline(s, old, lines, 22)

    bullets = [
        ("会议纪要  ·  自动记录、提炼、分发会议要点", "Rail 扩展  ·  六个 hook 接入"),
        ("文档处理  ·  智能起草、审阅、格式化文档", "extensions  ·  目录装载扩展"),
        ("流程自动化  ·  审批、归档、通知自动执行", "_skip_tool  ·  工具级拦截"),
        ("数据报表  ·  采集、分析、生成可视化报表", "任务迭代  ·  门层执行点①"),
        ("知识管理  ·  企业知识库构建与智能检索", "工具调用  ·  门层执行点②"),
        ("协同办公  ·  多人协作、任务分配、进度跟踪", "失败关闭  ·  升级先跑契约测试"),
        ("代码生成  ·  根据需求自动生成代码片段", "SwarmFlow  ·  状态机编排"),
        ("代码审查  ·  自动PR审查，识别潜在问题", "intake  ·  冻结问题与数据"),
        ("Bug修复  ·  定位根因并生成修复方案", "librarian  ·  检索与取证"),
        ("自动化测试  ·  生成测试用例并执行验证", "analyst  ·  分析并出数值"),
        ("项目脚手架  ·  快速搭建项目结构与环境", "writing  ·  只写有证据的声明"),
        ("代码重构  ·  智能优化代码结构与性能", "reviewer×3  ·  独立三审"),
        ("文献检索  ·  智能搜索、筛选、综述文献", "mcp.servers  ·  注册即用"),
        ("实验设计  ·  辅助实验方案设计与优化", "append_claim  ·  唯一写入口"),
        ("数据分析  ·  自动清洗、统计与可视化", "verify_claim  ·  落账前干跑"),
        ("科研写作  ·  辅助论文撰写与引用管理", "query  ·  只读检索声明"),
        ("创新灵感  ·  跨领域知识关联与思路启发", "audit  ·  双源对账报告"),
        ("学术协作  ·  多人合著、版本管理、同行评审", "freeze_codes  ·  错误码复用"),
        ("人机联动  ·  语音、手势、眼动多模态交互", "EvidenceWriter  ·  事件链"),
        ("机机联动  ·  跨设备协同、任务自动流转", "blob  ·  内容寻址存储"),
        ("智能体眼  ·  摄像头/传感器感知环境", "permissions  ·  策略评估"),
        ("智能体手  ·  机械臂/机器人执行物理操作", "HITL  ·  中断与人工放行"),
        ("智能体脚  ·  移动平台实现空间自主移动", "沙箱  ·  执行隔离"),
        ("虚实融合  ·  数字孪生、AR/VR联动体验", "JCS  ·  RFC 8785 规范化"),
    ]
    for old, new in bullets:
        s = replace_text(s, old, f"<tspan>{esc(new)}</tspan>")
    save("slide_05.svg", s)


# ------------------------------------------------------- skeletons for copies
def skeleton04(title: str) -> str:
    s = load("slide_04.svg.bak")
    s = replace_text(s, "DEMO或示意图（可选，有更好）", f"<tspan>{esc(title)}</tspan>")
    s = drop_text(s, "最终构想效果示意图或DEMO•  什么时机、什么方式、什么界面 触发该功能•  用户怎么输入、怎么输出•  关键的用户路径")
    return s


def skeleton03(title: str, labels) -> str:
    s = load("slide_03.svg.bak")
    s = replace_text(s, "创意方案构想", f"<tspan>{esc(title)}</tspan>")
    for old, new in labels:
        s = replace_text(s, old, new)
    for hint in ("此方案的核心能力", "若业内有类似场景或专利，方案的优势在哪",
                 "如果入选，方案如何打磨验证，简单分析下依赖哪些资源，预期的Demo形式"):
        s = drop_text(s, hint)
    return s


# ---------------------------------------------------------------- page 6
def page06() -> None:
    s = skeleton04("证据管道端到端：真实数据跑通八步")
    steps = [
        ("步 1 schema", "ClaimCard 1.4.0 + ClaimRow 1.2.0 校验通过"),
        ("步 2 execution", "exec_203fee8ec6748021 · completed · 审计可用"),
        ("步 3 context", "MANIFEST#7 传递性：data_ref 指向数据条目且哈希一致"),
        ("步 4 binding", "脚本 sha256:d36b43a4… / 产物 sha256:c9b51b95… 重算一致"),
        ("步 5 values", "中位数 799 行（exact）/ 均值 2372.18（float_rel 1e-6）"),
        ("步 6 citation", "DOI 10.17487/RFC8785 · 一手来源 · 快照已存"),
        ("步 7 deviation", "非探索性声明，无需偏差注记"),
        ("步 8 row", "row_57cebcd0b5d8c9a1 · seq 1 · 账本 3 行 · audit 0 findings"),
    ]
    parts = [text_el(52, 106, ["检索为固定快照，agent 编排在 M3 落地"], fs=12.5, fill=SUB, leading=17)]
    y = 146
    for name, detail in steps:
        parts.append(text_el(52, y, [name], fs=13.5, fill=RED, leading=20, bold=True))
        parts.append(text_el(172, y, [detail], fs=12.5, fill=INK, leading=19))
        y += 59
    nums = [("48", "项检查全绿"), ("20", "条负例逐步拒绝"), ("3", "行 append-only 账本"), ("0", "条 audit findings")]
    cards = []
    for i, (n, label) in enumerate(nums):
        x = 700 + (i % 2) * 285
        y2 = 120 + (i // 2) * 150
        cards.append(group(f"p06-num-{i+1}", [x, y2 - 10, 270, 130],
                           panel(x, y2 - 10, 270, 130),
                           text_el(x + 20, y2 + 60, [n], fs=44, fill=RED, leading=50, bold=True),
                           text_el(x + 20, y2 + 96, [label], fs=13, fill=SUB, leading=18)))
    attack = [("篡改 1 行账本", "TAMPER_DETECTED"), ("删除 rawlog 事件", "PHANTOM_EVENT"),
              ("删除产物副本", "ARTIFACT_MISSING"), ("rawlog 后崩溃", "UNCOMMITTED_EVENT → recover 回滚"),
              ("账本后崩溃", "recover 补完，行数不变")]
    ap = [text_el(700, 448, ["攻击与恢复（同一账本的对抗测试）"], fs=14, fill=RED, leading=20, bold=True)]
    ay = 482
    for k, v in attack:
        ap.append(text_el(706, ay, [f"· {k}"], fs=12.5, fill=INK, leading=18))
        ap.append(text_el(910, ay, [v], fs=12.5, fill=BLUE, leading=18))
        ay += 30
    save("p06_demo.svg", append_groups(
        s, group("p06-steps", [40, 88, 640, 580], *parts), *cards,
        group("p06-attack", [690, 424, 570, 230], *ap)))


# ---------------------------------------------------------------- page 7
def page07() -> None:
    s = skeleton04("四维自评：对照评分标准")
    dims = [
        ("创新性", "4 / 5", [
            "· 首创口径：把「可拒绝」写成冻结错误码与规则",
            "· 20 类错误码 + 六道门覆盖数值与引用两侧",
            "· RFC 8785 规范化，35 项官方向量自证",
        ]),
        ("实用性", "4 / 5", [
            "· 投稿前自检：引用、数值、快照逐条可核对",
            "· 已有可运行原型：八步链 76 项行为验收",
            "· 真实数据端到端：48 项检查、20 条负例",
        ]),
        ("技术可行性", "4 / 5", [
            "· 七道门禁全绿，冻结前后一致性由机检守护",
            "· 接口按 MCP / Rail 扩展点定型，不改 harness",
            "· 依赖极少：仅 Python 3.12 + jsonschema 4.26",
        ]),
        ("场景价值", "4 / 5", [
            "· 科研赛道：作者、导师、审稿人共用一份证据",
            "· 复现成本从周级降到分钟级（一条命令）",
            "· 同一证据链内核可延展到办公与 Coding",
        ]),
    ]
    parts = []
    for i, (name, score, why) in enumerate(dims):
        x = 40 + (i % 2) * 610
        y = 96 + (i // 2) * 268
        parts.append(group(f"p07-dim-{i+1}", [x, y, 600, 248],
                           panel(x, y, 600, 248),
                           text_el(x + 26, y + 44, [name], fs=20, fill=INK, leading=26, bold=True),
                           text_el(x + 480, y + 46, [score], fs=30, fill=RED, leading=34, bold=True),
                           text_el(x + 26, y + 92, why, fs=13, fill=SUB, leading=22)))
    parts.append(group("p07-note", [40, 630, 1200, 40],
                       text_el(44, 654, ["评分口径：对照赛题四维标准；每项保留 1 分的理由是生产件与评测规模仍待 M3 扩充。"],
                               fs=11.5, fill=SUB, leading=16)))
    save("p07_eval.svg", append_groups(s, *parts))


# ---------------------------------------------------------------- page 8
def page08() -> None:
    s = skeleton03("技术可行性：四层判据与七道门禁", [
        ("方案详情（必填）", '<tspan>四层判据</tspan><tspan fill="#C00000" font-weight="bold">（G1–G4）</tspan>'),
        ("方案优势（可选）", '<tspan>为什么可信</tspan><tspan fill="#C00000" font-weight="bold">（机检）</tspan>'),
        ("技术依赖（可选）", '<tspan>复跑方式</tspan><tspan fill="#C00000" font-weight="bold">（一条）</tspan>'),
    ])
    layers = [
        ("G1 语义层 · 42 断言", "六件 schema 通过 meta-schema、$ref 可达、C4 白名单、六件实例夹具"),
        ("G2 规则层 · 23 断言", "ClaimCard 1.4.0 三条新规则 + 角色词汇（十一角色同源同序）"),
        ("G3 一致性层 · 7 断言", "20 个八步链错误码唯一归属、全大写、链层契约 L1–L5 登记完整"),
        ("G4 确定性层 · 10 断言", "RFC 8785 官方向量与 row_id 派生：同输入必得同 id"),
    ]
    lp = []
    y = 156
    for i, (name, detail) in enumerate(layers):
        lp.append(group(f"p08-layer-{i+1}", [45, y - 26, 590, 62],
                        text_el(48, y, [name], fs=15, fill=RED, leading=21, bold=True),
                        text_el(48, y + 20, [detail], fs=12.5, fill=INK, leading=18)))
        y += 66
    gates = [
        "jcs 35 向量 · gen_composites 2 件 · validate_freeze 82 断言",
        "check_cross_refs 18 · check_docs_consistency 73 · m1_acceptance 76",
        "run_e2e 48 · 七道门禁全绿才允许冻结与发布",
        "版本对偶：文档声明 == schema 文件 == 内嵌引用版本",
        "单一事实源：错误码 freeze_codes.py、视图 gen_docs_views.py",
    ]
    cmd = [
        "$ bash run_gates.sh      # 七道门禁，退出码 0/1/2",
        "$ python demo/run_e2e.py # 真实数据端到端，48 项检查",
        "",
        "环境：Python 3.12+ · jsonschema 4.26.0 · git 2.5x",
        "离线可跑：RFC 8785 快照与 git-log 导出随仓库提交",
    ]
    save("p08_gates.svg", append_groups(
        s, group("p08-layers", [40, 126, 590, 300], *lp),
        group("p08-gates", [45, 452, 575, 190], text_el(48, 486, gates, fs=12.5, fill=INK, leading=24)),
        group("p08-cmd", [655, 452, 580, 190], text_el(658, 486, cmd, fs=12, fill=INK, leading=24))))


# ---------------------------------------------------------------- page 9
def page09() -> None:
    s = skeleton03("落地路线与所需资源", [
        ("方案详情（必填）", '<tspan>三步走</tspan><tspan fill="#C00000" font-weight="bold">（进展）</tspan>'),
        ("方案优势（可选）", '<tspan>为什么可控</tspan>'),
        ("技术依赖（可选）", '<tspan>所需资源与 Demo</tspan>'),
    ])
    route = [
        ("M1 已完成", ["八步链 + 六道门 + 事件签发 + WAL 恢复", "76 项行为验收 · 48 项端到端检查全绿"]),
        ("M3 下一步", ["并发写仲裁 · 远端对象存储 · ledger-mcp 服务化", "fail-closed 与拒绝日志 · 策略热更新"]),
        ("M4 集成上线", ["rail 扩展装进 extensions/ · MCP 注册进 config.yaml", "Auditor 独立进程对账与告警"]),
    ]
    rp = []
    y = 172
    for i, (name, detail) in enumerate(route):
        rp.append(group(f"p09-route-{i+1}", [45, y - 28, 580, 76],
                        text_el(48, y, [name], fs=16, fill=RED, leading=22, bold=True),
                        text_el(48, y + 24, detail, fs=12, fill=INK, leading=18)))
        y += 74
    adv = ["· 验收先行：每一阶段都有可执行检查，不靠口头承诺",
           "· 边界清楚：哪些复用平台件、哪些自研，v27 方案 D28 已写明",
           "· 风险可控：openjiuwen 按 commit 钉住，升级前先跑契约测试"]
    res = ["· 计算：1 台开发机即可复跑全部门禁与演示（无 GPU 依赖）",
           "· 数据：文献全文与快照存储；MANIFEST 元数据仓库",
           "· 人力：算法 1、工程 1、科研领域专家 1（评审口径）",
           "· Demo：本地 CLI + 账本目录，可现场重放与篡改演示"]
    save("p09_route.svg", append_groups(
        s, *rp,
        group("p09-adv", [45, 452, 575, 190], text_el(48, 486, adv, fs=12.5, fill=INK, leading=24)),
        group("p09-res", [655, 452, 580, 190], text_el(658, 486, res, fs=12.5, fill=INK, leading=24))))


# ---------------------------------------------------------------- page 10
def page10() -> None:
    s = skeleton04("材料完整性与参考文档")
    items = [
        ("创意名称", "思解 · 可被验证的科研论文生成系统"),
        ("创意描述", "约 430 字（<500），含问题、机制、编排与目标"),
        ("所属主题", "科研赛道（论文生成与验证）"),
        ("应用场景", "科研团队 / 期刊编辑 / 审稿人；痛点到影响"),
        ("方案详情", "六项核心能力 + 优势 + 技术依赖"),
        ("架构图", "八层总体架构（图见第 4 页）"),
        ("DEMO / 示意", "真实数据端到端，48 项检查全绿（第 6 页）"),
        ("四维评估", "门禁证据（第 8 页）+ 四维自评（第 7 页）"),
    ]
    parts = [text_el(48, 112, ["作品材料 · 必填要素逐项核对"], fs=16, fill=RED, leading=22, bold=True)]
    y = 160
    for k, v in items:
        parts.append(text_el(56, y, ["✓"], fs=15, fill="#2E7D32", leading=20, bold=True))
        parts.append(text_el(80, y, [k], fs=13.5, fill=INK, leading=20, bold=True))
        parts.append(text_el(230, y, [v], fs=13, fill=SUB, leading=19))
        y += 54
    parts.append(text_el(48, 646, ["全部必填要素齐备；页面顺序按评审阅读路径编排。"], fs=11.5, fill=SUB, leading=16))

    refs = [
        ("规范", ["RFC 8785 JSON Canonicalization Scheme", "DOI 10.17487/RFC8785"]),
        ("方案", ["科研智能体总体方案 v27", "D1–D28（含 D28 集成与复用边界）"]),
        ("规格", ["阶段 1 交付物 v1.7.0", "六件 schema 与反例测试规格"]),
        ("实现", ["m1/ 八步链 · m1/rails.py 六道门", "demo/run_e2e.py 端到端"]),
        ("验收", ["七道门禁全绿的 CI 记录", ".github/workflows/gates.yml"]),
        ("仓库", ["github.com/hesheng4/HuaWei", "提交与变更见 CHANGELOG"]),
    ]
    rp = [text_el(700, 112, ["参考文档与可核查入口"], fs=16, fill=RED, leading=22, bold=True)]
    ry = 160
    for k, lines in refs:
        rp.append(text_el(706, ry, [k], fs=12.5, fill=RED, leading=18, bold=True))
        rp.append(text_el(760, ry, lines, fs=12, fill=INK, leading=17))
        ry += 80
    save("p10_material.svg", append_groups(
        s, group("p10-check", [40, 96, 640, 580], *parts),
        group("p10-refs", [690, 96, 560, 580], *rp)))


# ---------------------------------------------------------------- page 11
def page11() -> None:
    # The big "Thank you." is inherited from the layout (layout:4) and may not be
    # edited; keep it and add a quiet footer with the work name and repo.
    s = load("slide_07.svg")
    groups = group(
        "p11-tail", [40, 620, 1000, 60],
        text_el(70, 646, ["思解 SIJIE ｜ 让每一句结论都能被验证 ｜ openJiuwen 智能体创意大赛 · 初赛 · 科研赛道"],
                fs=13, fill=SUB, leading=18),
        text_el(70, 670, ["github.com/hesheng4/HuaWei"], fs=12, fill=SUB, leading=16),
    )
    save("slide_07.svg", append_groups(s, groups))


def main() -> None:
    pristine = BASE / "_pristine"
    for src in sorted(pristine.glob("slide_0*.svg")):
        shutil.copyfile(src, SVG / src.name)
    for src, dst in (("slide_04.svg", "slide_04.svg.bak"), ("slide_03.svg", "slide_03.svg.bak")):
        shutil.copyfile(SVG / src, SVG / dst)
    for fn in (page01, page02, page03, page04, page05,
               page06, page07, page08, page09, page10, page11):
        fn()
    for bak in ("slide_04.svg.bak", "slide_03.svg.bak"):
        (SVG / bak).unlink()
    print("authored:", sorted(p.name for p in SVG.glob("*.svg")))


if __name__ == "__main__":
    main()
