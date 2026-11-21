import json
import logging
import sys

import pytest
from pydantic import ValidationError

from app.core.config import DEV_JWT_SECRET, Settings
from app.core.logging import JsonFormatter, configure_logging


def test_production_refuses_the_dev_jwt_secret() -> None:
    with pytest.raises(ValidationError, match="JWT_SECRET_KEY"):
        Settings(app_env="production", jwt_secret_key=DEV_JWT_SECRET)


def test_production_accepts_a_real_secret() -> None:
    settings = Settings(app_env="production", jwt_secret_key="a-real-secret-from-the-host")
    assert settings.app_env == "production"


def test_json_formatter_includes_extra_fields_and_exceptions() -> None:
    try:
        raise ValueError("boom")
    except ValueError:
        exc_info = sys.exc_info()
    record = logging.LogRecord(
        "gatesense", logging.ERROR, __file__, 1, "failed %s", ("job",), exc_info=exc_info
    )
    record.user_id = "u-1"

    line = json.loads(JsonFormatter().format(record))

    assert line["message"] == "failed job"
    assert line["level"] == "ERROR"
    assert line["user_id"] == "u-1"
    assert "ValueError: boom" in line["exception"]


def test_configure_logging_routes_uvicorn_through_root() -> None:
    configure_logging("debug")

    assert logging.getLogger().level == logging.DEBUG
    assert isinstance(logging.getLogger().handlers[0].formatter, JsonFormatter)
    assert logging.getLogger("uvicorn.access").disabled
