"""Test clients release their app's database pools on normal and exceptional exits."""

import inspect
from contextlib import AsyncExitStack, asynccontextmanager, nullcontext
from types import SimpleNamespace

import pytest
from fastapi import FastAPI

from review_platform.settings import Settings
from tests import conftest
from tests.support import clients as client_helpers

pytestmark = pytest.mark.no_db


@pytest.mark.anyio
@pytest.mark.parametrize("entry", ["fixture", "shared"])
@pytest.mark.parametrize("failed_test", [False, True])
async def test_app_pools_are_disposed_after_clients_close(monkeypatch, entry, failed_test):
    app = FastAPI()
    opened = []
    disposed = []

    def dispose(name):
        assert opened and all(client.is_closed for client in opened)
        disposed.append(name)

    app.state.context = SimpleNamespace(
        database=SimpleNamespace(dispose=lambda: dispose("review")),
    )
    monkeypatch.setattr(conftest, "create_app", lambda settings: app)
    monkeypatch.setattr(client_helpers, "create_app", lambda settings: app)
    settings = Settings(_env_file=None)
    outcome = pytest.raises(RuntimeError, match="test failed") if failed_test else nullcontext()

    with outcome:
        async with AsyncExitStack() as stack:
            if entry == "shared":
                opened.extend(await client_helpers.open_clients(stack, settings, 2))
            else:
                fixture = asynccontextmanager(inspect.unwrap(conftest.client))
                opened.append(await stack.enter_async_context(fixture(settings)))
            assert disposed == []
            if failed_test:
                raise RuntimeError("test failed")

    assert sorted(disposed) == ["review"]
