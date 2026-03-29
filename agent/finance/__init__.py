# agent/finance/__init__.py
"""
NeoMind Finance — Personal Finance & Investment Intelligence Module.

Provides multi-source news aggregation, encrypted local memory,
quantitative analysis tools, and mobile sync capabilities.

Short mode name: 'fin'

Architecture note (2026-03-28 redesign):
  Finance-ONLY modules (5): quant_engine, data_hub, fin_rag,
      investment_personas, response_validator
  Shared services (7): hybrid_search, secure_memory, news_digest,
      diagram_gen, dashboard, source_registry, memory_bridge
      → These now live in agent/services/ (stubs redirect imports)
  Integration modules (3): telegram_bot, openclaw_*, mobile_sync
      → These now live in agent/integration/

  get_finance_only_components() — returns only the 5 finance-specific modules.
  get_finance_components()      — backward-compat, returns all (finance + shared).
"""

__all__ = [
    'get_finance_components',
    'get_finance_only_components',
    'QuantEngine',
    'FinanceDataHub',
    'FinRAG',
    'InvestmentPersonas',
    'FinanceResponseValidator',
]


def get_finance_only_components(config=None):
    """Initialize finance-ONLY components. Shared services are in ServiceRegistry.

    Returns a dict with keys: quant, data_hub, rag, personas, validator.
    Used by FinancePersonality.on_activate() in Phase C.
    """
    components = {}

    for name, module_path, cls_name in [
        ('quant', 'agent.finance.quant_engine', 'QuantEngine'),
        ('data_hub', 'agent.finance.data_hub', 'FinanceDataHub'),
        ('rag', 'agent.finance.fin_rag', 'FinRAG'),
        ('personas', 'agent.finance.investment_personas', 'PERSONAS'),
        ('validator', 'agent.finance.response_validator', 'get_finance_validator'),
    ]:
        try:
            mod = __import__(module_path, fromlist=[cls_name])
            factory_or_cls = getattr(mod, cls_name)
            if cls_name == 'PERSONAS':
                components[name] = factory_or_cls          # Already a dict
            elif cls_name == 'get_finance_validator':
                components[name] = factory_or_cls(strict=False)  # Call factory
            else:
                components[name] = factory_or_cls()         # Instantiate class
        except ImportError:
            components[name] = None

    return components


def get_finance_components(config=None):
    """Lazy factory — import and instantiate ALL finance components.

    Returns a dict of initialized components including both finance-only
    and shared service modules. Handles missing optional dependencies gracefully.

    NOTE: This function exists for backward compatibility. Integration modules
    (telegram_bot, openclaw_skill, mobile_sync) still call this and expect
    the full dict. Once those are migrated to use ServiceRegistry directly,
    this function will be replaced by get_finance_only_components().
    """
    components = {}

    # ── Shared services (backward-compat — stubs redirect to agent/services/) ──

    try:
        from .hybrid_search import HybridSearchEngine
        components['search'] = HybridSearchEngine(config)
    except ImportError as e:
        components['search'] = None
        print(f"⚠️  Finance search unavailable: {e}")

    try:
        from .data_hub import FinanceDataHub
        components['data_hub'] = FinanceDataHub(config)
    except ImportError as e:
        components['data_hub'] = None
        print(f"⚠️  Finance data hub unavailable: {e}")

    try:
        from .secure_memory import SecureMemoryStore
        components['memory'] = SecureMemoryStore(config)
    except ImportError as e:
        components['memory'] = None
        print(f"⚠️  Secure memory unavailable: {e}")

    try:
        from .news_digest import NewsDigestEngine
        components['digest'] = NewsDigestEngine(
            search=components.get('search'),
            data_hub=components.get('data_hub'),
            memory=components.get('memory'),
        )
    except ImportError as e:
        components['digest'] = None
        print(f"⚠️  News digest unavailable: {e}")

    try:
        from .diagram_gen import DiagramGenerator
        components['diagram'] = DiagramGenerator()
    except ImportError as e:
        components['diagram'] = None
        print(f"⚠️  Diagram generator unavailable: {e}")

    try:
        from .dashboard import FinanceDashboard
        components['dashboard'] = FinanceDashboard()
    except ImportError as e:
        components['dashboard'] = None
        print(f"⚠️  Dashboard unavailable: {e}")

    try:
        from .mobile_sync import MobileSyncGateway
        sync = MobileSyncGateway(memory_store=components.get('memory'))
        # Auto-initialize OpenClaw if credentials are available
        sync.init_openclaw(components)
        components['sync'] = sync
    except ImportError as e:
        components['sync'] = None
        print(f"⚠️  Mobile sync unavailable: {e}")

    # ── Finance-only modules ────────────────────────────────────────────

    try:
        from .quant_engine import QuantEngine
        components['quant'] = QuantEngine()
    except ImportError as e:
        components['quant'] = None
        print(f"⚠️  Quant engine unavailable: {e}")

    try:
        from .fin_rag import FinRAG
        components['rag'] = FinRAG()
        # Wire RAG into digest engine for document-grounded debates
        if components.get('digest'):
            components['digest']._rag = components['rag']
    except ImportError:
        components['rag'] = None  # faiss-cpu / sentence-transformers not installed

    try:
        from .investment_personas import PERSONAS
        components['personas'] = PERSONAS
    except ImportError:
        components['personas'] = None

    try:
        from .response_validator import get_finance_validator
        components['validator'] = get_finance_validator(strict=False)
    except ImportError:
        components['validator'] = None

    return components
