from types import SimpleNamespace
from unittest.mock import Mock
import pytest
from vetorizafb.gui import Application


@pytest.mark.parametrize('answer', [True, False, None])
def test_close_choice_only_destroys_after_successful_save(monkeypatch,answer):
    from vetorizafb import gui
    monkeypatch.setattr(gui.messagebox,'askyesnocancel',lambda *a,**k:answer)
    root=SimpleNamespace(after_idle=Mock())
    saved=[]
    app=SimpleNamespace(busy=False,session=object(),root=root,_destroy=Mock(),
                        save_project=lambda after_save:saved.append(after_save))
    Application.close(app)
    if answer is True:
        assert len(saved)==1
        app._destroy.assert_not_called()
        saved[0]()
        root.after_idle.assert_called_once_with(app._destroy)
    else:
        assert not saved
        if answer is False:app._destroy.assert_called_once()
        else:app._destroy.assert_not_called()


def test_close_without_project_does_not_prompt(monkeypatch):
    from vetorizafb import gui
    prompt=Mock()
    monkeypatch.setattr(gui.messagebox,'askyesnocancel',prompt)
    app=SimpleNamespace(busy=False,session=None,_destroy=Mock())
    Application.close(app)
    app._destroy.assert_called_once()
    prompt.assert_not_called()
