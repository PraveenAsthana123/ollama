import shutil
import tempfile
from pathlib import Path

import scripts.config_integrity as config_integrity


def test_compute_checksums_covers_every_real_yaml_file():
    checksums = config_integrity.compute_checksums()
    real_files = {p.name for p in config_integrity.CONFIG_DIR.glob("*.yaml")}
    assert set(checksums) == real_files
    assert len(checksums) > 5  # sanity: this repo has many real config files


def test_committed_baseline_matches_current_config():
    """The real, committed CHECKSUMS.json must match the real, current
    config -- if this fails, someone edited a config file without running
    `config_integrity.py update`, exactly the drift this module exists to
    catch. Same discipline as the CI gate, run here so `pytest` alone
    catches it too."""
    result = config_integrity.check_drift()
    assert result["drifted"] is False, (
        f"Committed config/CHECKSUMS.json is out of date: {result}. "
        f"Run `python3 scripts/config_integrity.py update` and commit the result."
    )


def test_detects_a_real_modification():
    with tempfile.TemporaryDirectory() as tmp:
        tmp_dir = Path(tmp)
        shutil.copy(config_integrity.CONFIG_DIR / "inference-control-tower.yaml", tmp_dir)
        baseline = config_integrity.compute_checksums(tmp_dir)

        (tmp_dir / "inference-control-tower.yaml").write_text(
            (tmp_dir / "inference-control-tower.yaml").read_text() + "\n# tampered\n"
        )
        after = config_integrity.compute_checksums(tmp_dir)

    assert after["inference-control-tower.yaml"] != baseline["inference-control-tower.yaml"]


def test_detects_an_added_file():
    with tempfile.TemporaryDirectory() as tmp:
        tmp_dir = Path(tmp)
        (tmp_dir / "a.yaml").write_text("x: 1\n")
        baseline = config_integrity.compute_checksums(tmp_dir)
        (tmp_dir / "b.yaml").write_text("y: 2\n")
        after = config_integrity.compute_checksums(tmp_dir)

    added = set(after) - set(baseline)
    assert added == {"b.yaml"}


def test_detects_a_removed_file():
    with tempfile.TemporaryDirectory() as tmp:
        tmp_dir = Path(tmp)
        (tmp_dir / "a.yaml").write_text("x: 1\n")
        (tmp_dir / "b.yaml").write_text("y: 2\n")
        baseline = config_integrity.compute_checksums(tmp_dir)
        (tmp_dir / "b.yaml").unlink()
        after = config_integrity.compute_checksums(tmp_dir)

    removed = set(baseline) - set(after)
    assert removed == {"b.yaml"}
