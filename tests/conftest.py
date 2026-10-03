import os

import pytest

from nabla import synthetic


@pytest.fixture(scope="session")
def root(tmp_path_factory):
    r = synthetic.build(tmp_path_factory.mktemp("sv"), n_tickers=40)
    os.environ["SV_DATA_ROOT"] = str(r)
    return r


@pytest.fixture(scope="session")
def ds(root):
    from statevector import Dataset
    return Dataset(str(root))
