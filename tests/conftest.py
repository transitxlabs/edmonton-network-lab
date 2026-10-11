"""Fixture tests run offline, including accidental network use."""

import socket

import pytest


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def rejected(*args, **kwargs):
        raise AssertionError("Network access is disabled in fixture tests")

    monkeypatch.setattr(socket.socket, "connect", rejected)
    monkeypatch.setattr(socket, "create_connection", rejected)
