rootfs="$(install-slices bash_bins)"


# hello 

chroot "$rootfs" bash -c "echo Success > /test"

test "$(cat "$rootfs/test")" == "Success"

env --ignore-environment chroot "$rootfs" bash -c "[[ -n \$BASH_VERSION ]]"
