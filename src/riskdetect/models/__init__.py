"""Learned and statistical detectors that add evidence alongside the rules."""

import json
from pathlib import Path

from riskdetect.models.calibration import IsotonicCalibrator
from riskdetect.models.classifier import SupervisedClassifier, classifier_features, train_classifier
from riskdetect.models.gbdt import BoostingParams, GradientBoostedTrees
from riskdetect.models.isolation_forest import IsolationForest
from riskdetect.models.population import PopulationAnomaly, training_rows
from riskdetect.models.self_baseline import SelfBaselineAnomaly, change_score
from riskdetect.scoring.evidence import SignalSource

POPULATION_MODEL_FILE = "population_anomaly.json"
CLASSIFIER_FILE = "classifier.json"


def save_population_model(model: PopulationAnomaly, directory: Path) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / POPULATION_MODEL_FILE
    path.write_text(json.dumps(model.to_dict()), encoding="utf-8")
    return path


def save_classifier(model: SupervisedClassifier, directory: Path) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / CLASSIFIER_FILE
    path.write_text(json.dumps(model.to_dict()), encoding="utf-8")
    return path


def load_models(directory: Path) -> list[SignalSource]:
    """The detectors to use when scoring: the self-baseline always, plus the population
    model and the classifier if they have been fitted (``python -m riskdetect.models``)."""
    models: list[SignalSource] = [SelfBaselineAnomaly()]
    population = directory / POPULATION_MODEL_FILE
    if population.exists():
        models.append(PopulationAnomaly.from_dict(json.loads(population.read_text("utf-8"))))
    classifier = directory / CLASSIFIER_FILE
    if classifier.exists():
        models.append(SupervisedClassifier.from_dict(json.loads(classifier.read_text("utf-8"))))
    return models


__all__ = [
    "CLASSIFIER_FILE",
    "POPULATION_MODEL_FILE",
    "BoostingParams",
    "GradientBoostedTrees",
    "IsolationForest",
    "IsotonicCalibrator",
    "PopulationAnomaly",
    "SelfBaselineAnomaly",
    "SupervisedClassifier",
    "change_score",
    "classifier_features",
    "load_models",
    "save_classifier",
    "save_population_model",
    "train_classifier",
    "training_rows",
]
