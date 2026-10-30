"""Three display levels; all coordinates remain in original image pixels."""
import math

import cv2
from PIL import Image


class DisplayPyramid:
    def __init__(self, pixels, viewport=(1600, 1000)):
        self.pixels = pixels
        self.viewport = viewport
        h, w = pixels.shape[:2]
        self.size = (w, h)
        fit = min(1., viewport[0]/w, viewport[1]/h)
        # Intermediate resolution balances the two ends on a logarithmic scale.
        intermediate = min(math.sqrt(fit), math.sqrt(16_000_000/(w*h)))
        self.levels = []
        for scale in sorted({fit, intermediate}):
            if scale > 2/3:continue  # Keep a reduced level only for a useful saving.
            width, height = max(1, round(w*scale)), max(1, round(h*scale))
            if self.levels and self.levels[-1][0].size == (width,height):continue
            reduced = cv2.resize(pixels, (width,height), interpolation=cv2.INTER_AREA)
            self.levels.append((Image.fromarray(reduced), min(width/w,height/h)))

    def render(self, bounds, scale):
        x1,y1,x2,y2 = bounds
        output = (max(1,round((x2-x1)*scale)), max(1,round((y2-y1)*scale)))
        for image, resolution in self.levels:
            # Do not magnify a reduced source: switch to the next finer level.
            if resolution + 1e-9 >= scale:
                sx,sy = image.width/self.size[0],image.height/self.size[1]
                return image.transform(output, Image.Transform.EXTENT,
                    (x1*sx,y1*sy,x2*sx,y2*sy), Image.Resampling.BILINEAR)
        return Image.fromarray(self.pixels[y1:y2,x1:x2]).resize(output,Image.Resampling.BILINEAR)


def read_preview(path, viewport):
    """Read a screen-sized preview before loading the full-resolution session."""
    import numpy as np
    import rasterio
    from rasterio.enums import Resampling, ColorInterp
    with rasterio.open(path) as ds:
        if ds.dtypes[0] != 'uint8':return None
        scale=min(1.,viewport[0]/ds.width,viewport[1]/ds.height)
        width,height=max(1,round(ds.width*scale)),max(1,round(ds.height*scale))
        if ds.count>=3:
            data=ds.read([1,2,3],out_shape=(3,height,width),resampling=Resampling.average)
            return Image.fromarray(data.transpose(1,2,0))
        # Palette indexes must not be averaged as if they were colour intensities.
        band=ds.read(1,out_shape=(height,width),resampling=Resampling.nearest)
        if ds.colorinterp[0]==ColorInterp.palette:
            table=np.zeros((256,3),np.uint8)
            for index,colour in ds.colormap(1).items():
                if 0<=index<256:table[index]=colour[:3]
            return Image.fromarray(table[band])
        return Image.fromarray(band).convert('RGB')
