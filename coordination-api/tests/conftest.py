import os
import tempfile

import pytest

from app.config import Settings


@pytest.fixture
def settings(tmp_path):
    db_path = str(tmp_path / "test.db")
    return Settings(
        PORT=8000,
        INTERNAL_API_SECRET="test-secret",
        USE_SQLITE=True,
        SQLITE_DB_PATH=db_path,
        BRIGHTDATA_ACCOUNT_ID="C12345",
        BRIGHTDATA_ZONE="residential",
        BRIGHTDATA_PASSWORD="brightpass",
        BRIGHTDATA_HOST="brd.superproxy.io",
        BRIGHTDATA_PORT=33335,
    )
