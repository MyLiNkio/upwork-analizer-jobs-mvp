from pathlib import Path

import pytest

from benchmark import openai_batch


def test_submit_passes_jsonl_path_to_openai_file_upload(monkeypatch):
    captured = {}

    class Files:
        def create(self, *, file, purpose):
            captured["file"] = file
            captured["purpose"] = purpose
            return type("UploadedFile", (), {"id": "file-123"})()

    class Batches:
        def create(self, **kwargs):
            captured["batch"] = kwargs
            return type("Batch", (), {"id": "batch-123", "status": "validating"})()

    monkeypatch.setattr(openai_batch, "client", lambda: type("Client", (), {"files": Files(), "batches": Batches()})())

    result = openai_batch.submit(Path("batch_001.jsonl"), {"stage": "evaluation"}, "24h")

    assert captured["file"] == Path("batch_001.jsonl")
    assert captured["purpose"] == "batch"
    assert result["input_file_id"] == "file-123"
    assert result["batch_id"] == "batch-123"


def test_submit_rejects_non_jsonl_batch_input(monkeypatch):
    monkeypatch.setattr(openai_batch, "client", lambda: pytest.fail("client must not be created"))

    with pytest.raises(ValueError, match="must use the .jsonl extension"):
        openai_batch.submit(Path("batch_001.json"), {"stage": "evaluation"}, "24h")
