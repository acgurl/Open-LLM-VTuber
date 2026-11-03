"""Slash commands users can send to a connector bot."""

from dataclasses import dataclass

_ALIASES = {
    "bind": "bind",
    "绑定": "bind",
    "unbind": "unbind",
    "解绑": "unbind",
    "new": "new",
    "新对话": "new",
    "help": "help",
    "帮助": "help",
    "whoami": "whoami",
    "我是谁": "whoami",
}


@dataclass(frozen=True)
class Command:
    name: str
    argument: str


def parse_command(text: str) -> Command | None:
    """Return the command in ``text``, or None for an ordinary message.

    Unknown ``/words`` are treated as ordinary messages, so a user can still
    ask about paths or slashes.
    """
    text = text.strip()
    if not text.startswith(("/", "／")):
        return None
    head, _, argument = text[1:].partition(" ")
    name = _ALIASES.get(head.strip().lower())
    if name is None:
        return None
    return Command(name, argument.strip())


def help_text(bound: bool) -> str:
    lines = [
        "可用指令：",
        "/bind 绑定码 — 绑定网页账号",
        "/new — 开始新对话",
        "/whoami — 查看绑定状态",
        "/unbind — 解除绑定",
    ]
    if not bound:
        lines.append("首次使用请先 /bind。")
    return "\n".join(lines)


def unbound_text(web_url: str) -> str:
    where = f"在 {web_url} " if web_url else "在网页端"
    return (
        f"请先绑定账号：{where}用 CUC 校园邮箱登录并生成绑定码，然后发送 /bind 绑定码。"
    )


INELIGIBLE_TEXT = "该网页账号未使用 CUC 校园邮箱登录，无法使用这个机器人。"
BIND_USAGE_TEXT = "用法：/bind 绑定码（在网页端生成）"
BIND_FAILED_TEXT = "绑定码无效或已过期，请在网页端重新生成。"
BIND_LOCKED_TEXT = "尝试次数过多，请 10 分钟后再试。"
BIND_OK_TEXT = "绑定成功，现在可以直接和我对话了。"
UNBIND_OK_TEXT = "已解除绑定。"
NEW_CHAT_TEXT = "已开始新对话。"
BUSY_TEXT = "上一条消息还在处理中，请稍候。"
SERVER_BUSY_TEXT = "当前使用人数较多，请稍后再试。"
RATE_LIMITED_TEXT = "发送太频繁了，请稍后再试。"
TOO_LONG_TEXT = "消息太长了，请精简后再发。"
TIMEOUT_TEXT = "回复超时了，请稍后再试。"
ERROR_TEXT = "出了点问题，暂时无法回复。"
EMPTY_REPLY_TEXT = "（没有生成回复）"
