import pytest

from vidura.contract import (
    CONTRACT_VERSION,
    ContractVersionMismatch,
    enforce_payload_budget,
    validate_contract_version,
)


def test_validate_contract_version_accepts_matching_version():
    validate_contract_version({"contract_version": CONTRACT_VERSION})  # no raise


def test_validate_contract_version_rejects_mismatch():
    with pytest.raises(ContractVersionMismatch):
        validate_contract_version({"contract_version": CONTRACT_VERSION + 1})


def test_validate_contract_version_rejects_missing_field():
    with pytest.raises(ContractVersionMismatch):
        validate_contract_version({})


def test_payload_budget_keeps_all_chunks_under_budget():
    chunks = ["a" * 100, "b" * 100]
    result = enforce_payload_budget(chunks, budget_chars=1000)
    assert result == chunks


def test_payload_budget_drops_oldest_chunks_first():
    chunks = ["old" * 100, "new" * 100]
    result = enforce_payload_budget(chunks, budget_chars=400)
    assert result == ["new" * 100]


def test_payload_budget_always_keeps_at_least_one_chunk():
    chunks = ["x" * 10000]
    result = enforce_payload_budget(chunks, budget_chars=10)
    assert result == chunks
