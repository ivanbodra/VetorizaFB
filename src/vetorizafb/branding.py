"""Load the user's original branding without depending on the working directory."""
import os
from pathlib import Path
from PIL import Image, ImageTk


def icon_candidates():
    root = Path(__file__).resolve().parents[2]
    user = Path(os.environ.get('APPDATA', Path.home() / '.config')) / 'VetorizaFB'
    for folder in (user, Path(__file__).parent / 'assets', root, root / 'legacy/v3_1'):
        for name in ('logo_vetorizaFB.ico', 'logo_vetorizafb.ico', 'logo_vetorizafb.png'):
            yield folder / name


def apply_icon(window, path=None):
    for candidate in ([Path(path)] if path else icon_candidates()):
        if candidate.is_file():
            try:
                with Image.open(candidate) as image:
                    photo = ImageTk.PhotoImage(image.convert('RGBA').resize((64,64)))
                window.iconphoto(True, photo)
                window._vetorizafb_icon = photo
                return candidate
            except (OSError, ValueError):
                continue
    return None
