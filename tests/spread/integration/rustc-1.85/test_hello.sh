#!/usr/bin/env bash
# spellchecker: ignore rootfs rustc binutils libgcc println

# NOTE: We do not have the arch-independent slices for gcc/binutils yet,
#       so we need to determine the architecture here.
#       See: https://github.com/canonical/chisel-releases/issues/761
arch=$(uname -m)-linux-gnu
slices=(
    rustc-1.85_rustc
    gcc-15-"${arch//_/-}"_gcc-15
    binutils-"${arch//_/-}"_linker
    libgcc-15-dev_core
)
rootfs="$(install-slices "${slices[@]}")"
ln -s "${arch}"-gcc-15 "${rootfs}"/usr/bin/cc
ln -s "${arch}"-ld "${rootfs}"/usr/bin/ld

cp testfiles/hello.rs "${rootfs}/hello.rs"

chroot "${rootfs}" rustc-1.85 /hello.rs -o /hello
chroot "${rootfs}" /hello | grep -q "Hello from Rust!"
