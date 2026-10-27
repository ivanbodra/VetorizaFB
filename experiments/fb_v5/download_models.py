"""Explicit isolated experimental model download; no application changes."""
import argparse
import getpass
from pathlib import Path
import os
import re
import sys
import tempfile

from .poc import atomic_json, file_digest

MODELS = ("PP-OCRv6_small_rec", "PP-OCRv5_mobile_det")
BASE = "https://paddle-model-ecology.bj.bcebos.com/paddlex/official_inference_model/paddle3.0.0"


def download(name, root, connection):
    # Reuse stable connection validation and bounded archive extraction without
    # expanding the application model list or triggering a framework download.
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]/"src"))
    from vetorizafb.models import safe_extract
    if name not in MODELS:
        raise ValueError("Unsupported experimental model")
    root = Path(root).resolve()
    root.mkdir(parents=True, exist_ok=True)
    destination = root/(name+"_infer")
    if destination.exists():
        raise FileExistsError("Destination already exists; preserve and inspect it")
    with tempfile.TemporaryDirectory(prefix=".fb-model-", dir=root) as temp:
        temp = Path(temp)
        archive = temp/"model.tar"
        with connection.session() as session:
            with session.get(f"{BASE}/{name}_infer.tar", stream=True, timeout=(15, 45)) as response:
                response.raise_for_status()
                expected = int(response.headers.get("Content-Length", 0))
                if expected < 0 or expected > 64*1024*1024:
                    raise ValueError("Unexpected model size")
                size = 0
                with archive.open("wb") as stream:
                    for block in response.iter_content(1024*1024):
                        size += len(block)
                        if size > 64*1024*1024:
                            raise ValueError("Model exceeds experimental size budget")
                        stream.write(block)
                if expected and size != expected:
                    raise ValueError("Incomplete download")
        safe_extract(archive, temp/"unpacked")
        model = temp/"unpacked"/(name+"_infer")
        config = model/"inference.yml"
        if not config.is_file() or not (model/"inference.pdiparams").is_file() or not any((model/f).is_file() for f in ("inference.json", "inference.pdmodel")):
            raise ValueError("Incomplete inference model")
        if not re.search(r"model_name:\s*['\"]?"+re.escape(name)+r"\b", config.read_text()):
            raise ValueError("Model identity mismatch")
        atomic_json(model/"fb_download.json", dict(model=name, archive_sha256=file_digest(archive),
                                                  bytes=size, source=f"{BASE}/{name}_infer.tar"))
        os.rename(model, destination)
    return destination


def main():
    parser = argparse.ArgumentParser(__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--connection", choices=("system", "direct", "proxy"), default="system")
    parser.add_argument("--proxy-server", default="")
    parser.add_argument("--proxy-user", default="")
    parser.add_argument("--ca-file", default="")
    parser.add_argument("--models", nargs="+", choices=MODELS, default=MODELS)
    args = parser.parse_args()
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]/"src"))
    from vetorizafb.models import ConnectionSettings
    password = getpass.getpass("Senha do proxy: ") if args.proxy_user else ""
    connection = ConnectionSettings(args.connection, args.proxy_server, args.proxy_user, password, args.ca_file)
    connection.validate()
    import requests
    try:
        for name in args.models:
            print(download(name, args.root, connection))
    except requests.RequestException:
        # Keep connection/proxy credentials out of exception tracebacks.
        parser.exit(1, "Falha no download. Confira a conexão, o proxy e o certificado.\n")


if __name__ == "__main__":
    main()
