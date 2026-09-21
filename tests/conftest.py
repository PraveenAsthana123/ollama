"""Shared, repo-wide test fixtures.

gateway_auth bypass is autouse and global here specifically because it's a
cross-cutting concern added AFTER several test files already existed
(test_injection_guard.py, test_gateway_token_controls.py) -- without this,
every test that calls execution_gateway.execute() anywhere in the suite
would need its own gateway_auth mock, and it's exactly the kind of thing
that's easy to add to one file and silently miss in another (which is
literally what happened the first time this was wired in without a shared
conftest.py: three separate test files broke because each had rolled its
own isolation instead of sharing one). Other isolation concerns (event log
path, Redis client, semantic cache) stay local to the files that need them
-- they're not universal the way auth now is.
"""

from unittest.mock import patch

import pytest

import scripts.execution_gateway as gateway


@pytest.fixture(autouse=True)
def _bypass_gateway_auth_by_default():
    with patch.object(gateway.gateway_auth, "authorized", return_value=True):
        yield
