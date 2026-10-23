"""Load the user's original branding without depending on the working directory."""
import os
import sys
from pathlib import Path
from PIL import Image, ImageTk


def icon_candidates():
    root = Path(__file__).resolve().parents[2]
    user = Path(os.environ.get('APPDATA', Path.home() / '.config')) / 'VetorizaFB'
    selected=user/'selected-icon.txt'
    if selected.is_file():
        name=selected.read_text(encoding='utf-8').strip()
        if name in {'logo_vetorizafb.ico','logo_vetorizafb.png'}:yield user/name
    for folder in (user, Path(__file__).parent / 'assets', root, root / 'legacy/v3_1'):
        for name in ('logo_vetorizaFB.ico', 'logo_vetorizafb.ico', 'logo_vetorizafb.png', 'logo_vetorizaFB.png'):
            yield folder / name


def apply_icon(window, path=None):
    for candidate in ([Path(path)] if path else icon_candidates()):
        if candidate.is_file():
            try:
                with Image.open(candidate) as image:
                    image=image.convert('RGBA')
                    photos=[]
                    for size in (16,32,48,64,256):
                        resized=image.copy();resized.thumbnail((size,size),Image.Resampling.LANCZOS)
                        photos.append(ImageTk.PhotoImage(resized,master=window))
                photo=photos[3]
                window.iconphoto(True, *photos)
                if sys.platform=='win32' and candidate.suffix.lower()=='.ico':
                    window.iconbitmap(default=str(candidate))
                window._vetorizafb_icons=photos
                window._vetorizafb_icon = photo
                return candidate
            except (OSError, ValueError):
                continue
    return None


def asset_photo(window,name,size):
    """Read bundled original art at a bounded size, retaining its proportions."""
    path=Path(__file__).parent/'assets'/name
    with Image.open(path) as image:
        image=image.convert('RGBA');image.thumbnail(size,Image.Resampling.LANCZOS)
        return ImageTk.PhotoImage(image,master=window)
