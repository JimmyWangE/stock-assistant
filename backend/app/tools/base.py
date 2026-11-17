from dataclasses import dataclass, field


class ToolError(Exception):
    """工具无法给出结果时抛出；消息会原样交给模型，由模型向用户说明。"""


@dataclass
class ToolResult:
    # 交给模型阅读的文字，要精简：模型上下文有限
    text: str
    # 交给页面直接展示的内容（图表、表格），不经过模型
    blocks: list[dict] = field(default_factory=list)
