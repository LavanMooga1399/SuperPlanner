"""Random-key genetic algorithm over the serial SGS decoder (ARCHITECTURE 8.5)."""

from __future__ import annotations

import random
import statistics
import threading
import time
from dataclasses import dataclass
from typing import ClassVar

from ..compiled import CompiledProblem
from ..decoder import decode
from ..evaluate import Evaluated, evaluate_decode
from ..graph import cpm
from ..model import Placement
from ..objectives import ObjectiveRefs, dominates
from .base import (ALL_RULES, Alternative, GaParams, ProgressCallback, ProgressEvent, SolveResult,
                   SolverCapabilities, SolverConfig)
from .heuristic import rule_priorities


@dataclass
class _Ind:
    keys: list[float]
    genes: list[float]
    ev: Evaluated | None = None


class GaSolver:
    name: ClassVar[str] = "ga"
    capabilities: ClassVar[SolverCapabilities] = SolverCapabilities(
        alternative_resources=True, calendars=True, multi_objective=True, proves_optimality=False,
        proves_infeasibility=False, uses_hint=True, deterministic_with_seed=True)

    def solve(self, problem: CompiledProblem, config: SolverConfig, progress_cb: ProgressCallback | None = None,
              cancel_event: threading.Event | None = None) -> SolveResult:
        t0 = time.monotonic()
        deadline = t0 + config.time_limit_seconds
        p: GaParams = config.ga
        rng = random.Random(config.seed)
        refs = config.refs or ObjectiveRefs()
        tasks = problem.tasks
        n = len(tasks)
        gene_slots: list[tuple[int, int, int]] = []  # (task, req, n_alt)
        for t in tasks:
            if t.locked_start is not None and t.locked_resources is not None:
                continue
            if t.locked_start is not None:
                continue
            for i, rq in enumerate(t.requirements):
                if len(rq.alternatives) >= 2:
                    gene_slots.append((t.idx, i, len(rq.alternatives)))
        pop_size = p.population_size or min(80, max(20, n // 2))
        base_rate, base_sigma = p.mutation_rate, p.mutation_sigma
        rate, sigma = base_rate, base_sigma

        def choice_of(genes: list[float]) -> dict[tuple[int, int], int]:
            return {(ti, ri): min(int(g * na), na - 1) for (ti, ri, na), g in zip(gene_slots, genes)}

        evaluations = 0
        stop_reason: str | None = None

        def out_of_time() -> str | None:
            if cancel_event is not None and cancel_event.is_set():
                return "cancelled"
            if time.monotonic() >= deadline:
                return "time_limit"
            return None

        def evaluate(ind: _Ind) -> None:
            nonlocal evaluations
            dr = decode(problem, ind.keys, choice_of(ind.genes))
            ind.ev = evaluate_decode(problem, dr, config.weights, refs, "ga")
            evaluations += 1

        def encode(placements: list[Placement]) -> _Ind:
            pos = {pl.task_id: pl for pl in placements}
            order = sorted(range(n), key=lambda i: (pos[tasks[i].id].start if tasks[i].id in pos else 1 << 40, i))
            keys = [0.0] * n
            for r, i in enumerate(order):
                keys[i] = r / max(1, n)
            genes = []
            for ti, ri, na in gene_slots:
                pl = pos.get(tasks[ti].id)
                g = rng.random()
                if pl is not None and ri < len(pl.resource_ids):
                    k = problem.resource_index.get(pl.resource_ids[ri])
                    alts = tasks[ti].requirements[ri].alternatives
                    if k in alts:
                        g = (alts.index(k) + 0.5) / na
                genes.append(g)
            return _Ind(keys, genes)

        # --- population initialization (never fully random)
        cpm_res = cpm(problem)
        seeds: list[_Ind] = []
        for rule in ALL_RULES:
            pri = rule_priorities(problem, rule, cpm_res)
            dr = decode(problem, pri)
            ind = encode(dr.placements)
            ind.keys = list(pri)
            seeds.append(ind)
        if config.initial_solution:
            seeds.insert(0, encode(config.initial_solution))
        max_seeds = max(1, int(0.2 * pop_size))
        seeds = seeds[:max_seeds]
        population: list[_Ind] = list(seeds)
        n_mut = int(0.3 * pop_size)
        for j in range(n_mut):
            src = seeds[j % len(seeds)]
            population.append(self._mutate(_Ind(list(src.keys), list(src.genes)), rng, min(0.5, 2 * rate), sigma,
                                           p.swap_rate, len(gene_slots)))
        while len(population) < pop_size:
            population.append(_Ind([rng.random() for _ in range(n)], [rng.random() for _ in gene_slots]))

        archive: list[Evaluated] = []

        def offer(ev: Evaluated) -> None:
            if not ev.feasible:
                return
            vec = (ev.values.makespan_minutes, ev.values.weighted_tardiness, ev.values.cost)
            for a in archive:
                av = (a.values.makespan_minutes, a.values.weighted_tardiness, a.values.cost)
                if av == vec or dominates(av, vec):
                    return
            archive[:] = [a for a in archive if not dominates(
                vec, (a.values.makespan_minutes, a.values.weighted_tardiness, a.values.cost))]
            archive.append(ev)
            if len(archive) > p.archive_size:
                archive.sort(key=lambda a: a.values.score)
                del archive[p.archive_size:]

        best: _Ind | None = None
        for ind in population:
            stop_reason = out_of_time()
            if stop_reason:
                break
            evaluate(ind)
            offer(ind.ev)  # type: ignore[arg-type]
        population = [ind for ind in population if ind.ev is not None]
        if not population:  # cancelled before anything was evaluated: evaluate one seed
            evaluate(seeds[0])
            population = [seeds[0]]
        population.sort(key=lambda d: d.ev.key)  # type: ignore[union-attr]
        best = population[0]
        no_improve = 0
        generation = 0
        while stop_reason is None:
            if generation >= p.max_generations:
                stop_reason = "generation_limit"
                break
            if no_improve >= p.stagnation_generations:
                stop_reason = "stagnation"
                break
            generation += 1
            new_pop: list[_Ind] = population[:min(p.elite_count, len(population))]
            children: list[_Ind] = []
            while len(new_pop) + len(children) < pop_size:
                a = self._tournament(population, rng, p.tournament_size)
                b = self._tournament(population, rng, p.tournament_size)
                if rng.random() < p.crossover_rate:
                    keys = [x if rng.random() < 0.5 else y for x, y in zip(a.keys, b.keys)]
                    genes = [x if rng.random() < 0.5 else y for x, y in zip(a.genes, b.genes)]
                else:
                    keys, genes = list(a.keys), list(a.genes)
                children.append(self._mutate(_Ind(keys, genes), rng, rate, sigma, p.swap_rate, len(gene_slots)))
            evaluated_children = []
            for c in children:
                stop_reason = out_of_time()
                if stop_reason:
                    break
                evaluate(c)
                offer(c.ev)  # type: ignore[arg-type]
                evaluated_children.append(c)
            population = new_pop + evaluated_children
            population.sort(key=lambda d: d.ev.key)  # type: ignore[union-attr]
            improved = population[0].ev.key < best.ev.key  # type: ignore[union-attr]
            if improved:
                best = population[0]
                no_improve = 0
                rate, sigma = base_rate, base_sigma
            else:
                no_improve += 1
            diversity = 0.0
            if n and len(population) > 1:
                cols = list(zip(*[ind.keys for ind in population]))
                diversity = sum(statistics.pstdev(c) for c in cols) / len(cols)
            if not improved and (no_improve % 10 == 0 or diversity < 0.05):
                rate = min(0.5, max(0.01, rate * 1.5))
                sigma = min(0.5, max(0.01, sigma * 1.5))
            rate = max(0.01, rate)
            if progress_cb is not None:
                feas_frac = sum(1 for d in population if d.ev.feasible) / len(population)  # type: ignore[union-attr]
                progress_cb(ProgressEvent(
                    type="progress", solver="ga", elapsed_seconds=time.monotonic() - t0, iteration=generation,
                    best_score=best.ev.values.score, best_objectives=best.ev.values,  # type: ignore[union-attr]
                    feasible_found=best.ev.feasible,  # type: ignore[union-attr]
                    extra={"feasible_fraction": round(feas_frac, 4), "mutation_rate": round(rate, 6),
                           "diversity": round(diversity, 6)}))
        ev = best.ev
        assert ev is not None
        cancelled = stop_reason == "cancelled"
        alts = [Alternative(label="", solver="ga", objectives=a.values, placements=a.placements)
                for a in archive if a.placements is not ev.placements]
        return SolveResult(
            solver="ga", status="cancelled" if cancelled else "completed",
            feasibility="feasible" if ev.feasible else "unknown",
            termination_reason=stop_reason or "generation_limit",  # type: ignore[arg-type]
            optimality_proven=False, objectives=ev.values if ev.placements else None, placements=ev.placements,
            iterations=generation, elapsed_seconds=time.monotonic() - t0, alternatives=alts,
            diagnostics=[] if ev.feasible else ["The genetic algorithm found no schedule without hard violations."])

    @staticmethod
    def _tournament(pop: list[_Ind], rng: random.Random, size: int) -> _Ind:
        best = None
        for _ in range(min(size, len(pop))):
            c = pop[rng.randrange(len(pop))]
            if best is None or c.ev.key < best.ev.key:  # type: ignore[union-attr]
                best = c
        return best  # type: ignore[return-value]

    @staticmethod
    def _mutate(ind: _Ind, rng: random.Random, rate: float, sigma: float, swap_rate: float, n_genes: int) -> _Ind:
        keys = ind.keys
        for i in range(len(keys)):
            if rng.random() < rate:
                keys[i] = (keys[i] + rng.gauss(0.0, sigma)) % 1.0
        genes = ind.genes
        for i in range(n_genes):
            if rng.random() < rate:
                if rng.random() < 0.5:
                    genes[i] = rng.random()
                else:
                    genes[i] = (genes[i] + rng.gauss(0.0, sigma)) % 1.0
        if len(keys) >= 2 and rng.random() < swap_rate:
            a, b = rng.randrange(len(keys)), rng.randrange(len(keys))
            keys[a], keys[b] = keys[b], keys[a]
        ind.ev = None
        return ind
