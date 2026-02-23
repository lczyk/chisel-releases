#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from pathlib import Path

from chisel_releases_data.defs import UbuntuRelease, PR  # type: ignore[import-not-found]
from chisel_releases_data.loader import load_data  # type: ignore[import-not-found]


def print_pipe_friendly(output: str) -> None:
    """Print to stdout. Make sure we work with pipes.
    https://docs.python.org/3/library/signal.html#note-on-sigpipe
    """
    try:
        print(output)
        sys.stdout.flush()
    except BrokenPipeError:
        # Gracefully handle broken pipe when e.g. piping to head
        devnull = os.open(os.devnull, os.O_WRONLY)
        os.dup2(devnull, sys.stdout.fileno())
        sys.exit(1)


################################################################################


def _group_new_slices_by_pr(
    slices_in_head_by_pr: Mapping[PR, frozenset[str]],
    slices_in_base_by_pr: Mapping[PR, frozenset[str]],
) -> dict[PR, frozenset[str]]:
    prs: set[PR] = set(slices_in_head_by_pr.keys())
    if set(slices_in_base_by_pr.keys()) != prs:
        raise ValueError(
            "slices_in_head_by_pr and slices_in_base_by_pr must have the same keys."
        )
    new_slices_by_pr: dict[PR, frozenset[str]] = {}
    for pr in sorted(prs):
        slices_in_head = slices_in_head_by_pr.get(pr, frozenset())
        slices_in_base = slices_in_base_by_pr.get(pr, frozenset())
        new_slices = slices_in_head - slices_in_base
        removed_slices = slices_in_base - slices_in_head
        if removed_slices and logging.getLogger().isEnabledFor(logging.WARNING):
            slices_string = ", ".join(sorted(removed_slices))
            slices_string = (
                slices_string
                if len(slices_string) < 100
                else slices_string[:97] + "..."
            )
            logging.warning(
                "PR #%d removed %d slices: %s",
                pr.number,
                len(removed_slices),
                slices_string,
            )
        if new_slices:
            new_slices_by_pr[pr] = frozenset(new_slices)
    return new_slices_by_pr


@dataclass(frozen=False, unsafe_hash=True)
class Comparison:
    """A pair of PRs: one into a given release, and one into a future release."""

    pr: PR
    slices: frozenset[str]
    pr_future: PR
    slices_future: frozenset[str]

    # Slices from the ubuntu release of the base PR that have been
    # discontinued in the ubuntu release of the future PR.
    discontinued_slices: frozenset[str] = field(default_factory=frozenset)

    @property
    def ubuntu_release(self) -> UbuntuRelease:
        return self.pr.ubuntu_release

    @property
    def future_ubuntu_release(self) -> UbuntuRelease:
        return self.pr_future.ubuntu_release

    def __post_init__(self) -> None:
        if self.pr.ubuntu_release >= self.pr_future.ubuntu_release:
            raise ValueError("pr_future must be into a future release compared to pr.")
        self.slices = frozenset(self.slices)
        self.slices_future = frozenset(self.slices_future)

    def is_forward_ported(self) -> bool:
        return not self.missing_slices()

    def __str__(self) -> str:
        return (
            f"#{self.pr.number}-{self.ubuntu_release.version}.."
            f"#{self.pr_future.number}-{self.future_ubuntu_release.version}"
        )

    def missing_slices(self) -> frozenset[str]:
        missing_slices = self.slices - self.slices_future
        if not missing_slices:
            return frozenset()
        if self.discontinued_slices:
            # some slices were discontinued, so they are missing for a reason
            missing_slices -= self.discontinued_slices
        return frozenset(missing_slices)

    def overlap(self) -> frozenset[str]:
        return self.slices.intersection(self.slices_future)


def _get_comparisons(
    prs_by_ubuntu_release: Mapping[UbuntuRelease, frozenset[PR]],
    new_slices_by_pr: Mapping[PR, frozenset[str]],
    packages_by_release: Mapping[UbuntuRelease, set[str]],
) -> frozenset[Comparison]:
    prs: set[PR] = set()
    for prs_in_release in prs_by_ubuntu_release.values():
        prs.update(prs_in_release)

    # For each PR we have a mapping from ubuntu release to a set of PRs that
    # forward-port the new slices to that release. An empty set means no
    # forward-port found, a set with None means no new slices to forward-port.
    comparisons: set[Comparison] = set()

    for ubuntu_release, prs_in_release in prs_by_ubuntu_release.items():
        future_releases = [r for r in prs_by_ubuntu_release if r > ubuntu_release]
        if not future_releases:
            continue

        for pr in prs_in_release:
            new_slices = new_slices_by_pr.get(pr, frozenset())
            for future_release in future_releases:
                prs_into_future_release = prs_by_ubuntu_release.get(
                    future_release, frozenset()
                )
                if not prs_into_future_release:
                    # No PRs into this future release
                    continue

                for pr_future in prs_into_future_release:
                    new_slices_in_future = new_slices_by_pr.get(pr_future, frozenset())

                    # figure out which slices have been discontinued in the future release
                    # so we don't consider them as missing
                    discontinued_slices = new_slices - packages_by_release.get(
                        future_release, frozenset()
                    )

                    comparisons.add(
                        Comparison(
                            pr=pr,
                            slices=new_slices,
                            pr_future=pr_future,
                            slices_future=new_slices_in_future,
                            discontinued_slices=discontinued_slices,
                        )
                    )
    return frozenset(comparisons)


def _get_grouped_comparisons(
    prs_by_ubuntu_release: Mapping[UbuntuRelease, frozenset[PR]],
    new_slices_by_pr: Mapping[PR, frozenset[str]],
    packages_by_release: Mapping[UbuntuRelease, set[str]],
) -> Mapping[PR, Mapping[UbuntuRelease, frozenset[Comparison]]]:
    comparisons = _get_comparisons(
        prs_by_ubuntu_release, new_slices_by_pr, packages_by_release
    )

    # For convenience we group the comparisons by the PR in the current release, and then by the future release.
    grouped_comparisons: dict[PR, dict[UbuntuRelease, set[Comparison]]] = {}
    for comparison in comparisons:
        pr = comparison.pr
        future_release = comparison.future_ubuntu_release
        if pr not in grouped_comparisons:
            grouped_comparisons[pr] = {}
        if future_release not in grouped_comparisons[pr]:
            grouped_comparisons[pr][future_release] = set()
        grouped_comparisons[pr][future_release].add(comparison)

    # We may not have all the PRs in the grouped_comparisons, since they may not have had any PRs to compare to.
    # We need to add them with empty dicts.
    for prs_in_release in prs_by_ubuntu_release.values():
        for pr in prs_in_release:
            if pr not in grouped_comparisons:
                grouped_comparisons[pr] = {}

    # For each of the dicts in grouped_comparisons, we want all of the future releases, even if there are no comparisons
    for pr, comparisons_by_future_release in grouped_comparisons.items():
        ubuntu_release = pr.ubuntu_release
        future_releases = [r for r in prs_by_ubuntu_release if r > ubuntu_release]
        for future_release in future_releases:
            if future_release not in comparisons_by_future_release:
                comparisons_by_future_release[future_release] = set()
    return {
        pr: {r: frozenset(comparison) for r, comparison in future_releases.items()}
        for pr, future_releases in grouped_comparisons.items()
    }


def _group_prs_by_ubuntu_release(
    prs: frozenset[PR], ubuntu_releases: list[UbuntuRelease]
) -> dict[UbuntuRelease, frozenset[PR]]:
    _prs_by_ubuntu_release: dict[UbuntuRelease, set[PR]] = {
        ubuntu_release: set() for ubuntu_release in ubuntu_releases
    }
    _prs = list(sorted(prs))  # we want list for logging
    for pr in _prs:
        if pr.ubuntu_release not in _prs_by_ubuntu_release:
            logging.warning(
                "PR #%d is into unsupported Ubuntu release %s. Skipping.",
                pr.number,
                pr.ubuntu_release,
            )
            continue
        _prs_by_ubuntu_release[pr.ubuntu_release].add(pr)
    prs_by_ubuntu_release: dict[UbuntuRelease, frozenset[PR]] = {
        k: frozenset(v) for k, v in _prs_by_ubuntu_release.items()
    }

    # Make sure we have all the ubuntu_releases as keys, even if they have no PRs
    for ubuntu_release in ubuntu_releases:
        if ubuntu_release not in prs_by_ubuntu_release:
            prs_by_ubuntu_release[ubuntu_release] = frozenset()

    return prs_by_ubuntu_release


def forward_porting_status(
    slices: frozenset[str],
    comparisons_by_future_release: Mapping[UbuntuRelease, Iterable[Comparison]],
) -> bool:
    """Each ubuntu release must have at least one comparison with no missing slices."""

    if not slices:
        return True

    for comparisons in comparisons_by_future_release.values():
        if not any(c.is_forward_ported() for c in comparisons):
            return False
    return True


## MAIN ########################################################################


def main(args: argparse.Namespace) -> None:
    data = load_data(args.input)

    # raise NotImplementedError
    ubuntu_releases = sorted(data.packages_by_release.keys())

    prs_by_ubuntu_release = _group_prs_by_ubuntu_release(data.prs, ubuntu_releases)
    new_slices_by_pr = _group_new_slices_by_pr(
        data.slices_in_head_by_pr, data.slices_in_base_by_pr
    )
    grouped_comparisons = _get_grouped_comparisons(
        prs_by_ubuntu_release, new_slices_by_pr, data.packages_by_release
    )

    print_pipe_friendly(
        format_forward_port_json(
            grouped_comparisons, new_slices_by_pr, add_extra_info=True
        )
    )


################################################################################


FORWARD_PORT_MISSING_LABEL = "forward port missing"


def format_forward_port_json(
    grouped_comparisons: Mapping[PR, Mapping[UbuntuRelease, frozenset[Comparison]]],
    new_slices_by_pr: Mapping[PR, frozenset[str]],
    add_extra_info: bool = False,
) -> str:
    output = []
    for pr, comparisons_by_future_release in sorted(grouped_comparisons.items()):
        output_pr: dict = {
            "number": pr.number,
            "title": pr.title,
            "url": f"https://github.com/{pr.head.repo_owner}/{pr.head.repo_name}/pull/{pr.number}",
            "base": pr.base.ref,
            "head": f"{pr.head.repo_owner}/{pr.head.repo_name}/{pr.head.ref}",
        }
        output_pr["forward_ported"] = forward_porting_status(
            new_slices_by_pr.get(pr, frozenset()),
            comparisons_by_future_release,
        )
        output_pr["label"] = FORWARD_PORT_MISSING_LABEL in pr.labels
        output_pr["forward_ports"] = {}
        if add_extra_info:
            output_pr["comparisons"] = {}
            output_pr["discontinued"] = {}
            for i, (future_release, comparisons) in enumerate(
                comparisons_by_future_release.items()
            ):
                if not comparisons:
                    output_pr["discontinued"]["ubuntu-" + future_release.version] = []
                    continue
                comparison = next(iter(comparisons))
                discontinued_slices = sorted(comparison.discontinued_slices)
                output_pr["discontinued"]["ubuntu-" + future_release.version] = (
                    discontinued_slices
                )
                if i == 0 and "slices" not in output_pr:
                    output_pr["slices"] = sorted(comparison.slices)

        for future_release, comparisons in comparisons_by_future_release.items():
            forward_ports = [c for c in comparisons if not c.missing_slices()]
            forward_port_numbers = sorted([c.pr_future.number for c in forward_ports])
            output_pr["forward_ports"]["ubuntu-" + future_release.version] = (
                forward_port_numbers
            )
            if add_extra_info:
                cmp = []
                for c in comparisons:
                    missing = c.missing_slices()
                    overlap = c.overlap()
                    if not missing and not overlap:
                        continue
                    if not c.is_forward_ported() and not overlap:
                        continue
                    element: dict = {"number": c.pr_future.number}
                    if overlap:
                        element["overlap"] = sorted(overlap)
                        if missing:
                            element["missing"] = sorted(missing)
                    cmp.append(element)
                cmp = sorted(cmp, key=lambda r: r["number"])
                output_pr["comparisons"]["ubuntu-" + future_release.version] = cmp

        output.append(output_pr)
    return json.dumps(output)


## BOILERPLATE #################################################################


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Check labels on PRs and forward-port if needed.",
    )
    parser.add_argument(
        "input",
        type=Path,
        help="Path to the input data file (brotli compressed sqlite db).",
    )
    return parser.parse_args()


## ENTRYPOINT ##################################################################

if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    args = parse_args()

    logging.debug("Parsed args: %s", args)

    main(args)
