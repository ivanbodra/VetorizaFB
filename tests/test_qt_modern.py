"""Smoke tests for the modern shell; skipped when optional PySide6 is absent."""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication
from vetorizafb.qt_modern import ModernWindow


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def test_modern_shell_keeps_original_processing_controls(app):
    window = ModernWindow()
    try:
        assert window.properties_stack.count() == 4
        assert len(window.stage_navigation) == 4
        assert window.canvas is not None
        assert window.table is not None
        assert window.mode is not None
        assert "min_w" in window.fields
        assert window.tabs is not None  # referenced by the existing lifecycle
        assert window.controls  # original callbacks and buttons preserved
        window.select_stage(2)
        assert window.properties_stack.currentIndex() == 2
        assert window.stage_navigation[2].isChecked()
        window.select_stage(0)
        assert window.properties_stack.currentIndex() == 0
    finally:
        window.close()


def test_review_panel_can_be_collapsed(app):
    window = ModernWindow()
    try:
        window.show()
        app.processEvents()
        assert window._review_widget.isVisible()
        window.toggle_review()
        app.processEvents()
        assert not window._review_widget.isVisible()
        window.toggle_review()
        app.processEvents()
        assert window._review_widget.isVisible()
    finally:
        window.close()
