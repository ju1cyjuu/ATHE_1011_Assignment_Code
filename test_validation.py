import pytest
import csv
from pathlib import Path
from Assignment1 import ValidateHandler, EXPECTED_HEADERS, NUM_COLUMNS, FILENAME_PATTERN


@pytest.fixture
def validator():
    return ValidateHandler()

@pytest.fixture
def valid_csv(tmp_path):
    file_path = tmp_path / "SALES_DATA_20260816174000.csv"
    with open(file_path, "w", encoding="utf-8") as f:
        f.write(",".join(EXPECTED_HEADERS) + "\n")
        f.write("1001,2026-08-16 17:40:00,1,2001,5,10.0,50.0,cash\n")
    return file_path

@pytest.fixture
def invalid_csv_headers(tmp_path):
    file_path = tmp_path / "SALES_DATA_20260816174000.csv"
    with open(file_path, "w", encoding="utf-8") as f:
        f.write("wrong,headers,here\n")
        f.write("bad,data,row\n")
    return file_path

def test_filename_pattern_valid():
    assert FILENAME_PATTERN.match("SALES_DATA_20260816174000.csv")

def test_filename_pattern_invalid():
    assert not FILENAME_PATTERN.match("WRONGFILE.csv")

def test_valid_csv_passes(validator, valid_csv):
    errors = validator._validate_csv_file(valid_csv)
    assert errors == []

def test_column_count_mismatch(tmp_path, validator):
    file_path = tmp_path / "SALES_DATA_20260816174000.csv"
    with open(file_path, "w", encoding="utf-8") as f:
        f.write(",".join(EXPECTED_HEADERS) + "\n")
        f.write("1001,2026-08-16 17:40:00,1\n")  # only 3 columns
    errors = validator._validate_csv_file(file_path)
    assert any("column count" in e.lower() for e in errors)

def test_duplicate_transaction_id(tmp_path, validator):
    file_path = tmp_path / "SALES_DATA_20260816174000.csv"
    with open(file_path, "w", encoding="utf-8") as f:
        f.write(",".join(EXPECTED_HEADERS) + "\n")
        f.write("1001,2026-08-16 17:40:00,1,2001,5,10.0,50.0,cash\n")
        f.write("1001,2026-08-16 17:41:00,2,2002,3,20.0,60.0,cash\n")
    errors = validator._validate_csv_file(file_path)
    assert any("duplicate transaction_id" in e.lower() for e in errors)
    
def test_negative_quantity(tmp_path, validator):
    file_path = tmp_path / "SALES_DATA_20260816174000.csv"
    with open(file_path, "w", encoding="utf-8") as f:
        f.write(",".join(EXPECTED_HEADERS) + "\n")
        f.write("1002,2026-08-16 17:40:00,1,2001,-5,10.0,-50.0,cash\n")
    errors = validator._validate_csv_file(file_path)
    assert any("quantity must be > 0" in e.lower() for e in errors)
    assert any("total amount must be > 0" in e.lower() for e in errors)
