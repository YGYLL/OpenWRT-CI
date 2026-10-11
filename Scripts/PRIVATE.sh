#!/bin/bash
# SPDX-License-Identifier: MIT
# Sourced from package/ by Packages.sh, or by the isolated experiment workflow.
# Normal firmware builds do not opt in, so this hook is a no-op for them.

nss_usbnet_inject() {
	[[ "${NSS_USBNET_EXPERIMENT:-0}" == 1 ]] || return 0
	if [[ "${GITHUB_REF:-}" != refs/heads/nss-usbnet-dev ||
	      "${WRT_CONFIG:-}" != IPQ60XX-NSS-USBNET ]]; then
		printf '%s\n' 'NSS USB probe injection requires the dedicated development build.' >&2
		return 1
	fi
	local source_dir="${GITHUB_WORKSPACE:?}/Packages/nss-usbnet"
	if [[ ! -f ../include/kernel.mk || ! -d ../target/linux/qualcommax ||
	      ! -f "$source_dir/Makefile" || -e nss-usbnet || -L nss-usbnet ]]; then
		printf '%s\n' 'Invalid OpenWrt package directory or nss-usbnet already exists; refusing overwrite.' >&2
		return 1
	fi
	cp -a "$source_dir" ./nss-usbnet
}

nss_usbnet_inject
