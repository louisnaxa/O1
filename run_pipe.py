#!/usr/bin/env python3
"""
run_pipe.py — Point d'entrée CLI du tuyau V0.

Usage :
    python run_pipe.py "Écris greet(name) dans scratch/hello.py"
    python run_pipe.py "..." --repo owner/repo --branch main
    python run_pipe.py "..." --step          # mode débogage pas-à-pas
    python run_pipe.py "..." --log pipe.log  # log dans un fichier en plus de stdout

Inject en mode automatique (dans un autre terminal) :
    echo "ton message" > inject.txt
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import sys
from pathlib import Path

from orchestrateur.pipe import MAX_TURNS, run_pipe


def _setup_logging(verbose: bool) -> None:
    level = logging.DEBUG if verbose else logging.WARNING
    logging.basicConfig(level=level, format="%(name)s %(levelname)s %(message)s")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Tuyau agent↔superviseur V0",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("task", help="Consigne à envoyer à l'agent")
    parser.add_argument("--repo", default=None, help="owner/repo GitHub (ex: monuser/monrepo)")
    parser.add_argument("--branch", default=None, help="Branche à vérifier (ex: main)")
    parser.add_argument(
        "--step", action="store_true",
        help="Mode débogage : pause après chaque tour",
    )
    parser.add_argument(
        "--log", default=None, metavar="FILE",
        help="Fichier de log (en plus de stdout)",
    )
    parser.add_argument(
        "--max-turns", type=int, default=MAX_TURNS,
        help=f"Nombre max de tours (défaut : {MAX_TURNS})",
    )
    parser.add_argument(
        "--budget", type=float, default=2.0, metavar="USD",
        help="Budget max par appel agent en USD (défaut : 2.0)",
    )
    parser.add_argument("-v", "--verbose", action="store_true", help="Log DEBUG")
    args = parser.parse_args()

    _setup_logging(args.verbose)

    summary = asyncio.run(
        run_pipe(
            task=args.task,
            repo=args.repo,
            branch=args.branch,
            step=args.step,
            workdir=os.getcwd(),
            log_file=Path(args.log) if args.log else None,
            max_turns=args.max_turns,
            max_budget_usd=args.budget,
        )
    )

    # Code de sortie : 0 = STOP (succès), 1 = autre
    sys.exit(0 if summary["final_decision"] == "STOP" else 1)


if __name__ == "__main__":
    main()
