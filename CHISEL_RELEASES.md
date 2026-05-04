# `chisel-releases` -- agent orientation

self-contained briefing for an agent dropped into this repo. covers what chisel is, what this repo is, how it's organised, the rules a contribution must follow, and the conventions that ci enforces. portable -- copy this file into another context to bring an agent up to speed in one read.

## what chisel is

[chisel](https://github.com/canonical/chisel) is a tool that builds minimal ubuntu rootfs images by extracting only specific _slices_ of debian packages, instead of installing whole packages. slices are named subsets of a package's files, with their own dependency graph. typical use: building tiny container images that contain only what an application actually needs at runtime.

key facts about chisel itself (the tool) -- relevant context, not edited from this repo:

- written in go.
- consumes a _chisel release_ (this repo) as its source of truth for what slices exist and what they contain.
- cli has commands like `chisel cut --release <ref> --root <dir> <pkg>_<slice> ...` to materialise a sliced rootfs.
- docs: <https://documentation.ubuntu.com/chisel/en/latest/>.
- source: <https://github.com/canonical/chisel>.

## what `chisel-releases` is

this repo is the official store of slice definitions consumed by chisel. each ubuntu release is a separate git _branch_, not a directory:

- `ubuntu-20.04` (focal, eol)
- `ubuntu-22.04` (jammy)
- `ubuntu-22.10`, `ubuntu-23.04`, `ubuntu-23.10` (eol)
- `ubuntu-24.04` (noble) -- the lts most active right now
- `ubuntu-24.10` (oracular, eol)
- `ubuntu-25.04` (plucky, eol)
- `ubuntu-25.10` (questing)
- `ubuntu-26.04` (resolute) -- next lts in development

`main` is meta-only: ci scripts, contributing docs, workflow definitions. **`main` does not contain `slices/` or `chisel.yaml`**. all slice work happens on `ubuntu-XX.XX` branches.

### slice counts per release (rough size signal)

snapshot of `slices/*.yaml` count on `canonical/ubuntu-XX.XX`:

| release | slice files |
|---|---|
| ubuntu-20.04 | 98 |
| ubuntu-22.04 | 207 |
| ubuntu-24.04 | 603 |
| ubuntu-25.10 | 635 |
| ubuntu-26.04 | 651 |

each successor lts roughly triples-then-grows; the active surface for new contributions is `ubuntu-24.04` and newer.

## per-release branch layout

on every `ubuntu-XX.XX` branch:

```
chisel.yaml                  # release manifest: archives, suites, components, eol, signing keys
slices/                      # one yaml per package -- the slice definition files (sdfs)
    apparmor.yaml
    base-files.yaml
    bash.yaml
    ...                      # ~600+ files on ubuntu-24.04
spread.yaml                  # spread test runner config (lxd backend)
tests/spread/integration/    # one dir per package with `task.yaml` + `smoke.sh` style tests
tests/spread/lib/            # shared helpers (e.g. `install-slices` wrapper)
.github/                     # workflows + scripts (synced from main)
README.md, CONTRIBUTING.md
```

`main` only carries `.github/`, `README.md`, `CONTRIBUTING.md`. when working in this repo, **always check which branch you're on first** -- a checkout of `main` will have no slices.

## `chisel.yaml` -- release manifest

### schema format versions

- **v1** -- legacy. branches: `ubuntu-20.04`, `ubuntu-22.04`, `ubuntu-24.04`. uses `archives:` for the default ubuntu archive and a separate `v2-archives:` block for ubuntu pro / esm archives.
- **v2** -- requires chisel >= `v1.2.0`. branches: `ubuntu-25.10`. unifies pro archives under a single `archives:` block via a `pro:` subkey. `maintenance.standard` + `maintenance.end-of-life` required.
- **v3** -- requires chisel >= `v1.4.0`. branches: `ubuntu-26.04`. adds slice `hint:` field (see sdf section).

an agent reading a release manifest should branch on the `format:` line first.

### top-level keys

- `format` -- string, one of `v1` / `v2` / `v3`.
- `archives` -- map of archive name -> archive config. required.
- `v2-archives` -- v1-only: map for pro/esm archives.
- `public-keys` -- map of key id -> ascii-armored gpg block. required (referenced from each archive's `public-keys:`).
- `maintenance` -- map of stage dates. `standard` + `end-of-life` required (v2+); `expanded` + `legacy` optional, lts-only.

### archive entry subkeys

- `version` -- ubuntu version, mirrors the branch suffix (e.g. `24.04`).
- `components` -- list of apt components (`main`, `restricted`, `universe`, `multiverse`).
- `suites` -- list of apt suites (`<codename>`, `<codename>-security`, `<codename>-updates`, `<codename>-backports`).
- `public-keys` -- list of key ids referenced from the top-level `public-keys:` map.
- `priority` -- int in `[-1000, 1000]` for multi-archive precedence. higher wins. v3 may omit it on the default archive.
- `pro` -- one of `fips`, `fips-updates`, `esm-apps`, `esm-infra`. presence triggers ubuntu pro auth at runtime.

### example (v1, ubuntu-24.04)

```yaml
format: v1

maintenance:
  standard: 2024-04-25
  expanded: 2029-05-31
  legacy: 2034-04-25
  end-of-life: 2036-04-29

archives:
  ubuntu:
    priority: 10
    version: 24.04
    components: [main, universe]
    suites: [noble, noble-security, noble-updates]
    public-keys: [ubuntu-archive-key-2018]

v2-archives:
  ubuntu-esm-apps:
    pro: esm-apps
    priority: 16
    ...
  ubuntu-esm-infra:
    pro: esm-infra
    priority: 15
    ...

public-keys:
  ubuntu-archive-key-2018:
    id: "871920D1991BC93C"
    armor: |
      -----BEGIN PGP PUBLIC KEY BLOCK-----
      ...
```

key fields agents will hit:

- `archives.ubuntu.suites[0]` -- short codename (e.g. `noble`). first token before `-` is the codename used to query `archive.ubuntu.com`.
- `archives.ubuntu.components` -- which apt components are in scope.
- `archives.ubuntu.version` -- ubuntu version, mirrors the branch suffix.
- `maintenance.end-of-life` -- date; ci uses this to decide if a branch is still "live" (compared to `today`).

## slice definition files (sdfs)

one `slices/<pkg>.yaml` per debian source package.

### sdf top-level keys

- `package` -- required, string. debian package name; **must match the filename stem** (`slices/foo.yaml` -> `package: foo`).
- `archive` -- optional, string. selects which archive (from `chisel.yaml`'s `archives:`) to fetch the package from. omit to use the default.
- `essential` -- optional, list of `<pkg>_<slice>` ids applied to **every** slice in this file. typically holds the `<pkg>_copyright` slice so every slice ships its copyright file.
- `slices` -- required, map of slice name -> slice body.

### per-slice keys

under `slices.<name>`:

- `essential` -- optional, list of `<pkg>_<slice>` ids this slice depends on (cross-package allowed).
- `contents` -- optional, map of path -> entry options. paths must be lexicographically sorted.
- `mutate` -- optional, string. starlark script run after every slice's files are installed.
- `hint` -- optional, string, **v3+ only**. user-facing one-liner, max 40 chars. validated by `validate-hints` ci.

### content path entry options

within `slices.<name>.contents.<path>`:

| key | type | meaning |
|---|---|---|
| (bare path) | -- | copy from deb at this path |
| `copy` | string | copy from a different source path inside the deb |
| `make` | bool | create empty dir; requires trailing `/` on the path |
| `mode` | int (octal) | permission bits, e.g. `0755` |
| `text` | string | inline literal file contents (generated, not from deb) |
| `symlink` | string | create symlink to this target |
| `arch` | string or list | restrict to debian arches (`amd64`, `arm64`, `armhf`, `i386`, `ppc64el`, `riscv64`, `s390x`) |
| `mutable` | bool | path may be modified by `mutate:` scripts |
| `until` | `"mutate"` | path exists during install; chisel removes it after the mutate phase |
| `generate` | `"manifest"` | chisel writes a manifest at this path (use with glob, see manifest section) |
| `prefer` | string, **v2+** | resolve cross-package path conflicts; names the package whose version wins |

### `mutate:` script semantics

- language: starlark (google's tightly-scoped python dialect; not full python).
- runs after the files of every slice in the install set have been installed.
- available helpers:
  - `content.list(d)` -- list directory entries.
  - `content.read(f)` -- read text file.
  - `content.write(f, s)` -- write text file.
- typical use: merge `passwd`/`group` files (`base-passwd`), filter ca certificates (`ca-certificates`), splice apt sources, etc.
- `until: mutate` is the partner mechanism: a file marked `until: mutate` is available for the script to read, then chisel deletes it from the rootfs once mutation finishes -- so build-time inputs do not pollute the final image.

### canonical example

```yaml
package: base-files                 # debian source package name; must match filename stem

# essentials applied to *every* slice in this file:
essential:
  - base-files_copyright

slices:
  base:                             # slice name -- referenced as `base-files_base`
    essential:                      # other slices this one depends on (cross-package ok)
      - base-files_bin
      - base-files_etc

  bin:
    contents:                       # paths extracted from the deb
      /bin:
      /sbin:
      /usr/bin/:                    # trailing slash -> directory
      /usr/sbin/:

  lib:
    contents:
      /lib:
      /lib64: {arch: [amd64, ppc64el]}    # arch-specific entries
      /usr/lib/:

  var:
    contents:
      /var/run/: {symlink: /run}    # explicit symlink target

  copyright:
    contents:
      /usr/share/doc/base-files/copyright:
```

### addressing & conventions

- **`<pkg>_<slice>` is the canonical full identifier** -- e.g. `bash_bins`, `libc6_libs`. used in `essential:` cross-references and as cli args to `chisel cut`.
- **`copyright` slice convention** -- nearly every package has one; pulls `/usr/share/doc/<pkg>/copyright`. listed in the file-level `essential:` block so every other slice transitively ships it. **every slice that delivers functionality must ship copyright** -- not optional.
- **filename rule** -- `slices/<pkg>.yaml` with `<pkg>` exactly matching the `package:` field. ci enforces this implicitly via several scripts.
- **path sort rule** -- entries inside `contents:` must be lexicographically sorted; reviewers will reject unsorted blocks.
- **slice design approaches** -- two valid styles per chisel docs: group by content type (`bins`, `config`, `libs`) or group by functional use case. pick one per package; don't mix arbitrarily.

## chisel cli (consumer side)

agents may need to invoke the cli when testing slices. subcommands:

- `chisel cut --release <ref> --root <dir> [--arch <a>] <pkg>_<slice> ...` -- materialise a sliced rootfs.
- `chisel find <pattern>` -- search slices across the release.
- `chisel info <pkg>_<slice>` -- inspect a single slice.
- `chisel version` -- print version.
- `chisel help [cmd]` -- usage.

`--release` resolution:

- omitted -> falls back to host's `/etc/os-release`.
- `ubuntu-XX.XX` -> resolves to the matching git branch in this repo (online fetch).
- absolute path -> treats it as a local chisel-release directory tree.

`--ignore` flag accepts e.g. `unstable`, `unmaintained` -- needed when a release branch is past eol but you want to operate on it anyway.

## manifest

chisel can emit a build manifest into the rootfs:

- format: `jsonwall` -- newline-delimited json, zstd-compressed; one header object plus typed entries (packages, slices, paths, content mappings).
- emitted by paths declared with `generate: manifest` in some slice's contents. by convention this is the `base-files_chisel` slice writing to `/var/lib/chisel/manifest.wall`.
- example from `slices/base-files.yaml`: `/var/lib/chisel/**: {generate: manifest}`.
- consumed by sbom generators, vulnerability scanners, the in-repo `coverage-report` ci script (which reads installed manifests via `zstdcat`), and the in-repo `forward-port-missing` ci script (no -- that one uses github api, not manifests; the manifest only flows through `coverage-report`).

## ubuntu pro archives

four valid `pro:` values for archive entries: `fips`, `fips-updates`, `esm-apps`, `esm-infra`. consumer-side requirements:

- active ubuntu pro subscription.
- pro client installed and the relevant service enabled (`sudo pro enable esm-infra` etc.).
- chisel reads credentials from `/etc/apt/auth.conf.d/`; non-root invocations need read access (`setfacl -m u:$USER:r /etc/apt/auth.conf.d/90ubuntu-advantage`).

most lts release branches (20.04, 22.04, 24.04) ship `v2-archives:` blocks for `ubuntu-esm-apps` + `ubuntu-esm-infra`. `ubuntu-26.04` does not yet (todo in the manifest).

## the cardinal contribution rules

these are non-negotiable; ci and reviewers enforce them.

1. **branch off the target release branch, not `main`.** prs into `main` are wrong. target `ubuntu-XX.XX`. mentioned explicitly in `CONTRIBUTING.md`.
2. **forward-port to every newer live release.** if you change `ubuntu-22.04`, you must also open a pr (or pr chain) into `ubuntu-24.04`, `ubuntu-25.10`, `ubuntu-26.04` -- every live (non-eol) release newer than the target. ci has `forward-port-missing` workflow that auto-labels prs missing this. exception: the slice's package no longer exists in the newer release's archive (then the missing port is intentional and is auto-ignored).
3. **conventional commits.** prefixes: `feat:`, `fix:`, `test:`, `ci:`, `chore:`, `docs:`, `refactor:`. scope optional in parens. examples in `CONTRIBUTING.md`. subject lowercase, no trailing period, imperative mood, <=50 chars; body wrapped at 72.
4. **two maintainer approvals required to merge.** dont expect a single approval to be enough.
5. **green ci required.** maintainers wont review until checks are green.
6. **be holistic, not piecemeal.** one pr should be one cohesive contribution. multiple uncorrelated slice changes -> separate prs.
7. **do not force-push after receiving review comments.** merge in target branch updates if needed.
8. **cla required.** sign canonical contributor licence agreement before opening a pr.

## ci workflows (lives under `.github/workflows/`)

short summary -- enough for an agent to know what each fails for and where to look:

| workflow | purpose | failure means |
|---|---|---|
| `lint.yaml` | yamllint on slice files across listed releases | yaml syntax / formatting issue in an sdf |
| `install-slices.yaml` | actually `chisel cut` the changed slices and verify packages exist in the archive | slice cant be cut, or package not in archive for some arch |
| `removed-slices.yaml` | flag deletions/renames of `slices/*.yaml` between base and head | sdf removed -- treated as breaking unless underlying package is gone (see #1000) |
| `forward-port-missing.yaml` | label prs whose new slices are missing from newer live releases | a new slice exists in your branch but not in newer ones, and no pr proposes it |
| `pkg-deps.yaml` | diff slice's declared deps vs `apt depends` for the upstream package, comment summary on pr | informational; non-blocking comment |
| `validate-hints.yaml` | nlp check on hint text inside slice files | hint phrasing fails style check |
| `check-releases-archives.yaml` | scheduled archive health check across release branches | upstream archive change broke a release |
| `spread.yaml` | run integration tests under `tests/spread/integration/` | a slice's smoke test failed inside an lxd container |
| `test-ci.yaml` | run pytest on the repo's own ci scripts | bug in `forward-port-missing` / `validate-hints` python |
| `cla-check.yaml` | enforce cla signing | submitter hasnt signed cla |
| `pr-comments.yaml` | post pr comments based on uploaded artifacts (e.g. coverage, pkg-deps) | n/a -- it's just the messenger |
| `triage-prs.yaml` | scheduled label/triage automation | n/a |

scripts feeding these workflows live in `.github/scripts/`:

- `forward-port-missing/forward_port_missing.py` -- python; queries github api for prs, fetches `Packages.gz` from `archive.ubuntu.com`, decides which prs need the `forward port missing` label.
- `removed-slices/removed-slices` -- bash + yq; flags slice file deletions.
- `install-slices/install_slices.py` -- python; orchestrates `chisel cut` runs; uses `rmadison` to check archive existence.
- `pkg-deps/pkg-deps` -- bash + docker; diffs declared deps vs `apt depends`.
- `validate-hints/validate_hints.py` -- python + spacy.
- `test-coverage/coverage-report` + `coverage-to-md` -- bash + jq.

note: there is an open refactor track to unify these scripts (see `.github/scripts/REFACTOR.md` if present).

## archive lookup conventions

agents debugging "does package X exist in release Y?" should know:

- **http scrape (no deps)**: `https://archive.ubuntu.com/ubuntu/dists/<codename>{,-security,-updates,-backports}/<component>/binary-amd64/Packages.gz`. components are `main`, `restricted`, `universe`, `multiverse`. union them all to get the full set of packages in a release. regex `^Package:\s*(\S+)` extracts names.
- **`rmadison <pkg>`** (devscripts) -- queries launchpad. lower volume, per-pkg.
- which to use is convention drift; the http scrape is the more portable choice and what fp-missing uses.

## testing model

local testing of a slice change:

1. checkout the release branch.
2. install `chisel` cli (binary or `go install github.com/canonical/chisel/cmd/chisel@latest`).
3. `chisel cut --release . --root /tmp/test-rootfs <pkg>_<slice>` -- materialises into `/tmp/test-rootfs`.
4. exercise the binary: `chroot /tmp/test-rootfs <cmd> --version` etc.

repo-level integration tests live in `tests/spread/integration/<pkg>/`. each has:

- `task.yaml` -- spread task definition (`summary`, `prepare`, `execute`).
- `smoke.sh` -- the actual test commands.

these run under spread with an lxd backend (see `spread.yaml`). spawned with ephemeral `ubuntu:<release>` containers. **agents should not run spread locally without lxd configured** -- it allocates cloud-style resources via lxc.

## assumptions / gotchas an agent should internalise

- **never commit on `main`.** slice work is on release branches. `main` only takes ci/docs commits.
- **branch suffix matches `chisel.yaml` `archives.ubuntu.version`** -- e.g. `ubuntu-24.04` <-> `version: 24.04`. don't rename one without the other.
- **eol releases are read-only.** check `maintenance.end-of-life` in `chisel.yaml` against today. if past, the branch is frozen; don't propose changes there.
- **forward-port is not optional**, but is automatic-ignored when a package version is gone from the newer release archive (e.g. `librocksdb9.11.yaml` deleted because the newer release ships `librocksdb10` instead -- old pkg simply not in archive). this is the issue at the heart of [#1000](https://github.com/canonical/chisel-releases/issues/1000).
- **slice file == package mapping is 1:1.** one sdf per source package. don't put two packages in one yaml.
- **`<pkg>_<slice>` is the addressing primitive** for cross-slice references. when reading or writing `essential:` lists, that's the format.
- **architecture gating uses debian arches**: `amd64`, `arm64`, `armhf`, `i386`, `ppc64el`, `riscv64`, `s390x`. not `x86_64`/`aarch64` (those are kernel/golang arch names).
- **`copyright` slice is conventional** -- almost every package has one. listed in file-level `essential:` so every slice transitively pulls it. when adding a new sdf, include a `copyright:` slice unless you have a reason not to.
- **chisel cli mapping**: `chisel <cmd> --release ubuntu-XX.XX` resolves to the matching git branch in this repo (online), or `--release <path>` resolves to a local checkout, or no flag falls back to host's `/etc/os-release`.
- **`format:` field gates schema**: v1 / v2 / v3 differ -- `hint:` is v3-only, `prefer:` is v2+, `pro:` lives directly under `archives:` in v2+ but under `v2-archives:` in v1. always check `format:` in `chisel.yaml` before assuming a feature is available.
- **starlark, not python**: mutate scripts use starlark. no imports, no exceptions, restricted stdlib. only `content.list/read/write` for fs interaction.
- **path sort matters**: lexicographic order in `contents:` blocks is enforced socially by reviewers. resort before pushing.
- **`copyright` is mandatory for functional slices**: every functional slice must carry copyright (typically via the file-level `essential:` -> `<pkg>_copyright`).
- **forward-port chain order**: oldest -> newest. e.g. land in `ubuntu-24.04`, then port to `25.10`, then `26.04`. cross-link the prs in descriptions.

## quick repro commands

investigate from a fresh checkout:

```bash
# see live releases
git branch -r | grep ubuntu-

# inspect a release manifest
git show ubuntu-24.04:chisel.yaml | head -30

# list slices in a release
git ls-tree --name-only ubuntu-24.04 slices/ | head

# see the schema by example
git show ubuntu-24.04:slices/bash.yaml

# diff a single slice between two releases
git diff ubuntu-22.04:slices/coreutils.yaml ubuntu-24.04:slices/coreutils.yaml
```

write a contribution:

```bash
# branch off the target release
git fetch origin ubuntu-24.04
git checkout -b add-mypkg-slices ubuntu-24.04

# add slices/mypkg.yaml ...

# commit conventional
git commit -m "feat(mypkg): add core, bins, libs, copyright slices"

# open pr against ubuntu-24.04, then forward-port:
git checkout -b add-mypkg-slices-2510 ubuntu-25.10
git cherry-pick <commit-sha>
# resolve any drift, open pr against ubuntu-25.10, repeat for 26.04
```

## external references

- chisel tool: <https://github.com/canonical/chisel>
- chisel docs (entry): <https://documentation.ubuntu.com/chisel/latest/>
- how-to slice a package: <https://documentation.ubuntu.com/chisel/latest/how-to/slice-a-package/>
- sdf reference: <https://documentation.ubuntu.com/chisel/latest/reference/chisel-releases/slice-definitions/>
- chisel.yaml reference: <https://documentation.ubuntu.com/chisel/latest/reference/chisel-releases/chisel.yaml/>
- manifest reference: <https://documentation.ubuntu.com/chisel/latest/reference/manifest/>
- cut cli reference: <https://documentation.ubuntu.com/chisel/latest/reference/cmd/cut/>
- pro slices how-to: <https://documentation.ubuntu.com/chisel/latest/how-to/install-pro-package-slices/>
- this repo: <https://github.com/canonical/chisel-releases>
- contributing: `./CONTRIBUTING.md`
- navigator (live slice browser): <https://canonical.github.io/chisel-releases-navigator/>
- ubuntu release schedule (for codenames + eol): <https://wiki.ubuntu.com/Releases>

---

agents reading this: you have what you need to navigate this repo, understand contributions, and reason about ci failures. when in doubt, the relevant `ubuntu-XX.XX` branch's `chisel.yaml` and an existing well-formed sdf (`slices/bash.yaml`, `slices/base-files.yaml`) are reliable references.
