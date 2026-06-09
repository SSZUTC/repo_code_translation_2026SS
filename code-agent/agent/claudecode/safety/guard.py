"""安全审查系统 - High-Risk Operation Guard

复现 Claude Code 的核心安全机制：
- 对高风险操作（文件删除、破坏性 bash 命令等）发出警告并请求用户确认
- 在工具调用前进行安全审查
- 支持白名单/黑名单命令
- 支持多种确认模式（interactive / auto_deny / auto_allow）
"""
import re
from dataclasses import dataclass, field
from typing import List, Callable, Optional
from enum import Enum

from utils.logger import get_logger

logger = get_logger()


class RiskLevel(str, Enum):
    """风险级别"""
    SAFE = "safe"           # 安全操作
    LOW = "low"             # 低风险（如只读操作）
    MEDIUM = "medium"       # 中等风险（如修改代码）
    HIGH = "high"           # 高风险（如 rm -rf、大规模写入）
    CRITICAL = "critical"   # 极端风险（如格式化磁盘、系统级配置）


class ConfirmationMode(str, Enum):
    """确认模式"""
    INTERACTIVE = "interactive"   # 交互式询问用户（默认）
    AUTO_ALLOW = "auto_allow"     # 自动允许（生产环境慎用）
    AUTO_DENY = "auto_deny"       # 自动拒绝（最安全模式）


@dataclass
class RiskAssessment:
    """风险评估结果"""
    level: RiskLevel
    reasons: List[str] = field(default_factory=list)
    suggestions: List[str] = field(default_factory=list)
    blocked: bool = False

    def is_high_risk(self) -> bool:
        return self.level in (RiskLevel.HIGH, RiskLevel.CRITICAL)

    def to_dict(self):
        return {
            "level": self.level.value,
            "reasons": self.reasons,
            "suggestions": self.suggestions,
            "blocked": self.blocked
        }


# ============================================================
# 命令审查规则库
# ============================================================

# 绝对禁止的命令（无条件阻止）
BLOCKED_COMMANDS = [
    (r'\b(rm|del)\s+.*-.*[rfR]\b', RiskLevel.CRITICAL, "递归强制删除（rm -rf）"),
    (r'\bdd\s+if=.*of=', RiskLevel.CRITICAL, "dd 原始磁盘写入"),
    (r'\bmkfs\b', RiskLevel.CRITICAL, "文件系统格式化"),
    (r'\bshred\b', RiskLevel.CRITICAL, "shred 不可恢复删除"),
    (r':\s*>\s*', RiskLevel.HIGH, "文件清空 (: > file)"),
    (r'\bchmod\s+.*[+-]?[0-7]+', RiskLevel.HIGH, "修改文件权限"),
    (r'\bchown\s+-R', RiskLevel.HIGH, "递归修改文件所有权"),
    (r'\bsudo\b', RiskLevel.HIGH, "sudo 管理员权限操作"),
    (r'\b(pip|conda|npm|yarn|brew)\s+install\s+(-y|--yes|--force)', RiskLevel.HIGH, "带强制标志的包安装"),
    (r'\bapt-get\s+.*-y', RiskLevel.HIGH, "apt-get -y 自动安装"),
    (r'>\s*[~\/].*\.(bashrc|bash_profile|zshrc|profile)', RiskLevel.HIGH, "覆盖 shell 配置"),
    (r'\bgit\s+push', RiskLevel.MEDIUM, "git push 远程仓库写入"),
    (r'\bgit\s+commit', RiskLevel.MEDIUM, "git commit 仓库提交"),
]

# 高风险命令（需要用户确认）
HIGH_RISK_COMMANDS = [
    (r'\b(rm|del)\b', RiskLevel.HIGH, "文件删除操作"),
    (r'\bmv\b.*>|\bmv\b\s+\S+\s+/', RiskLevel.HIGH, "移动覆盖关键位置"),
    (r'\b(sed|awk)\s+.*-i\b', RiskLevel.MEDIUM, "原地文件修改 (sed -i)"),
    (r'\bpkill\b|\bkill\s+(-9)?', RiskLevel.HIGH, "进程强制终止"),
    (r'\bwget\b|\bcurl\b.*\|\s*(sh|bash)', RiskLevel.HIGH, "远程脚本管道执行"),
    (r'\bcurl\s+.*--insecure', RiskLevel.MEDIUM, "不安全的 HTTPS 请求"),
]

# 只读/安全命令（白名单）
SAFE_COMMANDS = [
    r'\bls\b', r'\bcat\b', r'\bhead\b', r'\btail\b', r'\bless\b', r'\bfind\b.*-name',
    r'\bgrep\b', r'\bwc\b', r'\bpwd\b', r'\becho\b', r'\bfile\b', r'\bstat\b',
    r'\bgit\s+status', r'\bgit\s+log', r'\bgit\s+diff', r'\bgit\s+show',
    r'\bpython\s+.*--version', r'\bwhich\b',
]

# 文件操作审查 - 禁止写的关键文件
BLOCKED_FILE_PATTERNS = [
    (r'(/etc|/system|C:\\Windows|/usr/bin)', RiskLevel.CRITICAL, "系统目录"),
    (r'\.(bashrc|bash_profile|zshrc|profile|ssh/authorized_keys)$', RiskLevel.HIGH, "系统配置文件"),
]

# 敏感路径 - 需要用户确认
SENSITIVE_FILE_PATTERNS = [
    r'\.env', r'\.pem$', r'\.key$', r'id_rsa', r'config\.yaml',
    r'aws', r'credentials', r'secret', r'token', r'\.env\.',
]


class SafetyGuard:
    """Claude Code 风格的安全审查器

    在每次工具调用前运行审查，判断是否需要用户确认或直接阻止。
    """

    def __init__(
        self,
        confirm_mode: ConfirmationMode = ConfirmationMode.INTERACTIVE,
        working_dir: Optional[str] = None,
        on_risk_callback: Optional[Callable[[str, RiskAssessment], bool]] = None,
    ):
        """
        Args:
            confirm_mode: 确认模式
            working_dir: 工作目录（用于路径审查）
            on_risk_callback: 自定义回调，返回 True 表示允许继续
        """
        self.confirm_mode = confirm_mode
        self.working_dir = working_dir
        self._on_risk_callback = on_risk_callback
        self.confirmation_history: List[dict] = []

    # ============================================================
    # 主入口
    # ============================================================

    def assess_bash_command(self, command: str) -> RiskAssessment:
        """审查 Bash 命令"""
        assessment = RiskAssessment(level=RiskLevel.LOW)
        command_lower = command.lower().strip()

        # 1. 检查绝对禁止命令
        for pattern, level, reason in BLOCKED_COMMANDS:
            if re.search(pattern, command_lower):
                assessment.level = level
                assessment.reasons.append(reason)
                assessment.blocked = True
                assessment.suggestions.append(
                    f"⚠️  该操作被禁止（{level.value}）。"
                )
                return assessment

        # 2. 检查高风险命令
        for pattern, level, reason in HIGH_RISK_COMMANDS:
            if re.search(pattern, command_lower):
                if assessment.level != RiskLevel.CRITICAL:
                    assessment.level = max(
                        [assessment.level, level],
                        key=lambda l: [RiskLevel.SAFE, RiskLevel.LOW,
                                       RiskLevel.MEDIUM, RiskLevel.HIGH,
                                       RiskLevel.CRITICAL].index(l)
                    )
                assessment.reasons.append(reason)
                assessment.suggestions.append(
                    f"⚠️  检测到高风险操作：{reason}。请确认是否继续。"
                )

        # 3. 检查是否为只读命令
        is_safe = any(re.search(p, command_lower) for p in SAFE_COMMANDS)
        if is_safe and not assessment.reasons:
            assessment.level = RiskLevel.SAFE

        return assessment

    def assess_file_write(self, file_path: str, content: str = "") -> RiskAssessment:
        """审查文件写入操作"""
        assessment = RiskAssessment(level=RiskLevel.MEDIUM)
        file_path = file_path.lower()

        # 1. 检查系统目录
        for pattern, level, reason in BLOCKED_FILE_PATTERNS:
            if re.search(pattern, file_path):
                assessment.level = level
                assessment.reasons.append(reason)
                assessment.blocked = True
                return assessment

        # 2. 检查敏感文件
        for pattern in SENSITIVE_FILE_PATTERNS:
            if re.search(pattern, file_path):
                assessment.level = RiskLevel.HIGH
                assessment.reasons.append(f"尝试修改敏感文件: {file_path}")
                assessment.suggestions.append(
                    "⚠️  该文件包含敏感信息，修改前请确认。"
                )

        # 3. 检查内容中的敏感信息
        sensitive_keywords = ['api_key', 'password', 'secret', 'token', 'AKIA']
        for kw in sensitive_keywords:
            if kw.lower() in content.lower():
                assessment.level = max(
                    [assessment.level, RiskLevel.HIGH],
                    key=lambda l: [RiskLevel.SAFE, RiskLevel.LOW,
                                   RiskLevel.MEDIUM, RiskLevel.HIGH,
                                   RiskLevel.CRITICAL].index(l)
                )
                assessment.reasons.append(f"内容包含敏感关键词: {kw}")

        return assessment

    # ============================================================
    # 确认流程
    # ============================================================

    def requires_confirmation(self, assessment: RiskAssessment) -> bool:
        """是否需要用户确认"""
        return assessment.is_high_risk() and not assessment.blocked

    def handle_risk(
        self,
        tool_name: str,
        tool_input: str,
        assessment: RiskAssessment
    ) -> tuple[bool, str]:
        """处理风险判断

        Returns:
            (allowed, message): 是否允许执行，以及反馈信息
        """
        # 记录到历史
        self.confirmation_history.append({
            "tool": tool_name,
            "input": tool_input[:200],
            "level": assessment.level.value,
            "reasons": assessment.reasons
        })

        # 被禁止
        if assessment.blocked:
            msg = f"🚫 操作被拒绝：{', '.join(assessment.reasons)}"
            logger.warning(msg)
            return False, msg

        # 无需确认
        if not self.requires_confirmation(assessment):
            return True, ""

        # 需要确认
        if self.confirm_mode == ConfirmationMode.AUTO_DENY:
            msg = f"🚫 [AUTO_DENY] 高风险操作被自动拒绝：{', '.join(assessment.reasons)}"
            logger.warning(msg)
            return False, msg

        if self.confirm_mode == ConfirmationMode.AUTO_ALLOW:
            msg = f"⚠️  [AUTO_ALLOW] 高风险操作被自动允许：{', '.join(assessment.reasons)}"
            logger.warning(msg)
            return True, msg

        # INTERACTIVE 模式
        if self._on_risk_callback:
            return self._on_risk_callback(tool_input, assessment)

        return self._interactive_confirm(tool_name, tool_input, assessment)

    def _interactive_confirm(
        self,
        tool_name: str,
        tool_input: str,
        assessment: RiskAssessment
    ) -> tuple[bool, str]:
        """交互式确认 - 打印警告并等待用户输入"""
        print("\n" + "=" * 80)
        print(f"⚠️  高风险操作检测 - {tool_name}")
        print("=" * 80)
        print(f"操作内容: {tool_input[:300]}")
        print(f"风险等级: {assessment.level.value.upper()}")
        if assessment.reasons:
            print("原因:")
            for r in assessment.reasons:
                print(f"  - {r}")
        if assessment.suggestions:
            print("建议:")
            for s in assessment.suggestions:
                print(f"  - {s}")
        print("=" * 80)

        # 在非交互式管道环境下，默认拒绝
        try:
            answer = input("是否继续执行? [y/N]: ").strip().lower()
        except EOFError:
            return False, "非交互式环境，高风险操作被拒绝"

        if answer in ('y', 'yes'):
            print("✅ 用户已确认，继续执行...\n")
            return True, "用户确认执行"
        print("❌ 用户拒绝执行\n")
        return False, "用户拒绝执行"

    # ============================================================
    # 工具方法
    # ============================================================

    def wrap_bash_tool(self, original_func):
        """包装 Bash 工具函数，在执行前进行安全审查"""
        def wrapped(command: str) -> str:
            assessment = self.assess_bash_command(command)
            allowed, msg = self.handle_risk("bash_execute", command, assessment)
            if not allowed:
                return f"[SAFETY GUARD] {msg}"
            return original_func(command)
        return wrapped

    def wrap_edit_tool(self, original_func):
        """包装 Edit 工具函数"""
        def wrapped(args_str: str) -> str:
            # 从输入中提取文件路径
            try:
                parts = args_str.strip().strip('"').strip("'").split("|", 2)
                if len(parts) >= 1:
                    file_path = parts[0].strip()
                    replacement = parts[2] if len(parts) >= 3 else ""
                    assessment = self.assess_file_write(file_path, replacement)
                    allowed, msg = self.handle_risk("edit_file", args_str, assessment)
                    if not allowed:
                        return f"[SAFETY GUARD] {msg}"
            except Exception:
                pass
            return original_func(args_str)
        return wrapped

    def get_history(self, limit: int = 20) -> list:
        """获取最近的审查历史"""
        return self.confirmation_history[-limit:]

    def summary(self) -> dict:
        """获取审查统计摘要"""
        total = len(self.confirmation_history)
        blocked = sum(1 for h in self.confirmation_history if any(
            r in ("CRITICAL", "HIGH") for r in [h["level"].upper()]
        ))
        return {
            "total_checks": total,
            "high_risk_count": blocked,
            "confirm_mode": self.confirm_mode.value,
        }
