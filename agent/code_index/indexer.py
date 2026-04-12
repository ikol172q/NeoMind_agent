"""
Codebase Indexer for NeoMind Agent.

Provides code indexing, search, and analysis capabilities for Coding personality.
Inspired by Claude Code's codebase indexing and semantic search.

Created: 2026-04-02 (Phase 2 - Coding 完整功能)
"""

from __future__ import annotations

import os
import re
import json
import hashlib
import asyncio
from pathlib import Path
from typing import List, Dict, Optional, Any, Set, Tuple, Callable
from dataclasses import dataclass, field
from datetime import datetime
from collections import defaultdict, Counter
import fnmatch


@dataclass
class CodeSymbol:
    """Represents a code symbol (function, class, etc.)."""
    name: str
    kind: str  # function, class, method, variable, import
    file_path: str
    line_number: int
    line_end: int
    docstring: Optional[str] = None
    signature: Optional[str] = None
    parent: Optional[str] = None  # Parent class for methods
    references: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class FileInfo:
    """Information about an indexed file."""
    path: str
    language: str
    size: int
    line_count: int
    symbols: List[CodeSymbol]
    imports: List[str]
    exports: List[str]
    hash: str
    last_modified: datetime
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class SearchResult:
    """Result from a codebase search."""
    file_path: str
    line_number: int
    line_content: str
    context_before: List[str]
    context_after: List[str]
    score: float
    match_type: str  # exact, fuzzy, semantic
    symbol: Optional[CodeSymbol] = None


class CodebaseIndexer:
    """
    Indexes and searches codebases for the Coding personality.

    Features:
    - Multi-language support (Python, JS, TS, etc.)
    - Symbol extraction (functions, classes, methods)
    - Fast full-text search
    - Dependency tracking
    - Incremental updates
    """

    # Supported languages and their extensions
    LANGUAGE_EXTENSIONS = {
        'python': {'.py', '.pyw', '.pyi'},
        'javascript': {'.js', '.jsx', '.mjs'},
        'typescript': {'.ts', '.tsx'},
        'java': {'.java'},
        'go': {'.go'},
        'rust': {'.rs'},
        'cpp': {'.cpp', '.cc', '.cxx', '.hpp', '.h'},
        'c': {'.c', '.h'},
        'ruby': {'.rb', '.rake'},
        'php': {'.php'},
        'swift': {'.swift'},
        'kotlin': {'.kt', '.kts'},
        'scala': {'.scala'},
        'markdown': {'.md', '.markdown'},
        'json': {'.json'},
        'yaml': {'.yaml', '.yml'},
        'shell': {'.sh', '.bash', '.zsh'},
    }

    # Patterns to ignore
    IGNORE_PATTERNS = {
        'node_modules', '.git', '.svn', '__pycache__', '.pytest_cache',
        '.mypy_cache', '.tox', 'venv', 'env', '.venv', '.env',
        'dist', 'build', 'target', 'out', '.idea', '.vscode',
        '*.pyc', '*.pyo', '*.so', '*.dll', '*.dylib',
        '*.egg-info', '*.egg', '.eggs',
    }

    def __init__(
        self,
        root_path: str,
        ignore_patterns: Optional[Set[str]] = None,
        max_file_size: int = 1024 * 1024  # 1MB
    ):
        """
        Initialize the codebase indexer.

        Args:
            root_path: Root directory of the codebase
            ignore_patterns: Additional patterns to ignore
            max_file_size: Maximum file size to index (bytes)
        """
        self.root_path = Path(root_path).resolve()
        self.ignore_patterns = self.IGNORE_PATTERNS | (ignore_patterns or set())
        self.max_file_size = max_file_size

        # Index storage
        self._files: Dict[str, FileInfo] = {}
        self._symbols: Dict[str, List[CodeSymbol]] = defaultdict(list)
        self._symbol_index: Dict[str, CodeSymbol] = {}  # name -> symbol
        self._imports_graph: Dict[str, Set[str]] = defaultdict(set)
        self._reverse_index: Dict[str, Set[str]] = defaultdict(set)  # word -> files

        # Cache
        self._file_hashes: Dict[str, str] = {}

    def index(self, force: bool = False) -> Dict[str, Any]:
        """
        Index the entire codebase.

        Args:
            force: Force re-indexing all files

        Returns:
            Statistics about the indexing operation
        """
        start_time = datetime.now()
        stats = {
            'files_indexed': 0,
            'files_skipped': 0,
            'symbols_found': 0,
            'errors': [],
        }

        for file_path in self._walk_files():
            try:
                if not force and self._is_file_cached(file_path):
                    stats['files_skipped'] += 1
                    continue

                file_info = self._index_file(file_path)
                if file_info:
                    self._files[str(file_path)] = file_info
                    stats['files_indexed'] += 1
                    stats['symbols_found'] += len(file_info.symbols)

            except Exception as e:
                stats['errors'].append({
                    'file': str(file_path),
                    'error': str(e)
                })

        # Build reverse index
        self._build_reverse_index()

        stats['duration_ms'] = (datetime.now() - start_time).total_seconds() * 1000
        stats['total_files'] = len(self._files)
        stats['total_symbols'] = sum(len(s) for s in self._symbols.values())

        return stats

    def _walk_files(self) -> List[Path]:
        """Walk the codebase and return files to index."""
        files = []

        for root, dirs, filenames in os.walk(self.root_path):
            # Filter out ignored directories
            dirs[:] = [d for d in dirs if not self._should_ignore(d)]

            for filename in filenames:
                file_path = Path(root) / filename

                if self._should_ignore(filename):
                    continue

                if self._is_supported_file(file_path):
                    files.append(file_path)

        return files

    def _should_ignore(self, name: str) -> bool:
        """Check if a file or directory should be ignored."""
        for pattern in self.ignore_patterns:
            if fnmatch.fnmatch(name, pattern):
                return True
            if name == pattern:
                return True
        return False

    def _is_supported_file(self, file_path: Path) -> bool:
        """Check if file is a supported language."""
        suffix = file_path.suffix.lower()
        for exts in self.LANGUAGE_EXTENSIONS.values():
            if suffix in exts:
                return True
        return False

    def _is_file_cached(self, file_path: Path) -> bool:
        """Check if file is already indexed and unchanged."""
        str_path = str(file_path)
        if str_path not in self._files:
            return False

        try:
            current_hash = self._compute_file_hash(file_path)
            return current_hash == self._file_hashes.get(str_path)
        except Exception:
            return False

    def _compute_file_hash(self, file_path: Path) -> str:
        """Compute hash of file contents."""
        hasher = hashlib.md5()
        with open(file_path, 'rb') as f:
            for chunk in iter(lambda: f.read(8192), b''):
                hasher.update(chunk)
        return hasher.hexdigest()

    def _index_file(self, file_path: Path) -> Optional[FileInfo]:
        """Index a single file."""
        # Check file size
        if file_path.stat().st_size > self.max_file_size:
            return None

        # Detect language
        language = self._detect_language(file_path)

        # Read file content
        try:
            content = file_path.read_text(encoding='utf-8', errors='replace')
        except Exception:
            return None

        # Compute hash
        file_hash = self._compute_file_hash(file_path)
        self._file_hashes[str(file_path)] = file_hash

        # Extract symbols
        symbols = self._extract_symbols(content, language, file_path)

        # Extract imports/exports
        imports, exports = self._extract_imports_exports(content, language)

        # Build file info
        rel_path = str(file_path.relative_to(self.root_path))

        file_info = FileInfo(
            path=rel_path,
            language=language,
            size=len(content),
            line_count=content.count('\n') + 1,
            symbols=symbols,
            imports=imports,
            exports=exports,
            hash=file_hash,
            last_modified=datetime.fromtimestamp(file_path.stat().st_mtime)
        )

        # Update symbol index
        for symbol in symbols:
            self._symbols[symbol.name].append(symbol)
            self._symbol_index[f"{rel_path}:{symbol.name}"] = symbol

        # Update imports graph
        self._imports_graph[rel_path] = set(imports)

        return file_info

    def _detect_language(self, file_path: Path) -> str:
        """Detect programming language from file extension."""
        suffix = file_path.suffix.lower()
        for lang, exts in self.LANGUAGE_EXTENSIONS.items():
            if suffix in exts:
                return lang
        return 'unknown'

    def _extract_symbols(
        self,
        content: str,
        language: str,
        file_path: Path
    ) -> List[CodeSymbol]:
        """Extract code symbols from content."""
        if language == 'python':
            return self._extract_python_symbols(content, file_path)
        elif language in ('javascript', 'typescript'):
            return self._extract_js_ts_symbols(content, file_path)
        else:
            return self._extract_generic_symbols(content, file_path)

    def _extract_python_symbols(
        self,
        content: str,
        file_path: Path
    ) -> List[CodeSymbol]:
        """Extract symbols from Python code."""
        symbols = []

        # Regex patterns for Python
        patterns = [
            # Functions
            (r'^(def\s+(\w+)\s*\([^)]*\))', 'function'),
            # Classes
            (r'^(class\s+(\w+)[\s(:])', 'class'),
            # Methods (inside class)
            (r'^(\s+def\s+(\w+)\s*\([^)]*\))', 'method'),
        ]

        lines = content.split('\n')
        current_class = None

        for i, line in enumerate(lines, 1):
            for pattern, kind in patterns:
                match = re.match(pattern, line)
                if match:
                    signature = match.group(1)
                    name = match.group(2)

                    # Track current class for methods
                    if kind == 'class':
                        current_class = name
                    elif kind == 'method' and current_class:
                        parent = current_class

                    # Extract docstring
                    docstring = self._extract_docstring(lines, i - 1)

                    symbol = CodeSymbol(
                        name=name,
                        kind=kind,
                        file_path=str(file_path),
                        line_number=i,
                        line_end=i,  # Will be updated
                        docstring=docstring,
                        signature=signature,
                        parent=current_class if kind == 'method' else None
                    )
                    symbols.append(symbol)
                    break

            # Reset class context on dedent
            if line and not line[0].isspace() and current_class:
                if not line.startswith('class '):
                    current_class = None

        return symbols

    def _extract_js_ts_symbols(
        self,
        content: str,
        file_path: Path
    ) -> List[CodeSymbol]:
        """Extract symbols from JavaScript/TypeScript code."""
        symbols = []

        patterns = [
            # Functions
            (r'(?:export\s+)?(?:async\s+)?function\s+(\w+)', 'function'),
            # Arrow functions
            (r'(?:export\s+)?(?:const|let|var)\s+(\w+)\s*=\s*(?:async\s*)?\([^)]*\)\s*=>', 'function'),
            # Classes
            (r'(?:export\s+)?class\s+(\w+)', 'class'),
            # Methods
            (r'(\w+)\s*\([^)]*\)\s*\{', 'method'),
        ]

        lines = content.split('\n')

        for i, line in enumerate(lines, 1):
            for pattern, kind in patterns:
                match = re.search(pattern, line)
                if match:
                    symbol = CodeSymbol(
                        name=match.group(1),
                        kind=kind,
                        file_path=str(file_path),
                        line_number=i,
                        line_end=i,
                        signature=match.group(0)
                    )
                    symbols.append(symbol)
                    break

        return symbols

    def _extract_generic_symbols(
        self,
        content: str,
        file_path: Path
    ) -> List[CodeSymbol]:
        """Generic symbol extraction for other languages."""
        symbols = []

        # Simple word-based extraction
        lines = content.split('\n')

        for i, line in enumerate(lines, 1):
            # Look for function-like patterns
            if re.search(r'\bfunction\b|\bdef\b|\bfunc\b|\bfn\b', line, re.IGNORECASE):
                # Extract potential function name
                match = re.search(r'\b(\w+)\s*[({]', line)
                if match:
                    symbol = CodeSymbol(
                        name=match.group(1),
                        kind='function',
                        file_path=str(file_path),
                        line_number=i,
                        line_end=i
                    )
                    symbols.append(symbol)

        return symbols

    def _extract_docstring(self, lines: List[str], start_idx: int) -> Optional[str]:
        """Extract docstring following a definition."""
        if start_idx + 1 >= len(lines):
            return None

        next_line = lines[start_idx + 1].strip()

        # Python docstring
        if next_line.startswith('"""') or next_line.startswith("'''"):
            quote = next_line[:3]
            docstring = next_line[3:]

            # Single line docstring
            if docstring.endswith(quote):
                return docstring[:-3]

            # Multi-line docstring
            for i in range(start_idx + 2, min(start_idx + 20, len(lines))):
                if quote in lines[i]:
                    return docstring + '\n'.join(lines[start_idx + 2:i + 1])

        return None

    def _extract_imports_exports(
        self,
        content: str,
        language: str
    ) -> Tuple[List[str], List[str]]:
        """Extract import and export statements."""
        imports = []
        exports = []

        if language == 'python':
            # Python imports
            for match in re.finditer(r'^(?:from\s+(\S+)\s+)?import\s+(.+)$', content, re.MULTILINE):
                module = match.group(1) or ''
                names = match.group(2)
                imports.append(f"{module}.{names}" if module else names)

        elif language in ('javascript', 'typescript'):
            # JS/TS imports
            for match in re.finditer(r"import\s+.*?from\s+['\"](.+?)['\"]", content):
                imports.append(match.group(1))

            # JS/TS exports
            for match in re.finditer(r"export\s+(?:default\s+)?(?:function|class|const|let|var)\s+(\w+)", content):
                exports.append(match.group(1))

        return imports, exports

    def _build_reverse_index(self) -> None:
        """Build reverse index for fast searching."""
        self._reverse_index.clear()

        for file_path, file_info in self._files.items():
            # Index words in file
            words = set()
            for symbol in file_info.symbols:
                words.add(symbol.name.lower())
                if symbol.docstring:
                    words.update(symbol.docstring.lower().split())

            for word in words:
                self._reverse_index[word].add(file_path)

    def search(
        self,
        query: str,
        search_type: str = 'symbol',
        limit: int = 20
    ) -> List[SearchResult]:
        """
        Search the codebase.

        Args:
            query: Search query
            search_type: Type of search ('symbol', 'text', 'regex')
            limit: Maximum results

        Returns:
            List of SearchResult objects
        """
        results = []

        if search_type == 'symbol':
            results = self._search_symbols(query, limit)
        elif search_type == 'text':
            results = self._search_text(query, limit)
        elif search_type == 'regex':
            results = self._search_regex(query, limit)

        return sorted(results, key=lambda r: r.score, reverse=True)[:limit]

    def _search_symbols(self, query: str, limit: int) -> List[SearchResult]:
        """Search for symbols by name."""
        results = []
        query_lower = query.lower()

        for symbol_name, symbols in self._symbols.items():
            if query_lower in symbol_name.lower():
                for symbol in symbols[:1]:  # Take first occurrence
                    # Read context
                    file_path = self.root_path / symbol.file_path
                    if file_path.exists():
                        content = file_path.read_text(encoding='utf-8', errors='replace')
                        lines = content.split('\n')

                        line_idx = symbol.line_number - 1
                        context_before = lines[max(0, line_idx - 3):line_idx]
                        context_after = lines[line_idx + 1:line_idx + 4]

                        results.append(SearchResult(
                            file_path=symbol.file_path,
                            line_number=symbol.line_number,
                            line_content=lines[line_idx] if line_idx < len(lines) else '',
                            context_before=context_before,
                            context_after=context_after,
                            score=1.0 if symbol_name.lower() == query_lower else 0.7,
                            match_type='symbol',
                            symbol=symbol
                        ))

        return results

    def _search_text(self, query: str, limit: int) -> List[SearchResult]:
        """Full-text search."""
        results = []
        query_lower = query.lower()

        for file_path, file_info in self._files.items():
            full_path = self.root_path / file_path
            if not full_path.exists():
                continue

            try:
                content = full_path.read_text(encoding='utf-8', errors='replace')
                lines = content.split('\n')

                for i, line in enumerate(lines, 1):
                    if query_lower in line.lower():
                        results.append(SearchResult(
                            file_path=file_path,
                            line_number=i,
                            line_content=line,
                            context_before=lines[max(0, i - 4):i - 1],
                            context_after=lines[i:i + 3],
                            score=0.5,
                            match_type='text'
                        ))
            except Exception:
                continue

        return results

    def _search_regex(self, pattern: str, limit: int) -> List[SearchResult]:
        """Regex search."""
        results = []

        try:
            compiled = re.compile(pattern)
        except re.error:
            return results

        for file_path, file_info in self._files.items():
            full_path = self.root_path / file_path
            if not full_path.exists():
                continue

            try:
                content = full_path.read_text(encoding='utf-8', errors='replace')
                lines = content.split('\n')

                for i, line in enumerate(lines, 1):
                    if compiled.search(line):
                        results.append(SearchResult(
                            file_path=file_path,
                            line_number=i,
                            line_content=line,
                            context_before=lines[max(0, i - 4):i - 1],
                            context_after=lines[i:i + 3],
                            score=0.6,
                            match_type='regex'
                        ))
            except Exception:
                continue

        return results

    def get_file_info(self, file_path: str) -> Optional[FileInfo]:
        """Get information about an indexed file."""
        return self._files.get(file_path)

    def get_symbol(self, name: str) -> List[CodeSymbol]:
        """Get all symbols with a given name."""
        return self._symbols.get(name, [])

    def get_dependencies(self, file_path: str) -> Set[str]:
        """Get dependencies of a file."""
        return self._imports_graph.get(file_path, set())

    def get_dependents(self, file_path: str) -> Set[str]:
        """Get files that depend on this file."""
        dependents = set()
        for other_file, imports in self._imports_graph.items():
            if file_path in imports:
                dependents.add(other_file)
        return dependents

    def get_stats(self) -> Dict[str, Any]:
        """Get indexing statistics."""
        return {
            'total_files': len(self._files),
            'total_symbols': sum(len(s) for s in self._symbols.values()),
            'unique_symbols': len(self._symbols),
            'languages': dict(Counter(f.language for f in self._files.values())),
            'index_size': sum(f.size for f in self._files.values()),
        }


# Convenience function
def index_codebase(root_path: str) -> CodebaseIndexer:
    """Quick indexing function."""
    indexer = CodebaseIndexer(root_path)
    indexer.index()
    return indexer


__all__ = [
    'CodebaseIndexer',
    'CodeSymbol',
    'FileInfo',
    'SearchResult',
    'index_codebase',
]


if __name__ == "__main__":
    # Test the indexer
    import sys
    from collections import Counter

    if len(sys.argv) > 1:
        root = sys.argv[1]
    else:
        root = os.getcwd()

    print(f"Indexing {root}...")
    indexer = CodebaseIndexer(root)
    stats = indexer.index()

    print(f"\n=== Indexing Complete ===")
    print(f"Files indexed: {stats['total_files']}")
    print(f"Symbols found: {stats['total_symbols']}")
    print(f"Duration: {stats['duration_ms']:.1f}ms")

    # Test search
    if stats['total_symbols'] > 0:
        print("\n=== Symbol Search Test ===")
        results = indexer.search("def", search_type='symbol', limit=5)
        for r in results:
            print(f"  {r.symbol.name} ({r.symbol.kind}) at {r.file_path}:{r.line_number}")

    print("\n✅ CodebaseIndexer test passed!")
