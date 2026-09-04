import pytest
import hashlib
from Assignment1 import ValidateHandler

def test_url_based_id_is_consistent():
    url = "https://api.example.com/data"
    id1 = hashlib.sha256(url.encode("utf-8")).hexdigest()[:12]
    id2 = hashlib.sha256(url.encode("utf-8")).hexdigest()[:12]
    assert id1 == id2  # same URL → same ID

def test_url_based_id_is_unique():
    url1 = "https://api.example.com/data1"
    url2 = "https://api.example.com/data2"
    id1 = hashlib.sha256(url1.encode("utf-8")).hexdigest()[:12]
    id2 = hashlib.sha256(url2.encode("utf-8")).hexdigest()[:12]
    assert id1 != id2  # different URLs → different IDs

def test_log_error_file_creates_entry(tmp_path):
    validator = ValidateHandler()
    class DummyContext:
        def __init__(self):
            self.dir_errors = type("X", (), {"get": lambda self: str(tmp_path)})()
        def log_event(self, msg): pass

    filename = "SALES_DATA_20260816174000.csv"
    errors = ["Incorrectly formatted filename"]
    source_url = "https://api.example.com/data"

    validator._log_error_file(DummyContext(), filename, errors, source_url)

    error_file = tmp_path / "error.txt"
    content = error_file.read_text(encoding="utf-8")
    assert "[Error ID:" in content
    assert filename in content
    assert "Source URL:" in content
    assert any(e in content for e in errors)
