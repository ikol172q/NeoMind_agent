# agent/finance/__init__.py
"""
NeoMind Finance — Personal Finance & Investment Intelligence Module.

Provides multi-source news aggregation, encrypted local memory,
quantitative analysis tools, and mobile sync capabilities.

Short mode name: 'fin'
"""

__all__ = [
    'HybridSearchEngine',
    'FinanceDataHub',
    'SecureMemoryStore',
    'NewsDigestEngine',
    'QuantEngine',
    'DiagramGenerator',
    'MobileSyncGateway',
    'SourceTrustTracker',
    'FinanceDashboard',
    'RSS_FEEDS',
]


def get_finance_components(config=None):
    """Lazy factory — import and instantiate all finance components.

    Returns a dict of initialized components. Handles missing optional
    dependencies gracefully.
    """
    components = {}

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
        from .quant_engine import QuantEngine
        components['quant'] = QuantEngine()
    except ImportError as e:
        components['quant'] = None
        print(f"⚠️  Quant engine unavailable: {e}")

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

    return components
