import pytest
from lab.core import Lab, valid_name


@pytest.mark.parametrize('name', ['../other', 'a/b', '', 'a b', '..'])
def test_experiment_paths_stay_inside_workspace(name):
    with pytest.raises(ValueError):
        valid_name(name)


def test_document_tool_rejects_escape_without_reading_files():
    lab = object.__new__(Lab)
    with pytest.raises(ValueError, match='inside fixtures'):
        lab.ingest_document('alice', '../.env')


def test_document_tool_rejects_absolute_path():
    lab = object.__new__(Lab)
    with pytest.raises(ValueError, match='inside fixtures'):
        lab.ingest_document('alice', 'C:/Windows/system.ini')
