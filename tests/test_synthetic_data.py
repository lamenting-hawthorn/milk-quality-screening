import pandas as pd

import pipeline
import synthetic_data


def _read_generated_frames(directory):
    return [pd.read_excel(path, engine="openpyxl") for path in sorted(directory.glob("*.xlsx"))]


def test_synthetic_generator_is_content_deterministic(tmp_path):
    first_dir = tmp_path / "first"
    second_dir = tmp_path / "second"

    first = synthetic_data.generate_synthetic_workbooks(first_dir, seed=1234)
    second = synthetic_data.generate_synthetic_workbooks(second_dir, seed=1234)

    assert first["records"] == second["records"] == 1200
    assert first["injected_event"] == second["injected_event"]
    for first_frame, second_frame in zip(_read_generated_frames(first_dir), _read_generated_frames(second_dir)):
        pd.testing.assert_frame_equal(first_frame, second_frame)


def test_generated_workbooks_are_accepted_by_public_parser(tmp_path):
    input_dir = tmp_path / "input"
    synthetic_data.generate_synthetic_workbooks(input_dir)

    loaded = pipeline.load_all(input_dir)

    assert len(loaded) == 1200
    assert loaded["facility"].unique().tolist() == ["FacilityAlpha"]
    assert sorted(loaded["file_month"].unique().tolist()) == [1, 2, 3, 4]

