import socket

import pytest

from app import config
from tests.conftest import NetworkBlocked


def test_guard_blocks_real_network():
    with pytest.raises(NetworkBlocked):
        socket.create_connection(("example.com", 443), timeout=1)


def test_no_developer_env_leaks():
    s = config.get_settings()
    assert s.model_embed == "" and s.model_fast == "" and s.gcp_project == "test-project"
