"""Solver registry (ARCHITECTURE 7.2)."""

from __future__ import annotations

from .base import Solver
from .cpsat import CpSatSolver
from .ga import GaSolver
from .heuristic import HeuristicSolver

SOLVERS: dict[str, type] = {"heuristic": HeuristicSolver, "cpsat": CpSatSolver, "ga": GaSolver}


def get_solver(name: str) -> Solver:
    return SOLVERS[name]()


__all__ = ["SOLVERS", "get_solver", "HeuristicSolver", "CpSatSolver", "GaSolver"]
