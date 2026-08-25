"""Create, execute, reveal, or export a sealed walk-forward experiment.

The manifest format is JSON so the command does not add a YAML parser runtime
dependency. Use ``--preview`` before ``--execute`` to inspect chronology without
calculating outcomes.
"""

import argparse
import json
from pathlib import Path

from app import create_app
from app.research.walk_forward import WalkForwardService


def _read_manifest(path: str) -> dict:
    try:
        return json.loads(Path(path).read_text())
    except OSError as exc:
        raise SystemExit(f'Unable to read manifest: {exc}') from exc
    except json.JSONDecodeError as exc:
        raise SystemExit(f'Manifest must be valid JSON: {exc}') from exc


def main():
    parser = argparse.ArgumentParser(description='Run reproducible walk-forward research.')
    parser.add_argument('--manifest', help='Path to a JSON experiment manifest')
    parser.add_argument('--preview', action='store_true', help='Validate data and print folds only')
    parser.add_argument('--execute', action='store_true', help='Create/seal and execute the OOS folds')
    parser.add_argument('--resume', metavar='EXPERIMENT_ID', help='Resume a sealed experiment')
    parser.add_argument('--reveal-holdout', metavar='EXPERIMENT_ID', help='Deliberately execute final holdout')
    parser.add_argument('--export', metavar='EXPERIMENT_ID', help='Print full canonical report JSON')
    args = parser.parse_args()

    selected = sum(bool(value) for value in [
        args.preview, args.execute, args.resume, args.reveal_holdout, args.export,
    ])
    if selected != 1:
        parser.error('Choose exactly one action: --preview, --execute, --resume, --reveal-holdout, or --export')
    if (args.preview or args.execute) and not args.manifest:
        parser.error('--manifest is required with --preview and --execute')

    app = create_app()
    with app.app_context():
        if args.preview:
            print(json.dumps(WalkForwardService.preview(_read_manifest(args.manifest)), indent=2, default=str))
            return
        if args.execute:
            experiment, _ = WalkForwardService.create(_read_manifest(args.manifest))
            completed = WalkForwardService.execute(experiment.id)
            print(json.dumps(WalkForwardService.detail(completed.id), indent=2, default=str))
            return
        if args.resume:
            completed = WalkForwardService.execute(args.resume)
            print(json.dumps(WalkForwardService.detail(completed.id), indent=2, default=str))
            return
        if args.reveal_holdout:
            completed = WalkForwardService.reveal_holdout(args.reveal_holdout, revealed_by='cli')
            print(json.dumps(WalkForwardService.detail(completed.id), indent=2, default=str))
            return
        print(json.dumps(WalkForwardService.detail(args.export), indent=2, default=str))


if __name__ == '__main__':
    main()
