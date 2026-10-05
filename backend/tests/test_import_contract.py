from pathlib import Path


def test_required_import_columns_are_documented():
    readme = Path(__file__).parents[2].joinpath('README.md').read_text()
    assert 'Products:' in readme
    assert 'Expenses:' in readme
    assert 'Sales:' in readme
