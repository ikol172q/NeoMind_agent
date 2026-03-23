# agent/memory/example_usage.py
"""
Example usage of the SharedMemory system for cross-personality memory.

This demonstrates how the three personalities (chat, coding, finance) work together
by sharing user context through the cross-personality memory layer.
"""

from .shared_memory import SharedMemory


def demo_three_personality_collaboration():
    """
    Demonstrate how all three personalities collaborate through shared memory.
    """
    # Initialize shared memory (would use ~/.neomind/shared_memory.db in production)
    memory = SharedMemory()

    # ═══════════════════════════════════════════════════════════════════════
    # CHAT PERSONALITY learns user preferences and facts
    # ═══════════════════════════════════════════════════════════════════════
    print("\n🤖 CHAT MODE: Learning about user preferences and background\n")

    # User tells chat mode about their preferences
    memory.set_preference("timezone", "America/Los_Angeles", "chat")
    memory.set_preference("language", "en", "chat")
    memory.set_preference("name", "Alice", "chat")

    # Chat learns facts about the user
    memory.remember_fact("work", "Senior Software Engineer at Google", "chat")
    memory.remember_fact("education", "BS Computer Science from MIT", "chat")
    memory.remember_fact("interests", "Machine Learning and distributed systems", "chat")

    print("✓ Set preferences: timezone, language, name")
    print("✓ Remembered facts about work, education, interests")

    # ═══════════════════════════════════════════════════════════════════════
    # CODING PERSONALITY reads user context and adds its own patterns
    # ═══════════════════════════════════════════════════════════════════════
    print("\n💻 CODING MODE: Using user context and tracking coding patterns\n")

    # Coding mode retrieves the user context learned by chat
    prefs = memory.get_all_preferences()
    print(f"✓ Retrieved user preferences: {list(prefs.keys())}")

    # Coding mode reads facts from chat
    facts = memory.recall_facts("work")
    print(f"✓ Retrieved work context: {facts[0]['fact']}")

    # Coding mode tracks coding patterns
    memory.record_pattern("language", "Python", "coding")
    memory.record_pattern("language", "Python", "coding")
    memory.record_pattern("language", "Python", "coding")
    memory.record_pattern("language", "Go", "coding")
    memory.record_pattern("language", "Go", "coding")
    memory.record_pattern("framework", "PyTorch", "coding")

    print("✓ Tracked coding patterns: Python (3x), Go (2x), PyTorch (1x)")

    # ═══════════════════════════════════════════════════════════════════════
    # FINANCE PERSONALITY reads all shared data and tracks investments
    # ═══════════════════════════════════════════════════════════════════════
    print("\n📈 FINANCE MODE: Using user context and tracking investments\n")

    # Finance reads user's timezone (to schedule market analysis)
    tz = memory.get_preference("timezone")
    print(f"✓ Retrieved timezone for market hours: {tz}")

    # Finance reads user's education (to gauge sophistication)
    edu_facts = memory.recall_facts("education")
    print(f"✓ User background: {edu_facts[0]['fact']}")

    # Finance tracks investment patterns
    memory.record_pattern("frequent_stock", "AAPL", "fin")
    memory.record_pattern("frequent_stock", "AAPL", "fin")
    memory.record_pattern("frequent_stock", "MSFT", "fin")
    memory.record_pattern("risk_level", "moderate", "fin")

    print("✓ Tracked investment patterns: AAPL (2x), MSFT (1x), risk_level: moderate")

    # ═══════════════════════════════════════════════════════════════════════
    # User feedback across modes
    # ═══════════════════════════════════════════════════════════════════════
    print("\n🎯 FEEDBACK: Recording corrections and praise\n")

    memory.record_feedback("praise", "Your analysis of AAPL earnings was spot-on", "fin")
    memory.record_feedback("correction", "MSFT stock symbol was MSFT not MSF", "chat")
    memory.record_feedback("complaint", "Response was too verbose", "coding")

    print("✓ Recorded feedback: 1 praise, 1 correction, 1 complaint")

    # ═══════════════════════════════════════════════════════════════════════
    # Generate context summaries for each personality
    # ═══════════════════════════════════════════════════════════════════════
    print("\n" + "=" * 70)
    print("CONTEXT SUMMARIES FOR SYSTEM PROMPT INJECTION")
    print("=" * 70)

    print("\n🤖 CHAT MODE CONTEXT:\n")
    context_chat = memory.get_context_summary("chat", max_tokens=300)
    print(context_chat)

    print("\n💻 CODING MODE CONTEXT:\n")
    context_coding = memory.get_context_summary("coding", max_tokens=300)
    print(context_coding)

    print("\n📈 FINANCE MODE CONTEXT:\n")
    context_fin = memory.get_context_summary("fin", max_tokens=300)
    print(context_fin)

    # ═══════════════════════════════════════════════════════════════════════
    # Statistics
    # ═══════════════════════════════════════════════════════════════════════
    print("\n" + "=" * 70)
    print("SHARED MEMORY STATISTICS")
    print("=" * 70)

    stats = memory.get_stats()
    print(f"\nTotal stored data:")
    print(f"  - Preferences: {stats['preferences']}")
    print(f"  - Facts: {stats['facts']}")
    print(f"  - Patterns: {stats['patterns']}")
    print(f"  - Feedback: {stats['feedback']}")

    # Show all patterns
    print(f"\nAll patterns (sorted by frequency):")
    all_patterns = memory.get_patterns(limit=20)
    for pattern in all_patterns:
        print(f"  - {pattern['pattern_type']}: {pattern['pattern_value']} (count={pattern['count']}, source={pattern['source_mode']})")

    # ═══════════════════════════════════════════════════════════════════════
    # Export/Backup capability
    # ═══════════════════════════════════════════════════════════════════════
    print("\n" + "=" * 70)
    print("EXPORT/BACKUP")
    print("=" * 70)

    export = memory.export_json()
    print(f"\nExported {len(export['preferences'])} preferences")
    print(f"Exported {len(export['facts'])} facts")
    print(f"Exported {len(export['patterns'])} patterns")
    print(f"Exported {len(export['feedback'])} feedback entries")

    memory.close()
    print("\n✓ Demo complete!\n")


def demo_mode_switching_context():
    """
    Demonstrate context preservation when switching between modes.
    """
    print("\n" + "=" * 70)
    print("MODE SWITCHING WITH PRESERVED CONTEXT")
    print("=" * 70)

    memory = SharedMemory()

    # Chat mode: set preference
    print("\n1. User in CHAT mode sets a preference:")
    memory.set_preference("coffee_order", "oat latte", "chat")
    print("   → 'Remember my coffee order: oat latte'")

    # Switch to coding mode: coding mode reads the preference
    print("\n2. User switches to CODING mode:")
    coffee = memory.get_preference("coffee_order")
    print(f"   → Coding remembers: '{coffee}'")
    print("   → Responds: 'Starting a coding session. I remember you like an oat latte!'")

    # Back to chat: context is preserved
    print("\n3. User switches back to CHAT mode:")
    coffee_again = memory.get_preference("coffee_order")
    print(f"   → Chat remembers: '{coffee_again}'")
    print("   → Responds: 'Welcome back. Oat latte break time?'")

    memory.close()
    print("\n✓ Context seamlessly preserved across mode switches!\n")


def demo_collaborative_problem_solving():
    """
    Demonstrate how three modes collaborate to solve a complex problem.
    """
    print("\n" + "=" * 70)
    print("COLLABORATIVE PROBLEM SOLVING: Analyzing a Startup Investment")
    print("=" * 70)

    memory = SharedMemory()

    # Finance mode: researches the investment
    print("\n🤖 FINANCE MODE: Initial analysis")
    memory.remember_fact("investment_candidate", "TechStartup Inc seeking $10M Series B", "fin")
    memory.record_pattern("sector_interest", "AI/ML", "fin")
    memory.record_pattern("investment_horizon", "5_years", "fin")
    print("   ✓ Researched company: TechStartup Inc")
    print("   ✓ Noted sector: AI/ML")

    # Coding mode: technical due diligence
    print("\n💻 CODING MODE: Technical evaluation")
    memory.remember_fact("tech_stack", "Python, PyTorch, Kubernetes on AWS", "coding")
    memory.record_pattern("language", "Python", "coding")  # Already knew this
    print("   ✓ Reviewed codebase")
    print("   ✓ Tech stack is solid (Python/PyTorch)")

    # Chat mode: business/team assessment
    print("\n🤖 CHAT MODE: Business strategy review")
    memory.remember_fact("team_quality", "Ex-Google engineers, strong leadership", "chat")
    memory.set_preference("investment_risk_tolerance", "moderate", "chat")
    print("   ✓ Team assessment: Strong")
    print("   ✓ Risk tolerance: Moderate")

    # Finance mode synthesizes all insights
    print("\n📈 FINAL DECISION (using all modes' insights):")
    context = memory.get_context_summary("fin", max_tokens=500)
    print(f"\nCollected insights:\n{context}")

    print("\nRecommendation:")
    print("  ✓ AI/ML sector aligns with your interests")
    print("  ✓ Technical team and stack are solid")
    print("  ✓ Risk profile matches moderate tolerance")
    print("  ✓ RECOMMENDATION: Consider investing (size TBD based on portfolio)")

    memory.close()
    print("\n✓ All three personalities contributed to the analysis!\n")


if __name__ == "__main__":
    print("\n" + "=" * 70)
    print("NeoMind Phase 3: Three-Personality Shared Memory Demo")
    print("=" * 70)

    demo_three_personality_collaboration()
    demo_mode_switching_context()
    demo_collaborative_problem_solving()

    print("\n" + "=" * 70)
    print("Phase 3 Gstack Integration Complete")
    print("=" * 70)
    print("""
The SharedMemory system enables:

✓ Three-personality differentiation (chat/coding/finance)
  - Each personality has its own style and expertise
  - But they share a common knowledge base about the user

✓ Cross-personality memory sharing
  - What chat learns about the user, coding and finance can access
  - Facts, preferences, and patterns propagate across modes
  - Each mode prioritizes its own data in context summaries

✓ Continuous learning
  - Every interaction adds to shared knowledge
  - User feedback (corrections, praise) influences all modes
  - Patterns accumulate over time for better personalization

✓ Production-ready
  - Minimal dependencies (sqlite3 + stdlib only)
  - Thread-safe concurrent access (WAL mode)
  - Atomic writes with proper error handling
  - Works in CLI and Docker environments
    """)
