from dataclasses import asdict, replace
import json
import sys
from pathlib import Path

import cv2
import numpy as np
import pytest

from experiments.fb_v5.poc import (PrepareOptions, StageCache, crop, digest,
    evaluate_detection, morph_regions, parse_parts, parse_whole, prepare,
    reading_scores, recognize_regions, split_layout, stage_keys, read_regions, interpret_regions, iou)


def keys(**changes):
    options = dict(source="image-a", prepare_options=asdict(PrepareOptions()),
                   detector="detector-a", model="weights-sha-a", layout="layout-a", grouping="groups-a")
    options.update(changes)
    return stage_keys(**options)


@pytest.mark.parametrize("change,affected", [
    (dict(source="image-b"), {"prepared", "regions", "readings", "grouping"}),
    (dict(prepare_options={"threshold": 160}), {"prepared", "regions", "readings", "grouping"}),
    (dict(detector="detector-b"), {"regions", "readings", "grouping"}),
    (dict(model="weights-b"), {"readings", "grouping"}),
    (dict(layout="layout-b"), {"readings", "grouping"}),
    (dict(grouping="groups-b"), {"grouping"}),
])
def test_stage_dependencies(change, affected):
    a, b = keys(), keys(**change)
    assert {stage for stage in a if a[stage] != b[stage]} == affected


def test_cache_reuses_real_outputs_and_recovers_corruption(tmp_path):
    cache = StageCache(tmp_path)
    calls = []
    def compute():
        calls.append(1)
        return [{"box": [1, 2, 5, 9]}]
    key = digest("test")
    assert cache.get_or_compute("regions", key, compute) == (compute_result := [{"box": [1, 2, 5, 9]}], False)
    assert cache.get_or_compute("regions", key, compute) == (compute_result, True)
    assert len(calls) == 1
    (tmp_path/"regions"/(key+".json")).write_text("{broken")
    assert not cache.get_or_compute("regions", key, compute)[1]
    assert len(calls) == 2
    with pytest.raises(ValueError):
        cache.get_or_compute("../other", key, compute)


def test_preparation_cache_preserves_arrays(tmp_path):
    cache = StageCache(tmp_path)
    a = prepare(np.full((100, 100, 3), 255, np.uint8))
    key = digest("arrays")
    assert not cache.get_or_compute("prepared", key, lambda: a)[1]
    b, hit = cache.get_or_compute("prepared", key, lambda: pytest.fail("cached"))
    assert hit and all(np.array_equal(a[k], b[k]) for k in a)
    (tmp_path/"prepared"/(key+".npz")).write_bytes(b"not a zip")
    assert not cache.get_or_compute("prepared", key, lambda: a)[1]


def synthetic_sounding():
    image = np.full((110, 170, 3), 255, np.uint8)
    # Detached 1 and 0 in main integer, small lowered decimetre to the right.
    cv2.line(image, (20, 35), (20, 68), (0, 0, 0), 3)
    cv2.ellipse(image, (39, 51), (8, 17), 0, 0, 360, (0, 0, 0), 3)
    cv2.ellipse(image, (56, 67), (4, 7), 0, 0, 360, (0, 0, 0), 2)
    return image


def test_preview_detection_has_no_recognition_side_effects():
    before = set(sys.modules)
    image = synthetic_sounding()
    prepared = prepare(image)
    regions = morph_regions(prepared)
    assert len(regions) == 1
    assert not any(m.startswith(("paddleocr", "paddle.")) for m in set(sys.modules)-before)
    assert np.array_equal(image, synthetic_sounding())


def test_straight_line_mask_does_not_erase_isolated_one():
    image = synthetic_sounding()
    cv2.line(image, (145, 0), (145, 109), (0, 0, 0), 2)
    # Use a large enough tile to contain a genuinely long line.
    image = cv2.copyMakeBorder(image, 0, 120, 0, 0, cv2.BORDER_CONSTANT, value=(255, 255, 255))
    cv2.line(image, (145, 0), (145, 229), (0, 0, 0), 2)
    prepared = prepare(image)
    assert prepared["lines"][:, 145].sum() > 0
    assert prepared["lines"][35:68, 20].sum() == 0
    regions = morph_regions(prepared)
    assert any(b["box"][0] <= 20 < b["box"][2] for b in regions)


def test_structure_uses_geometry_and_never_numeric_neighbours():
    image = synthetic_sounding()
    region = [15, 30, 65, 80]
    patch = crop(image, region, 0)
    assert split_layout(patch) is not None
    assert parse_whole("103", True) == dict(integer="10", decimetre="3", value=10.3)
    assert parse_whole("103", False) == dict(integer="103", decimetre=None, value=103.)
    assert parse_whole("1003", True)["value"] == 100.3  # No 31 m range cutoff.
    assert parse_whole("1O3", True)["value"] is None
    assert parse_whole("10,3", False)["value"] == 10.3
    assert parse_parts("10", "33")["value"] is None
    assert parse_parts("11")["value"] == 11


def test_detection_is_one_to_one_and_counts_fragment_false_boxes():
    truth = [dict(box=[10, 10, 40, 40])]
    regions = [dict(box=[10, 10, 40, 40]), dict(box=[10, 10, 20, 40]),
               dict(box=[100, 100, 120, 120])]
    result = evaluate_detection(regions, truth)
    assert result["found"] == 1
    assert result["false_regions"] == 2
    assert result["fragments_or_bad_boxes"] == result["spurious"] == 1
    assert evaluate_detection(regions, truth, ignore=[[90, 90, 130, 130]])["ignored"] == 1


def test_integer_and_decimal_errors_can_overlap():
    reference = [dict(integer="10", decimetre="3"), dict(integer="11", decimetre=None)]
    predictions = [dict(integer="1", decimetre="8", value=1.8),
                   dict(integer="11", decimetre=None, value=11.)]
    assert reading_scores(predictions, reference) == dict(total=2, excluded=0, exact=1,
        integer_errors=1, decimetre_errors=1, abstentions=0)


def test_ambiguous_reference_is_detection_only():
    truth = [dict(box=[1, 1, 10, 20], integer="10", decimetre=None,
                  recognition_eligible=False)]
    assert evaluate_detection([dict(box=truth[0]["box"])], truth)["found"] == 1
    assert reading_scores([dict(integer="109", decimetre=None, value=109.)], truth)["total"] == 0


def test_interpretation_reuses_cached_text_without_recognition():
    class Reader:
        calls = 0
        def predict(self, crops):
            self.calls += 1
            return [("103", .9)]*len(crops)
    reader = Reader()
    raw = read_regions(synthetic_sounding(), [dict(box=[15, 30, 65, 80])], reader)
    assert "value" not in raw[0]
    assert interpret_regions(raw)[0]["value"] == 10.3
    assert interpret_regions(raw)[0]["value"] == 10.3
    assert reader.calls == 1


def test_model_outputs_are_retained_and_not_guessed():
    class FakeReader:
        def predict(self, crops):
            return [("103", .8) for _ in crops]
    image = synthetic_sounding()
    out = recognize_regions(image, [dict(box=[15, 30, 65, 80])], FakeReader())
    assert out[0]["value"] == 10.3
    assert out[0]["readings"]["whole"] == {"text": "103", "score": .8}
    with pytest.raises(ValueError):
        recognize_regions(image, [], FakeReader(), strategy="oracle_split")


def test_crop_offsets_never_resize_native_boxes():
    a = np.zeros((200, 300, 3), np.uint8)
    assert crop(a, [11, 17, 30, 50], 0).shape == (33, 19, 3)
    with pytest.raises(ValueError):
        crop(a, [299, 0, 301, 10])


@pytest.mark.parametrize("settings", [dict(glyph_height=0), dict(threshold=-1),
    dict(background_window=10), dict(clahe_clip=float("nan"))])
def test_settings_validation(settings):
    with pytest.raises(ValueError):
        replace(PrepareOptions(), **settings)


def test_reference_has_distinct_source_soundings_and_explicit_ambiguity():
    path = Path(__file__).parents[1]/"sample/reference.json"
    if not path.is_file():
        pytest.skip("Source annotations are in the separately supplied evidence archive")
    reference = json.loads(path.read_text())
    boxes = []
    count = eligible = 0
    for tile in reference["tiles"]:
        x, y = tile["roi"][:2]
        for sounding in tile["soundings"]:
            b = sounding["box"]
            boxes.append((tile["id"], [b[0]+x, b[1]+y, b[2]+x, b[3]+y]))
            count += 1
            eligible += sounding.get("recognition_eligible", True)
    assert (count, eligible) == (59, 58)
    assert all(iou(a[1], b[1]) < .5 for i, a in enumerate(boxes)
               for b in boxes[i+1:] if a[0] != b[0])


def test_explicit_download_validates_and_preserves_existing_models(tmp_path):
    import io
    import tarfile
    from experiments.fb_v5.download_models import download
    name = "PP-OCRv5_mobile_det"
    stream = io.BytesIO()
    with tarfile.open(fileobj=stream, mode="w") as tar:
        for filename, content in {"inference.yml": f"Global:\n  model_name: {name}\n".encode(),
                                  "inference.json": b"{}", "inference.pdiparams": b"weights"}.items():
            info = tarfile.TarInfo(name+"_infer/"+filename)
            info.size = len(content)
            tar.addfile(info, io.BytesIO(content))
    payload = stream.getvalue()
    class Response:
        headers = {"Content-Length": str(len(payload))}
        def __enter__(self):return self
        def __exit__(self, *args):pass
        def raise_for_status(self):pass
        def iter_content(self, size):yield payload
    class Session:
        def __enter__(self):return self
        def __exit__(self, *args):pass
        def get(self, url, **kwargs):
            assert url.endswith(name+"_infer.tar")
            return Response()
    class Connection:
        def session(self):return Session()
    destination = download(name, tmp_path, Connection())
    assert (destination/"inference.pdiparams").read_bytes() == b"weights"
    assert json.loads((destination/"fb_download.json").read_text())["bytes"] == len(payload)
    with pytest.raises(FileExistsError):
        download(name, tmp_path, Connection())


def test_actual_geotiff_preview_is_detection_only_cached_and_globally_positioned(tmp_path):
    import rasterio
    from rasterio.transform import from_origin
    from experiments.fb_v5.preview import preview
    path = tmp_path/"sheet.tif"
    image = np.full((160, 220, 3), 255, np.uint8)
    image[20:130, 10:180] = synthetic_sounding()
    with rasterio.open(path, "w", driver="GTiff", width=220, height=160,
                       count=3, dtype="uint8", crs="EPSG:22524",
                       transform=from_origin(100, 200, .5, .5)) as ds:
        ds.write(image.transpose(2, 0, 1))
    before = set(sys.modules)
    first = preview(path, tmp_path/"out", roi=[10, 20, 170, 110])
    second = preview(path, tmp_path/"out", roi=[10, 20, 170, 110])
    assert first["recognition_executed"] is False
    assert second["cache_hits"] == dict(prepared=True, regions=True)
    assert first["regions"] == second["regions"]
    assert first["regions"][0]["box"][0] >= 10
    assert first["regions"][0]["box"][1] >= 20
    assert not any(m.startswith(("paddleocr", "paddle.")) for m in set(sys.modules)-before)
