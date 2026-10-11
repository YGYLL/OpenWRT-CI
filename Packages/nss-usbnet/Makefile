# SPDX-License-Identifier: GPL-2.0-only
include $(TOPDIR)/rules.mk

PKG_NAME:=nss-usbnet
PKG_VERSION:=0.1.0
PKG_RELEASE:=1
PKG_LICENSE:=GPL-2.0-only
PKG_FLAGS:=nonshared
PKG_BUILD_DEPENDS:=qca-nss-drv

include $(INCLUDE_DIR)/kernel.mk
include $(INCLUDE_DIR)/package.mk

define KernelPackage/nss-usbnet
  SUBMENU:=Network Devices
  TITLE:=Read-only USB WAN NSS mapping probe
  DEPENDS:=@TARGET_qualcommax_ipq60xx @KERNEL_DEBUG_FS +kmod-qca-nss-drv
  FILES:=$(PKG_BUILD_DIR)/nss_usbnet.ko
endef

define KernelPackage/nss-usbnet/description
  Manually loaded usb0 status probe. Reads existing NSS mappings without
  creating interfaces, intercepting packets, or changing network settings.
endef

define Build/Prepare
	$(INSTALL_DIR) $(PKG_BUILD_DIR)
	$(CP) ./src/* $(PKG_BUILD_DIR)/
endef

define Build/Compile
	@test -r "$(STAGING_DIR)/usr/include/qca-nss-drv/nss_arch.h"
	@test -r "$(STAGING_DIR)/usr/include/qca-nss-drv/nss_def.h"
	@test -r "$(STAGING_DIR)/usr/include/qca-nss-drv/nss_cmn.h"
	@test -s "$(LINUX_DIR)/Module.symvers"
	@test -s "$(PKG_SYMVERS_DIR)/qca-nss-drv.symvers"
	@awk '$$2 == "nss_cmn_get_interface_number_by_dev" && $$4 ~ /^EXPORT_SYMBOL/ { found = 1 } END { exit !found }' \
		"$(PKG_SYMVERS_DIR)/qca-nss-drv.symvers" || \
		{ echo 'Required NSS lookup symbol is not exported by this build' >&2; exit 1; }
	+$(KERNEL_MAKE) M="$(PKG_BUILD_DIR)" \
		NSS_USBNET_INCLUDE="$(STAGING_DIR)/usr/include/qca-nss-drv" modules
endef

# Deliberately no AUTOLOAD, init script, hotplug script, or KCONFIG overrides.
$(eval $(call KernelPackage,nss-usbnet))
