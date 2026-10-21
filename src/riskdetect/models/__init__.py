"""Learned and statistical detectors that add evidence alongside the rules."""

import json
from pathlib import Path

from riskdetect.models.isolation_forest import IsolationForest
from riskdetect.models.population import PopulationAnomaly, training_rows
from riskdetect.models.self_baseline import SelfBaselineAnomaly, change_score
from riskdetect.scoring.evidence import SignalSource

POPULATION_MODEL_FILE = "population_anomaly.json"


def save_population_model(model: PopulationAnomaly, directory: Path) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / POPULATION_MODEL_FILE
    path.write_text(json.dumps(model.to_dict()), encoding="utf-8")
    return path


def load_models(directory: Path) -> list[SignalSource]:
    """The detectors to use when scoring: the self-baseline always, plus the
    population model if one has been fitted (``python -m riskdetect.models``)."""
    models: list[SignalSource] = [SelfBaselineAnomaly()]
    path = directory / POPULATION_MODEL_FILE
    if path.exists():
        data = json.loads(path.read_text(encoding="utf-8"))
        models.append(PopulationAnomaly.from_dict(data))
    return models


__all__ = [
    "POPULATION_MODEL_FILE",
    "IsolationForest",
    "PopulationAnomaly",
    "SelfBaselineAnomaly",
    "change_score",
    "load_models",
    "save_population_model",
    "training_rows",
]
