from types import SimpleNamespace

import pytest

from vetorizafb.auto_bounds import suggest_bounds


def boxes(width, height, count):
    return [SimpleNamespace(w=width, h=height) for _ in range(count)]


def test_bounds_follow_chart_specific_character_clusters_despite_specks():
    first = (boxes(1, 1, 1500) + boxes(11, 14, 150) +
             boxes(15, 20, 280) + boxes(5, 20, 35))
    second = (boxes(4, 4, 1800) + boxes(23, 29, 230) +
              boxes(28, 36, 270) + boxes(13, 35, 75))
    assert suggest_bounds(first, .5) == (4, 16, 13, 21)
    assert suggest_bounds(second, 1) == (12, 29, 28, 37)


def test_insufficient_contours_do_not_change_bounds():
    with pytest.raises(ValueError, match='Poucas caixas'):
        suggest_bounds(boxes(12, 20, 5), 1)
