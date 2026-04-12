"""
Memory Taxonomy — Structured type guidance for NeoMind memories.

Teaches the LLM WHEN to save memories, WHAT format to use, and
HOW to apply them. Injected into system prompt alongside selected memories.

Four memory types:
  - user: Role, goals, preferences, knowledge
  - feedback: Guidance on approach (corrections + confirmations)
  - project: Ongoing work, goals, deadlines
  - reference: Pointers to external resources
"""

MEMORY_TYPES = [
    {
        'name': 'user',
        'description': 'Information about the user — role, goals, knowledge, preferences',
        'when_to_save': (
            'When you learn details about the user\'s role, expertise, '
            'responsibilities, or preferred working style.'
        ),
        'how_to_use': (
            'Tailor responses to the user\'s level and context. '
            'A senior engineer gets different explanations than a beginner.'
        ),
        'body_structure': 'Concise factual statement about the user.',
        'scope': 'private',
        'examples': [
            'User is a data scientist focused on ML pipeline observability.',
            'User prefers Chinese for communication, English for code.',
        ],
    },
    {
        'name': 'feedback',
        'description': 'Guidance the user gave about how to approach work',
        'when_to_save': (
            'When the user corrects your approach ("don\'t do X", "stop doing Y") '
            'OR confirms a non-obvious approach worked ("yes exactly", "perfect"). '
            'Record both corrections AND validations.'
        ),
        'how_to_use': (
            'Follow this guidance so the user doesn\'t repeat themselves. '
            'Include WHY so you can judge edge cases.'
        ),
        'body_structure': (
            'Lead with the rule. Then: **Why:** (the reason). '
            'Then: **How to apply:** (when this guidance applies).'
        ),
        'scope': 'private (default), project (for project-wide conventions)',
        'examples': [
            'Don\'t mock the database in integration tests. '
            '**Why:** Mock/prod divergence masked a broken migration last quarter. '
            '**How to apply:** All test files in tests/integration/',
            'User wants terse responses — no trailing summaries.',
        ],
    },
    {
        'name': 'project',
        'description': 'Ongoing work, goals, deadlines, architecture decisions',
        'when_to_save': (
            'When you learn who is doing what, why, or by when. '
            'Always convert relative dates to absolute dates when saving.'
        ),
        'how_to_use': (
            'Use to understand the broader context behind the user\'s request. '
            'Make informed suggestions that respect constraints and deadlines.'
        ),
        'body_structure': (
            'Lead with the fact or decision. Then: **Why:** (motivation/constraint). '
            'Then: **How to apply:** (how this shapes suggestions).'
        ),
        'scope': 'private or project (bias toward project)',
        'examples': [
            'Auth middleware rewrite is driven by legal/compliance (not tech debt). '
            '**Why:** Legal flagged session token storage. '
            '**How to apply:** Scope decisions should favor compliance over ergonomics.',
        ],
    },
    {
        'name': 'reference',
        'description': 'Pointers to where information can be found',
        'when_to_save': (
            'When you learn about resources in external systems and their purpose — '
            'bug trackers, dashboards, Slack channels, documentation sites.'
        ),
        'how_to_use': (
            'When the user references an external system or asks about something '
            'that might be documented elsewhere.'
        ),
        'body_structure': 'Resource name/URL + what it contains + when to check it.',
        'scope': 'usually project',
        'examples': [
            'Pipeline bugs tracked in Linear project "INGEST".',
            'Grafana board at grafana.internal/d/api-latency — check when editing request-path code.',
        ],
    },
]


def build_taxonomy_prompt() -> str:
    """Build the memory taxonomy section for system prompt injection.

    Returns a formatted string describing all memory types with guidance.
    """
    lines = [
        "## Memory Types\n",
        "When saving memories, use the appropriate type:\n",
    ]

    for mt in MEMORY_TYPES:
        lines.append(f"### {mt['name'].upper()}")
        lines.append(f"**Description:** {mt['description']}")
        lines.append(f"**When to save:** {mt['when_to_save']}")
        lines.append(f"**How to use:** {mt['how_to_use']}")
        lines.append(f"**Body format:** {mt['body_structure']}")
        lines.append(f"**Scope:** {mt['scope']}")
        if mt.get('examples'):
            lines.append("**Examples:**")
            for ex in mt['examples']:
                lines.append(f"  - {ex}")
        lines.append("")

    lines.append("**Do NOT save:** Code patterns, architecture, file paths, or git history (derivable from code).")
    lines.append("**Do NOT save:** Ephemeral task details or current conversation context.\n")

    return "\n".join(lines)
