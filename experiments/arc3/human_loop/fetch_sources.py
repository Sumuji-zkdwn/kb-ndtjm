"""Download the two public source archives; the laboratory archive stays local."""
import argparse
from pathlib import Path
import requests
from data import digest, save_json

PUBLIC = {
    'arc-human.zip': {
        'url': 'https://drive.usercontent.google.com/download?id=1aJmVxDPEyQ7m-FUVqHXCU_LcJGsnmBuk&export=download&confirm=t',
        'landing': 'https://arcprize.org/blog/arc-agi-3-human-dataset',
        'sha256': '99a32ffc3b9e55bc3077b979d00906f256c26354b5fada0b052690b2f5cd634a',
        'bytes': 111142305,
    },
    'janssen-raw.zip': {
        'url': 'https://osf.io/download/8c4ks/',
        'landing': 'https://doi.org/10.1371/journal.pone.0307832',
        'sha256': '9b3cfe6384418e9e9e3bdd05589d7b4345029b55ef22792fac0929ad5dad9ea3',
        'bytes': 135933590,
    },
}


def fetch(output):
    output = Path(output); output.mkdir(parents=True, exist_ok=True)
    for name, spec in PUBLIC.items():
        target = output/name
        if not target.exists():
            part = target.with_suffix('.partial')
            with requests.get(spec['url'], stream=True, timeout=(15, 60)) as r:
                r.raise_for_status()
                total = 0
                with part.open('wb') as f:
                    for chunk in r.iter_content(1<<20):
                        total += len(chunk)
                        if total > spec['bytes']: raise ValueError('Public archive size changed; review a new source version')
                        f.write(chunk)
            if digest(part) != spec['sha256']: raise ValueError('Source bytes changed; do not silently accept')
            part.replace(target)
        if digest(target) != spec['sha256']: raise ValueError('Cached public archive changed')
        print(name, 'verified', flush=True)
    save_json(output/'public-sources.json', PUBLIC)


if __name__ == '__main__':
    p=argparse.ArgumentParser(); p.add_argument('--output', required=True)
    fetch(p.parse_args().output)
