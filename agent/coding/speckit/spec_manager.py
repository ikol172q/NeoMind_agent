"""
SpecManager — CRUD for .specify/ artifacts in the user's workspace.

The .specify/ directory lives in the project being worked on (not inside
NeoMind's own source tree), resolved via WorkspaceManager.project_root.

Directory structure managed:
    <project>/.specify/
        memory/
            constitution.md
        specs/
            <feature-slug>/
                spec.md
                plan.md
                tasks.md
                research.md
                data-model.md
                checklist.md
                contracts/
"""

from __future__ import annotations

import os
import re
import json
from pathlib import Path
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional


class SpecManager:
    """CRUD for .specify/ artifacts in a project workspace."""

    def __init__(self, workspace_root: str):
        self.workspace_root = Path(workspace_root).resolve()
        self.specify_dir = self.workspace_root / ".specify"
        self.memory_dir = self.specify_dir / "memory"
        self.specs_dir = self.specify_dir / "specs"

    # ── Init / ensure directories ─────────────────────────────────

    def ensure_dirs(self) -> None:
        """Create .specify/ directory structure if it doesn't exist."""
        self.memory_dir.mkdir(parents=True, exist_ok=True)
        self.specs_dir.mkdir(parents=True, exist_ok=True)

    # ── Constitution ──────────────────────────────────────────────

    def init_constitution(self, project_name: str) -> Path:
        """Create .specify/memory/constitution.md from template. Returns path."""
        self.ensure_dirs()
        template = _load_template("constitution-template.md")
        now = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        content = template.replace("[PROJECT_NAME]", project_name)
        content = content.replace("[RATIFICATION_DATE]", now)
        content = content.replace("[LAST_AMENDED_DATE]", now)
        content = content.replace("[CONSTITUTION_VERSION]", "1.0.0")
        path = self.memory_dir / "constitution.md"
        path.write_text(content)
        return path

    def load_constitution(self) -> Optional[str]:
        """Read the current constitution. Returns None if not initialized."""
        path = self.memory_dir / "constitution.md"
        if path.exists():
            return path.read_text()
        return None

    def has_constitution(self) -> bool:
        return (self.memory_dir / "constitution.md").exists()

    def get_constitution_prompt(self) -> Optional[str]:
        """Produce the constitution section for injection into the system prompt."""
        raw = self.load_constitution()
        if not raw:
            return None
        # Extract by section *name* (case-insensitive, ignores roman-numeral
        # prefix) so editing the constitution outline (e.g. dropping "II.")
        # doesn't silently strip content from the system prompt.
        principles = _extract_named_section(raw, "Core Principles")
        quality_gates = _extract_named_section(raw, "Quality Gates")
        anti_patterns = _extract_named_section(raw, "Anti-Patterns")
        agent_principles = _extract_named_section(raw, "Agent Operating Principles")

        parts = [
            "## Project Constitution (from .specify/memory/constitution.md)",
            "ALL implementation decisions MUST adhere to these principles.",
        ]
        if principles:
            parts.append(f"### Core Principles\n{principles}")
        if quality_gates:
            parts.append(f"### Quality Gates\n{quality_gates}")
        if agent_principles:
            parts.append(f"### Agent Operating Principles\n{agent_principles}")
        if anti_patterns:
            parts.append(f"### Anti-Patterns (NEVER)\n{anti_patterns}")

        parts.append(
            "\nWhen a proposed change conflicts with a constitutional principle, you MUST:\n"
            "1. Flag the conflict explicitly\n"
            "2. Explain which principle is violated\n"
            "3. Propose an alternative that respects the constitution"
        )
        return "\n\n".join(parts)

    # ── Specs ─────────────────────────────────────────────────────

    def create_spec(self, feature_name: str, description: str = "") -> Path:
        """Create a new feature spec directory + spec.md from template."""
        self.ensure_dirs()
        slug = _slugify(feature_name)
        feature_dir = self.specs_dir / slug
        feature_dir.mkdir(parents=True, exist_ok=True)

        template = _load_template("spec-template.md")
        now = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        content = template.replace("[FEATURE_NAME]", feature_name)
        content = content.replace("[CREATED_DATE]", now)
        content = content.replace("[UPDATED_DATE]", now)

        spec_path = feature_dir / "spec.md"
        spec_path.write_text(content)

        # Write metadata
        meta = {
            "feature_name": feature_name,
            "slug": slug,
            "created": now,
            "status": "draft",
        }
        (feature_dir / "meta.json").write_text(json.dumps(meta, indent=2))

        return spec_path

    def load_spec(self, feature_slug: str) -> Optional[str]:
        """Read spec.md for a feature."""
        path = self.specs_dir / feature_slug / "spec.md"
        if path.exists():
            return path.read_text()
        return None

    def update_spec(self, feature_slug: str, content: str) -> bool:
        """Overwrite spec.md for a feature."""
        path = self.specs_dir / feature_slug / "spec.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
        # Update meta
        meta_path = path.parent / "meta.json"
        if meta_path.exists():
            meta = json.loads(meta_path.read_text())
            meta["updated"] = datetime.now(timezone.utc).strftime("%Y-%m-%d")
            meta_path.write_text(json.dumps(meta, indent=2))
        return True

    def list_specs(self) -> List[Dict[str, Any]]:
        """List all feature specs in .specify/specs/."""
        specs = []
        if not self.specs_dir.exists():
            return specs
        for d in sorted(self.specs_dir.iterdir()):
            if not d.is_dir():
                continue
            spec_md = d / "spec.md"
            meta_json = d / "meta.json"
            if not spec_md.exists():
                continue
            meta = {}
            if meta_json.exists():
                try:
                    meta = json.loads(meta_json.read_text())
                except json.JSONDecodeError:
                    pass
            specs.append({
                "slug": d.name,
                "feature_name": meta.get("feature_name", d.name),
                "status": meta.get("status", "unknown"),
                "created": meta.get("created", ""),
                "path": str(spec_md),
            })
        return specs

    def get_feature_dir(self, feature_slug: str) -> Path:
        return self.specs_dir / feature_slug

    # ── Plans ─────────────────────────────────────────────────────

    def create_plan(self, feature_slug: str) -> Path:
        """Create plan.md from template for a feature."""
        feature_dir = self.specs_dir / feature_slug
        feature_dir.mkdir(parents=True, exist_ok=True)

        template = _load_template("plan-template.md")
        now = datetime.now(timezone.utc).strftime("%Y-%m-%d")

        # Try to read constitution version. Only match a bare `version:` at
        # the start of a line — avoids picking up `plan_version:` /
        # `constitution_version:` / other suffix forms.
        const_version = "1.0.0"
        const_raw = self.load_constitution()
        if const_raw:
            m = re.search(r"^version:\s*([\d.]+)", const_raw, re.MULTILINE)
            if m:
                const_version = m.group(1)

        content = template.replace("[FEATURE_NAME]", feature_slug)
        content = content.replace("[PATH_TO_SPEC_MD]", f".specify/specs/{feature_slug}/spec.md")
        content = content.replace("[CONSTITUTION_VERSION]", const_version)
        content = content.replace("[CREATED_DATE]", now)

        plan_path = feature_dir / "plan.md"
        plan_path.write_text(content)
        return plan_path

    def load_plan(self, feature_slug: str) -> Optional[str]:
        path = self.specs_dir / feature_slug / "plan.md"
        if path.exists():
            return path.read_text()
        return None

    # ── Tasks ─────────────────────────────────────────────────────

    def create_tasks(self, feature_slug: str) -> Path:
        """Create tasks.md from template for a feature."""
        feature_dir = self.specs_dir / feature_slug
        feature_dir.mkdir(parents=True, exist_ok=True)

        template = _load_template("tasks-template.md")
        now = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        content = template.replace("[FEATURE_NAME]", feature_slug)
        content = content.replace("[PATH_TO_PLAN_MD]", f".specify/specs/{feature_slug}/plan.md")
        content = content.replace("[CREATED_DATE]", now)

        tasks_path = feature_dir / "tasks.md"
        tasks_path.write_text(content)
        return tasks_path

    def load_tasks(self, feature_slug: str) -> Optional[str]:
        path = self.specs_dir / feature_slug / "tasks.md"
        if path.exists():
            return path.read_text()
        return None

    def parse_tasks(self, feature_slug: str) -> List[Dict[str, Any]]:
        """Parse tasks.md into structured task items for TaskManager sync.

        Tolerates any ordering of `[P]` and `[USx]` tags after the task id:
            "- [ ] T001 [P] [US1] Description"
            "- [ ] T001 [US1] [P] Description"
            "- [ ] T001 [US1] Description"
            "- [ ] T001 Description"
        """
        raw = self.load_tasks(feature_slug)
        if not raw:
            return []
        tasks = []
        current_story = ""
        # Match the checkbox + task id, then accept the rest as a free tail.
        # Tags are extracted from the tail in any order.
        line_re = re.compile(r"- \[([ xX])\]\s+(T\d+)\s+(.+)")
        story_tag_re = re.compile(r"\[(US\d+)\]")
        parallel_tag_re = re.compile(r"\[P\]")
        for line in raw.split("\n"):
            m = line_re.match(line)
            if m:
                checked = m.group(1) != " "
                task_id = m.group(2)
                tail = m.group(3)
                story_match = story_tag_re.search(tail)
                story = story_match.group(1) if story_match else current_story
                parallel = bool(parallel_tag_re.search(tail))
                # Strip recognized tags from description (any order)
                desc = parallel_tag_re.sub("", tail)
                desc = story_tag_re.sub("", desc)
                # Collapse repeated whitespace introduced by stripping
                desc = re.sub(r"\s+", " ", desc).strip()
                tasks.append({
                    "id": task_id,
                    "description": desc,
                    "user_story": story,
                    "completed": checked,
                    "parallel": parallel,
                    "feature_slug": feature_slug,
                })
            # Track current story header
            story_m = re.match(r"##\s+Phase\s+\d+:\s+User Story\s+\d+\s+[—–-]\s+(.*)", line)
            if story_m:
                current_story = story_m.group(1).strip()
        return tasks

    # ── Research ──────────────────────────────────────────────────

    def write_research(self, feature_slug: str, content: str) -> Path:
        feature_dir = self.specs_dir / feature_slug
        feature_dir.mkdir(parents=True, exist_ok=True)
        path = feature_dir / "research.md"
        path.write_text(content)
        return path

    def load_research(self, feature_slug: str) -> Optional[str]:
        path = self.specs_dir / feature_slug / "research.md"
        if path.exists():
            return path.read_text()
        return None

    # ── Checklist ─────────────────────────────────────────────────

    def create_checklist(self, feature_slug: str) -> Path:
        feature_dir = self.specs_dir / feature_slug
        feature_dir.mkdir(parents=True, exist_ok=True)
        template = _load_template("checklist-template.md")
        now = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        content = template.replace("[FEATURE_NAME]", feature_slug)
        content = content.replace("[CREATED_DATE]", now)
        path = feature_dir / "checklist.md"
        path.write_text(content)
        return path

    def load_checklist(self, feature_slug: str) -> Optional[str]:
        path = self.specs_dir / feature_slug / "checklist.md"
        if path.exists():
            return path.read_text()
        return None

    def get_checklist_stats(self, feature_slug: str) -> Dict[str, int]:
        """Count total / completed / incomplete checklist items."""
        raw = self.load_checklist(feature_slug)
        if not raw:
            return {"total": 0, "completed": 0, "incomplete": 0}
        total = 0
        completed = 0
        for line in raw.split("\n"):
            if re.match(r"- \[x\]", line, re.IGNORECASE):
                total += 1
                completed += 1
            elif re.match(r"- \[ \]", line):
                total += 1
        return {"total": total, "completed": completed, "incomplete": total - completed}


# ── Helpers ───────────────────────────────────────────────────────

def _load_template(name: str) -> str:
    """Load a template file from agent/coding/speckit/templates/."""
    import os as _os
    _tpl_dir = Path(__file__).resolve().parent / "templates"
    _path = _tpl_dir / name
    if _path.exists():
        return _path.read_text()
    # Fallback: try relative to cwd
    _fallback = Path(_os.getcwd()) / "agent" / "coding" / "speckit" / "templates" / name
    if _fallback.exists():
        return _fallback.read_text()
    raise FileNotFoundError(f"Template not found: {name}")


def _slugify(name: str) -> str:
    """Convert a feature name to a filesystem-safe slug."""
    slug = name.strip().lower()
    slug = re.sub(r"[^a-z0-9]+", "-", slug)
    slug = slug.strip("-")
    return slug or "feature"


def _extract_section(text: str, start_header: str, end_header: str) -> Optional[str]:
    """Extract a markdown section between two headers."""
    start_idx = text.find(start_header)
    if start_idx == -1:
        return None
    end_idx = text.find(end_header, start_idx + len(start_header))
    if end_idx == -1:
        section = text[start_idx:]
    else:
        section = text[start_idx:end_idx]
    return section.strip()


def _extract_named_section(text: str, name: str) -> Optional[str]:
    """Extract an H2 section by its name, tolerant of roman-numeral / dotted
    prefixes (e.g. matches "## II. Core Principles", "## 2. Core Principles",
    "## Core Principles"). Returns content up to the next H2.
    """
    # Header line matcher: ## [optional roman/numeric prefix and dot] name
    header_pattern = re.compile(
        r"^##\s+(?:[IVXLCDM]+\.?\s+|\d+\.?\s+)?" + re.escape(name) + r"\b.*$",
        re.IGNORECASE | re.MULTILINE,
    )
    match = header_pattern.search(text)
    if not match:
        return None
    start_idx = match.start()
    # Find next H2 (any) after this header
    next_h2 = re.search(r"^##\s+", text[match.end():], re.MULTILINE)
    if next_h2:
        end_idx = match.end() + next_h2.start()
        return text[start_idx:end_idx].strip()
    return text[start_idx:].strip()


__all__ = ["SpecManager"]
