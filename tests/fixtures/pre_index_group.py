"""Frozen pre-index algorithm from e41353d: behavioral regression oracle."""
import numpy as np
from vetorizafb.core import Sounding

def reference_group(digits, config):
    """Baseline-style chart grouping with typed digits and retained provenance.

    This is a geometric candidate generator, not a cartographic classifier.
    Contour labels and hazard annotations still require review.
    """
    ds = sorted([d for d in digits if d.text is not None
                 and d.confidence >= config.min_confidence],
                key=lambda d: (d.box.center[0], d.box.center[1]))
    used, out = set(), []
    for i, first in enumerate(ds):
        if i in used:
            continue
        members = [first]
        used.add(i)
        last_x, first_y = first.box.center
        for j in range(i+1, len(ds)):
            candidate = ds[j]
            x, y = candidate.box.center
            x_limit=config.tol_x*config.scale
            y_limit=config.tol_y*config.scale
            if config.grouping == 'relative':
                # Decimetre centres are lower than the integer baseline. A fixed
                # six-pixel Y limit rejected valid decimals even on the test chart.
                x_limit=max(x_limit,1.4*first.box.h)
                y_limit=max(y_limit,.6*first.box.h)
            if x-last_x > x_limit:
                break
            if j not in used and abs(y-first_y) <= y_limit:
                members.append(candidate)
                used.add(j)
                last_x = x
                if len(members) == 4:
                    break
        texts = ''.join(d.text for d in members)
        is_decimal = False
        if 2 <= len(members) <= 3:
            integers, tail = members[:-1], members[-1]
            mean_h = float(np.mean([d.box.h for d in integers]))
            mean_y = float(np.mean([d.box.center[1] for d in integers]))
            is_decimal = (tail.box.h <= config.decimal_height_ratio*mean_h
                          and tail.box.center[1]-mean_y >= config.decimal_drop*mean_h
                          and int(texts[:-1]) <= config.decimal_max_integer)
        depth = int(texts[:-1]) + int(texts[-1])/10 if is_decimal else float(texts)
        xmin = min(d.box.x for d in members)
        xmax = max(d.box.x+d.box.w for d in members)
        ymin = min(d.box.y for d in members)
        ymax = max(d.box.y+d.box.h for d in members)
        out.append(Sounding((xmin+xmax)/2, (ymin+ymax)/2, depth,
                            min(d.confidence for d in members),
                            (xmin,ymin,xmax,ymax), [d.index for d in members],
                            "subscript_decimal" if is_decimal else "integer"))
    return out
