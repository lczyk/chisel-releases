# `chisel-releases` -- agent orientation

briefing for an agent that will create prs against the
[`canonical/chisel-releases`](https://github.com/canonical/chisel-releases)
repo. captures what's not in `README.md` / `CONTRIBUTING.md`: tribal
review conventions, schema gotchas across format versions, and patterns
that get prs rejected.

assumed access:

- this file may live anywhere on disk -- do not assume it's inside the
  chisel-releases checkout.
- you can read the repo via `gh` / clone / fetch any release branch.
  authoritative content lives in the branches; this doc only summarises.
- when this doc and the repo disagree, trust the repo.

what to read in the repo (rather than re-read here):

- per-release `chisel.yaml` -- the release manifest (schema features
  available, eol, archives, codename).
- per-release `slices/*.yaml` -- canonical examples of well-formed sdfs;
  `slices/base-files.yaml` and `slices/bash.yaml` are good references.
- repo-level `CONTRIBUTING.md` (on `main`) -- the canonical statement of
  the contribution rules. summarised below; defer to it on conflict.
- repo-level `README.md` (on `main`) -- list of supported releases.

## what chisel is

[chisel](https://github.com/canonical/chisel) is a tool that builds minimal ubuntu rootfs images by extracting only specific _slices_ of debian packages, instead of installing whole packages. slices are named subsets of a package's files, with their own dependency graph. typical use: building tiny container images that contain only what an application actually needs at runtime.

key facts about chisel itself (the tool) -- relevant context, not edited from this repo:

- written in go.
- consumes a _chisel release_ (this repo) as its source of truth for what slices exist and what they contain.
- cli has commands like `chisel cut --release <ref> --root <dir> <pkg>_<slice> ...` to materialise a sliced rootfs.
- docs: <https://documentation.ubuntu.com/chisel/en/latest/>.
- source: <https://github.com/canonical/chisel>.

## branch model

one git branch per ubuntu release: `ubuntu-XX.XX` (e.g. `ubuntu-22.04`, `ubuntu-24.04`, `ubuntu-25.10`, `ubuntu-26.04`). `main` is meta-only -- ci, workflows, contributing docs; **no `slices/` or `chisel.yaml` on `main`**. all slice work targets a release branch.

active branches grow over time -- ubuntu-24.04 has ~600 sdfs, ubuntu-26.04 ~650. eol branches are frozen.

per-release branch root:

- `chisel.yaml` -- release manifest.
- `slices/<pkg>.yaml` -- one per debian source package.
- `spread.yaml` + `tests/spread/integration/<pkg>/{task.yaml,smoke.sh}` -- integration tests.
- `tests/spread/lib/` -- shared spread helpers.
- `.github/` -- workflows + ci scripts (synced from `main`).

for the current set of live (non-eol) releases consult the repo's `README.md` -- it's kept up to date.

## `chisel.yaml` (release manifest)

agents rarely edit this -- but you read it to know which schema features are available on the branch you're targeting.

schema versions:

- **v1** -- `ubuntu-20.04`, `-22.04`, `-24.04`. has separate `v2-archives:` block for pro/esm archives.
- **v2** -- `ubuntu-25.10`. requires chisel >= `v1.2.0`. pro archives unified under `archives:` via `pro:` subkey. adds `prefer:` content option.
- **v3** -- `ubuntu-26.04`. requires chisel >= `v1.4.0`. adds `hint:` field on slices and `v3-essential:` block.

key fields you'll consult:

- `format:` -- gates which sdf features are available.
- `archives.ubuntu.suites[0]` -- short codename (e.g. `noble`). first token before `-` is the apt codename.
- `archives.ubuntu.version` -- ubuntu version; mirrors branch suffix.
- `maintenance.end-of-life` -- date. eol branches are read-only.

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

### canonical examples (read from the repo)

`slices/base-files.yaml` and `slices/bash.yaml` on any live release branch are well-formed reference sdfs covering most schema features. read them rather than rely on a snapshot here.

### addressing & conventions

- **`<pkg>_<slice>` is the canonical full identifier** -- e.g. `bash_bins`, `libc6_libs`. used in `essential:` cross-references and as cli args to `chisel cut`.
- **`copyright` slice convention** -- nearly every package has one; pulls `/usr/share/doc/<pkg>/copyright` (the deb-shipped copyright). listed in the file-level `essential:` so every other slice transitively ships it. **upstream `LICENSE.txt` / `NOTICE` / `ThirdPartyNotices.txt` are not the same thing** -- they belong in a separate `license:` (or `notice:`) slice that itself depends on `<pkg>_copyright`.
- **filename rule** -- `slices/<pkg>.yaml` with `<pkg>` exactly matching the `package:` field. ci enforces this implicitly via several scripts.
- **path sort rule** -- entries inside `contents:` must be lexicographically (bytewise ascii) sorted. reviewers reject unsorted blocks. occasional false-positives if a path embeds a non-ascii or odd character; check carefully.
- **slice design approaches** -- two valid styles per chisel docs: group by content type (`bins`, `config`, `libs`) or group by functional use case. pick one per package; don't mix arbitrarily.

### canonical slice names (strong reviewer preference)

slice names are convention, not enforced -- but reviewers re-classify aggressively. use these:

- `bins` -- executables (note plural; never `bin`).
- `libs` -- shared libraries (plural; never `lib`).
- `headers` -- `/usr/include/...` files.
- `config` / `configs` -- conf files. break up large `config` slices into `<purpose>-config`: `modprobe-config`, `tmpfiles-config`, `pam-config`, `kernel-parameters`, `system-users`.
- `scripts` -- shell helpers / non-binary executables. don't park them in `bins`.
- `data` -- static data (locales, templates, fonts).
- `jars` -- jvm artefacts.
- `copyright` -- the deb copyright file.
- `license` / `notice` -- upstream licence/notice (not deb copyright).
- `core` -- minimum-functional subset. **not "everything"**. avoid `all` (rejected as ambiguous).
- `standard` -- fuller-featured set above `core` (python-style naming).
- when a deb already names something `<pkg>-core` (e.g. `git-core`), keep that name verbatim in the slice rather than renaming to `core`.

### dependency rules

- **stay true to the deb's declared deps.** even if a transitive pull-in would cover it, list each direct apt `Depends:` as an `essential:` entry. reviewers cross-check via `pkg-deps` ci output.
- **`Depends:` only -- not `Recommends:` or `Suggests:`.** including `Recommends:` packages as essentials is rejected.
- **maintainer postinst scripts are not mirrored automatically.** if upstream's postinst would invoke another package's tool (e.g. `update-mime-database`), you must either drop the dep or write the equivalent `mutate:` script. just listing the dep without replicating the side-effect is wrong.
- **slice in support of a known need, not speculatively.** "general rule: only create the slices we need". hypothetical / future-proof slices get rejected.
- **published slices are append-only in spirit.** removing files from an existing slice is a regression -- create a new variant slice (e.g. `<existing>-only`, or a stricter `core`) instead.
- **slice definitions stay use-case-agnostic.** comments like _"this slice exists for app X"_ get rejected. describe what it ships, not why a consumer wants it.

### path entry style nits

- **multiarch lib glob is `*-linux-*`**, not the explicit triple. e.g. `/usr/lib/*-linux-*/libnghttp2.so.14*:`. covers `x86_64-linux-gnu`, `aarch64-linux-gnu`, etc. uniformly.
- **drop trailing `*` when only one version exists** -- `libfoo.so.1:` not `libfoo.so.1*:`.
- **don't add explicit `symlink:` if the deb already ships the symlink.** chisel preserves deb-provided links automatically; manual `symlink:` is for paths the deb does _not_ ship.
- **annotate explicit symlinks with a comment** showing the target: `/usr/bin/dotnet:  # Symlink to ../lib/dotnet/dotnet`.
- **inline-style for short single-key options**: `/path: {arch: [amd64, arm64]}` rather than a multi-line block.
- **arch list formatting is rigid**: lowercase, alphabetical, no inner spaces inside the brackets. `[amd64, arm64, ppc64el, riscv64, s390x]` (yes -- single space after commas, no padding). `[ amd64, ... s390x ]` is rejected.

### `mutate:` -- common mistakes

- **mutate is for merging / transforming files that already exist**, not for synthesis. if a binary needs file `F`, ship `F` from the deb; don't try to construct it via `content.write`.
- **mutate runs once after the entire install set is in place**, not per slice. don't write a mutate that assumes execution order across slices.
- **`until: mutate` collisions**: if a file is needed during mutate _and_ at runtime, you can't drop it. either two paths (one transient, one persistent) or restructure the slice.

### `v3-essential:` (v3+ only)

v3 adds a parallel `v3-essential:` map alongside the regular `essential:` list. used for arch-gated cross-package deps:

```yaml
v3-essential:
  dotnet-sdk-aot-10.0_libs: {arch: [amd64, arm64]}
```

regular `essential:` still takes a flat list of `<pkg>_<slice>` strings. only `v3-essential:` accepts per-entry options (currently just `arch:`).

historical chisel bug: malformed entries in `essential:` (e.g. typoed slice id) used to be silently dropped. patched in upstream chisel; older chisel versions running against new releases may misbehave.

## chisel cli (for testing your slices)

- `chisel cut --release <ref> --root <dir> [--arch <a>] <pkg>_<slice> ...` -- materialise a sliced rootfs.
- `chisel find <pattern>` -- search slices in a release.
- `chisel info <pkg>_<slice>` -- inspect a single slice.

`--release` accepts `ubuntu-XX.XX` (resolves to the branch online), an absolute path (local checkout), or omits to default to host's `/etc/os-release`.

## manifest, pro archives (when relevant)

- **manifest** -- chisel can emit a build manifest at any path declared with `generate: manifest`. by convention `base-files_chisel` writes `/var/lib/chisel/manifest.wall` (jsonwall, zstd). agents only touch this when slicing `base-files`.
- **pro slices** -- a slice ships from a pro archive iff its sdf has `archive: <name>` pointing at a `pro:`-tagged archive in `chisel.yaml` (`fips`, `fips-updates`, `esm-apps`, `esm-infra`). most lts branches have these archives wired up; `ubuntu-26.04` does not yet.

## contribution rules (summary -- defer to repo `CONTRIBUTING.md`)

read [`CONTRIBUTING.md` on `main`](https://github.com/canonical/chisel-releases/blob/main/CONTRIBUTING.md) for the canonical statement. agent-relevant points it covers:

- **branch off the target release branch, not `main`.** prs into `main` are wrong.
- **conventional commits** for subject prefixes (`feat:`, `fix:`, `test:`, `ci:`, `chore:`, `docs:`, `refactor:`); subject lowercase, imperative, <=50 chars, no trailing period; body wrapped at 72.
- **two maintainer approvals to merge**; cla signed; green ci before review; no force-push after review comments; one cohesive change per pr.

extras that are NOT in `CONTRIBUTING.md` but matter:

- **forward-port to every newer live release.** open a pr chain (oldest -> newest). ci's `forward-port-missing` workflow auto-labels prs missing this. exception: the slice's package no longer exists in the newer release's archive -- then the missing port is intentional and auto-ignored.
- **two-approval rule has a practical exception**: trivial forward-port prs (pure cherry-picks of already-approved breaking changes) sometimes land on one approval. don't rely on it for substantive work.
- mark non-forward-port prs with `### Forward porting\nn/a` in the description body.

## ci checks an agent's pr will hit

| check | failure means |
|---|---|
| `lint` | yaml syntax / formatting issue in an sdf |
| `install-slices` | slice can't be `chisel cut`, or package not in archive for some arch |
| `removed-slices` | sdf deleted -- breaking unless underlying package is gone from archive |
| `forward-port-missing` | new slice exists in your branch but not in newer live releases (auto-labels pr) |
| `pkg-deps` | informational comment diffing declared deps vs `apt depends`; non-blocking |
| `validate-hints` | `hint:` text fails nlp style check (v3+ only) |
| `spread` | a slice's smoke test failed inside the lxd test container |
| `cla-check` | cla unsigned |

heads-up: github copilot auto-reviews on prs and frequently proposes patterns reviewers reject (inner-spaced arch lists, `: {}` on essentials). don't follow its suggestions blindly.

## multiarch quirks an agent will hit

- **`binutils-common` is per-arch** despite `Architecture: all`-looking contents -- a deb metadata oddity. don't assume one slice file covers all arches.
- **cross-toolchain packages** (`<tool>-<triple>-linux-gnu`, e.g. `binutils-aarch64-linux-gnu`) ship the prefixed binaries (`aarch64-linux-gnu-ld`). the unprefixed symlinks (`/usr/bin/ld -> aarch64-linux-gnu-ld`) are **not** in the cross deb -- consumers must create them. convention: arch-specific sdfs leave them out; the top-level `binutils` sdf carries the unprefixed name with a `# -> ${ARCH_TRIPLET}-ld` comment.
- **`/proc/self/exe` linker workaround** for chroot-based java tests lives in `tests/spread/lib/link-proc`. needed because chroot breaks `/proc/self/exe` resolution.

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

testing rules from review history:

- **every binary in a `bins` slice must be exercised in spread.** "please test every binary being delivered by that slice" is a recurring rejection.
- **untestable means unshippable.** if a slice can't be properly tested, reviewers will push to drop it rather than ship it untested.
- **80%-ish coverage is the soft target** in pr coverage comments. not a hard gate but watched.
- **spread runs against `distro-info --latest`** for newest release; sometimes the lxd image lags the announcement -- there's a fallback to `ubuntu-daily:` channel ([pr#1001](https://github.com/canonical/chisel-releases/pull/1001)).

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
- **forward-port chain order**: oldest -> newest. cross-link the prs in descriptions.
- **slice rename across releases** (e.g. `bins` -> `scripts`) lands as a chain: breaking pr in oldest target, then fastforward prs into newer branches with `n/a` forward-port marker.
- **versioned soname packages** (e.g. `librocksdb9.11`) get deleted when upstream rolls a new soname (`librocksdb10`). `removed-slices` ci ignores the deletion if the old package is no longer in the archive.

## inspecting the repo without a full checkout

via `gh` or git fetch, common operations (no assumption about cwd):

```bash
# list live release branches
gh api repos/canonical/chisel-releases/branches --paginate \
  --jq '.[] | select(.name | test("^ubuntu-")) | .name'

# read a release manifest
gh api repos/canonical/chisel-releases/contents/chisel.yaml?ref=ubuntu-24.04 \
  --jq '.content' | base64 -d

# read a single sdf
gh api repos/canonical/chisel-releases/contents/slices/bash.yaml?ref=ubuntu-24.04 \
  --jq '.content' | base64 -d

# diff a slice between releases (needs a clone or sparse fetch)
git -C <chisel-releases-repo> diff ubuntu-22.04:slices/coreutils.yaml ubuntu-24.04:slices/coreutils.yaml
```

contribution flow (run inside a chisel-releases checkout, wherever it lives):

```bash
git -C <repo> fetch origin ubuntu-24.04
git -C <repo> checkout -b add-mypkg-slices ubuntu-24.04
# add slices/mypkg.yaml + tests/spread/integration/mypkg/{task.yaml,smoke.sh}
git -C <repo> commit -m "feat(mypkg): add core, bins, libs, copyright slices"
# open pr against ubuntu-24.04, then chain forward-ports through 25.10 -> 26.04
```

## external references

- chisel source: <https://github.com/canonical/chisel>
- chisel docs: <https://documentation.ubuntu.com/chisel/latest/>
  - how-to: slice a package -- <https://documentation.ubuntu.com/chisel/latest/how-to/slice-a-package/>
  - sdf reference -- <https://documentation.ubuntu.com/chisel/latest/reference/chisel-releases/slice-definitions/>
  - chisel.yaml reference -- <https://documentation.ubuntu.com/chisel/latest/reference/chisel-releases/chisel.yaml/>
  - manifest reference -- <https://documentation.ubuntu.com/chisel/latest/reference/manifest/>
  - cut cli reference -- <https://documentation.ubuntu.com/chisel/latest/reference/cmd/cut/>
  - pro slices how-to -- <https://documentation.ubuntu.com/chisel/latest/how-to/install-pro-package-slices/>
- chisel-releases repo: <https://github.com/canonical/chisel-releases>
  - `CONTRIBUTING.md` (authoritative): <https://github.com/canonical/chisel-releases/blob/main/CONTRIBUTING.md>
  - `README.md` (live release list): <https://github.com/canonical/chisel-releases/blob/main/README.md>
- chisel releases navigator (browse slices interactively): <https://canonical.github.io/chisel-releases-navigator/>
- ubuntu release schedule (codenames + eol): <https://wiki.ubuntu.com/Releases>

---

when this doc disagrees with the repo, trust the repo. when in doubt, read `slices/bash.yaml` or `slices/base-files.yaml` on the target release branch as a reference sdf.
