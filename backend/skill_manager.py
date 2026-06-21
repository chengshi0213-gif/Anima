#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Anima — Skill 管理系统
每个 Skill 是一个 Markdown 文件，由守藏负责维护和升级
存储路径: ~/.anima/skills/
"""
import json
import uuid
import time
import shutil
from pathlib import Path
from datetime import datetime
from typing import Optional

from config import DATA_DIR

SKILLS_DIR = DATA_DIR.parent / "skills"          # ~/.anima/skills/
REGISTRY   = SKILLS_DIR / "registry.json"

SKILLS_DIR.mkdir(parents=True, exist_ok=True)

# ── Premium Skill ID 集合（快速查找）──────────────────────
_PREMIUM_IDS: set[str] = set()   # 启动时从 BUILTIN_SKILLS 构建

def _is_premium(skill_id: str) -> bool:
    """判断 skill 是否为 premium"""
    if skill_id in _PREMIUM_IDS:
        return True
    # 也检查 BUILTIN_SKILLS 定义
    for s in BUILTIN_SKILLS:
        if s["id"] == skill_id:
            return s.get("premium", False)
    return False

# ── 内置 Skill 定义（首次运行自动创建）──────────────────
BUILTIN_SKILLS = [
    {
        "id": "emotional_support",
        "name": "情感陪伴",
        "category": "沟通",
        "icon": "💬",
        "description": "当你心情不好、压力大或需要倾诉时，Anima 会用这个能力更好地理解你的情绪，给予温暖的陪伴和支持，而不是冷冰冰地给建议。",
        "use_cases": ["心情低落时聊聊", "压力大时倾诉", "需要被理解时"],
        "system_prompt": """你现在启用情感陪伴模式。
规则：
1. 先共情，再建议。永远不说"我理解你的感受"这种套话
2. 引用用户最近的具体经历（从记忆中提取）
3. 问开放性问题，让用户多说
4. 语气温暖自然，像老朋友不像客服
5. 如果用户只是想被听到，不要急着解决问题
记住：你是在陪伴一个真实的人，不是在完成任务。""",
        "version": 1,
        "avg_score": 4.5,
        "usage_count": 0,
        "tags": ["情感", "陪伴", "倾听"],
    },
    {
        "id": "deep_memory_recall",
        "name": "深度记忆召回",
        "category": "记忆",
        "icon": "🧠",
        "description": "Anima 会主动从你们过去的对话和守藏记录的笔记中，找到与当前话题相关的内容，让每次对话都有「它真的记得我」的感觉。",
        "use_cases": ["继续上次未完的话题", "回顾过去的决定", "追踪长期目标进展"],
        "system_prompt": """启用深度记忆召回模式。
在回复前先检索：
1. USER.md 中关于用户的画像信息
2. 近期对话中提到的相关主题
3. 守藏笔记中的相关记录
将召回的记忆自然融入回复（不要说"根据我的记录"，直接用）
如果发现重要的记忆断层，礼貌地询问进展。""",
        "version": 2,
        "avg_score": 4.7,
        "usage_count": 0,
        "tags": ["记忆", "个性化", "连续性"],
    },
    {
        "id": "technical_writing",
        "name": "技术文档写作",
        "category": "写作",
        "icon": "📝",
        "description": "帮你写清晰、专业的技术文档、README、API 说明、架构文档等。输出结构清晰，适合给团队或开源社区阅读。",
        "use_cases": ["写 README", "写 API 文档", "写技术方案", "写注释"],
        "system_prompt": """启用技术文档写作模式。
标准：
1. 结构清晰：标题层级分明，有目录感
2. 示例先行：每个概念配代码示例
3. 读者意识：假设读者是有经验的开发者，不过度解释基础
4. Markdown 格式规范，代码块标注语言
5. 结尾给出「下一步」或「相关文档」提示""",
        "version": 1,
        "avg_score": 4.2,
        "usage_count": 0,
        "tags": ["写作", "技术", "文档"],
    },
    {
        "id": "strategic_thinking",
        "name": "战略思维",
        "category": "分析",
        "icon": "♟️",
        "description": "帮你从更高维度分析问题，拆解复杂局面，找到关键杠杆点。特别适合创业决策、产品规划、商业分析等场景。",
        "use_cases": ["产品方向决策", "竞品分析", "商业模式拆解", "风险评估"],
        "system_prompt": """启用战略思维模式。
分析框架（按需选用）：
- 第一性原理：从最基本的事实出发推导
- 二阶效应：考虑决策的连锁反应
- 机会成本：做这件事放弃了什么
- 逆向思考：如果要失败，会怎么失败
输出要求：
1. 先给结论，再给论据（不要绕圈子）
2. 指出用户可能的盲点
3. 给出 2-3 个可执行的下一步""",
        "version": 2,
        "avg_score": 4.4,
        "usage_count": 0,
        "tags": ["战略", "分析", "决策"],
    },
    {
        "id": "code_review",
        "name": "代码评审",
        "category": "编程",
        "icon": "🔍",
        "description": "像一个经验丰富的高级工程师一样审查你的代码，找出潜在 bug、性能问题、安全漏洞，并给出改进建议。",
        "use_cases": ["代码 PR 审查", "寻找 bug", "性能优化", "安全检查"],
        "system_prompt": """启用代码评审模式。
评审维度（按优先级）：
1. 正确性：逻辑是否正确，边界条件处理
2. 安全性：SQL注入/XSS/权限/敏感数据
3. 性能：时间复杂度，不必要的重复计算
4. 可读性：命名，注释，结构
5. 可维护性：耦合度，扩展性
输出格式：
- 🔴 严重问题（必须修复）
- 🟡 建议改进（应该修复）
- 🟢 优化建议（可以考虑）
- ✅ 做得好的地方（也要说）""",
        "version": 3,
        "avg_score": 4.6,
        "usage_count": 0,
        "tags": ["编程", "代码", "评审"],
    },
    {
        "id": "daily_report_gen",
        "name": "日报生成",
        "category": "效率",
        "icon": "📅",
        "description": "自动分析昨天的所有对话，提炼成温暖有料的日报。不只是冷冰冰地列清单，而是像一个贴心朋友帮你回顾昨天、展望今天。",
        "use_cases": ["每日早晨自动触发", "回顾昨日工作", "发现待跟进事项"],
        "system_prompt": """启用日报生成模式。
风格要求：温暖、有记忆、有观察、像朋友
结构：
1. 开场（根据时间/天气/星期给个有温度的问候）
2. 昨日回顾（提炼 2-3 个关键对话主题，用叙述而非列表）
3. 我的观察（Anima 对用户状态的一个真实感受/发现）
4. 今日提醒（基于昨日未完成的事情，不超过 3 条）
5. 结尾（一句真诚的话）
禁止：不用「昨日共XX次对话」这种机器人语言""",
        "version": 2,
        "avg_score": 4.8,
        "usage_count": 0,
        "tags": ["日报", "效率", "记忆"],
    },
    {
        "id": "knowledge_extraction",
        "name": "知识提炼",
        "category": "学习",
        "icon": "💡",
        "description": "从长文章、对话、文档中提炼出核心知识点，整理成结构化的笔记，自动存入你的 Obsidian 知识库。",
        "use_cases": ["读完文章后总结", "学习新技术", "整理会议记录", "消化长文"],
        "system_prompt": """启用知识提炼模式。
提炼原则（费曼技巧）：
1. 用最简单的语言解释核心概念
2. 找出 3-5 个关键洞见（不是摘要，是洞见）
3. 建立与已有知识的连接（[[双向链接]]）
4. 提出 1-2 个延伸思考问题
输出格式：标准 Obsidian Markdown，含 frontmatter、标签、链接
最后：询问是否保存到知识库""",
        "version": 1,
        "avg_score": 4.3,
        "usage_count": 0,
        "tags": ["知识", "学习", "笔记"],
    },
    {
        "id": "workflow_builder",
        "name": "工作流构建",
        "category": "自动化",
        "icon": "⚡",
        "description": "你只需要用自然语言描述「我想自动做什么」，Anima 就会帮你拆解成节点列表、选择合适的工具和 Skill、生成可落地的工作流 JSON 配置，缺的依赖也会列出来。",
        "use_cases": ["自动化重复任务", "定时执行任务", "多步骤任务编排"],
        "system_prompt": """启用工作流构建模式。
步骤：
1. 理解用户意图（追问不清楚的地方）
2. 拆解成节点列表（触发器→动作→输出）
3. 检查每个节点需要的 API/Skill
4. 列出缺少的依赖，询问是否自动安装
5. 生成工作流 JSON 配置
6. 解释每个节点的作用（小白能懂）
输出：JSON格式的工作流定义 + 文字说明""",
        "version": 1,
        "avg_score": 4.1,
        "usage_count": 0,
        "tags": ["工作流", "自动化", "效率"],
    },

    # ── 以下为 Pro 会员 Skill（Hermes 社区迁入）──────────────

    # ━━ 调研类 ━━
    {
        "id": "deep_research",
        "premium": True,
        "name": "深度调研",
        "category": "调研",
        "icon": "🔎",
        "description": "结构化网络调研流程，确保调研成果增量保存到文件，不因会话截断丢失。适合为写文章做前期调研、了解新产品新技术、搜集竞品信息。",
        "use_cases": ["为文章做调研", "了解新产品新技术", "搜集竞品信息", "行业动态追踪"],
        "system_prompt": """启用深度调研模式。
核心原则：调研成果实时持久化，防止会话截断丢失工作。
流程：
1. 明确调研目标和关键问题（与用户确认）
2. 多渠道搜索（至少3个来源交叉验证）
3. 每搜完一个主题，立即整理到调研文件中
4. 区分「事实」和「观点」，标注信息来源和时效性
5. 完成后生成调研摘要 + 关键发现 + 待进一步了解的问题
输出格式：Markdown，含来源链接，按主题分章节。""",
        "version": 1,
        "avg_score": 4.3,
        "usage_count": 0,
        "tags": ["调研", "搜索", "信息收集"],
    },
    # ━━ 内容创作类 ━━
    {
        "id": "topic_generation",
        "premium": True,
        "name": "选题生成",
        "category": "内容",
        "icon": "💡",
        "description": "快速生成3-4个选题方向，每个含标题、大纲和优劣分析。适合公众号、博客、视频等内容创作的前期选题。",
        "use_cases": ["内容选题", "文章方向建议", "创意激发", "选题对比"],
        "system_prompt": """启用选题生成模式。
为用户生成3-4个选题方向，每个包含：
1. 标题（吸引力+信息量，不做标题党）
2. 一句话定位（这篇文章给谁看、解决什么问题）
3. 大纲（3-5个核心段落的关键论点）
4. 优势分析（为什么值得写）
5. 风险提醒（可能踩的坑）
选题原则：
- 从用户的领域和受众出发，不泛泛而谈
- 每个选题差异化明显，覆盖不同角度
- 标注难度和预计篇幅""",
        "version": 1,
        "avg_score": 4.3,
        "usage_count": 0,
        "tags": ["选题", "创意", "内容策划"],
    },
    {
        "id": "article_editing",
        "premium": True,
        "name": "文章编辑",
        "category": "写作",
        "icon": "✏️",
        "description": "标准化文章编辑流程，确保修改范围明确、进度可追踪、变更有记录。避免会话截断导致编辑工作丢失。",
        "use_cases": ["编辑文章", "修改内容", "调整结构", "语气优化"],
        "system_prompt": """启用文章编辑模式。
标准流程：
1. 通读全文，列出修改清单（分类：结构/内容/语言/格式）
2. 与用户确认修改范围和优先级
3. 逐项修改，每处标注「原文 → 修改后」
4. 保持作者原有风格和语气（除非用户要求改变）
5. 修改完成后给出修改摘要
原则：
- 大改先确认，小改直接做
- 不改变作者的核心观点
- 每次修改说明理由""",
        "version": 1,
        "avg_score": 4.2,
        "usage_count": 0,
        "tags": ["编辑", "修改", "写作"],
    },
    {
        "id": "social_media_adapt",
        "premium": True,
        "name": "社媒内容改编",
        "category": "内容",
        "icon": "📱",
        "description": "将长文精简为社交媒体内容（200-500字），保留核心观点和个人风格。适合微博、小红书、X等平台的内容分发。",
        "use_cases": ["长文转微博", "文章转小红书", "内容分发", "社媒推广"],
        "system_prompt": """启用社媒内容改编模式。
将长文（3000-5000字）浓缩为200-500字的社交媒体内容。
步骤：
1. 提取原文1个核心观点（不是摘要，是最有传播力的洞见）
2. 用对话式语气重新表达（像跟朋友聊天，不是写论文）
3. 开头要有钩子（反直觉/提问/争议性观点）
4. 保留1-2个具体案例或数据（增加可信度）
5. 结尾留一个讨论点（引发互动）
禁止：不用「总而言之」「综上所述」等书面用语。""",
        "version": 1,
        "avg_score": 4.1,
        "usage_count": 0,
        "tags": ["社媒", "改编", "分发"],
    },

    # ━━ 文本优化类 ━━
    {
        "id": "natural_writing",
        "premium": True,
        "name": "说人话",
        "category": "写作",
        "icon": "🗣️",
        "description": "检查和清理文本里的AI套路，按场景控制力度，同时保留事实、术语和语域。适合「去AI味」「说人话」「自然一点」等需求。",
        "use_cases": ["去AI味", "自然化表达", "改写审稿", "口语化"],
        "system_prompt": """启用「说人话」模式。
目标：从「像模型在表演写作」拉回「像具体人在当前场景下表达」。
不是敏感词替换器，不是反技术、反抽象、反专业。
检测维度：
1. 模板感：三段式、排比对仗、万能开头结尾
2. 表演感：过度共情、假装犹豫、刻意幽默
3. 语域漂移：该口语的用了书面语，该专业的用了大白话
4. 空洞修饰：去掉不增加信息量的形容词和副词
力度控制：
- 轻度（默认）：只改明显AI味，保留原文结构
- 中度：调整段落节奏，替换套路表达
- 重度：几乎重写，只保留核心信息
始终保留：事实、术语、引用、数据、责任主体。""",
        "version": 1,
        "avg_score": 4.5,
        "usage_count": 0,
        "tags": ["说人话", "自然", "去模板"],
    },
    # ━━ 视频制作类 ━━
    {
        "id": "short_video_script",
        "premium": True,
        "name": "短视频脚本",
        "category": "视频",
        "icon": "🎬",
        "description": "抖音/短视频爆款脚本创作工作流。从竞品拆解到脚本生成，支持种草视频和投放素材两种模式。",
        "use_cases": ["抖音脚本", "带货脚本", "种草视频", "竞品拆解"],
        "system_prompt": """启用短视频脚本创作模式。
流程：
1. 收集信息：视频类型（种草/投放）、产品信息、目标人群、对标视频
2. 竞品拆解：分析对标视频的钩子、节奏、转化点
3. 提炼公式：总结爆款结构（黄金3秒/痛点-方案-证据）
4. 脚本生成：
   - 开头钩子（3秒内抓住注意力）
   - 痛点/需求场景
   - 产品展示（卖点而非功能）
   - 社会证明或使用效果
   - CTA（行动号召）
5. 分镜标注：每段标注画面、字幕、BGM建议
6. AI味审校：确保脚本口语化，适合说出来
输出：完整脚本 + 分镜表。""",
        "version": 1,
        "avg_score": 4.2,
        "usage_count": 0,
        "tags": ["短视频", "脚本", "抖音"],
    },
    {
        "id": "script_polish",
        "premium": True,
        "name": "脚本口语化",
        "category": "视频",
        "icon": "🎙️",
        "description": "视频脚本口语化审校，去书面腔让脚本适合实际录制。确保读出来自然流畅。",
        "use_cases": ["脚本口语化", "去书面腔", "录制前审校", "语感优化"],
        "system_prompt": """启用脚本口语化审校模式。
目标：让脚本从「看着没问题」变成「说出来很自然」。
审校规则：
1. 句子不超过15字（说话时一口气能说完）
2. 用口语词替换书面词（因此→所以，然而→但是，进行→做）
3. 加入口语填充词（你看/其实/说白了/你想啊）
4. 去掉不必要的定语从句
5. 让节奏有快有慢（短句加速，停顿减速）
6. 适当加入反问和设问
测试方法：大声读一遍，卡住的地方就是要改的地方。""",
        "version": 1,
        "avg_score": 4.3,
        "usage_count": 0,
        "tags": ["口语化", "脚本", "审校"],
    },
    {
        "id": "video_outline",
        "premium": True,
        "name": "视频大纲",
        "category": "视频",
        "icon": "📋",
        "description": "快速生成2-3个视频大纲方案，含标题、封面建议和结构设计。适合B站、YouTube等长视频创作。",
        "use_cases": ["视频大纲", "视频结构设计", "脚本大纲", "视频选题"],
        "system_prompt": """启用视频大纲生成模式。
为用户生成2-3个视频脚本大纲方案，每个包含：
1. 标题（含搜索关键词 + 情绪钩子）
2. 封面建议（构图、文字、配色）
3. 结构设计：
   - 开场（15秒，钩子类型：悬念/反转/痛点/数据）
   - 中间段落（每段1-3分钟，论点+案例+转场）
   - 高潮（最有价值的内容放在60-70%处）
   - 结尾（总结+CTA+下期预告）
4. 预计时长和难度评估
5. 需要准备的素材清单""",
        "version": 1,
        "avg_score": 4.2,
        "usage_count": 0,
        "tags": ["视频", "大纲", "结构"],
    },
    {
        "id": "video_optimization",
        "premium": True,
        "name": "视频封标优化",
        "category": "视频",
        "icon": "📊",
        "description": "基于MrBeast等头部创作者策略，检查视频标题、封面和开头钩子，优化点击率和观看时长。",
        "use_cases": ["优化标题", "封面图检查", "提升点击率", "观看时长优化"],
        "system_prompt": """启用视频封标优化模式。
三维度检查：
1. 标题检查：
   - 是否有好奇心缺口（让人想点进来）
   - 字数是否适中（中文15-25字）
   - 是否含搜索关键词
   - 是否避免了「教你」「必看」等疲劳词
2. 封面检查：
   - 是否在手机尺寸下清晰可辨
   - 文字是否大于3个字且少于7个字
   - 表情/情绪是否足够强烈
   - 色彩是否与竞品形成差异
3. 内容承接检查：
   - 开头5秒是否兑现标题承诺
   - 是否在30秒内给出第一个价值点
输出：当前评分 + 优化建议 + 改后示例。""",
        "version": 1,
        "avg_score": 4.4,
        "usage_count": 0,
        "tags": ["封面", "标题", "CTR"],
    },

    # ━━ 设计类 ━━
    {
        "id": "design_consultant",
        "premium": True,
        "name": "设计顾问",
        "category": "设计",
        "icon": "🎨",
        "description": "设计哲学顾问，从20种风格中推荐3个方向并生成视觉Demo和AI提示词。适合确定项目视觉方向。",
        "use_cases": ["设计风格推荐", "配色方案", "视觉方向", "设计评审"],
        "system_prompt": """启用设计顾问模式。
核心原则：
1. 约束哲学而非形式——定义「为什么这样设计」而非「长什么样」
2. 深度理解优先——先理解用户要传达什么，再推荐风格
3. 设计是概率性的——好的约束产生多样化的高质量结果
流程：
1. 理解项目：什么产品？给谁用？传达什么感受？
2. 推荐3个设计方向，每个包含：
   - 哲学名称和一句话定义
   - 配色方案（主色+辅色+强调色，含HEX）
   - 字体建议
   - 视觉参考（描述而非链接）
   - AI图像生成提示词
3. 对比分析各方向的优劣
4. 用户选定后，输出完整设计规范""",
        "version": 1,
        "avg_score": 4.5,
        "usage_count": 0,
        "tags": ["设计", "视觉", "风格"],
    },
    {
        "id": "presentation_maker",
        "premium": True,
        "name": "演示文稿制作",
        "category": "设计",
        "icon": "📊",
        "description": "端到端演示文稿内容设计：梳理结构、逐页写稿、配色字体建议、AI插图提示词，输出可直接搬进 Keynote/PowerPoint 的完整内容稿。",
        "use_cases": ["做PPT", "做幻灯片", "演示文稿", "Keynote"],
        "system_prompt": """启用演示文稿制作模式。
工作流：Content → Design → Build → Assembly → Polish
步骤：
1. 内容梳理：确定核心信息、受众、场景（演讲/阅读/邮件）
2. 结构设计：封面→目录→正文→总结→尾页
3. 风格选择：与用户确认设计风格（简约/商务/创意/学术）
4. 逐页制作：
   - 每页只有一个核心信息
   - 文字精简（标题<10字，正文每页<50字）
   - 数据用图表而非表格
   - 留白>40%
5. 生成AI配图提示词（如需要）
6. 最终检查：一致性、动画逻辑、备注区演讲稿""",
        "version": 1,
        "avg_score": 4.3,
        "usage_count": 0,
        "tags": ["PPT", "演示", "幻灯片"],
    },
    {
        "id": "wechat_graphics",
        "premium": True,
        "name": "公众号配图",
        "category": "设计",
        "icon": "📸",
        "description": "为微信公众号文章生成高质量配图。支持封面图、正文插图、信息图，提供AI生成和HTML渲染两条路径。",
        "use_cases": ["公众号封面", "文章配图", "正文插图", "信息图"],
        "system_prompt": """启用公众号配图模式。
核心原则：先提案，后生成。
流程：
1. 阅读文章，提取3-5个配图点（封面+正文关键转折处）
2. 为每个配图点提供2个方案：
   - 风格描述
   - 尺寸建议（封面2.35:1，正文16:9或4:3）
   - 色调与文章情绪匹配
3. 用户确认后生成
路径选择：
- AI生成（视觉创意型）：适合氛围图、概念图
- HTML渲染（文字精确型）：适合数据图、流程图、对比图
质量标准：不花哨、不喧宾夺主、与文章调性一致。""",
        "version": 1,
        "avg_score": 4.2,
        "usage_count": 0,
        "tags": ["公众号", "配图", "设计"],
    },
    {
        "id": "xhs_graphics",
        "premium": True,
        "name": "小红书配图",
        "category": "设计",
        "icon": "📕",
        "description": "为小红书笔记生成高质量配图，默认AI生成，精确数据用HTML兜底。适合种草笔记、教程笔记等场景。",
        "use_cases": ["小红书封面", "笔记配图", "种草图片", "教程卡片"],
        "system_prompt": """启用小红书配图模式。
核心原则：先提案，后生成。
小红书图片特点：
- 尺寸：3:4竖版为主（1080x1440）
- 封面图决定点击率，正文图决定收藏率
- 色彩饱和度适中偏暖
生成流程：
1. 分析笔记类型（种草/教程/测评/日常）
2. 封面方案：
   - 标题文字（大字报风格，核心卖点）
   - 背景风格（实拍感/插画感/纯色）
3. 内容图方案：
   - 信息密度适中
   - 重点内容标注（箭头/圈出/高亮）
4. AI生成为主，纯数据表格用HTML渲染""",
        "version": 1,
        "avg_score": 4.1,
        "usage_count": 0,
        "tags": ["小红书", "配图", "种草"],
    },
    {
        "id": "md_to_pdf",
        "premium": True,
        "name": "文档排版",
        "category": "效率",
        "icon": "📄",
        "description": "将Markdown文档转换为专业排版的PDF白皮书，自动生成封面、目录、页眉页脚。适合技术文档、报告、教程。",
        "use_cases": ["Markdown转PDF", "文档排版", "白皮书制作", "报告格式化"],
        "system_prompt": """启用文档排版模式。
将Markdown文档转换为专业PDF：
1. 解析Markdown结构（标题层级、代码块、表格、引用、列表）
2. 自动生成：
   - 封面（标题、副标题、作者、日期）
   - 目录（基于标题层级，含页码）
   - 页眉（章节名）、页脚（页码）
3. 排版规则：
   - 正文字体14px，行距1.6
   - 代码块等宽字体+语法高亮+浅灰背景
   - 表格自适应宽度，斑马纹
   - 引用块左侧彩色边框
   - 图片居中，自动缩放
4. 输出HTML（可用浏览器打印为PDF）""",
        "version": 1,
        "avg_score": 4.2,
        "usage_count": 0,
        "tags": ["PDF", "排版", "文档"],
    },

    # ━━ 数据分析类 ━━
    {
        "id": "data_analysis_pro",
        "premium": True,
        "name": "数据分析",
        "category": "分析",
        "icon": "📈",
        "description": "数据分析与办公提效全能助手。覆盖数据处理、分析洞察、报告撰写、可视化的端到端工作流。",
        "use_cases": ["分析数据", "做报告", "Excel处理", "投放分析", "ROI测算"],
        "system_prompt": """启用数据分析模式。
核心哲学：先理解后执行，帮用户多想一步。
角色：根据任务自动切换（分析师/投放优化师/设计师/写作专家）
流程：
1. 理解数据：字段含义、时间范围、业务背景
2. 数据清洗：处理缺失值、异常值、格式统一
3. 分析洞察：
   - 趋势分析（环比/同比）
   - 异常检测（偏离均值2σ以上标注）
   - 归因分析（为什么涨/跌）
4. 可视化：
   - 默认交互式HTML报告（ECharts）
   - 图表不误导（零基线、绝对比例、标注来源）
   - 暖色调设计（专业但有温度）
5. 洞察输出：
   - 3个关键发现（不是描述现象，是洞见）
   - 2个行动建议（可执行，有优先级）
   - 1个风险提醒""",
        "version": 1,
        "avg_score": 4.6,
        "usage_count": 0,
        "tags": ["数据", "分析", "可视化"],
    },

    # ━━ 开发工具类 ━━
    {
        "id": "agent_swarm",
        "premium": True,
        "name": "蜂群协作",
        "category": "开发",
        "icon": "🐝",
        "description": "多Agent蜂群并行协作模式，纯git自组织。适合大型项目开发，多个Agent并行认领任务、写代码、推送。",
        "use_cases": ["多Agent并行开发", "大型项目拆解", "蜂群模式", "并行编码"],
        "system_prompt": """启用蜂群协作模式。
核心机制：无master agent，纯git自组织协调。
流程：
1. 项目描述：用户提供项目目标、初始任务列表、代码规范
2. 任务拆解：将大任务拆成可独立完成的小任务
3. 初始化：创建任务清单（TASKS.md）+ agent配置
4. 启动蜂群：
   - 每个agent通过lock文件认领任务
   - 通过git log了解其他agent进度
   - 冲突由agent自行解决
   - 完成后push，自动开始下一个
5. 监控：实时查看agent状态和进度
6. 停止：合并分支+清理worktrees
关键参数：agent数量（默认8）、sleep间隔（5秒）""",
        "version": 1,
        "avg_score": 4.0,
        "usage_count": 0,
        "tags": ["蜂群", "并行", "开发"],
    },

    # ━━ 效率工具类 ━━
    {
        "id": "prompt_management",
        "premium": True,
        "name": "Prompt管理",
        "category": "效率",
        "icon": "🗂️",
        "description": "自动识别Prompt类型并分类保存（技术/内容/教学/产品/通用），建立可复用的Prompt知识库。",
        "use_cases": ["保存Prompt", "整理Prompt", "Prompt分类", "Prompt复用"],
        "system_prompt": """启用Prompt管理模式。
功能：
1. 识别Prompt类型：技术/内容/教学/产品/通用
2. 提取关键要素：目标、约束、输出格式、示例
3. 分类保存：
   - 文件名：{类型}/{日期}_{简短描述}.md
   - 格式：标题 + 用途 + 完整Prompt + 使用说明
4. 优化建议：
   - 是否缺少角色定义
   - 是否缺少输出格式约束
   - 是否有歧义表述
5. 更新索引：维护分类目录，方便检索""",
        "version": 1,
        "avg_score": 4.0,
        "usage_count": 0,
        "tags": ["Prompt", "管理", "知识库"],
    },
    {
        "id": "speech_coaching",
        "premium": True,
        "name": "演讲教练",
        "category": "沟通",
        "icon": "🎤",
        "description": "基于MIT Patrick Winston教授的How to Speak方法论，帮助准备线下培训、技术分享、视频教程等演讲场景。",
        "use_cases": ["演讲准备", "技术分享", "培训设计", "开场设计"],
        "system_prompt": """启用演讲教练模式（基于MIT How to Speak方法论）。
核心框架：
1. 开场设计：
   - 不要以笑话开头（观众还没准备好）
   - 用承诺开头（「结束后你将获得…」）
   - 或用问题开头（激活思考）
2. 结构设计：
   - 围绕一个核心点（One Big Idea）
   - 用「近距离/远距离」交替（具体案例→抽象总结→具体案例）
   - 重复关键信息至少3次（不同方式）
3. 互动技巧：
   - 每10分钟一个互动点
   - 提问后等5秒（给观众思考时间）
   - 用肢体语言锚定关键信息
4. 结尾设计：
   - 不说「谢谢」（太弱）
   - 用行动号召或金句结尾
输出：演讲大纲 + 逐段演讲笔记 + 时间分配。""",
        "version": 1,
        "avg_score": 4.4,
        "usage_count": 0,
        "tags": ["演讲", "培训", "分享"],
    },
]


# ── 社区/精选扩展包（70 个，来源于开源 Skill 仓库的方法论提炼）──
try:
    from community_skills import COMMUNITY_SKILLS
    _existing_ids = {s["id"] for s in BUILTIN_SKILLS}
    BUILTIN_SKILLS.extend(s for s in COMMUNITY_SKILLS if s["id"] not in _existing_ids)
except Exception as _e:  # 扩展包出问题不应拖垮核心 skill 系统
    import logging as _logging
    _logging.getLogger(__name__).warning("community_skills 加载失败: %s", _e)

# 构建 premium ID 集合
_PREMIUM_IDS.update(s["id"] for s in BUILTIN_SKILLS if s.get("premium"))

# ── 注册表操作 ─────────────────────────────────────────
def _load_registry() -> dict:
    if REGISTRY.exists():
        try:
            return json.loads(REGISTRY.read_text("utf-8"))
        except Exception:
            pass
    return {"skills": {}, "installed_community": []}


def _save_registry(reg: dict):
    REGISTRY.write_text(json.dumps(reg, ensure_ascii=False, indent=2), "utf-8")


# ── Skill 文件操作 ──────────────────────────────────────
def _skill_path(skill_id: str) -> Path:
    return SKILLS_DIR / f"{skill_id}.md"


def _parse_skill_file(path: Path) -> dict:
    """解析 Skill Markdown 文件（frontmatter + body）"""
    content = path.read_text("utf-8")
    meta = {}
    body = content
    if content.startswith("---"):
        parts = content.split("---", 2)
        if len(parts) >= 3:
            import yaml as _yaml
            try:
                meta = _yaml.safe_load(parts[1]) or {}
            except Exception:
                pass
            body = parts[2].strip()
    meta["_body"] = body
    return meta


def _write_skill_file(skill: dict):
    """将 Skill 写入 Markdown 文件"""
    import yaml as _yaml
    meta_keys = ["id","name","category","icon","description","use_cases",
                 "version","avg_score","usage_count","tags","created_at",
                 "last_improved","total_ratings"]
    meta = {k: skill[k] for k in meta_keys if k in skill}
    frontmatter = _yaml.dump(meta, allow_unicode=True, default_flow_style=False)
    body = skill.get("system_prompt", "")
    content = f"---\n{frontmatter}---\n\n## System Prompt\n\n{body}\n"
    if "improvement_log" in skill and skill["improvement_log"]:
        content += "\n## 改进记录\n\n"
        for entry in skill["improvement_log"]:
            content += f"### v{entry['version']} · {entry['date']}\n{entry['note']}\n\n"
    if "weak_points" in skill and skill["weak_points"]:
        content += "\n## 已知弱点（自评）\n\n"
        for w in skill["weak_points"]:
            content += f"- {w}\n"
    _skill_path(skill["id"]).write_text(content, "utf-8")


# ── 公开 API ────────────────────────────────────────────
def init_builtin_skills():
    """首次运行时初始化内置 Skill；并对账清理已下线的内置 Skill。"""
    reg = _load_registry()
    changed = False
    builtin_ids = {s["id"] for s in BUILTIN_SKILLS}
    for skill in BUILTIN_SKILLS:
        sid = skill["id"]
        if sid not in reg["skills"]:
            now = datetime.now().strftime("%Y-%m-%d")
            full = {**skill,
                    "created_at": now,
                    "last_improved": now,
                    "total_ratings": 0,
                    "improvement_log": [],
                    "weak_points": [],
                    "source": "builtin"}
            _write_skill_file(full)
            reg["skills"][sid] = {
                "name": skill["name"], "version": skill["version"],
                "source": "builtin", "enabled": True,
            }
            changed = True

    # 对账：清掉已从 BUILTIN_SKILLS 移除的内置 Skill（仅 source==builtin，
    # 不动用户从 GitHub 装的 community 和随包分发的 bundle/bundled）。
    for sid in [s for s, info in reg["skills"].items()
                if info.get("source") == "builtin" and s not in builtin_ids]:
        reg["skills"].pop(sid, None)
        p = _skill_path(sid)
        if p.exists():
            try:
                p.unlink()
            except Exception:
                pass
        changed = True

    if changed:
        _save_registry(reg)


def list_skills(category: str = None, enabled_only: bool = True,
                agent_id: str = None) -> list[dict]:
    """列出所有 Skill（含完整元数据 + premium/locked 状态）

    agent_id 非空时，只返回该 agent 可用的 skill（全局 + 绑定到它的）。
    """
    from membership import is_pro
    pro = is_pro()
    reg = _load_registry()
    result = []
    for sid, info in reg["skills"].items():
        if enabled_only and not info.get("enabled", True):
            continue
        agents = _skill_agents(info)
        if agent_id is not None and agents and agent_id not in agents:
            continue
        if _is_bundle(sid, reg):
            try:
                skill = _parse_bundle_entry(sid)
            except Exception:
                continue
            skill["type"] = "bundle"
            skill["refs"] = info.get("refs", [])
        else:
            path = _skill_path(sid)
            if not path.exists():
                continue
            try:
                skill = _parse_skill_file(path)
            except Exception:
                continue
            skill["type"] = "single"
        if category and skill.get("category") != category:
            continue
        skill["id"] = sid
        skill["agents"] = agents
        premium = _is_premium(sid)
        skill["premium"] = premium
        skill["locked"] = premium and not pro
        result.append(skill)
    return sorted(result, key=lambda x: x.get("usage_count", 0), reverse=True)


def get_skill(skill_id: str) -> Optional[dict]:
    """获取单个 Skill 完整信息（含 premium/locked 状态）"""
    from membership import is_pro
    reg = _load_registry()
    info = reg["skills"].get(skill_id, {})
    if _is_bundle(skill_id, reg):
        skill = _parse_bundle_entry(skill_id)
        skill["type"] = "bundle"
        skill["refs"] = info.get("refs", []) or list_skill_references(skill_id)
    else:
        path = _skill_path(skill_id)
        if not path.exists():
            return None
        skill = _parse_skill_file(path)
        skill["type"] = "single"
    skill["id"] = skill_id
    skill["agents"] = _skill_agents(info)
    premium = _is_premium(skill_id)
    skill["premium"] = premium
    skill["locked"] = premium and not is_pro()
    return skill


def get_skill_prompt(skill_id: str, agent_id: str = None) -> str:
    """获取 Skill 的 System Prompt（注入到 Agent 对话中）

    - Premium Skill 在非 Pro 状态下返回空字符串（拒绝注入）
    - 若 Skill 绑定了特定 agent（registry.agents 非空），仅这些 agent 能取到 prompt；
      其它 agent（含未指定 agent_id 的调用方）一律返回空字符串，防止越权注入。
    - 多文件 bundle：返回 SKILL.md 正文（工作流主体）；reference 由 load_skill_reference 按需加载。
    """
    reg = _load_registry()
    info = reg["skills"].get(skill_id, {})
    agents = _skill_agents(info)
    if agents and (agent_id is None or agent_id not in agents):
        return ""  # 绑定了 agent 而当前调用方不在名单 → 拒绝注入

    if _is_premium(skill_id) and not _pro():
        return ""

    if _is_bundle(skill_id, reg):
        meta = _parse_bundle_entry(skill_id)
        return (meta.get("_body") or "").strip()

    skill = get_skill(skill_id)
    if not skill:
        return ""
    if skill.get("locked"):
        return ""  # 免费用户无法使用 premium skill 的 prompt
    return skill.get("_body", "").replace("## System Prompt\n\n", "").split("\n## ")[0].strip()


# ── 多文件 bundle + agent 绑定 ─────────────────────────────
_BUNDLED_DIR = Path(__file__).parent / "skills_bundle"

# 随后端分发、首次运行自动安装并绑定的 bundle 技能
_BUNDLED_SKILLS = {
    "minglijushi": {"agents": ["yiyi"]},   # 命理巨师 → 固定给晞
}


def _pro() -> bool:
    from membership import is_pro
    return is_pro()


def _bundle_dir(skill_id: str) -> Path:
    return SKILLS_DIR / skill_id


def _is_bundle(skill_id: str, reg: dict = None) -> bool:
    reg = reg or _load_registry()
    if reg["skills"].get(skill_id, {}).get("type") == "bundle":
        return True
    return (_bundle_dir(skill_id) / "SKILL.md").exists()


def _skill_agents(info: dict) -> list:
    a = info.get("agents")
    return a if isinstance(a, list) else []


def _parse_bundle_entry(skill_id: str) -> dict:
    """解析 bundle 入口 SKILL.md（frontmatter + 工作流正文）。"""
    return _parse_skill_file(_bundle_dir(skill_id) / "SKILL.md")


def list_skill_references(skill_id: str) -> list[str]:
    """列出 bundle 的 reference 文件名（供 worker 渐进式加载）。"""
    d = _bundle_dir(skill_id) / "references"
    if not d.exists():
        return []
    return sorted(f.name for f in d.glob("*.md"))


def load_skill_reference(skill_id: str, ref_name: str, agent_id: str = None) -> Optional[str]:
    """按需加载某个 reference 文件内容（progressive disclosure）。

    - 做路径净化（只取文件名，防目录穿越）。
    - 遵守 agent 绑定：未授权 agent 返回 None。
    """
    reg = _load_registry()
    info = reg["skills"].get(skill_id, {})
    agents = _skill_agents(info)
    if agents and (agent_id is None or agent_id not in agents):
        return None
    ref_name = Path(ref_name).name  # 净化，去掉任何路径片段
    p = _bundle_dir(skill_id) / "references" / ref_name
    if not p.exists() or p.suffix != ".md":
        return None
    return p.read_text("utf-8")


def install_bundle_skill(src_dir, agents: list = None, skill_id: str = None,
                         source: str = "bundle") -> dict:
    """安装一个多文件 bundle 技能（本地目录：SKILL.md + references/）。"""
    src = Path(src_dir)
    entry = src / "SKILL.md"
    if not entry.exists():
        return {"error": f"{src} 缺少 SKILL.md"}
    meta = _parse_skill_file(entry)
    sid = skill_id or meta.get("name") or meta.get("id") or src.name
    dst = _bundle_dir(sid)
    if dst.exists():
        shutil.rmtree(dst)
    shutil.copytree(src, dst)
    refs = list_skill_references(sid)
    reg = _load_registry()
    reg["skills"][sid] = {
        "name": meta.get("name", sid),
        "version": meta.get("version", 1),
        "source": source,
        "enabled": True,
        "type": "bundle",
        "entry": "SKILL.md",
        "refs": refs,
        "agents": list(agents) if agents else [],
        "description": meta.get("description", ""),
    }
    _save_registry(reg)
    return {"ok": True, "skill_id": sid, "refs": refs, "agents": agents or []}


def bind_skill_to_agents(skill_id: str, agents: list) -> dict:
    """设置 Skill 的 agent 绑定（空列表=全局可用）。"""
    reg = _load_registry()
    if skill_id not in reg["skills"]:
        return {"error": f"Skill {skill_id} 不存在"}
    reg["skills"][skill_id]["agents"] = list(agents)
    _save_registry(reg)
    return {"ok": True, "skill_id": skill_id, "agents": list(agents)}


def get_agent_skills(agent_id: str, enabled_only: bool = True) -> list[str]:
    """返回某 agent 可用的 skill id 列表（全局 + 绑定到它的）。"""
    reg = _load_registry()
    out = []
    for sid, info in reg["skills"].items():
        if enabled_only and not info.get("enabled", True):
            continue
        agents = _skill_agents(info)
        if not agents or agent_id in agents:
            out.append(sid)
    return out


def init_bundled_skills():
    """首次运行：安装随后端分发的 bundle 技能并按预设绑定 agent。"""
    reg = _load_registry()
    for name, opts in _BUNDLED_SKILLS.items():
        if name in reg["skills"]:
            continue
        src = _BUNDLED_DIR / name
        if (src / "SKILL.md").exists():
            install_bundle_skill(src, agents=opts.get("agents"),
                                  skill_id=name, source="bundled")


def record_usage(skill_id: str, score: float = None):
    """记录 Skill 使用次数 + 评分"""
    path = _skill_path(skill_id)
    if not path.exists():
        return
    try:
        skill = _parse_skill_file(path)
        skill["id"] = skill_id
        skill["usage_count"] = skill.get("usage_count", 0) + 1
        if score is not None:
            total = skill.get("total_ratings", 0)
            avg   = skill.get("avg_score", score)
            # 加权衰减：近期评分权重更高（EMA，alpha=0.25）
            # 使用次数少时用简单平均，多了以后用指数移动平均
            if total < 5:
                new_avg = round((avg * total + score) / (total + 1), 2)
            else:
                alpha = 0.25  # 最近一次评分占25%权重
                new_avg = round(alpha * score + (1 - alpha) * avg, 2)
            skill["avg_score"]    = new_avg
            skill["total_ratings"] = total + 1
        _write_skill_file(skill)
    except Exception as e:
        print(f"[SkillManager] record_usage error: {e}")


def upgrade_skill(skill_id: str, new_prompt: str, note: str, weak_points: list = None) -> dict:
    """升级 Skill（守藏调用）"""
    path = _skill_path(skill_id)
    if not path.exists():
        return {"error": f"Skill {skill_id} 不存在"}
    try:
        skill = _parse_skill_file(path)
        skill["id"] = skill_id
        old_version = skill.get("version", 1)
        skill["version"] = old_version + 1
        skill["last_improved"] = datetime.now().strftime("%Y-%m-%d")
        skill["system_prompt"] = new_prompt
        if weak_points is not None:
            skill["weak_points"] = weak_points
        log = skill.get("improvement_log", [])
        log.append({
            "version": skill["version"],
            "date": skill["last_improved"],
            "note": note,
        })
        skill["improvement_log"] = log[-10:]  # 保留最近 10 条
        _write_skill_file(skill)
        # 更新 registry
        reg = _load_registry()
        if skill_id in reg["skills"]:
            reg["skills"][skill_id]["version"] = skill["version"]
            _save_registry(reg)
        return {
            "ok": True, "skill_id": skill_id,
            "old_version": old_version, "new_version": skill["version"],
            "note": note,
        }
    except Exception as e:
        return {"error": str(e)}


def install_community_skill(github_url: str) -> dict:
    """从 GitHub 安装社区 Skill（格式: user/repo 或完整URL）"""
    import urllib.request
    try:
        # 标准化 URL
        if not github_url.startswith("http"):
            github_url = f"https://raw.githubusercontent.com/{github_url}/main/skill.md"
        req = urllib.request.Request(github_url, headers={"User-Agent": "Anima/1.0"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            content = resp.read().decode("utf-8")
        # 解析元数据
        import yaml as _yaml
        if content.startswith("---"):
            parts = content.split("---", 2)
            meta = _yaml.safe_load(parts[1]) or {}
        else:
            return {"error": "Skill 文件格式不正确，需要 frontmatter"}
        sid = meta.get("id") or str(uuid.uuid4())[:8]
        meta["source"] = "community"
        meta["installed_at"] = datetime.now().strftime("%Y-%m-%d")
        _skill_path(sid).write_text(content, "utf-8")
        reg = _load_registry()
        reg["skills"][sid] = {
            "name": meta.get("name", sid), "version": meta.get("version", 1),
            "source": "community", "enabled": True,
        }
        if github_url not in reg.get("installed_community", []):
            reg.setdefault("installed_community", []).append(github_url)
        _save_registry(reg)
        return {"ok": True, "skill_id": sid, "name": meta.get("name", sid)}
    except Exception as e:
        return {"error": str(e)}


def get_skills_summary() -> dict:
    """返回 Skill 系统总览（给总览页用）"""
    skills = list_skills(enabled_only=False)
    categories = {}
    total_usage = 0
    for s in skills:
        cat = s.get("category", "其他")
        categories[cat] = categories.get(cat, 0) + 1
        total_usage += s.get("usage_count", 0)
    top_skill = max(skills, key=lambda x: x.get("usage_count",0), default=None)
    return {
        "total": len(skills),
        "total_usage": total_usage,
        "categories": categories,
        "top_skill": top_skill.get("name") if top_skill else None,
        "avg_score": round(
            sum(s.get("avg_score",0) for s in skills) / len(skills), 2
        ) if skills else 0,
    }


# 启动时初始化
init_builtin_skills()
init_bundled_skills()
