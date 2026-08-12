"""图像编辑意图识别工具。

提供不依赖大模型的轻量规则，用于识别“删除对象”指令、提取删除目标并补充负面词。
这些规则是 Agent 输出之外的安全兜底，避免后续节点重新引入用户明确要求删除的对象。
"""

from __future__ import annotations

import re


REMOVE_MARKERS = ("去掉", "删除", "移除", "删掉", "清除", "消除", "抹除", "不要出现")
CHARACTER_MARKERS = (
    "人物",
    "角色",
    "冒险者",
    "人类",
    "小人",
    "NPC",
    "npc",
    "类人生物",
)


def is_remove_request(request: str) -> bool:
    """判断当前请求是否明确要求删除画面对象。"""

    return any(marker in request for marker in REMOVE_MARKERS)


def extract_removal_target(request: str) -> str:
    """从常见中文表达中提取被删除对象，失败时返回通用描述。"""

    normalized = re.sub(r"\s+", "", request)
    patterns = (
        r"(?:可以|请|麻烦)?(?:将|把)(?P<target>.+?)(?:去掉|删除|移除|删掉|清除|消除|抹除)",
        r"(?:去掉|删除|移除|删掉|清除|消除|抹除)(?P<target>[^，。；！？?]{1,24})",
        r"(?P<target>[^，。；！？?]{1,24})(?:不要出现)",
    )
    for pattern in patterns:
        match = re.search(pattern, normalized, flags=re.IGNORECASE)
        if match:
            target = match.group("target").strip("的这个所有全部")
            if target:
                return target
    return "用户指定对象"


def is_character_target(target: str, request: str = "") -> bool:
    """判断删除目标是否属于人物、角色或类人生物。"""

    text = f"{target} {request}"
    return any(marker.lower() in text.lower() for marker in CHARACTER_MARKERS)


def removal_negative_terms(target: str, request: str = "") -> list[str]:
    """生成删除操作所需的确定性负面词，并保持顺序去重。"""

    terms = [target] if target and target != "用户指定对象" else []
    if is_character_target(target, request):
        terms.extend(
            [
                "人物",
                "角色",
                "冒险者",
                "人类",
                "NPC",
                "类人生物",
                "人物剪影",
                "人物倒影",
                "人物阴影",
            ]
        )
    return list(dict.fromkeys(terms))
