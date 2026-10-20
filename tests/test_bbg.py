"""Terminal connector without a Terminal: helpers and failure modes."""
import pandas as pd
import pytest

from nabla import bloomberg as bbg


class FakeEl:
    def __init__(self, name, value=None, children=None):
        self._name, self._value, self._children = name, value, children or []

    def name(self): return self._name
    def getValue(self): return self._value
    def isComplexType(self): return bool(self._children)
    def isArray(self): return False
    def numElements(self): return len(self._children)
    def getElement(self, i): return self._children[i]


def test_security_adds_yellow_key():
    assert bbg.security("AAPL") == "AAPL US Equity"
    assert bbg.security("SPX Index") == "SPX Index"


def test_flat_skips_complex_elements():
    el = FakeEl("fieldData", children=[FakeEl("PX_LAST", 1.5), FakeEl("bulk", children=[FakeEl("x", 1)])])
    assert bbg._flat(el) == {"PX_LAST": 1.5}


def test_missing_blpapi_is_a_clear_error():
    try:
        import blpapi  # noqa: F401
        pytest.skip("blpapi installed")
    except ImportError:
        with pytest.raises(bbg.BloombergError, match="not installed"):
            bbg.Terminal()


def test_save_writes_pull_time(tmp_path, monkeypatch):
    monkeypatch.setattr(bbg, "OUT", tmp_path)
    f = bbg.save(bbg._stamp(pd.DataFrame({"a": [1]})), "t")
    assert f.exists() and f.with_suffix(".json").exists()
