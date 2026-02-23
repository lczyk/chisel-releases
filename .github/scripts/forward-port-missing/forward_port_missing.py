#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import logging
import os
import re
import subprocess as sub
import sys
import time
from collections.abc import Iterable, Mapping
from contextlib import contextmanager
from dataclasses import dataclass, field
from functools import total_ordering
from pathlib import Path
from typing import Callable, Iterator


################################################################################
@total_ordering
@dataclass(frozen=True, order=False)
class UbuntuRelease:
    version: str
    codename: str

    def __str__(self) -> str:
        return f"ubuntu-{self.version} ({self.codename})"

    @property
    def version_tuple(self) -> tuple[int, int]:
        year, month = self.version.split(".")
        return int(year), int(month)

    def __lt__(self, other: object) -> bool:
        if not isinstance(other, UbuntuRelease):
            return NotImplemented
        return self.version_tuple < other.version_tuple

    @classmethod
    def from_distro_info_line(cls, line: str) -> UbuntuRelease:
        match = re.match(r"Ubuntu (\d{1,2}\.\d{2})( LTS)? \"([A-Za-z ]+)\"", line)
        if not match:
            raise ValueError(f"Invalid distro-info line: '{line}'")
        return cls(version=match.group(1), codename=match.group(3))

    @classmethod
    def from_branch_name(cls, branch: str) -> UbuntuRelease:
        assert branch.startswith("ubuntu-"), "Branch name must start with 'ubuntu-'"
        version = branch.split("-", 1)[1]
        codename = _VERSION_TO_CODENAME.get(version)
        if codename is None:
            raise ValueError(f"Unknown Ubuntu version '{version}' for branch '{branch}'")
        return cls(version=version, codename=codename)

    @property
    def short_codename(self) -> str:
        """Return the first word of the codename in lowercase. E.g. 'focal' from 'Focal Fossa'."""
        return self.codename.split()[0].lower()

    @classmethod
    def from_dict(cls, data: dict) -> UbuntuRelease:
        return cls(
            version=data["version"],
            codename=data["codename"],
        )


_ALL_RELEASES: set[UbuntuRelease] = set()
_VERSION_TO_CODENAME: dict[str, str] = {}
SUPPORTED_RELEASES: set[UbuntuRelease] = set()
_DEVEL_RELEASE: UbuntuRelease | None = None


def init_distro_info() -> None:
    all_output = sub.getoutput("distro-info --all --fullname").strip()
    supported_output = sub.getoutput("distro-info --supported --fullname").strip()
    devel_output = sub.getoutput("distro-info --devel --fullname").strip()

    global _ALL_RELEASES, _VERSION_TO_CODENAME, SUPPORTED_RELEASES, _DEVEL_RELEASE

    _ALL_RELEASES = set(UbuntuRelease.from_distro_info_line(line) for line in all_output.splitlines())
    _VERSION_TO_CODENAME = {release.version: release.codename for release in _ALL_RELEASES}

    SUPPORTED_RELEASES = set(UbuntuRelease.from_distro_info_line(line) for line in supported_output.splitlines())
    assert SUPPORTED_RELEASES.issubset(_ALL_RELEASES), "Supported releases must be a subset of all releases."

    _DEVEL_RELEASE = UbuntuRelease.from_distro_info_line(devel_output) if devel_output else None
    assert _DEVEL_RELEASE is None or _DEVEL_RELEASE in _ALL_RELEASES, "Devel release must be in all releases."


################################################################################

CHISEL_RELEASES_URL = os.environ.get("CHISEL_RELEASES_URL", "https://github.com/canonical/chisel-releases")


@contextmanager
def timing_context() -> Iterator[Callable[[], float]]:
    t1 = t2 = time.perf_counter()
    yield lambda: t2 - t1
    t2 = time.perf_counter()


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


@dataclass(frozen=True)
class Commit:
    ref: str
    repo_name: str
    repo_owner: str
    repo_url: str
    sha: str

    @classmethod
    def from_github_json(cls, data: dict) -> Commit:
        return Commit(
            ref=data["ref"],
            repo_name=data["repo"]["name"],
            repo_owner=data["repo"]["owner"]["login"],
            repo_url=data["repo"]["html_url"],
            sha=data["sha"],
        )

    @classmethod
    def from_dict(cls, data: dict) -> Commit:
        return Commit(
            ref=data["ref"],
            repo_name=data["repo_name"],
            repo_owner=data["repo_owner"],
            repo_url=data["repo_url"],
            sha=data["sha"],
        )


FORWARD_PORT_MISSING_LABEL = "forward port missing"


@total_ordering
@dataclass(frozen=True, order=False)
class PR:
    number: int
    title: str
    user: str
    head: Commit
    base: Commit
    label: bool
    url: str

    @property
    def ubuntu_release(self) -> UbuntuRelease:
        return UbuntuRelease.from_branch_name(self.base.ref)

    def __lt__(self, other: object) -> bool:
        if not isinstance(other, PR):
            return NotImplemented
        return self.number < other.number

    @classmethod
    def from_github_json(cls, data: dict) -> PR:
        has_label = any(label.get("name") == FORWARD_PORT_MISSING_LABEL for label in data["labels"])
        return PR(
            number=data["number"],
            title=data["title"],
            user=data["user"]["login"],
            head=Commit.from_github_json(data["head"]),
            base=Commit.from_github_json(data["base"]),
            label=has_label,
            url=data["html_url"],
        )

    @classmethod
    def from_dict(cls, data: dict) -> PR:
        return PR(
            number=data["number"],
            title=data["title"],
            user=data["user"],
            head=Commit.from_dict(data["head"]),
            base=Commit.from_dict(data["base"]),
            label=data["label"],
            url=data["url"],
        )


def check_github_token() -> None:
    token = os.getenv("GH_TOKEN", None)
    if token is not None:
        logging.debug("GH_TOKEN is set.")
        if not token.strip():
            logging.warning("GH_TOKEN is empty.")
    else:
        logging.debug("GH_TOKEN is not set.")


################################################################################


def _group_new_slices_by_pr(
    slices_in_head_by_pr: Mapping[PR, frozenset[str]],
    slices_in_base_by_pr: Mapping[PR, frozenset[str]],
) -> dict[PR, frozenset[str]]:
    prs: set[PR] = set(slices_in_head_by_pr.keys())
    if set(slices_in_base_by_pr.keys()) != prs:
        raise ValueError("slices_in_head_by_pr and slices_in_base_by_pr must have the same keys.")
    new_slices_by_pr: dict[PR, frozenset[str]] = {}
    for pr in sorted(prs):
        slices_in_head = slices_in_head_by_pr.get(pr, frozenset())
        slices_in_base = slices_in_base_by_pr.get(pr, frozenset())
        new_slices = slices_in_head - slices_in_base
        removed_slices = slices_in_base - slices_in_head
        if removed_slices and logging.getLogger().isEnabledFor(logging.WARNING):
            slices_string = ", ".join(sorted(removed_slices))
            slices_string = slices_string if len(slices_string) < 100 else slices_string[:97] + "..."
            logging.warning("PR #%d removed %d slices: %s", pr.number, len(removed_slices), slices_string)
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
                prs_into_future_release = prs_by_ubuntu_release.get(future_release, frozenset())
                if not prs_into_future_release:
                    # No PRs into this future release
                    continue

                for pr_future in prs_into_future_release:
                    new_slices_in_future = new_slices_by_pr.get(pr_future, frozenset())

                    # figure out which slices have been discontinued in the future release
                    # so we don't consider them as missing
                    discontinued_slices = new_slices - packages_by_release.get(future_release, frozenset())

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
    comparisons = _get_comparisons(prs_by_ubuntu_release, new_slices_by_pr, packages_by_release)

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
    _prs_by_ubuntu_release: dict[UbuntuRelease, set[PR]] = {ubuntu_release: set() for ubuntu_release in ubuntu_releases}
    _prs = list(sorted(prs))  # we want list for logging
    for pr in _prs:
        if pr.ubuntu_release not in _prs_by_ubuntu_release:
            logging.warning("PR #%d is into unsupported Ubuntu release %s. Skipping.", pr.number, pr.ubuntu_release)
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


################################################################################


def load_data_from_json(
    input_path: Path,
) -> tuple[
    frozenset[PR],
    Mapping[PR, frozenset[str]],
    Mapping[PR, frozenset[str]],
    Mapping[UbuntuRelease, set[str]],
]:
    """Load PR and package data from JSON file."""
    if not input_path.is_file():
        raise FileNotFoundError(f"Input file '{input_path}' does not exist or is not a file.")

    logging.info("Loading data from '%s'...", input_path)

    with input_path.open("r") as f:
        data = json.load(f)

    assert isinstance(data, dict), "Expected loaded data to be a dict."
    expected_keys = {"ubuntu_releases", "prs", "packages_by_release"}
    if set(data.keys()) != expected_keys:
        raise ValueError(f"Loaded data keys do not match expected keys: {expected_keys}")

    # Reconstruct PRs
    prs_list = []
    slices_in_head_by_pr_dict = {}
    slices_in_base_by_pr_dict = {}

    for pr_data in data["prs"]:
        pr = PR.from_dict(pr_data)
        prs_list.append(pr)
        slices_in_head_by_pr_dict[pr] = frozenset(pr_data["slices"]["head"])
        slices_in_base_by_pr_dict[pr] = frozenset(pr_data["slices"]["base"])

    # Reconstruct packages by release
    packages_by_release = {}
    for release_key, packages in data["packages_by_release"].items():
        # release_key is like "ubuntu-24.04"
        version = release_key.removeprefix("ubuntu-")
        # Find matching release from ubuntu_releases
        matching_release = next((r for r in data["ubuntu_releases"] if r["version"] == version), None)
        if matching_release:
            ubuntu_release = UbuntuRelease.from_dict(matching_release)
            packages_by_release[ubuntu_release] = set(packages)

    logging.info("Loaded data from '%s'.", input_path)
    file_size = input_path.stat().st_size
    logging.info("Input file size: %.2f MiB", file_size / (1024 * 1024))

    return frozenset(prs_list), slices_in_head_by_pr_dict, slices_in_base_by_pr_dict, packages_by_release


## MAIN ########################################################################


def main(args: argparse.Namespace) -> None:
    (
        prs,
        slices_in_head_by_pr,
        slices_in_base_by_pr,
        packages_by_release,
    ) = load_data_from_json(args.input)
    ubuntu_releases = sorted(packages_by_release.keys())

    prs_by_ubuntu_release = _group_prs_by_ubuntu_release(prs, ubuntu_releases)
    new_slices_by_pr = _group_new_slices_by_pr(slices_in_head_by_pr, slices_in_base_by_pr)
    grouped_comparisons = _get_grouped_comparisons(prs_by_ubuntu_release, new_slices_by_pr, packages_by_release)

    print_pipe_friendly(format_forward_port_json(grouped_comparisons, new_slices_by_pr, add_extra_info=False))


################################################################################


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
            "url": pr.url,
            "base": pr.base.ref,
            "head": f"{pr.head.repo_owner}/{pr.head.repo_name}/{pr.head.ref}",
        }
        output_pr["forward_ported"] = forward_porting_status(
            new_slices_by_pr.get(pr, frozenset()),
            comparisons_by_future_release,
        )
        output_pr["label"] = pr.label
        output_pr["forward_ports"] = {}
        if add_extra_info:
            output_pr["comparisons"] = {}
            output_pr["discontinued"] = {}
            for i, (future_release, comparisons) in enumerate(comparisons_by_future_release.items()):
                if not comparisons:
                    output_pr["discontinued"]["ubuntu-" + future_release.version] = []
                    continue
                comparison = next(iter(comparisons))
                discontinued_slices = sorted(comparison.discontinued_slices)
                output_pr["discontinued"]["ubuntu-" + future_release.version] = discontinued_slices
                if i == 0 and "slices" not in output_pr:
                    output_pr["slices"] = sorted(comparison.slices)

        for future_release, comparisons in comparisons_by_future_release.items():
            forward_ports = [c for c in comparisons if not c.missing_slices()]
            forward_port_numbers = sorted([c.pr_future.number for c in forward_ports])
            output_pr["forward_ports"]["ubuntu-" + future_release.version] = forward_port_numbers
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
    parser.add_argument("input", type=Path, help="Path to the input data file (brotli compressed sqlite db).")
    return parser.parse_args()


## ENTRYPOINT ##################################################################

if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    init_distro_info()
    check_github_token()

    args = parse_args()
    logging.debug("Parsed args: %s", args)

    main(args)
