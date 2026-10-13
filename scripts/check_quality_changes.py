"""Keep acceptance truth/tolerances separate from reconstruction changes."""
import argparse
from pathlib import PurePosixPath
import subprocess


def violations(paths):
    protected = [p for p in paths if (p.startswith("docs/quality/") and not p.endswith(".md"))
                 or p.endswith((".truth.json", ".quality-lock.json", "/quality_metrics.py", "/annotation_io.py"))]
    evaluator = {"annotation_io.py", "quality_benchmark.py", "quality_metrics.py", "reproducibility.py", "cli.py"}
    algorithms = [p for p in paths if p.startswith("src/punctora_core/")
                  and PurePosixPath(p).name not in evaluator]
    return protected, algorithms


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", required=True)
    args = parser.parse_args(argv)
    commits = subprocess.check_output(["git", "rev-list", "--reverse", "--no-merges", f"{args.base}..HEAD"],
                                      text=True).splitlines()
    for commit in commits:
        paths = subprocess.check_output(["git", "diff-tree", "--no-commit-id", "--name-only", "-r",
                                         "--diff-filter=ACMR", commit], text=True).splitlines()
        protected, algorithms = violations(paths)
        if protected and algorithms:
            parser.exit(1, "Acceptance truth/tolerances and reconstruction algorithms changed in one commit.\n"
                        f"Commit: {commit}\nProtected: {protected}\nAlgorithms: {algorithms}\n"
                        "Split and review these changes independently.\n")
    print("Acceptance lock separation passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
