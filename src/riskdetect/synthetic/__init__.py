"""Simulated users and platforms with a known answer key, for building and testing."""

from riskdetect.synthetic.generator import (
    AnswerKeyEntry,
    SimulationResult,
    assign_personas,
    simulate,
)
from riskdetect.synthetic.personas import PERSONAS, PersonaName
from riskdetect.synthetic.platforms import PROFILES
from riskdetect.synthetic.scenario import Scenario, ScenarioError, load_scenario
from riskdetect.synthetic.writer import read_answer_key, write_simulation

__all__ = [
    "PERSONAS",
    "PROFILES",
    "AnswerKeyEntry",
    "PersonaName",
    "Scenario",
    "ScenarioError",
    "SimulationResult",
    "assign_personas",
    "load_scenario",
    "read_answer_key",
    "simulate",
    "write_simulation",
]
