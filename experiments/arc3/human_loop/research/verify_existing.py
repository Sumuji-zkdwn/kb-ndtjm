"""Replay existing finite examples and inspect the stored mathematical figure.

This checks copied source modules, not a new human-state or ARC decision model.
Python standard library only; no source edits, network access, or Lean rebuild.
"""
import argparse
import hashlib
import importlib.util
import json
import math
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parent
sys.dont_write_bytecode = True


def require(condition, message):
    if not condition:
        raise AssertionError(message)


def module(name, relative):
    spec = importlib.util.spec_from_file_location(name, ROOT / relative)
    result = importlib.util.module_from_spec(spec)
    sys.modules[name] = result
    spec.loader.exec_module(result)
    return result


def verify():
    provenance = json.loads((ROOT / 'provenance.json').read_text(encoding='utf-8'))
    artifacts = provenance['source_modules'] + provenance['artifacts']
    for item in artifacts:
        raw = (ROOT / item['file']).read_bytes()
        require(len(raw) == item['bytes'], f"Size mismatch: {item['file']}")
        require(hashlib.sha256(raw).hexdigest() == item['sha256'],
                f"Source/artifact hash mismatch: {item['file']}")

    primitive = module('recorded_primitive', 'sources/primitive/primitive.py')
    model = primitive.three_state_system()
    ab, ba = model.run(2, ['B', 'A']), model.run(2, ['A', 'B'])
    require((ab.final_state, ba.final_state) == (0, 1), 'Original AB/BA states')
    require(ab.observation == ba.observation == 0, 'Common current observation')
    word = model.distinguishing_word(ab.final_state, ba.final_state)
    require(word == ('B',), 'Original shortest distinguishing continuation')
    require((model.run(0, word).observation, model.run(1, word).observation) == (0, 1),
            'B must distinguish the two hidden states')
    try:
        model.quotient(model.initial_partition())
    except ValueError as exc:
        rejected = str(exc)
    else:
        raise AssertionError('Unsafe observational quotient accepted')
    _, partition = model.quotient()
    require(partition == (0, 1, 2), 'Future partition must retain all three states')

    # examples.py imports finite by its original module name.
    module('finite', 'sources/flow/finite.py')
    examples = module('recorded_flow_examples', 'sources/flow/examples.py')
    flow = examples.hidden_load()
    probe = flow.distinguish('calm', 'loaded')
    unknown = flow.distinguish('calm', 'loaded', 0)
    require(probe['status'] == 'distinguished' and probe['word'] == ['push'],
            'Original Flow hidden-load witness')
    require(unknown['status'] == 'unknown_budget', 'Budget exhaustion is not equivalence')

    target = 0.2
    roots = [target]
    inverse_checks = []
    for depth in range(1, 5):
        roots = sorted(math.cos((math.acos(value) + 2 * math.pi * k) / 3)
                       for value in roots for k in range(3))
        require(len(roots) == 3 ** depth, 'Inverse branch count')
        require(min(b - a for a, b in zip(roots, roots[1:])) > 1e-9,
                'Inverse states must be distinct')
        residuals = []
        for state in roots:
            value = state
            for _ in range(depth):
                value = 4 * value ** 3 - 3 * value
            residuals.append(abs(value - target))
            energy = lambda u: (state ** 2 - 0.75) ** 2 - u * state
            require(abs((energy(0) - energy(1)) - state) < 1e-14,
                    'Energy difference at the same unchanged state')
        residual = max(residuals)
        require(residual < 1e-10, 'Composed T3 residual')
        inverse_checks.append({'depth': depth, 'distinct_inverse_states': len(roots),
                               'max_residual': residual})

    saved = json.loads((ROOT / 'figures/checks.json').read_text(encoding='utf-8'))
    require(saved['root_observation'] == target, 'Figure root observation')
    require([r['distinct_inverse_states'] for r in saved['inverse_tree_checks']] == [3, 9, 27, 81],
            'Recorded figure branch counts')
    return {
        'status': 'passed',
        'hashed_files_checked': len(artifacts),
        'primitive': {'AB': ab.as_dict(), 'BA': ba.as_dict(),
                      'distinguishing_word': list(word),
                      'initial_partition': list(model.initial_partition()),
                      'future_partition': list(partition),
                      'unsafe_quotient_rejected': rejected},
        'flow': {'distinguishing_probe': probe, 'zero_budget_result': unknown},
        'chebyshev': inverse_checks,
        'same_state_energy_difference_checked': True,
        'original_sources_copied_without_changes': True,
        'lean_rebuilt': False,
        'human_state_identified': False,
        'arc_decision_integration_implemented': False,
        'scheduled_exploration_started': False,
        'official_submission': 'manual_only',
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    report = json.dumps(verify(), ensure_ascii=False, indent=2) + '\n'
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(report, encoding='utf-8')
    print(report, end='')


if __name__ == '__main__':
    main()
