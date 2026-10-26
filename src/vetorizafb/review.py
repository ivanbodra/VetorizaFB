"""Explicit point review with original values and an append-only decision trail."""
from copy import deepcopy
from dataclasses import asdict, replace
from datetime import datetime, timezone
import math
import uuid

from .core import Sounding


def depth_value(value):
    value = float(value)
    if not math.isfinite(value) or abs(value*10-round(value*10)) > 1e-6:
        raise ValueError("Depth must be finite with at most one decimal place")
    return value


def snapshot(sounding):
    result = asdict(sounding)
    result['bounds'] = list(result['bounds'])
    return result


class ReviewSet:
    def __init__(self, soundings=()):
        self.items = [dict(id=i, original=snapshot(s), current=snapshot(s),
                           status="unreviewed", note="", history=[])
                      for i, s in enumerate(soundings)]
        self._by_id={item['id']:item for item in self.items}
        self._next_id=len(self.items)

    def item(self, point_id):
        return self._by_id[int(point_id)]

    def change(self, point_id, action, *, depth=None, xy=None, note=""):
        item = self.item(point_id)
        before = deepcopy(item['current'])
        previous_status = item['status']
        if action in {"accepted", "rejected", "unreviewed"}:
            item['status'] = action
        elif action == "correct_depth":
            item['current']['depth'] = depth_value(depth)
            item['status'] = "unreviewed"
            if 'manual_depth' not in item['current']['flags']:
                item['current']['flags'].append('manual_depth')
        elif action in {"reposition","offset"}:
            if xy is None or not all(math.isfinite(float(v)) for v in xy):
                raise ValueError("Finite pixel coordinates required")
            item['current']['pixel_x'], item['current']['pixel_y'] = map(float, xy)
            item['status'] = "rejected" if action=='offset' and previous_status=='rejected' else "unreviewed"
            if 'manual_position' not in item['current']['flags']:
                item['current']['flags'].append('manual_position')
        elif action in {"restore_depth","restore_position","restore_both"}:
            original=item['original']
            if original is None:raise ValueError("Manual points have no original reading")
            keys=[]
            if action in {"restore_depth","restore_both"}:keys.append('depth')
            if action in {"restore_position","restore_both"}:keys.extend(('pixel_x','pixel_y'))
            if all(item['current'][k]==original[k] for k in keys):return False
            for key in keys:item['current'][key]=deepcopy(original[key])
            flags=item['current']['flags']
            if 'depth' in keys:flags[:]=[f for f in flags if f!='manual_depth']
            if 'pixel_x' in keys:flags[:]=[f for f in flags if f!='manual_position']
            item['status']='unreviewed'
        else:
            raise ValueError("Unknown review action")
        item['current']['review_status'] = item['status']
        item['note'] = note or item['note']
        item['history'].append(dict(timestamp_utc=datetime.now(timezone.utc).isoformat(),
                                    action=action, previous_status=previous_status,
                                    before=before, after=deepcopy(item['current']), note=note))

    def offset(self,point_ids,dx,dy,*,note='',context=None):
        """Prevalidate all targets before recording an indexed batch translation."""
        dx,dy=float(dx),float(dy)
        if not all(math.isfinite(v) for v in (dx,dy)):raise ValueError('Finite offsets required')
        ids=list(dict.fromkeys(int(i) for i in point_ids))
        changes=[]
        for point_id in ids:
            item=self.item(point_id);s=item['current']
            xy=(s['pixel_x']+dx,s['pixel_y']+dy)
            if not all(math.isfinite(v) for v in xy):raise ValueError('Finite positions required')
            changes.append((point_id,xy))
        if not changes or (dx==0 and dy==0):return None
        batch_id=uuid.uuid4().hex
        details=dict(context or {},pixel_dx=dx,pixel_dy=dy)
        for point_id,xy in changes:
            self.change(point_id,'offset',xy=xy,note=note)
            self.item(point_id)['history'][-1].update(batch_id=batch_id,offset=deepcopy(details))
        return batch_id

    def add_manual(self, x, y, depth, *, note=''):
        x, y = float(x), float(y)
        if not math.isfinite(x) or not math.isfinite(y):
            raise ValueError("Finite pixel coordinates required")
        sounding = Sounding(x, y, depth_value(depth), None, (x,y,x,y), [],
                            "manual", flags=['manual_addition'])
        point_id=self._next_id;self._next_id+=1
        item=dict(id=point_id, original=None, current=snapshot(sounding),
                               status='unreviewed', note=note, history=[dict(
                                   timestamp_utc=datetime.now(timezone.utc).isoformat(),
                                   action='manual_addition', after=snapshot(sounding),note=note)])
        self.items.append(item);self._by_id[point_id]=item
        return point_id

    def soundings(self, *, accepted_only=False):
        return [Sounding(**deepcopy(item['current'])) for item in self.items
                if item['status'] == 'accepted' or (not accepted_only and item['status'] != 'rejected')]

    @property
    def counts(self):
        return {status:sum(i['status']==status for i in self.items)
                for status in ('unreviewed','accepted','rejected')}

    @classmethod
    def from_items(cls, items):
        result = cls()
        ids = set()
        for raw in deepcopy(items):
            if not isinstance(raw['id'], int) or raw['id'] in ids:
                raise ValueError("Invalid/duplicate point ID")
            ids.add(raw['id'])
            if raw['status'] not in {'unreviewed','accepted','rejected'}:
                raise ValueError("Invalid review status")
            s = Sounding(**raw['current'])
            depth_value(s.depth)
            if s.review_status != raw['status'] or not all(math.isfinite(float(v)) for v in (s.pixel_x,s.pixel_y,*s.bounds)):
                raise ValueError("Inconsistent point record")
            if len(s.bounds)!=4 or s.bounds[2]<s.bounds[0] or s.bounds[3]<s.bounds[1]:
                raise ValueError("Invalid point bounds")
            if s.confidence is not None and (not math.isfinite(float(s.confidence)) or not 0<=s.confidence<=1):
                raise ValueError("Invalid point confidence")
            result.items.append(raw)
            result._by_id[raw['id']]=raw
        result._next_id=max(ids,default=-1)+1
        return result
