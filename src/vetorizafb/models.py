"""Local model discovery and explicit, isolated downloads from official Paddle BOS."""
from dataclasses import dataclass, field
import json
import os
from pathlib import Path, PurePosixPath
import re
import sys
import tarfile
import tempfile
from urllib.parse import quote, urlsplit, urlunsplit

from .core import check_cancel, ProcessingCancelled

MODEL_NAMES = ('PP-OCRv6_small_rec', 'PP-OCRv6_medium_rec', 'PP-OCRv5_server_rec')
MODEL_BASE_URL = 'https://paddle-model-ecology.bj.bcebos.com/paddlex/official_inference_model/paddle3.0.0'
MAX_ARCHIVE = 512 * 1024 * 1024
MAX_UNPACKED = 1024 * 1024 * 1024


class ModelDownloadError(ValueError):
    pass


def cache_root():
    return Path(os.environ.get('PADDLE_PDX_CACHE_HOME', Path.home()/'.paddlex'))/'official_models'


def preferences_path():
    return Path(os.environ.get('APPDATA', Path.home()/'.config'))/'VetorizaFB'/'models.json'


def default_model_root():
    if os.environ.get('VETORIZAFB_MODELS_DIR'):return Path(os.environ['VETORIZAFB_MODELS_DIR'])
    try:
        value=json.loads(preferences_path().read_text(encoding='utf-8'))['root']
        if isinstance(value,str) and value:return Path(value)
    except (OSError,ValueError,KeyError,TypeError):pass
    if getattr(sys,'frozen',False):
        portable=Path(sys.executable).parent/'models'
        if discover_models(portable):return portable
    return cache_root()


def save_model_root(root):
    path=preferences_path();path.parent.mkdir(parents=True,exist_ok=True)
    # Only the location is persisted: never proxy passwords or usernames.
    from .pipeline import write_json_atomic
    write_json_atomic(path,{'root':str(Path(root).resolve())})


@dataclass(frozen=True)
class LocalModel:
    name: str
    path: Path


def inspect_model(path):
    path=Path(path)
    try:
        config=path/'inference.yml'
        if not config.is_file() or not 0<config.stat().st_size<=2*1024*1024:return None
        if not (path/'inference.pdiparams').is_file() or (path/'inference.pdiparams').stat().st_size==0:return None
        if not any((path/n).is_file() and (path/n).stat().st_size>0 for n in ('inference.json','inference.pdmodel')):return None
        text=config.read_text(encoding='utf-8')
        match=re.search(r"(?m)^\s*model_name:\s*['\"]?([A-Za-z0-9_-]+)",text)
        if not match or match[1] not in MODEL_NAMES:return None
        return LocalModel(match[1],path.resolve())
    except (OSError,UnicodeError):return None


def discover_models(root):
    root=Path(root).expanduser()
    direct=inspect_model(root)
    if direct:return [direct]
    try:children=sorted(root.iterdir(),key=lambda p:p.name)
    except OSError:return []
    found=[]
    for child in children:
        if child.name.startswith('.'):continue
        model=inspect_model(child)
        if model:found.append(model)
    return found


@dataclass(frozen=True)
class ConnectionSettings:
    mode: str='system'
    server: str=''
    username: str=field(default='',repr=False)
    password: str=field(default='',repr=False)
    ca_file: str=''

    def proxy_url(self):
        server=self.server.strip()
        if '://' not in server:server='http://'+server
        parsed=urlsplit(server)
        try:port=parsed.port
        except ValueError:raise ValueError('Porta de proxy inválida.') from None
        if parsed.scheme not in ('http','https') or not parsed.hostname or port is None or not 1<=port<=65535 or parsed.username is not None or parsed.password is not None or parsed.path not in ('','/') or parsed.query or parsed.fragment:
            raise ValueError('Informe o proxy como servidor:porta, sem credenciais no endereço.')
        host=parsed.netloc
        if self.username:host=f'{quote(self.username,safe="")}:{quote(self.password,safe="")}@{host}'
        elif self.password:raise ValueError('Informe o usuário do proxy.')
        return urlunsplit((parsed.scheme,host,'','',''))

    def validate(self):
        if self.mode not in ('system','direct','proxy'):raise ValueError('Modo de conexão inválido.')
        if self.mode=='proxy':self.proxy_url()
        if self.ca_file and not Path(self.ca_file).is_file():raise ValueError('Arquivo de certificado não encontrado.')

    def session(self):
        import requests
        self.validate()
        session=requests.Session()
        session.trust_env=self.mode=='system'
        if self.mode=='proxy':session.proxies={'http':self.proxy_url(),'https':self.proxy_url()}
        if self.ca_file:session.verify=self.ca_file
        return session


def safe_extract(archive,destination,cancel=None):
    """Copy only bounded regular files/directories; never follow archive links."""
    total=count=0;destination=Path(destination)
    with tarfile.open(archive,'r:*') as source:
        for member in source:
            check_cancel(cancel);count+=1;total+=member.size
            path=PurePosixPath(member.name)
            if count>1000 or total>MAX_UNPACKED or member.size<0 or len(member.name)>512:
                raise ModelDownloadError('Pacote de modelo excede os limites permitidos.')
            if path.is_absolute() or '..' in path.parts or '\\' in member.name or ':' in member.name or not (member.isfile() or member.isdir()):
                raise ModelDownloadError('Pacote de modelo contém um caminho ou tipo de arquivo inválido.')
            target=destination.joinpath(*path.parts)
            if member.isdir():target.mkdir(parents=True,exist_ok=True);continue
            target.parent.mkdir(parents=True,exist_ok=True)
            with source.extractfile(member) as src,target.open('xb') as dst:
                remaining=member.size
                while remaining:
                    check_cancel(cancel);data=src.read(min(1024*1024,remaining))
                    if not data:raise ModelDownloadError('Pacote de modelo incompleto.')
                    dst.write(data);remaining-=len(data)


def download_model(name,root,connection=None,*,cancel=None,progress=None,session_factory=None):
    if name not in MODEL_NAMES:raise ValueError('Modelo não suportado.')
    check_cancel(cancel);root=Path(root).expanduser().resolve()
    for model in discover_models(root):
        if model.name==name:return model
    destination=root/name
    if destination.exists():raise ModelDownloadError('Já existe uma pasta incompleta com esse nome. Use outra pasta ou confira seu conteúdo antes de tentar novamente.')
    connection=connection or ConnectionSettings();connection.validate()
    root.mkdir(parents=True,exist_ok=True)
    import requests
    try:
        with tempfile.TemporaryDirectory(prefix='.vf-download-',dir=root) as temp:
            temp=Path(temp);archive=temp/'model.tar'
            with (session_factory or connection.session)() as session:
                with session.get(f'{MODEL_BASE_URL}/{name}_infer.tar',stream=True,timeout=(15,45),verify=connection.ca_file or None) as response:
                    if response.status_code==407:raise ModelDownloadError('O proxy recusou a autenticação. Confira usuário e senha; autenticação integrada NTLM/Kerberos pode exigir suporte da rede.')
                    if response.status_code==404:raise ModelDownloadError('O modelo não foi encontrado na fonte oficial.')
                    if response.status_code in (401,403):raise ModelDownloadError('A rede ou o servidor recusou o acesso ao modelo.')
                    response.raise_for_status()
                    expected=int(response.headers.get('Content-Length','0'))
                    if expected<0 or expected>MAX_ARCHIVE:raise ModelDownloadError('Tamanho de download inválido.')
                    received=0
                    with archive.open('wb') as stream:
                        for chunk in response.iter_content(1024*1024):
                            check_cancel(cancel)
                            if not chunk:continue
                            received+=len(chunk)
                            if received>MAX_ARCHIVE:raise ModelDownloadError('Download excede o tamanho permitido.')
                            stream.write(chunk)
                            if progress:progress(received,expected)
                    if expected and received!=expected:raise ModelDownloadError('Download incompleto. Tente novamente.')
            check_cancel(cancel);unpacked=temp/'unpacked';unpacked.mkdir()
            safe_extract(archive,unpacked,cancel)
            models=[m for m in discover_models(unpacked) if m.name==name]
            if len(models)!=1:raise ModelDownloadError('O pacote recebido não contém o modelo solicitado completo.')
            check_cancel(cancel)
            # A concurrent completed installation is reused, never overwritten.
            if destination.exists():
                model=inspect_model(destination)
                if model and model.name==name:return model
                raise ModelDownloadError('A pasta de destino já existe; seu conteúdo foi preservado.')
            os.rename(models[0].path,destination)
            return LocalModel(name,destination)
    except ProcessingCancelled:raise
    except requests.exceptions.SSLError:
        raise ModelDownloadError('Falha na validação TLS. Confira o certificado da rede; é possível informar um certificado CA na conexão.') from None
    except requests.exceptions.ProxyError:
        raise ModelDownloadError('Não foi possível conectar ao proxy. Confira servidor, porta e autenticação.') from None
    except requests.exceptions.Timeout:
        raise ModelDownloadError('Tempo de conexão ou transferência esgotado. Confira a rede e tente novamente.') from None
    except requests.exceptions.RequestException:
        raise ModelDownloadError('Falha no download. Confira a conexão e a liberação da fonte oficial na rede.') from None
    except (tarfile.TarError,UnicodeError):
        raise ModelDownloadError('O arquivo recebido não é um pacote de modelo válido.') from None
