"""
Optional Services for NeoMind Agent.

Implements P2-P3 priority services:
- OAuthService: OAuth 2.0 authentication flows
- VoiceService: Voice input/output (text-to-speech, speech-to-text stubs)
- PromptSuggestionService: Intelligent prompt suggestions
- MagicDocsService: Auto documentation generation

Created: 2026-04-02
"""

from __future__ import annotations
import os, json, hashlib, time, re
from dataclasses import dataclass, field
from typing import List, Dict, Optional, Any
from pathlib import Path

__all__ = [
    "OAuthToken",
    "OAuthService",
    "VoiceResult",
    "VoiceService",
    "SuggestionResult",
    "PromptSuggestionService",
    "DocResult",
    "MagicDocsService",
]


# ═══════════════════════════════════════════════════════════════════════════════
# Data classes
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass
class OAuthToken:
    """Represents an OAuth 2.0 token."""
    access_token: str
    token_type: str = "Bearer"
    expires_in: int = 3600
    refresh_token: Optional[str] = None
    scope: Optional[str] = None
    obtained_at: float = field(default_factory=time.time)

    @property
    def is_expired(self) -> bool:
        return time.time() > (self.obtained_at + self.expires_in - 60)


@dataclass
class OAuthProvider:
    """Registered OAuth provider configuration."""
    name: str
    client_id: str
    client_secret: str
    auth_url: str
    token_url: str
    scopes: List[str] = field(default_factory=list)


@dataclass
class VoiceResult:
    """Result from voice operations."""
    success: bool
    message: str = ""
    error: Optional[str] = None
    audio_path: Optional[str] = None
    text: Optional[str] = None


@dataclass
class SuggestionResult:
    """Result from prompt suggestion."""
    success: bool
    suggestions: List[str] = field(default_factory=list)
    message: str = ""
    error: Optional[str] = None


@dataclass
class DocResult:
    """Result from documentation generation."""
    success: bool
    content: str = ""
    output_path: Optional[str] = None
    message: str = ""
    error: Optional[str] = None


# ═══════════════════════════════════════════════════════════════════════════════
# OAuthService
# ═══════════════════════════════════════════════════════════════════════════════

class OAuthService:
    """OAuth 2.0 authentication flow manager."""

    def __init__(self, config_path: Optional[str] = None):
        self.config_path = Path(config_path or os.path.expanduser("~/.neomind/oauth"))
        self.config_path.mkdir(parents=True, exist_ok=True)
        self._tokens: Dict[str, OAuthToken] = {}
        self._providers: Dict[str, OAuthProvider] = {}
        self._load_providers()

    # ── persistence ──

    def _providers_file(self) -> Path:
        return self.config_path / "providers.json"

    def _tokens_file(self) -> Path:
        return self.config_path / "tokens.json"

    def _load_providers(self) -> None:
        pf = self._providers_file()
        if pf.exists():
            try:
                data = json.loads(pf.read_text())
                for name, cfg in data.items():
                    self._providers[name] = OAuthProvider(**cfg)
            except (json.JSONDecodeError, TypeError):
                pass
        tf = self._tokens_file()
        if tf.exists():
            try:
                data = json.loads(tf.read_text())
                for name, tok in data.items():
                    self._tokens[name] = OAuthToken(**tok)
            except (json.JSONDecodeError, TypeError):
                pass

    def _save_providers(self) -> None:
        data = {}
        for name, p in self._providers.items():
            data[name] = {
                "name": p.name,
                "client_id": p.client_id,
                "client_secret": p.client_secret,
                "auth_url": p.auth_url,
                "token_url": p.token_url,
                "scopes": p.scopes,
            }
        self._providers_file().write_text(json.dumps(data, indent=2))

    def _save_tokens(self) -> None:
        data = {}
        for name, t in self._tokens.items():
            data[name] = {
                "access_token": t.access_token,
                "token_type": t.token_type,
                "expires_in": t.expires_in,
                "refresh_token": t.refresh_token,
                "scope": t.scope,
                "obtained_at": t.obtained_at,
            }
        self._tokens_file().write_text(json.dumps(data, indent=2))

    # ── public API ──

    def register_provider(
        self,
        name: str,
        client_id: str,
        client_secret: str,
        auth_url: str,
        token_url: str,
        scopes: Optional[List[str]] = None,
    ) -> None:
        """Register an OAuth provider."""
        self._providers[name] = OAuthProvider(
            name=name,
            client_id=client_id,
            client_secret=client_secret,
            auth_url=auth_url,
            token_url=token_url,
            scopes=scopes or [],
        )
        self._save_providers()

    def get_auth_url(
        self,
        provider_name: str,
        redirect_uri: str = "http://localhost:8080/callback",
    ) -> str:
        """Build the authorization URL the user should visit."""
        provider = self._providers.get(provider_name)
        if not provider:
            raise ValueError(f"Unknown provider: {provider_name}")
        state = hashlib.sha256(f"{provider_name}{time.time()}".encode()).hexdigest()[:16]
        import urllib.parse
        params = urllib.parse.urlencode({
            "client_id": provider.client_id,
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "scope": " ".join(provider.scopes),
            "state": state,
        })
        return f"{provider.auth_url}?{params}"

    def exchange_code(
        self,
        provider_name: str,
        code: str,
        redirect_uri: str = "http://localhost:8080/callback",
    ) -> OAuthToken:
        """Exchange an authorization code for an access token."""
        provider = self._providers.get(provider_name)
        if not provider:
            raise ValueError(f"Unknown provider: {provider_name}")

        import urllib.request
        import urllib.parse

        data = urllib.parse.urlencode({
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": redirect_uri,
            "client_id": provider.client_id,
            "client_secret": provider.client_secret,
        }).encode()

        req = urllib.request.Request(
            provider.token_url,
            data=data,
            headers={"Accept": "application/json", "Content-Type": "application/x-www-form-urlencoded"},
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            body = json.loads(resp.read().decode())

        token = OAuthToken(
            access_token=body["access_token"],
            token_type=body.get("token_type", "Bearer"),
            expires_in=int(body.get("expires_in", 3600)),
            refresh_token=body.get("refresh_token"),
            scope=body.get("scope"),
        )
        self._tokens[provider_name] = token
        self._save_tokens()
        return token

    def get_token(self, provider_name: str) -> Optional[OAuthToken]:
        """Return the stored token for a provider, or None."""
        return self._tokens.get(provider_name)

    def refresh_token(self, provider_name: str) -> OAuthToken:
        """Refresh an expired token using the stored refresh_token."""
        token = self._tokens.get(provider_name)
        if not token or not token.refresh_token:
            raise ValueError(f"No refresh token available for {provider_name}")
        provider = self._providers.get(provider_name)
        if not provider:
            raise ValueError(f"Unknown provider: {provider_name}")

        import urllib.request
        import urllib.parse

        data = urllib.parse.urlencode({
            "grant_type": "refresh_token",
            "refresh_token": token.refresh_token,
            "client_id": provider.client_id,
            "client_secret": provider.client_secret,
        }).encode()

        req = urllib.request.Request(
            provider.token_url,
            data=data,
            headers={"Accept": "application/json", "Content-Type": "application/x-www-form-urlencoded"},
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            body = json.loads(resp.read().decode())

        new_token = OAuthToken(
            access_token=body["access_token"],
            token_type=body.get("token_type", "Bearer"),
            expires_in=int(body.get("expires_in", 3600)),
            refresh_token=body.get("refresh_token", token.refresh_token),
            scope=body.get("scope", token.scope),
        )
        self._tokens[provider_name] = new_token
        self._save_tokens()
        return new_token

    def revoke_token(self, provider_name: str) -> None:
        """Remove the stored token for a provider."""
        self._tokens.pop(provider_name, None)
        self._save_tokens()

    def list_providers(self) -> List[str]:
        """Return names of all registered providers."""
        return list(self._providers.keys())


# ═══════════════════════════════════════════════════════════════════════════════
# VoiceService
# ═══════════════════════════════════════════════════════════════════════════════

class VoiceService:
    """Voice input/output service."""

    def __init__(self) -> None:
        self._engine: Optional[str] = self._detect_engine()

    def _detect_engine(self) -> Optional[str]:
        """Detect available TTS engine."""
        import shutil
        if shutil.which("say"):
            return "say"
        if shutil.which("espeak"):
            return "espeak"
        return None

    def is_available(self) -> bool:
        """Check whether a TTS engine is available on this system."""
        return self._engine is not None

    def text_to_speech(self, text: str, output_path: Optional[str] = None) -> VoiceResult:
        """Convert text to speech audio.

        If *output_path* is given the audio is saved to that file (AIFF on
        macOS via ``say``, WAV via ``espeak``).  Otherwise the audio is
        played through the default output device.
        """
        if not self._engine:
            return VoiceResult(
                success=False,
                error="No TTS engine found. Install 'say' (macOS) or 'espeak' (Linux).",
            )

        import subprocess

        try:
            if self._engine == "say":
                cmd = ["say", text]
                if output_path:
                    cmd.extend(["-o", output_path])
            else:  # espeak
                cmd = ["espeak", text]
                if output_path:
                    cmd.extend(["-w", output_path])

            subprocess.run(cmd, check=True, capture_output=True, timeout=60)
            return VoiceResult(
                success=True,
                message="Speech synthesis complete.",
                audio_path=output_path,
            )
        except subprocess.TimeoutExpired:
            return VoiceResult(success=False, error="TTS timed out after 60 seconds.")
        except subprocess.CalledProcessError as exc:
            return VoiceResult(success=False, error=f"TTS failed: {exc.stderr.decode(errors='replace')}")
        except Exception as exc:
            return VoiceResult(success=False, error=str(exc))

    def speech_to_text(self, audio_path: str) -> VoiceResult:
        """Convert speech audio to text (stub).

        Full implementation requires an external API such as OpenAI Whisper.
        """
        return VoiceResult(
            success=False,
            error="Speech-to-text requires external API (Whisper, etc.). Not yet implemented.",
        )


# ═══════════════════════════════════════════════════════════════════════════════
# PromptSuggestionService
# ═══════════════════════════════════════════════════════════════════════════════

class PromptSuggestionService:
    """Suggest prompts based on context and history."""

    def __init__(self) -> None:
        self._history: List[str] = []
        self._templates: Dict[str, List[str]] = {
            "chat": [
                "Explain the concept of {topic}",
                "Compare {a} and {b}",
                "Summarize the following text",
                "What is {topic}?",
                "Give me pros and cons of {topic}",
                "How does {topic} work?",
                "What are the best practices for {topic}?",
            ],
            "coding": [
                "Fix the bug in {file}",
                "Refactor {component} for readability",
                "Add tests for {module}",
                "Explain this code: {snippet}",
                "Optimize the performance of {function}",
                "Convert this code to use async/await",
                "Add type hints to {file}",
                "Write a docstring for {function}",
            ],
            "finance": [
                "Analyze stock {ticker}",
                "Compare portfolios: {a} vs {b}",
                "What's the risk of investing in {asset}?",
                "Backtest strategy: {description}",
                "Summarize earnings for {company}",
                "Calculate the Sharpe ratio for {portfolio}",
                "What are the top movers today?",
            ],
        }

    def suggest(
        self,
        mode: str = "chat",
        context: str = "",
        count: int = 5,
    ) -> SuggestionResult:
        """Return relevant prompt suggestions.

        Suggestions are drawn from templates for the given *mode* and ranked
        by keyword overlap with *context*.
        """
        templates = list(self._templates.get(mode, self._templates["chat"]))

        # If context provided, score templates by keyword overlap
        if context:
            keywords = set(re.findall(r"\w+", context.lower()))

            def _score(template: str) -> int:
                words = set(re.findall(r"\w+", template.lower()))
                return len(words & keywords)

            templates.sort(key=_score, reverse=True)

        # Supplement with history-based suggestions
        history_suggestions: List[str] = []
        if self._history:
            for past in reversed(self._history[-20:]):
                if past not in templates and past not in history_suggestions:
                    history_suggestions.append(f"(recent) {past}")
                if len(history_suggestions) >= 2:
                    break

        combined = templates[:count] + history_suggestions
        return SuggestionResult(
            success=True,
            suggestions=combined[:count],
            message=f"{len(combined[:count])} suggestions for mode '{mode}'",
        )

    def add_template(self, mode: str, template: str) -> None:
        """Add a custom template to a mode."""
        self._templates.setdefault(mode, []).append(template)

    def record_usage(self, prompt: str) -> None:
        """Record a prompt that was actually used, for future suggestions."""
        self._history.append(prompt)
        # Keep history bounded
        if len(self._history) > 500:
            self._history = self._history[-250:]


# ═══════════════════════════════════════════════════════════════════════════════
# MagicDocsService
# ═══════════════════════════════════════════════════════════════════════════════

class MagicDocsService:
    """Auto-generate documentation from code."""

    def __init__(self, working_dir: Optional[str] = None) -> None:
        self.working_dir = working_dir or os.getcwd()

    # ── internal helpers ──

    def _parse_python_file(self, path: str) -> Dict[str, Any]:
        """Use the ``ast`` module to extract classes, functions, and docstrings."""
        import ast

        source = Path(path).read_text(encoding="utf-8")
        tree = ast.parse(source, filename=path)

        module_doc = ast.get_docstring(tree)
        classes: List[Dict[str, Any]] = []
        functions: List[Dict[str, Any]] = []

        for node in ast.iter_child_nodes(tree):
            if isinstance(node, ast.ClassDef):
                methods: List[Dict[str, Any]] = []
                for item in node.body:
                    if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        methods.append({
                            "name": item.name,
                            "args": self._format_args(item.args),
                            "returns": self._format_annotation(item.returns),
                            "docstring": ast.get_docstring(item),
                            "is_async": isinstance(item, ast.AsyncFunctionDef),
                            "lineno": item.lineno,
                        })
                classes.append({
                    "name": node.name,
                    "bases": [self._format_annotation(b) for b in node.bases],
                    "docstring": ast.get_docstring(node),
                    "methods": methods,
                    "lineno": node.lineno,
                })
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                functions.append({
                    "name": node.name,
                    "args": self._format_args(node.args),
                    "returns": self._format_annotation(node.returns),
                    "docstring": ast.get_docstring(node),
                    "is_async": isinstance(node, ast.AsyncFunctionDef),
                    "lineno": node.lineno,
                })

        return {
            "module_docstring": module_doc,
            "classes": classes,
            "functions": functions,
            "path": path,
        }

    @staticmethod
    def _format_annotation(node: Any) -> str:
        if node is None:
            return ""
        import ast
        try:
            return ast.unparse(node)
        except Exception:
            return "..."

    @staticmethod
    def _format_args(args) -> str:
        import ast
        parts: List[str] = []
        defaults_offset = len(args.args) - len(args.defaults)
        for i, arg in enumerate(args.args):
            name = arg.arg
            ann = ""
            if arg.annotation:
                try:
                    ann = f": {ast.unparse(arg.annotation)}"
                except Exception:
                    ann = ": ..."
            default = ""
            di = i - defaults_offset
            if di >= 0 and di < len(args.defaults):
                try:
                    default = f" = {ast.unparse(args.defaults[di])}"
                except Exception:
                    default = " = ..."
            parts.append(f"{name}{ann}{default}")
        if args.vararg:
            parts.append(f"*{args.vararg.arg}")
        for kw in args.kwonlyargs:
            name = kw.arg
            ann = ""
            if kw.annotation:
                try:
                    ann = f": {ast.unparse(kw.annotation)}"
                except Exception:
                    ann = ": ..."
            parts.append(f"{name}{ann}")
        if args.kwarg:
            parts.append(f"**{args.kwarg.arg}")
        return ", ".join(parts)

    # ── public API ──

    def generate_module_doc(self, file_path: str) -> DocResult:
        """Generate markdown documentation for a single Python module."""
        try:
            info = self._parse_python_file(file_path)
        except Exception as exc:
            return DocResult(success=False, error=f"Failed to parse {file_path}: {exc}")

        lines: List[str] = []
        module_name = Path(file_path).stem
        lines.append(f"# Module: `{module_name}`")
        lines.append("")
        lines.append(f"**Source:** `{file_path}`")
        lines.append("")

        if info["module_docstring"]:
            lines.append(info["module_docstring"])
            lines.append("")

        # Functions
        if info["functions"]:
            lines.append("## Functions")
            lines.append("")
            for fn in info["functions"]:
                prefix = "async " if fn["is_async"] else ""
                ret = f" -> {fn['returns']}" if fn["returns"] else ""
                lines.append(f"### `{prefix}{fn['name']}({fn['args']}){ret}`")
                lines.append("")
                if fn["docstring"]:
                    lines.append(fn["docstring"])
                    lines.append("")

        # Classes
        if info["classes"]:
            lines.append("## Classes")
            lines.append("")
            for cls in info["classes"]:
                bases_str = f"({', '.join(cls['bases'])})" if cls["bases"] else ""
                lines.append(f"### `class {cls['name']}{bases_str}`")
                lines.append("")
                if cls["docstring"]:
                    lines.append(cls["docstring"])
                    lines.append("")
                if cls["methods"]:
                    lines.append("#### Methods")
                    lines.append("")
                    for m in cls["methods"]:
                        prefix = "async " if m["is_async"] else ""
                        ret = f" -> {m['returns']}" if m["returns"] else ""
                        lines.append(f"- **`{prefix}{m['name']}({m['args']}){ret}`**")
                        if m["docstring"]:
                            # Indent docstring under bullet
                            for dline in m["docstring"].split("\n"):
                                lines.append(f"  {dline}")
                        lines.append("")

        content = "\n".join(lines)
        return DocResult(success=True, content=content, message=f"Generated docs for {module_name}")

    def generate_project_doc(
        self,
        directory: Optional[str] = None,
        output_path: Optional[str] = None,
    ) -> DocResult:
        """Walk a directory and generate combined documentation for all .py files."""
        root = Path(directory or self.working_dir)
        if not root.is_dir():
            return DocResult(success=False, error=f"Not a directory: {root}")

        py_files = sorted(root.rglob("*.py"))
        if not py_files:
            return DocResult(success=False, error=f"No Python files found in {root}")

        index_lines: List[str] = [f"# Project Documentation", "", f"**Root:** `{root}`", ""]
        index_lines.append("## Modules")
        index_lines.append("")

        all_sections: List[str] = []
        count = 0

        for pf in py_files:
            # Skip __pycache__ and hidden dirs
            if "__pycache__" in str(pf) or any(p.startswith(".") for p in pf.parts):
                continue
            rel = pf.relative_to(root)
            result = self.generate_module_doc(str(pf))
            if result.success and result.content.strip():
                index_lines.append(f"- [`{rel}`](#{rel.stem})")
                all_sections.append(result.content)
                count += 1

        index_lines.append("")
        index_lines.append("---")
        index_lines.append("")

        full_content = "\n".join(index_lines) + "\n" + "\n---\n\n".join(all_sections)

        if output_path:
            Path(output_path).parent.mkdir(parents=True, exist_ok=True)
            Path(output_path).write_text(full_content, encoding="utf-8")

        return DocResult(
            success=True,
            content=full_content,
            output_path=output_path,
            message=f"Generated documentation for {count} modules.",
        )

    def generate_api_doc(self, file_path: str) -> DocResult:
        """Generate API-reference-style documentation for a Python file."""
        try:
            info = self._parse_python_file(file_path)
        except Exception as exc:
            return DocResult(success=False, error=f"Failed to parse {file_path}: {exc}")

        lines: List[str] = []
        module_name = Path(file_path).stem
        lines.append(f"# API Reference: `{module_name}`")
        lines.append("")

        # Top-level functions
        for fn in info["functions"]:
            prefix = "async " if fn["is_async"] else ""
            ret = f" -> {fn['returns']}" if fn["returns"] else ""
            lines.append(f"## `{prefix}{fn['name']}({fn['args']}){ret}`")
            lines.append("")
            if fn["docstring"]:
                lines.append(fn["docstring"])
            else:
                lines.append("*No documentation.*")
            lines.append("")

        # Class methods
        for cls in info["classes"]:
            bases_str = f"({', '.join(cls['bases'])})" if cls["bases"] else ""
            lines.append(f"## class `{cls['name']}{bases_str}`")
            lines.append("")
            if cls["docstring"]:
                lines.append(cls["docstring"])
                lines.append("")
            for m in cls["methods"]:
                if m["name"].startswith("_") and m["name"] != "__init__":
                    continue
                prefix = "async " if m["is_async"] else ""
                ret = f" -> {m['returns']}" if m["returns"] else ""
                lines.append(f"### `{prefix}{cls['name']}.{m['name']}({m['args']}){ret}`")
                lines.append("")
                if m["docstring"]:
                    lines.append(m["docstring"])
                else:
                    lines.append("*No documentation.*")
                lines.append("")

        content = "\n".join(lines)
        return DocResult(
            success=True,
            content=content,
            message=f"Generated API reference for {module_name}",
        )
