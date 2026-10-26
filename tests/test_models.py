from dataclasses import replace
import io
from pathlib import Path
import tarfile
import threading

import pytest
import requests

from vetorizafb.core import ProcessingCancelled
from vetorizafb.models import (ConnectionSettings,ModelDownloadError,MODEL_NAMES,discover_models,
    inspect_model,download_model,safe_extract,default_model_root,save_model_root)

NAME=MODEL_NAMES[0]


def model_files(root,name=NAME):
    root=Path(root);root.mkdir(parents=True,exist_ok=True)
    (root/'inference.yml').write_text(f'Global:\n  model_name: {name}\n')
    (root/'inference.json').write_text('{}');(root/'inference.pdiparams').write_bytes(b'weights')
    return root


def archive_bytes(name=NAME,bad_path=None):
    stream=io.BytesIO()
    with tarfile.open(fileobj=stream,mode='w') as archive:
        data={'inference.yml':f'Global:\n  model_name: {name}\n'.encode(),'inference.json':b'{}','inference.pdiparams':b'weights'}
        for file,value in data.items():
            member=tarfile.TarInfo(bad_path or f'{name}_infer/{file}');member.size=len(value)
            archive.addfile(member,io.BytesIO(value))
            if bad_path:break
    return stream.getvalue()


class Response:
    status_code=200
    def __init__(self,data,status=200):self.data=data;self.status_code=status;self.headers={'Content-Length':str(len(data))}
    def __enter__(self):return self
    def __exit__(self,*args):pass
    def raise_for_status(self):
        if self.status_code>=400:raise requests.HTTPError('private transport details')
    def iter_content(self,size):
        for i in range(0,len(self.data),1024):yield self.data[i:i+1024]


class Session:
    def __init__(self,response):self.response=response;self.calls=[]
    def __enter__(self):return self
    def __exit__(self,*args):pass
    def get(self,url,**kwargs):self.calls.append((url,kwargs));return self.response


def test_discovery_preserves_existing_cache_and_accepts_parent_or_leaf(tmp_path):
    original=model_files(tmp_path/(NAME+'_infer'));model_files(tmp_path/'medium',MODEL_NAMES[1])
    (tmp_path/'incomplete').mkdir();(tmp_path/'incomplete'/'inference.yml').write_text(f'model_name: {NAME}')
    assert {m.name for m in discover_models(tmp_path)}==set(MODEL_NAMES[:2])
    assert discover_models(original)[0].path==original
    assert (original/'inference.pdiparams').read_bytes()==b'weights'
    model_files(tmp_path/'detector','PP-OCRv6_small_det')
    assert len(discover_models(tmp_path))==2


def test_model_root_uses_existing_paddlex_cache_without_importing_paddle(tmp_path,monkeypatch):
    monkeypatch.delenv('VETORIZAFB_MODELS_DIR',raising=False)
    monkeypatch.setenv('APPDATA',str(tmp_path/'settings'))
    monkeypatch.setenv('PADDLE_PDX_CACHE_HOME',str(tmp_path/'cache'))
    assert default_model_root()==tmp_path/'cache'/'official_models'
    save_model_root(tmp_path/'elsewhere')
    assert default_model_root()==tmp_path/'elsewhere'


def test_proxy_modes_are_isolated_and_credentials_are_encoded_not_persisted(tmp_path,monkeypatch):
    monkeypatch.setenv('HTTPS_PROXY','http://inherited.example:8080')
    assert ConnectionSettings().session().trust_env
    direct=ConnectionSettings(mode='direct').session()
    assert not direct.trust_env and not direct.proxies
    cfg=ConnectionSettings(mode='proxy',server='proxy.example:3128',username='DOMAIN\\name@x',password='secret:@/#')
    proxy=cfg.session()
    assert not proxy.trust_env and proxy.proxies['https'].startswith('http://DOMAIN%5Cname%40x:')
    assert 'secret:@/#' not in repr(cfg) and 'DOMAIN' not in repr(cfg)
    assert __import__('os').environ['HTTPS_PROXY']=='http://inherited.example:8080'


@pytest.mark.parametrize('server',['proxy','http://user:pass@proxy:80','ftp://proxy:12','proxy:99999','proxy:abc','http://proxy:80/pac?x=1'])
def test_invalid_proxy_configuration_fails_before_network(server):
    with pytest.raises(ValueError):ConnectionSettings(mode='proxy',server=server).validate()


def test_download_is_explicit_validates_contents_and_reuses_complete_models(tmp_path):
    session=Session(Response(archive_bytes()));progress=[]
    model=download_model(NAME,tmp_path,ConnectionSettings(mode='direct'),session_factory=lambda:session,progress=lambda a,b:progress.append((a,b)))
    assert model.path==tmp_path/NAME and inspect_model(model.path)==model
    assert session.calls[0][0].startswith('https://paddle-model-ecology.bj.bcebos.com/')
    assert progress[-1][0]==progress[-1][1]
    assert not list(tmp_path.glob('.vf-download-*'))
    assert download_model(NAME,tmp_path,session_factory=lambda:pytest.fail('No network for cached model'))==model


@pytest.mark.parametrize('path',['../escape','/absolute','C:/escape','model/../../escape','model\\escape'])
def test_archive_paths_cannot_escape_destination(tmp_path,path):
    archive=tmp_path/'model.tar';archive.write_bytes(archive_bytes(bad_path=path))
    with pytest.raises(ModelDownloadError):safe_extract(archive,tmp_path/'out')
    assert not (tmp_path.parent/'escape').exists()


def test_archive_links_are_rejected(tmp_path):
    archive=tmp_path/'link.tar'
    with tarfile.open(archive,'w') as tar:
        member=tarfile.TarInfo('link');member.type=tarfile.SYMTYPE;member.linkname='/etc/passwd';tar.addfile(member)
    with pytest.raises(ModelDownloadError):safe_extract(archive,tmp_path/'out')


def test_wrong_or_partial_model_is_never_published(tmp_path):
    session=Session(Response(archive_bytes(MODEL_NAMES[1])))
    with pytest.raises(ModelDownloadError):download_model(NAME,tmp_path,session_factory=lambda:session)
    assert not list(tmp_path.iterdir())
    destination=tmp_path/NAME;destination.mkdir();(destination/'keep').write_text('preserve')
    with pytest.raises(ModelDownloadError):download_model(NAME,tmp_path,session_factory=lambda:pytest.fail('No request'))
    assert (destination/'keep').read_text()=='preserve'


def test_cancelled_download_cleans_partial_files_and_preserves_existing_models(tmp_path):
    other=model_files(tmp_path/MODEL_NAMES[1],MODEL_NAMES[1]);cancel=threading.Event()
    session=Session(Response(archive_bytes()))
    with pytest.raises(ProcessingCancelled):
        download_model(NAME,tmp_path,cancel=cancel,session_factory=lambda:session,progress=lambda *args:cancel.set())
    assert list(tmp_path.iterdir())==[other]


@pytest.mark.parametrize('error,message',[(requests.exceptions.ProxyError('secret-password'),'proxy'),(requests.exceptions.SSLError('secret-password'),'TLS'),(requests.exceptions.Timeout('secret-password'),'esgotado')])
def test_network_errors_are_actionable_and_do_not_expose_secrets(tmp_path,error,message):
    class Broken(Session):
        def get(self,*args,**kwargs):raise error
    with pytest.raises(ModelDownloadError) as caught:download_model(NAME,tmp_path,session_factory=lambda:Broken(None))
    assert message in str(caught.value) and 'secret-password' not in str(caught.value)
    assert not list(tmp_path.iterdir())


def test_proxy_authentication_failure_reports_407(tmp_path):
    with pytest.raises(ModelDownloadError,match='autenticação'):
        download_model(NAME,tmp_path,session_factory=lambda:Session(Response(b'',407)))


def test_local_adapter_passes_explicit_directory_without_a_download(tmp_path,monkeypatch):
    import sys
    from types import SimpleNamespace
    from vetorizafb.ocr import PaddleRecognizer
    model=model_files(tmp_path/NAME);monkeypatch.setenv('VETORIZAFB_MODELS_DIR',str(tmp_path))
    called=[]
    monkeypatch.setitem(sys.modules,'paddleocr',SimpleNamespace(TextRecognition=lambda **kw:called.append(kw)))
    PaddleRecognizer(NAME)
    assert called[0]['model_dir']==str(model)
