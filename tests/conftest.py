import pytest

from harborlight_tutor.runner import run_offline


@pytest.fixture(scope="session")
def comparison():
    return run_offline("improved")
