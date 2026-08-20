"""The investment project the web/lattice tests are allowed to write to.

These tests do not read a dashboard, they *drive* one: they empty the
watchlist, reset the paper portfolio, seed symbols, and place orders. For
as long as they pointed at ``fin-core`` that meant every full suite run
wiped and rewrote the owner's real watchlist and real paper positions,
and left whatever the last test happened to seed.

That is also why the suite's tail kept reshuffling. Thirteen modules
cleared the same shared watchlist, so which tests failed depended on
collection order rather than on any defect — see the module-scoped
restore fixture in conftest.py, which patched the symptom.

``test-fixture`` is a registered project that exists only for this. It
distils a real lattice (11 observations / 5 themes / 3 sub-themes /
3 calls when this was written, against fin-core's 5 / 3 / 0), so pointing
at it widens coverage rather than trading flakiness for mass skipping —
the calls-dependent tests run here instead of skipping as undistilled.

Override with NEOMIND_TEST_PROJECT to aim the suite somewhere else. Aim
it at a project whose data you are willing to lose.
"""
from __future__ import annotations

import os

PROJECT = os.environ.get("NEOMIND_TEST_PROJECT", "test-fixture")
