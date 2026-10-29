"""Read human observations, never execute source archives or serialized Java objects.

Action columns: previous action, stage, past signal, condition, target, split group.
Duration columns: observed duration, event (0=censored), stage, condition, split group.
All predictors precede their target. Domains keep separate observation semantics.
"""
from __future__ import annotations
import argparse
from collections import Counter, defaultdict
import csv
import hashlib
import io
import json
from pathlib import Path
import re
import xml.etree.ElementTree as ET
import zipfile
import numpy as np

DOMAINS = ('arc', 'lab', 'janssen')
SCHEMA = 2


def digest(path):
    with open(path, 'rb') as f:
        return hashlib.file_digest(f, 'sha256').hexdigest()


def save_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + '.tmp')
    tmp.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + '\n', encoding='utf-8')
    tmp.replace(path)


def arc_records(stream):
    """Full JSON decoding keeps frame/action association auditable; one line at a time."""
    for b in stream:
        if b.strip():
            d = json.loads(b)['data']
            if 'action_input' in d:
                yield d
            elif 'cards' not in d or 'total_actions' not in d:
                raise ValueError('Unrecognized ARC recording row')


def arc_session(records, group):
    actions, durations = [], []
    previous = None
    previous_action = 8  # explicit start symbol, outside ARC action IDs
    last_change = 0
    level_start = 0
    count = 0
    max_level = 0
    resets = 0
    for d in records:
        raw_action = str(d['action_input']['id'])
        a = 0 if raw_action == 'RESET' else int(raw_action.removeprefix('ACTION'))
        d['available_actions'] = [0 if str(v) == 'RESET' else int(str(v).removeprefix('ACTION')) for v in d.get('available_actions', [])]
        if not 0 <= a <= 7:
            raise ValueError('Unknown ARC action')
        level = int(d['levels_completed'])
        if previous is not None:
            # Features use the previous returned observation, never d's outcome.
            stage = min(int(previous['levels_completed']), 3)
            signal = min((count - last_change) // 8, 3)
            condition = int(6 in previous.get('available_actions', []))
            actions.append([previous_action, stage, signal, condition, a, group])
            count += 1
            if level > max_level:
                if level != max_level + 1:
                    raise ValueError('ARC multi-level jump needs explicit handling')
                durations.append([count - level_start, 1, min(max_level, 3), condition, group])
                level_start = count
                max_level = level
            if a == 0:
                resets += 1
            # A level regression is a full reset: do not fabricate fresh human trials.
            # Track elapsed effort until first attainment of each new level.
        frame = d.get('frame', [])
        frame_hash = hashlib.sha256(json.dumps(frame, separators=(',', ':')).encode()).digest()
        if previous is None or frame_hash != previous['_frame_hash']:
            last_change = count
        d.pop('frame', None)
        d['_frame_hash'] = frame_hash
        previous = d
        previous_action = a
    if previous is None:
        raise ValueError('Empty replay')
    solved = previous['state'] == 'WIN'
    if not solved and count > level_start:
        durations.append([count - level_start, 0, min(max_level, 3),
                          int(6 in previous.get('available_actions', [])), group])
    return actions, durations, {'actions': count, 'solved': solved, 'level_resets': resets,
                                'levels': max_level, 'game_version': previous['game_id']}


def read_arc(path):
    actions, durations, sessions = [], [], []
    with zipfile.ZipFile(path) as z:
        names = sorted(n for n in z.namelist() if n.endswith('.recording.jsonl') and not n.startswith('__MACOSX/'))
        games = sorted({n.split('/')[1] for n in names})
        for i, name in enumerate(names):
            game = name.split('/')[1]
            with z.open(name) as f:
                a, d, meta = arc_session(arc_records(f), games.index(game))
            actions.extend(a); durations.extend(d)
            sessions.append({'game': game, **meta})
            if (i + 1) % 25 == 0:
                print(f'ARC replay {i+1}/{len(names)}', flush=True)
    return actions, durations, {'group_unit': 'environment', 'groups': len(games), 'sessions': len(names),
        'per_game_replays': dict(Counter(x['game'] for x in sessions)),
        'solves': sum(x['solved'] for x in sessions), 'versions': sorted({x['game_version'] for x in sessions}),
        'article_replays': 342, 'archive_replays': len(names),
        'identity_limit': 'Replay GUID is not a participant ID. Environment holdout, not verified participant holdout.',
        'action_target': 'next ARC action ID, after preceding returned frame',
        'duration_target': 'actions until first attainment of the next level; final unfinished level censored',
        'notice_label': 'unobserved; frame stagnation is only a predictive proxy'}


def csv_rows(z, name):
    return list(csv.DictReader(io.StringIO(z.read(name).decode('utf-8-sig'))))


def direction(dx, dy):
    return (int(np.sign(dx)) + 1) * 3 + int(np.sign(dy)) + 1


def read_lab(path):
    actions, durations = [], []
    with zipfile.ZipFile(path) as z:
        names = sorted(n for n in z.namelist() if '/04_data/' in n and n.endswith('/Player1.csv'))
        pairs = sorted({n.split('/')[3] for n in names})
        for n in names:
            prefix = n.rsplit('/', 1)[0]
            group = pairs.index(n.split('/')[3])
            condition = {'Comp': 0, 'Coop': 1}[n.split('/')[2]]
            field = csv_rows(z, prefix + '/TokenField.csv')
            end = float(field[-1]['time'])
            for player in (1, 2):
                rows = csv_rows(z, f'{prefix}/Player{player}.csv')
                prev_action, run = 9, 0
                for before, after in zip(rows, rows[1:]):
                    if float(after['rt']) < float(before['rt']):
                        raise ValueError('Nonmonotone lab trace')
                    a = direction(float(after['x'])-float(before['x']), float(after['y'])-float(before['y']))
                    actions.append([prev_action, min(int(float(before['rt']) // 60), 3), min(run // 8, 3), condition, a, group])
                    run = run + 1 if a == prev_action else 0
                    prev_action = a
                harvests = csv_rows(z, f'{prefix}/Harvest_Player{player}.csv')
                last = 0.
                for row in harvests:
                    t = float(row['rt'])
                    if t <= last:
                        raise ValueError('Nonpositive lab harvest interval')
                    durations.append([t-last, 1, min(int(last // 60), 3), condition, group])
                    last = t
                if end > last:
                    durations.append([end-last, 0, min(int(last // 60), 3), condition, group])
    return actions, durations, {'group_unit': 'pair across rounds and conditions', 'groups': len(pairs),
        'sessions': len(names), 'person_rounds': 2*len(names),
        'action_target': 'next sampled avatar displacement in 9 sign directions (includes stay); not keypress',
        'duration_target': 'seconds until next recorded harvest; censored at last field observation',
        'deduplication': '04_data only; 03_rawdata duplicate copies excluded',
        'privacy': 'No pair names, original filenames, absolute timestamps, or participant identifiers exported'}


def resolve_reference(element, parents):
    """Resolve XStream relative XML paths without Java deserialization."""
    seen = set()
    while 'reference' in element.attrib:
        if id(element) in seen:
            raise ValueError('Cyclic XStream reference')
        seen.add(id(element))
        path = element.attrib['reference']
        current = element
        for part in path.split('/'):
            if part == '..':
                current = parents[current]
            elif part and part != '.':
                match = re.fullmatch(r'(.+?)(?:\[(\d+)\])?', part)
                tag, index = match.group(1), int(match.group(2) or 1)
                matches = [x for x in current if x.tag == tag]
                current = matches[index-1]
        element = current
    return element


def janssen_round(raw, group, condition, round_no):
    root = ET.fromstring(raw)
    parents = {child: parent for parent in root.iter() for child in parent}
    events = root.find('sorted-set')
    people = defaultdict(list)
    mapping = {'UP': 0, 'DOWN': 1, 'LEFT': 2, 'RIGHT': 3}
    unresolved = 0
    for e in events:
        kind = e.tag.rsplit('.', 1)[-1]
        if kind not in ('MovementEvent', 'TokenCollectedEvent'):
            continue  # explicitly exclude chat, network metadata and demographic data
        node = resolve_reference(e.find('id'), parents)
        uid = node.findtext('uuid')
        if not uid:
            raise ValueError('Missing participant linkage in Janssen event')
        a = mapping[e.findtext('direction')] if kind == 'MovementEvent' else 4
        people[uid].append((int(e.findtext('creationTime')), a))
    actions, durations = [], []
    for sequence in people.values():
        sequence.sort(key=lambda x: x[0])
        prev, run = 5, 0
        phase = min((round_no - 1)//3, 2)
        for i, (t, a) in enumerate(sequence):
            actions.append([prev, phase, min(run//4, 3), condition, a, group])
            if i:
                dt = (t - sequence[i-1][0])/1000
                if dt > 0:
                    durations.append([dt, 1, phase, condition, group])
                else:
                    unresolved += 1  # millisecond ties are reported, not silently replaced by epsilon
            run = run + 1 if a == prev else 0
            prev = a
    return actions, durations, len(people), unresolved


def read_janssen(path):
    actions, durations = [], []
    person_rounds, ties = 0, 0
    with zipfile.ZipFile(path) as z:
        # Round 0 is explicit practice. Keep every available experimental round 1..9.
        names = sorted(n for n in z.namelist() if re.search(r'/[1-9]-round-save\.xml$', n))
        sessions = sorted({n.rsplit('/', 1)[0] for n in names})
        treatments = sorted({n.split('/')[1] for n in names})
        for i, name in enumerate(names):
            group = sessions.index(name.rsplit('/', 1)[0])
            condition = treatments.index(name.split('/')[1])
            a, d, people, tied = janssen_round(z.read(name), group, condition, int(name.rsplit('/', 1)[1][0]))
            actions.extend(a); durations.extend(d)
            person_rounds += people; ties += tied
            if (i+1) % 24 == 0:
                print(f'Janssen round {i+1}/{len(names)}', flush=True)
    return actions, durations, {'group_unit': 'whole experimental session across all rounds',
        'groups': len(sessions), 'rounds': len(names), 'person_rounds': person_rounds,
        'treatments': treatments, 'same_millisecond_intervals_excluded': ties,
        'action_target': 'next recorded movement direction or token collection, per participant',
        'duration_target': 'positive seconds between recorded movement/harvest events; no inferred terminal censor',
        'duration_limit': 'Conditional on a subsequent recorded event, not an unconditional waiting-time distribution.',
        'privacy': 'No UUID, network address, station number, chat text, or absolute timestamp exported',
        'source': 'DeCaro, DeCaro, Janssen, Lee, Graci & Flener (2024), doi:10.1371/journal.pone.0307832, OSF v3drm'}


def prepare(arc_zip, lab_zip, janssen_zip, output):
    output = Path(output)
    if output.exists():
        raise FileExistsError('Choose a new immutable dataset output directory')
    output.mkdir(parents=True)
    metadata = {'schema': SCHEMA, 'sources': {}, 'domains': {}}
    arrays = {}
    for domain, file, reader in zip(DOMAINS, (arc_zip, lab_zip, janssen_zip), (read_arc, read_lab, read_janssen)):
        a, d, meta = reader(file)
        arrays[domain+'_actions'] = np.asarray(a, dtype=np.int32).reshape(-1, 6)
        arrays[domain+'_durations'] = np.asarray(d, dtype=np.float64).reshape(-1, 5)
        meta.update(action_observations=len(a), duration_observations=len(d),
                    censored=sum(1 for x in d if x[1] == 0))
        metadata['sources'][domain] = {'sha256': digest(file), 'bytes': Path(file).stat().st_size}
        metadata['domains'][domain] = meta
        print(domain, len(a), len(d), flush=True)
    np.savez_compressed(output/'observations.npz', **arrays)
    metadata['observations_sha256'] = digest(output/'observations.npz')
    metadata['normalizer_sha256'] = digest(__file__)
    save_json(output/'manifest.json', metadata)
    return metadata


if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('--arc-zip', required=True); p.add_argument('--lab-zip', required=True)
    p.add_argument('--janssen-zip', required=True); p.add_argument('--output', required=True)
    args = p.parse_args()
    prepare(args.arc_zip, args.lab_zip, args.janssen_zip, args.output)
