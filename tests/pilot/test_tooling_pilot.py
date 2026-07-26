import json
from pathlib import Path


def test_tooling_pilot_round_trips_utf8_artifact(tmp_path: Path) -> None:
    artifact = tmp_path / "nabla-пилот.json"
    expected = {
        "task_id": "BOOT-PILOT-001",
        "status": "ok",
    }

    artifact.write_text(
        json.dumps(expected, ensure_ascii=False),
        encoding="utf-8",
    )

    assert json.loads(artifact.read_text(encoding="utf-8")) == expected
