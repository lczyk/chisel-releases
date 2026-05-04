# `.github/scripts/` refactor notes

scratch notes from a survey of the ci scripts. trigger was [issue #1000](https://github.com/canonical/chisel-releases/issues/1000) (`removed-slices` flagging deletions for packages no longer in the release), but the scope grew to the whole `scripts/` tree once the overlap became obvious.

## issue #1000 in one line

`removed-slices` treats any `DR` filter hit on `slices/*.yaml` as a hard failure. when a release bumps a versioned package (e.g. `librocksdb9.11` -> `librocksdb10`) and the old apt package is gone from the archive, the slice file deletion is the right thing -- but ci fails it.

example run: <https://github.com/canonical/chisel-releases/actions/runs/24840089749/job/72711239563?pr=999>

fix shape: gate the failure on "is this package still in the archive for this release?". if absent, allow the deletion.

## the shape of the fix already exists in the repo

[forward_port_missing.py](.github/scripts/forward-port-missing/forward_port_missing.py) does this exact archive-existence check today. comment line 11: _"Any slices for any discontinued packages are ignored."_ same semantics we want for `removed-slices`.

reusable bits already there:

- [`fetch_packages_in_release()`](.github/scripts/forward-port-missing/forward_port_missing.py#L177-L227) -- pulls `Packages.gz` from `archive.ubuntu.com/ubuntu/dists/<codename>{,-security,-updates,-backports}/<component>/binary-amd64/`, unions `main+restricted+universe+multiverse`, regex `^Package:`. no binary deps.
- [chisel.yaml codename parsing](.github/scripts/forward-port-missing/forward_port_missing.py#L277-L292) -- branch-agnostic (`archives.ubuntu.suites` first token).
- [missing-slices ∩ packages-in-release](.github/scripts/forward-port-missing/forward_port_missing.py#L328-L331) -- the precedent for the gate.

so the fix isn't "invent new logic"; it's "factor the existing helper out and call it from a second site".

## survey of overlap across scripts

| concern | sites |
|---|---|
| archive package-existence query | [forward_port_missing.py:177](.github/scripts/forward-port-missing/forward_port_missing.py#L177) (http scrape, no deps); [install_slices.py:215](.github/scripts/install-slices/install_slices.py#L215) (`rmadison`, devscripts dep) |
| chisel.yaml parsing | [install_slices.py:138](.github/scripts/install-slices/install_slices.py#L138) (`Archive(version, components, suites)`); [forward_port_missing.py:268-292](.github/scripts/forward-port-missing/forward_port_missing.py#L268-L292) (codename + `maintenance.end-of-life`, inline) |
| slice file parsing (`.package`, `.slices`) | [install_slices.py:193](.github/scripts/install-slices/install_slices.py#L193) (python yaml); [removed-slices:60-63](.github/scripts/removed-slices/removed-slices#L60-L63) (bash + yq); [pkg-deps:31,43](.github/scripts/pkg-deps/pkg-deps#L31) (bash + yq); [coverage-report:68](.github/scripts/test-coverage/coverage-report#L68) (`yq ea`) |
| `<pkg>_<slice>` naming | [install_slices.py:186 `full_slice_name`](.github/scripts/install-slices/install_slices.py#L186); [removed-slices:62 sed](.github/scripts/removed-slices/removed-slices#L62); [coverage-report:68 yq fmt](.github/scripts/test-coverage/coverage-report#L68) |
| supported-branches discovery (`ubuntu-XX.XX` + eol filter) | [forward_port_missing.py:230](.github/scripts/forward-port-missing/forward_port_missing.py#L230) only -- premature to extract |
| github api (auth, pagination) | [forward_port_missing.py:85](.github/scripts/forward-port-missing/forward_port_missing.py#L85) only -- premature |

`pkg-deps` and `coverage-report` add their own per-script concerns on top: docker + `apt depends` for the former, `zstdcat`/jsonl manifest reading for the latter. those stay local.

## proposed layout

```
.github/scripts/common/
    __init__.py
    archive.py          # packages_in(archive) -> set[str], http scrape
    chisel_yaml.py      # ChiselRelease(version, codename, components, suites, end_of_life)
    slice_file.py       # parse(path), parse_combined(path), full_name(pkg, slc)
    test_archive.py
    test_chisel_yaml.py
    test_slice_file.py
```

import shape: scripts do `from common.archive import packages_in`. needs `PYTHONPATH=.github/scripts` in workflow env -- one-line addition per workflow yaml. avoid `sys.path` hacks at the top of scripts.

ci: add a `pytest .github/scripts/common/` job in [test-ci.yaml](.github/workflows/test-ci.yaml) alongside the existing `validate-hints` and `forward-port-missing` jobs.

naming bikeshed: `common/`, `lib/`, `_shared/`, `chisel_ci/`. `common/` reads fine and matches usual python conventions. mild risk if ever vendored as an installed package (name clash) -- n/a, scripts run in-place.

## tool-elimination side-effects after full migration

- `yq` -- gone (all callers ported to python yaml)
- `rmadison` / `devscripts` -- gone (http scrape replaces shell-out)
- `jq` -- gone iff `coverage-to-md` ported
- `bc` -- gone iff `coverage-to-md` ported
- `zstd` -- still needed in test-coverage env
- docker -- still needed for `pkg-deps`

## punch list

ordering: common modules first (foundational), then per-script ports. each script port lands as its own commit / small pr, conventional commit prefixes per repo style.

- [ ] `common/chisel_yaml.py` + tests
- [ ] `common/archive.py` (http scrape) + tests
- [ ] `common/slice_file.py` (`parse`, `parse_combined`, `full_name`) + tests
- [ ] `common/__init__.py`
- [ ] `pytest .github/scripts/common/` ci job in test-ci.yaml
- [ ] `PYTHONPATH=.github/scripts` env in every workflow that runs a python script
- [ ] port `removed-slices` bash -> python on top of common, archive-existence gate -- closes #1000
- [ ] port `pkg-deps` bash -> python (yaml via common, docker via `subprocess`)
- [ ] port `coverage-report` bash -> python (manifest reader stays local)
- [ ] port `coverage-to-md` bash -> python (consistency; otherwise leave bash)
- [ ] migrate `install_slices.py` to common, drop `rmadison` shell-out
- [ ] migrate `forward_port_missing.py` to common
- [ ] update workflow yamls: drop `apt install yq jq bc devscripts` lines accordingly
- [ ] verify `.gitignore` covers `__pycache__/` and `.pytest_cache/` (add iff missing)

## open questions

- ? mega-pr vs staged. staged is friendlier to review but #1000 fix wants common modules in place first -- so at minimum two prs (common foundation + removed-slices port). everything else can trickle.
- ? port `coverage-to-md` or leave bash. small isolated formatter; only argument for porting is uniformity.
- ? extract supported-branches discovery now or wait for a 2nd caller. waiting is cheaper.
- ? archive scrape is slow-ish; cache `Packages.gz` per ci run, or only fetch components for the current branch (forward-port-missing fetches all live releases; removed-slices only needs the current one).
