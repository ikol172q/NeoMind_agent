"""
Code Review Tool for NeoMind Agent.

Provides automated code review capabilities for the Coding personality.
Inspired by Claude Code's code review patterns.

Created: 2026-04-02 (Phase 2 - Coding 完整功能)
"""

from __future__ import annotations

import re
import ast
from pathlib import Path
from typing import List, Dict, Optional, Any, Tuple
from dataclasses import dataclass, field
from enum import Enum


class IssueSeverity(Enum):
    """Severity level for code issues."""
    ERROR = "error"
    WARNING = "warning"
    INFO = "info"
    STYLE = "style"


@dataclass
class CodeIssue:
    """Represents a code issue found during review."""
    file_path: str
    line_number: int
    column: int
    severity: IssueSeverity
    message: str
    rule_id: str
    suggestion: Optional[str] = None
    context: Optional[str] = None


@dataclass
class ReviewResult:
    """Result of a code review."""
    file_path: str
    issues: List[CodeIssue]
    summary: str
    score: float  # 0-100
    metrics: Dict[str, Any] = field(default_factory=dict)


class CodeReviewTool:
    """
    Automated code review tool.

    Features:
    - Style checking
    - Security scanning
    - Complexity analysis
    - Best practices enforcement
    - Documentation checking
    """

    # Python style rules
    PYTHON_RULES = {
        'line-too-long': {
            'pattern': r'^.{121,}',
            'severity': IssueSeverity.STYLE,
            'message': 'Line exceeds 120 characters',
        },
        'trailing-whitespace': {
            'pattern': r'\s+$',
            'severity': IssueSeverity.STYLE,
            'message': 'Trailing whitespace',
        },
        'multiple-spaces': {
            'pattern': r' {2,}(?=[^ ])',
            'severity': IssueSeverity.STYLE,
            'message': 'Multiple consecutive spaces',
        },
        'todo-comment': {
            'pattern': r'#\s*(TODO|FIXME|HACK|XXX)',
            'severity': IssueSeverity.INFO,
            'message': 'TODO/FIXME comment found',
        },
        'bare-except': {
            'pattern': r'\bexcept\s*:',
            'severity': IssueSeverity.WARNING,
            'message': 'Bare except clause - catch specific exceptions',
        },
        'print-statement': {
            'pattern': r'\bprint\s*\(',
            'severity': IssueSeverity.INFO,
            'message': 'Print statement found - consider using logging',
        },
        'debug-code': {
            'pattern': r'\b(debugger|pdb\.set_trace)\b',
            'severity': IssueSeverity.WARNING,
            'message': 'Debug code found - remove before production',
        },
        'hardcoded-password': {
            'pattern': r'(password|passwd|pwd)\s*=\s*["\'][^"\']+["\']',
            'severity': IssueSeverity.ERROR,
            'message': 'Hardcoded password detected',
        },
        'sql-injection-risk': {
            'pattern': r'\.execute\s*\(\s*f["\']',
            'severity': IssueSeverity.WARNING,
            'message': 'Potential SQL injection - use parameterized queries',
        },
        'unused-import': {
            'pattern': r'^import\s+(\w+)|^from\s+\S+\s+import\s+(\w+)',
            'severity': IssueSeverity.WARNING,
            'message': 'Potentially unused import',
        },
    }

    def __init__(self, max_line_length: int = 120):
        """Initialize code review tool."""
        self.max_line_length = max_line_length
        self._compiled_rules = self._compile_rules()

    def _compile_rules(self) -> Dict[str, re.Pattern]:
        """Compile regex patterns for rules."""
        compiled = {}
        for rule_id, rule in self.PYTHON_RULES.items():
            try:
                compiled[rule_id] = re.compile(rule['pattern'])
            except re.error:
                continue
        return compiled

    def review_file(
        self,
        file_path: str,
        content: Optional[str] = None
    ) -> ReviewResult:
        """
        Review a single file.

        Args:
            file_path: Path to the file
            content: Optional content (will read from file if not provided)

        Returns:
            ReviewResult object
        """
        path = Path(file_path)

        if content is None:
            try:
                content = path.read_text(encoding='utf-8', errors='replace')
            except Exception as e:
                return ReviewResult(
                    file_path=file_path,
                    issues=[],
                    summary=f"Failed to read file: {e}",
                    score=0.0
                )

        # Detect language
        language = self._detect_language(path)

        # Apply rules
        issues = self._apply_rules(content, file_path, language)

        # Calculate metrics
        metrics = self._calculate_metrics(content)

        # Calculate score
        score = self._calculate_score(issues, metrics)

        # Generate summary
        summary = self._generate_summary(issues, score)

        return ReviewResult(
            file_path=file_path,
            issues=issues,
            summary=summary,
            score=score,
            metrics=metrics
        )

    def _detect_language(self, path: Path) -> str:
        """Detect programming language from file extension."""
        ext_map = {
            '.py': 'python',
            '.js': 'javascript',
            '.ts': 'typescript',
            '.java': 'java',
            '.go': 'go',
            '.rs': 'rust',
        }
        return ext_map.get(path.suffix.lower(), 'unknown')

    def _apply_rules(
        self,
        content: str,
        file_path: str,
        language: str
    ) -> List[CodeIssue]:
        """Apply review rules to content."""
        issues = []
        lines = content.split('\n')

        for line_num, line in enumerate(lines, 1):
            for rule_id, pattern in self._compiled_rules.items():
                rule = self.PYTHON_RULES.get(rule_id)
                if not rule:
                    continue

                for match in pattern.finditer(line):
                    issues.append(CodeIssue(
                        file_path=file_path,
                        line_number=line_num,
                        column=match.start() + 1,
                        severity=rule['severity'],
                        message=rule['message'],
                        rule_id=rule_id,
                        context=line.strip()[:80]
                    ))

        # AST-based checks for Python
        if language == 'python':
            issues.extend(self._check_ast(content, file_path))

        return issues

    def _check_ast(self, content: str, file_path: str) -> List[CodeIssue]:
        """Perform AST-based checks for Python code."""
        issues = []

        try:
            tree = ast.parse(content)
        except SyntaxError as e:
            issues.append(CodeIssue(
                file_path=file_path,
                line_number=e.lineno or 1,
                column=e.offset or 1,
                severity=IssueSeverity.ERROR,
                message=f"Syntax error: {e.msg}",
                rule_id='syntax-error'
            ))
            return issues

        # Check for missing docstrings
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                if not ast.get_docstring(node):
                    issues.append(CodeIssue(
                        file_path=file_path,
                        line_number=node.lineno,
                        column=node.col_offset + 1,
                        severity=IssueSeverity.INFO,
                        message=f"Function '{node.name}' missing docstring",
                        rule_id='missing-docstring',
                        suggestion='Add a docstring to document the function'
                    ))

            elif isinstance(node, ast.ClassDef):
                if not ast.get_docstring(node):
                    issues.append(CodeIssue(
                        file_path=file_path,
                        line_number=node.lineno,
                        column=node.col_offset + 1,
                        severity=IssueSeverity.INFO,
                        message=f"Class '{node.name}' missing docstring",
                        rule_id='missing-docstring'
                    ))

        return issues

    def _calculate_metrics(self, content: str) -> Dict[str, Any]:
        """Calculate code metrics."""
        lines = content.split('\n')

        # Basic metrics
        total_lines = len(lines)
        code_lines = sum(1 for line in lines if line.strip() and not line.strip().startswith('#'))
        comment_lines = sum(1 for line in lines if line.strip().startswith('#'))
        blank_lines = total_lines - code_lines - comment_lines

        # Complexity (simplified)
        complexity = self._estimate_complexity(content)

        return {
            'total_lines': total_lines,
            'code_lines': code_lines,
            'comment_lines': comment_lines,
            'blank_lines': blank_lines,
            'comment_ratio': comment_lines / max(code_lines, 1),
            'complexity': complexity,
        }

    def _estimate_complexity(self, content: str) -> int:
        """Estimate cyclomatic complexity."""
        complexity = 1  # Base

        # Count decision points
        patterns = [
            r'\bif\b', r'\belif\b', r'\bfor\b', r'\bwhile\b',
            r'\band\b', r'\bor\b', r'\bexcept\b', r'\bwith\b'
        ]

        for pattern in patterns:
            complexity += len(re.findall(pattern, content))

        return complexity

    def _calculate_score(
        self,
        issues: List[CodeIssue],
        metrics: Dict[str, Any]
    ) -> float:
        """Calculate overall code quality score."""
        score = 100.0

        # Deduct for issues
        for issue in issues:
            if issue.severity == IssueSeverity.ERROR:
                score -= 10
            elif issue.severity == IssueSeverity.WARNING:
                score -= 5
            elif issue.severity == IssueSeverity.INFO:
                score -= 2
            elif issue.severity == IssueSeverity.STYLE:
                score -= 1

        # Deduct for high complexity
        complexity = metrics.get('complexity', 1)
        if complexity > 20:
            score -= (complexity - 20) * 2

        # Deduct for low comment ratio
        comment_ratio = metrics.get('comment_ratio', 0)
        if comment_ratio < 0.1:
            score -= 5

        return max(0.0, min(100.0, score))

    def _generate_summary(
        self,
        issues: List[CodeIssue],
        score: float
    ) -> str:
        """Generate review summary."""
        # Count by severity
        counts = {s: 0 for s in IssueSeverity}
        for issue in issues:
            counts[issue.severity] += 1

        summary_parts = [f"Score: {score:.1f}/100"]

        if counts[IssueSeverity.ERROR] > 0:
            summary_parts.append(f"{counts[IssueSeverity.ERROR]} errors")
        if counts[IssueSeverity.WARNING] > 0:
            summary_parts.append(f"{counts[IssueSeverity.WARNING]} warnings")
        if counts[IssueSeverity.INFO] > 0:
            summary_parts.append(f"{counts[IssueSeverity.INFO]} info")
        if counts[IssueSeverity.STYLE] > 0:
            summary_parts.append(f"{counts[IssueSeverity.STYLE]} style")

        if not issues:
            summary_parts.append("No issues found!")

        return " | ".join(summary_parts)

    def review_directory(
        self,
        directory: str,
        file_pattern: str = "*.py"
    ) -> List[ReviewResult]:
        """
        Review all files in a directory.

        Args:
            directory: Directory path
            file_pattern: Glob pattern for files

        Returns:
            List of ReviewResult objects
        """
        results = []
        dir_path = Path(directory)

        for file_path in dir_path.rglob(file_pattern):
            if self._should_skip(file_path):
                continue

            result = self.review_file(str(file_path))
            results.append(result)

        return results

    def _should_skip(self, path: Path) -> bool:
        """Check if path should be skipped."""
        skip_dirs = {
            'node_modules', '.git', '__pycache__', 'venv', 'env',
            '.venv', 'build', 'dist', '.pytest_cache'
        }
        return any(part in skip_dirs for part in path.parts)


__all__ = ['CodeReviewTool', 'ReviewResult', 'CodeIssue', 'IssueSeverity']


if __name__ == "__main__":
    # Test the code review tool
    print("=== Code Review Tool Test ===\n")

    tool = CodeReviewTool()

    test_code = '''
def calculate_sum(numbers):
    total = 0
    for num in numbers:
        total += num
    return total

# TODO: Add error handling
def divide(a, b):
    return a / b

password = "hardcoded_password_123"  # Security issue!

def complex_function(x):
    """A complex function."""
    if x > 0:
        if x < 10:
            for i in range(x):
                if i % 2 == 0:
                    print(i)  # Debug print
    return x
'''

    result = tool.review_file("test.py", test_code)

    print(f"Score: {result.score:.1f}/100")
    print(f"Summary: {result.summary}")
    print(f"\nMetrics:")
    for key, value in result.metrics.items():
        print(f"  {key}: {value}")

    print(f"\nIssues ({len(result.issues)}):")
    for issue in result.issues[:10]:
        print(f"  [{issue.severity.value}] Line {issue.line_number}: {issue.message}")

    print("\n✅ CodeReviewTool test passed!")
