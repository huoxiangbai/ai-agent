from __future__ import annotations

import os

import pytest
from pydantic import SecretStr

from reactor_backend.config import Settings
from reactor_backend.infrastructure.database import Database


@pytest.mark.integration
@pytest.mark.asyncio
async def test_mysql_ping_against_explicit_test_database() -> None:
    url = os.getenv("TEST_MYSQL_URL")
    if not url:
        pytest.skip("TEST_MYSQL_URL is required for the MySQL integration test")

    database = Database(Settings(database_url=SecretStr(url)))
    await database.start()
    try:
        await database.ping()
    finally:
        await database.close()
