"""Research-validation API for sealed walk-forward experiments."""

import json

from flask import Blueprint, Response, jsonify, request

from app.models.db import ResearchExperiment
from app.research.walk_forward import WalkForwardService


research_bp = Blueprint('research', __name__)


def _payload_or_error():
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        raise ValueError('Request body must be a JSON object')
    return payload


@research_bp.route('/experiments/preview', methods=['POST'])
def preview_experiment():
    try:
        return jsonify(WalkForwardService.preview(_payload_or_error())), 200
    except ValueError as exc:
        return jsonify({'error': str(exc)}), 400


@research_bp.route('/experiments', methods=['POST'])
def create_experiment():
    try:
        experiment, created = WalkForwardService.create(_payload_or_error())
        return jsonify({
            'created': created,
            'experiment': experiment.to_dict(),
        }), 201 if created else 200
    except ValueError as exc:
        return jsonify({'error': str(exc)}), 400


@research_bp.route('/experiments', methods=['GET'])
def list_experiments():
    experiments = (
        ResearchExperiment.query
        .order_by(ResearchExperiment.created_at.desc())
        .limit(50)
        .all()
    )
    return jsonify({'experiments': [experiment.to_dict() for experiment in experiments]}), 200


@research_bp.route('/experiments/<experiment_id>/execute', methods=['POST'])
def execute_experiment(experiment_id):
    try:
        experiment = WalkForwardService.execute(experiment_id)
        return jsonify(WalkForwardService.detail(experiment.id)), 200
    except ValueError as exc:
        return jsonify({'error': str(exc)}), 400


@research_bp.route('/experiments/<experiment_id>/reveal-holdout', methods=['POST'])
def reveal_holdout(experiment_id):
    try:
        payload = request.get_json(silent=True) or {}
        revealed_by = str(payload.get('revealed_by', 'api')).strip()[:100] or 'api'
        experiment = WalkForwardService.reveal_holdout(experiment_id, revealed_by=revealed_by)
        return jsonify(WalkForwardService.detail(experiment.id)), 200
    except ValueError as exc:
        return jsonify({'error': str(exc)}), 400


@research_bp.route('/experiments/<experiment_id>/export', methods=['GET'])
def export_experiment(experiment_id):
    try:
        payload = WalkForwardService.detail(experiment_id)
    except ValueError as exc:
        return jsonify({'error': str(exc)}), 404
    filename = f'walk_forward_{experiment_id[:8]}.json'
    return Response(
        json.dumps(payload, indent=2, default=str),
        mimetype='application/json',
        headers={'Content-Disposition': f'attachment; filename={filename}'},
    )


@research_bp.route('/experiments/<experiment_id>', methods=['GET'])
def get_experiment(experiment_id):
    try:
        return jsonify(WalkForwardService.detail(experiment_id)), 200
    except ValueError as exc:
        return jsonify({'error': str(exc)}), 404
