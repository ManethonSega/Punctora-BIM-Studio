"""Discrete geometric flight fitting, independent of building elevations."""
import numpy as np


def fit_tread_sequences(patches):
    """Fit at least four observed treads, allowing up to two missing between them.

    A missing tread is inferred only inside a measured sequence. End steps are
    never extrapolated. Competing fits prefer coverage and fewer missing steps.
    """
    candidates = []
    for first, a in enumerate(patches):
        for second in range(first+1, len(patches)):
            b = patches[second]
            delta = b['xy']-a['xy']
            distance = float(np.linalg.norm(delta))
            if distance < .18 or distance > 1.35:
                continue
            direction = delta/distance
            if abs(direction@a['axis']) > .2 or abs(direction@b['axis']) > .2:
                continue
            for gap in (1, 2, 3):
                rise, going = (b['z']-a['z'])/gap, distance/gap
                if not .10 <= rise <= .24 or not .18 <= going <= .45:
                    continue
                matches = {}
                for index, patch in enumerate(patches):
                    height_index = (patch['z']-a['z'])/rise
                    step = int(round(height_index))
                    if not 0 <= step < 100:
                        continue
                    d = patch['xy']-a['xy']
                    error = abs(patch['z']-a['z']-step*rise)
                    along_error = abs(float(d@direction)-step*going)
                    cross_error = abs(float(d@np.array([-direction[1], direction[0]])))
                    if (error > .025 or along_error > .045 or cross_error > .10
                            or abs(direction@patch['axis']) > .2
                            or abs(patch['width']-a['width']) > .25):
                        continue
                    score = error+along_error+cross_error
                    if step not in matches or score < matches[step][0]:
                        matches[step] = (score, index)
                steps = sorted(matches)
                # A distant unrelated patch cannot jump a long unsupported run.
                breaks = np.where(np.diff(steps) > 3)[0]
                if len(breaks):
                    steps = steps[:int(breaks[0])+1]
                if len(steps) < 4 or steps[0] != 0:
                    continue
                missing = steps[-1]+1-len(steps)
                if missing > (steps[-1]+1)*.4:
                    continue
                indices = [matches[step][1] for step in steps]
                selected = [patches[i] for i in indices]
                # Refit the lattice against all observations, not the seed pair.
                design = np.column_stack([np.ones(len(steps)), steps])
                zfit = np.linalg.lstsq(design, [p['z'] for p in selected], rcond=None)[0]
                xyfit = np.linalg.lstsq(design, [p['xy'] for p in selected], rcond=None)[0]
                fitted_going = float(np.linalg.norm(xyfit[1]))
                fitted_direction = xyfit[1]/fitted_going
                candidates.append({'indices': indices, 'observed_steps': steps,
                    'steps': steps[-1]+1, 'rise': float(zfit[1]),
                    'going': fitted_going, 'direction': fitted_direction,
                    'first_xy': xyfit[0], 'first_z': float(zfit[0]),
                    'missing': missing})
    candidates.sort(key=lambda c: (-len(c['indices']), c['missing'], c['indices']))
    used, result = set(), []
    for candidate in candidates:
        if used.intersection(candidate['indices']):
            continue
        used.update(candidate['indices'])
        result.append(candidate)
    return sorted(result, key=lambda c: (c['first_z'], *c['first_xy']))
