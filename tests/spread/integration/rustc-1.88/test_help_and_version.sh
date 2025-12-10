#!/usr/bin/env bash
# spellchecker: ignore rootfs rustc

rootfs="$(install-slices rustc-1.88_rustc)"
chroot "${rootfs}/" rustc-1.88 --help | grep -q "Usage: rustc"
chroot "${rootfs}/" rustc-1.88 --version | grep -q 'rustc 1.88'
