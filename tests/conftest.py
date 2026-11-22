"""Keep API unit tests independent of live local benchmark processes."""
import pytest


@pytest.fixture(autouse=True)
def isolated_api_jobs(monkeypatch, tmp_path):
    from lab import api
    from lab.benchmark import BenchmarkJobs
    monkeypatch.setattr(api, 'jobs', BenchmarkJobs(tmp_path))
