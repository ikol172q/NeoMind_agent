"""
Multi-Format Export Service for NeoMind.

Exports conversation history in multiple formats:
- Markdown (structured with headers per turn)
- JSON (full structured data with metadata)
- HTML (styled, self-contained single file)
"""

import json
import time
import html
from typing import List, Dict, Any, Optional


def export_markdown(history: List[Dict[str, Any]], options: Dict[str, Any] = None) -> str:
    """Export conversation as structured Markdown.

    Options:
        include_tools: bool (default True) — include tool use blocks
        include_timestamps: bool (default False)
    """
    opts = options or {}
    include_tools = opts.get('include_tools', True)
    include_timestamps = opts.get('include_timestamps', False)

    lines = ["# NeoMind Session Export\n"]
    lines.append(f"**Exported:** {time.strftime('%Y-%m-%d %H:%M:%S')}\n")

    for i, msg in enumerate(history):
        role = msg.get('role', 'unknown')
        content = msg.get('content', '')

        if role == 'system':
            continue  # Skip system messages

        # Role header
        role_label = {'user': 'User', 'assistant': 'Assistant'}.get(role, role.title())
        lines.append(f"\n## {role_label}")
        if include_timestamps and msg.get('timestamp'):
            lines.append(f"*{msg['timestamp']}*\n")

        # Content
        if isinstance(content, list):
            for block in content:
                if isinstance(block, dict):
                    if block.get('type') == 'text':
                        lines.append(block.get('text', ''))
                    elif block.get('type') == 'tool_use' and include_tools:
                        tool = block.get('name', '?')
                        inp = json.dumps(block.get('input', {}), indent=2)
                        lines.append(f"\n```tool-use: {tool}\n{inp}\n```\n")
                    elif block.get('type') == 'tool_result' and include_tools:
                        result = str(block.get('content', ''))[:500]
                        lines.append(f"\n```tool-result\n{result}\n```\n")
        else:
            lines.append(str(content))

        lines.append("")

    return "\n".join(lines)


def export_json(history: List[Dict[str, Any]], options: Dict[str, Any] = None) -> str:
    """Export conversation as structured JSON."""
    opts = options or {}
    data = {
        'exported_at': time.strftime('%Y-%m-%dT%H:%M:%SZ'),
        'format_version': '1.0',
        'message_count': len(history),
        'messages': [],
    }

    for msg in history:
        role = msg.get('role', 'unknown')
        if role == 'system' and not opts.get('include_system', False):
            continue
        data['messages'].append({
            'role': role,
            'content': msg.get('content', ''),
        })

    return json.dumps(data, indent=2, ensure_ascii=False)


def export_html(history: List[Dict[str, Any]], options: Dict[str, Any] = None) -> str:
    """Export conversation as self-contained HTML."""
    opts = options or {}
    include_tools = opts.get('include_tools', True)

    messages_html = []
    for msg in history:
        role = msg.get('role', 'unknown')
        if role == 'system':
            continue

        content = msg.get('content', '')
        css_class = f"message-{role}"

        if isinstance(content, list):
            parts = []
            for block in content:
                if isinstance(block, dict):
                    if block.get('type') == 'text':
                        parts.append(f"<p>{html.escape(block.get('text', ''))}</p>")
                    elif block.get('type') == 'tool_use' and include_tools:
                        tool = html.escape(block.get('name', '?'))
                        inp = html.escape(json.dumps(block.get('input', {}), indent=2))
                        parts.append(f'<div class="tool-use"><strong>{tool}</strong><pre>{inp}</pre></div>')
                    elif block.get('type') == 'tool_result' and include_tools:
                        result = html.escape(str(block.get('content', ''))[:500])
                        parts.append(f'<div class="tool-result"><pre>{result}</pre></div>')
            content_html = "\n".join(parts)
        else:
            content_html = f"<p>{html.escape(str(content))}</p>"

        role_label = {'user': 'User', 'assistant': 'NeoMind'}.get(role, role.title())
        messages_html.append(
            f'<div class="{css_class}">'
            f'<div class="role">{role_label}</div>'
            f'{content_html}'
            f'</div>'
        )

    body = "\n".join(messages_html)

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>NeoMind Session Export</title>
<style>
body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; max-width: 800px; margin: 0 auto; padding: 20px; background: #1a1a2e; color: #e0e0e0; }}
.message-user {{ background: #16213e; padding: 12px 16px; border-radius: 8px; margin: 8px 0; border-left: 3px solid #0f3460; }}
.message-assistant {{ background: #1a1a2e; padding: 12px 16px; border-radius: 8px; margin: 8px 0; border-left: 3px solid #e94560; }}
.role {{ font-weight: bold; font-size: 0.85em; color: #888; margin-bottom: 4px; }}
.tool-use {{ background: #0d1117; padding: 8px; border-radius: 4px; margin: 4px 0; border: 1px solid #30363d; }}
.tool-result {{ background: #0d1117; padding: 8px; border-radius: 4px; margin: 4px 0; border: 1px solid #238636; }}
pre {{ white-space: pre-wrap; word-wrap: break-word; font-size: 0.9em; }}
p {{ margin: 4px 0; line-height: 1.5; }}
h1 {{ color: #e94560; }}
</style>
</head>
<body>
<h1>NeoMind Session Export</h1>
<p style="color:#888">Exported: {time.strftime('%Y-%m-%d %H:%M:%S')}</p>
{body}
</body>
</html>"""


def detect_format(filename: str) -> str:
    """Detect export format from filename extension."""
    ext = filename.rsplit('.', 1)[-1].lower() if '.' in filename else ''
    return {
        'md': 'markdown',
        'markdown': 'markdown',
        'json': 'json',
        'html': 'html',
        'htm': 'html',
        'txt': 'text',
    }.get(ext, 'markdown')


def export_conversation(history: List[Dict[str, Any]], fmt: str = 'markdown',
                        options: Dict[str, Any] = None) -> str:
    """Export conversation in the specified format.

    Args:
        history: Conversation history
        fmt: 'markdown', 'json', 'html', or 'text'
        options: Format-specific options

    Returns:
        Formatted string
    """
    exporters = {
        'markdown': export_markdown,
        'json': export_json,
        'html': export_html,
        'text': export_markdown,  # Text falls back to markdown
    }
    exporter = exporters.get(fmt, export_markdown)
    return exporter(history, options)
