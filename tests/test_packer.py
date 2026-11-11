import copy
import json
import subprocess

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from context_budgeter.api import app
from context_budgeter.packer import Chunk, PackRequest, pack, render


def chunk(id="a", source="doc", text="Alpha", score=0.9):
    return {"id": id, "source": source, "text": text, "score": score}


def run(chunks=None, **kwargs):
    return pack(
        PackRequest.model_validate(
            {"chunks": chunks if chunks is not None else [chunk()], "max_bytes": 1000, **kwargs}
        )
    )


def test_exact_bytes():
    r = run()
    assert r.used_bytes == len(r.context.encode("utf-8"))
    assert r.citations == {"a": "doc"}


def test_empty():
    assert run([]).context == ""


def test_zero_budget():
    r = run(max_bytes=0)
    assert r.selected_ids == [] and r.skipped[0].reason == "over_budget"


def test_exact_fit_and_one_less():
    cost = len(render(Chunk.model_validate(chunk())).encode())
    assert run(max_bytes=cost).selected_ids == ["a"]
    assert not run(max_bytes=cost - 1).selected_ids


def test_separator_counted():
    chunks = [chunk(), chunk("b", text="Beta")]
    r = run(chunks)
    assert "\n\n" in r.context
    assert run(chunks, max_bytes=r.used_bytes - 1).selected_ids == ["a"]


@pytest.mark.parametrize("text", ["Привет мир", "你好世界", "🌍 café", "a\nb\tc", "é"])
def test_unicode(text):
    r = run([chunk(text=text)])
    assert r.used_bytes == len(r.context.encode())
    assert r.used_bytes <= r.available_bytes


def test_reserved():
    r = run(max_bytes=50, reserved_bytes=30)
    assert r.available_bytes == 20
    assert r.used_bytes <= 20


def test_score_order():
    assert run([chunk("a", score=0.2), chunk("b", text="Beta", score=0.9)]).selected_ids == [
        "b",
        "a",
    ]


def test_tie_order():
    assert run([chunk("b", text="Beta"), chunk("a")]).selected_ids == ["a", "b"]


def test_reorder_stable():
    chunks = [chunk(), chunk("b", text="Beta")]
    assert run(chunks) == run(list(reversed(chunks)))


def test_normalized_duplicate():
    r = run([chunk(), chunk("b", text="  ALPHA  ")])
    assert r.selected_ids == ["a"] and r.skipped[0].reason == "duplicate_text"


def test_source_limit():
    r = run([chunk(), chunk("b", text="Beta")], per_source=1)
    assert r.skipped[0].reason == "source_limit"


def test_oversized_does_not_block_smaller():
    r = run([chunk(text="x" * 2000), chunk("b", text="Beta", score=0.1)], max_bytes=50)
    assert r.selected_ids == ["b"]


def test_rejected_duplicate_does_not_reserve_fingerprint():
    r = run([chunk(source="x" * 200), chunk("b", source="d")], max_bytes=50)
    assert r.selected_ids == ["b"]


def test_no_mutation():
    chunks = [chunk()]
    before = copy.deepcopy(chunks)
    run(chunks)
    assert chunks == before


@pytest.mark.parametrize(
    "change",
    [
        {"max_bytes": -1},
        {"reserved_bytes": 1001},
        {"per_source": 0},
        {"max_bytes": True},
        {"unknown": 1},
    ],
)
def test_invalid_limits(change):
    with pytest.raises(ValidationError):
        run(**change)


@pytest.mark.parametrize(
    "change",
    [
        {"id": "bad\nid"},
        {"source": "bad source"},
        {"text": "  "},
        {"score": float("nan")},
        {"score": float("inf")},
        {"score": -0.1},
        {"unexpected": 1},
    ],
)
def test_invalid_chunk(change):
    with pytest.raises(ValidationError):
        run([dict(chunk(), **change)])


def test_duplicate_id():
    with pytest.raises(ValidationError):
        run([chunk(), chunk()])


def test_large_input():
    chunks = [chunk(str(i), source=str(i), text=f"Chunk {i}", score=0.5) for i in range(300)]
    r = run(chunks, max_bytes=300)
    assert r.used_bytes <= 300 and r.used_bytes == len(r.context.encode())


def test_api():
    c = TestClient(app)
    assert c.post("/pack", json={"chunks": [chunk()], "max_bytes": 100}).json()["selected_ids"] == [
        "a"
    ]
    assert c.post("/pack", json={"chunks": [chunk()], "max_bytes": -1}).status_code == 422
    assert c.get("/health").status_code == 200


def test_cli(tmp_path):
    p = tmp_path / "r.json"
    p.write_text(json.dumps({"chunks": [chunk()], "max_bytes": 100}))
    result = subprocess.run(["context-pack", str(p)], check=False, capture_output=True, text=True)
    assert result.returncode == 0 and json.loads(result.stdout)["selected_ids"] == ["a"]
    p.write_text("{}")
    assert (
        subprocess.run(["context-pack", str(p)], check=False, capture_output=True).returncode == 2
    )
