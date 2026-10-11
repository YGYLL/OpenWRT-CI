// SPDX-License-Identifier: GPL-2.0-only
/* v0.1: on-demand observation only; never attach to a packet path. */
#include <linux/debugfs.h>
#include <linux/device.h>
#include <linux/err.h>
#include <linux/if_arp.h>
#include <linux/module.h>
#include <linux/netdevice.h>
#include <linux/rtnetlink.h>
#include <linux/seq_file.h>
#include <linux/skbuff.h>
#include <net/net_namespace.h>

/* Supplied by the matching qca-nss-drv Build/InstallDev, not local copies. */
#include <nss_arch.h>
#include <nss_def.h>
#include <nss_cmn.h>

#define PROBE_IFNAME "usb0"

static struct dentry *nss_usbnet_debugfs;

static int nss_usbnet_status_show(struct seq_file *seq, void *unused)
{
	struct net_device *dev;
	struct device *parent;
	const char *driver;
	int nss_ifnum;

	seq_puts(seq, "version=0.1.0\nmode=read_only\nnamespace=init\n");
	seq_printf(seq, "ifname=%s\n", PROBE_IFNAME);

	/*
	 * Serialize lookup and observation against rename/unregister. A reference
	 * exists only during this read, including the NSS lookup; never cached.
	 */
	rtnl_lock();
	dev = dev_get_by_name(&init_net, PROBE_IFNAME);
	if (!dev) {
		seq_puts(seq, "found=0\nnss_ifnum=unavailable\n");
		goto unlock;
	}

	parent = dev->dev.parent;
	driver = parent ? dev_driver_string(parent) : "none";
	nss_ifnum = nss_cmn_get_interface_number_by_dev(dev);

	seq_printf(seq, "found=1\nifindex=%d\ndriver=%s\n", dev->ifindex,
		   driver);
	seq_printf(seq, "parent=%s\nbus=%s\n",
		   parent ? dev_name(parent) : "none",
		   parent && parent->bus ? parent->bus->name : "none");
	seq_printf(seq, "cdc_ncm=%u\ntype=%u\nmtu=%u\n",
		   !strcmp(driver, "cdc_ncm"), dev->type, dev->mtu);
	seq_printf(seq, "registered=%u\nrunning=%u\ncarrier=%u\npresent=%u\n",
		   dev->reg_state == NETREG_REGISTERED, netif_running(dev),
		   netif_carrier_ok(dev), netif_device_present(dev));
	seq_printf(seq, "operstate=%u\nflags=%#x\nfeatures=%#llx\n",
		   READ_ONCE(dev->operstate), dev->flags,
		   (unsigned long long)dev->features);
	seq_printf(seq, "rx_queues=%u\ntx_queues=%u\nrx_handler_present=%u\n",
		   dev->real_num_rx_queues, dev->real_num_tx_queues,
		   !!rcu_access_pointer(dev->rx_handler));
	if (dev->type == ARPHRD_ETHER && dev->addr_len == ETH_ALEN)
		seq_printf(seq, "mac=%pM\n", dev->dev_addr);
	/* Report the actual result, including -1. This is not proof of offload. */
	seq_printf(seq, "nss_ifnum=%d\nnss_lookup=nss_cmn_get_interface_number_by_dev\n",
		   nss_ifnum);
	dev_put(dev);
unlock:
	rtnl_unlock();
	return 0;
}

/* The file operations hold THIS_MODULE while a reader has the file open. */
DEFINE_SHOW_ATTRIBUTE(nss_usbnet_status);

static int __init nss_usbnet_init(void)
{
	struct dentry *status;
	int err;

	nss_usbnet_debugfs = debugfs_create_dir("nss_usbnet", NULL);
	if (IS_ERR(nss_usbnet_debugfs))
		return PTR_ERR(nss_usbnet_debugfs);
	if (!nss_usbnet_debugfs)
		return -ENOMEM;

	status = debugfs_create_file("status", 0400, nss_usbnet_debugfs,
				     NULL, &nss_usbnet_status_fops);
	if (IS_ERR_OR_NULL(status)) {
		err = status ? PTR_ERR(status) : -ENOMEM;
		debugfs_remove_recursive(nss_usbnet_debugfs);
		return err;
	}

	pr_info("nss_usbnet: read-only usb0 probe loaded; read debugfs nss_usbnet/status\n");
	return 0;
}

static void __exit nss_usbnet_exit(void)
{
	debugfs_remove_recursive(nss_usbnet_debugfs);
	pr_info("nss_usbnet: read-only probe unloaded\n");
}

module_init(nss_usbnet_init);
module_exit(nss_usbnet_exit);
MODULE_DESCRIPTION("Read-only usb0 and existing NSS interface mapping probe");
MODULE_AUTHOR("OpenWRT-CI contributors");
MODULE_LICENSE("GPL");
MODULE_VERSION("0.1.0");
