"""The local Store must give the model exactly what statevector's Dataset gave it."""
import pandas as pd
import pytest

from nabla import data, live, model, store


@pytest.fixture(scope="module")
def st(root):
    return store.Store(root)


def test_tables_match_dataset(ds, st):
    assert st.universe() == ds.universe()
    assert st.trading_days() == ds.trading_days()
    for panel in ("stocks_daily", "state_vector", "fundamentals_actuals"):
        a = ds.get(panel, limit=data.BIG).sort_values(["ticker", "date"]).reset_index(drop=True)
        b = st.get(panel, limit=data.BIG).sort_values(["ticker", "date"]).reset_index(drop=True)
        pd.testing.assert_frame_equal(a, b)
    pd.testing.assert_frame_equal(ds.benchmark("SPX"), st.benchmark("SPX"))
    pd.testing.assert_frame_equal(data.load_splits(ds), data.load_splits(st))


def test_book_is_identical(ds, st):
    cfg = model.load_config()
    a, b = live.build_book(ds, cfg), live.build_book(st, cfg)
    assert a["holdings"] == b["holdings"]
    assert a["as_of"] == b["as_of"]


def test_missing_root_is_a_clear_error(tmp_path):
    with pytest.raises(FileNotFoundError, match="bbg_ingest"):
        store.Store(tmp_path)
