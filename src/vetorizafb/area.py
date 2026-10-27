"""Image-coordinate rectangular and polygonal selection geometry."""
import cv2
import numpy as np


def is_polygon(area):
    return area is not None and len(area) >= 3 and all(isinstance(p,(tuple,list)) and len(p)==2 for p in area)


def bounds(area, width, height):
    if area is None:return (0,0,width,height)
    if not is_polygon(area):return tuple(area)
    xs,ys=zip(*area)
    x,y=min(xs),min(ys)
    return x,y,max(xs)-x+1,max(ys)-y+1


def inside(area, x, y):
    if area is None:return True
    if not is_polygon(area):
        a,b,w,h=area
        return a<=x<a+w and b<=y<b+h
    contour=np.asarray(area,dtype=np.float32)
    return cv2.pointPolygonTest(contour,(float(x),float(y)),False)>=0


def polygon_mask(area, rect):
    if not is_polygon(area):return None
    x,y,w,h=rect
    mask=np.zeros((h,w),np.uint8)
    vertices=np.asarray([(px-x,py-y) for px,py in area],dtype=np.int32)
    cv2.fillPoly(mask,[vertices],255)
    return mask
