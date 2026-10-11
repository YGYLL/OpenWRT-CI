# NSS USB WAN v0.1：只读探测

面向京东云亚瑟 AX1800 Pro，使用本仓库已有的
`qualcommax/ipq60xx`、`jdcloud_re-ss-01` 配置。v0.1 只观察 init 网络命名空间
中的 `usb0`，不提供任何 NSS 流量加速。它没有自动加载配置。

## 观察范围与生命周期

手动加载后读取 `/sys/kernel/debug/nss_usbnet/status`，可查看驱动名、父设备、总线、
MTU、接口类型、MAC、队列数量、features、运行状态、carrier、设备 present 状态、
已有 RX handler 是否存在，以及 NSS 查询 API 返回的真实接口编号。

- 每次读取使用 RTNL 锁、`dev_get_by_name()` 和配对的 `dev_put()`；不缓存设备指针。
- USB 不存在或已经注销：返回 `found=0`、`nss_ifnum=unavailable`。
- USB 重插或更名：下一次读取重新查找 `usb0`；不会跟随改名后的设备。
- USBnet 的 disconnect 在释放设备前调用 `unregister_netdev()`，与读取时的 RTNL
  序列化；读取时持有的短期引用在解锁前释放。
- debugfs 文件为 `0400`，没有 write 操作；文件打开期间 `THIS_MODULE` 引用防止卸载。
  正常卸载移除 debugfs 目录。没有 notifier、worker、timer 或网络回调需要排空。
- 返回编号是一次观察，不保证映射之后仍存在，更不能证明 ECM 已经可以安全卸载流量。
  `-1` 原样输出。NSS 驱动在查询失败时可能记录一条 warning，因此不要高频轮询。

模块不创建或注册 NSS 虚拟接口，不收发或接管 SKB，不注册 RX handler，不修改
`net_device_ops`，不操作 ECM、RPS、防火墙和网络配置。`rx_handler_present` 只是读字段。
驱动静态符号依赖会阻止 NSS 驱动在探测模块使用期间正常卸载。

## 已恢复的输入与 ABI 边界

已核实以下上游输入：

| 项目 | 已核实内容 |
| --- | --- |
| ImmortalWrt | [`0fb9b10cb9df51fb076470e1dd93d1c30dd89d83`](https://github.com/VIKINGYFY/immortalwrt/commit/0fb9b10cb9df51fb076470e1dd93d1c30dd89d83) |
| 内核 | [`kernel-6.18`](https://github.com/VIKINGYFY/immortalwrt/blob/0fb9b10cb9df51fb076470e1dd93d1c30dd89d83/target/linux/generic/kernel-6.18) 指定 Linux 6.18.52，源归档 SHA256 为 `2b69564f7d4fea0c859b1959ba33709ee6e9139bd100e30a853b57159a8221b8` |
| NSS 驱动 | 上述源码的 `package/qca-nss/qca-nss-drv/Makefile`：`PKG_SOURCE_VERSION=6aa14c7`、`PKG_RELEASE=18`、`QSDK_VERSION=13.1` |
| ECM | 同一源码的 `qca-nss-ecm/Makefile`：`PKG_SOURCE_VERSION=8c7355b`、`PKG_RELEASE=9` |
| NSS 固件 | 固定源码的 `nss-firmware/Makefile` 无条件指定 12.5.210；旧的 `CONFIG_NSS_FIRMWARE_VERSION_12_5` 不是该版本的有效 Kconfig 选项。驱动包 QSDK 版本与 NSS 固件版本是不同字段 |
| 查询 API | [实际 NSS 源码](https://github.com/CodeLinaro-mirror/qsdk_oss_lklm_nss-drv/blob/6aa14c78e097b29c493ff2fef87e4d35906b2b5a/nss_cmn.c) 中 `nss_cmn_get_interface_number_by_dev()` 查询类型 0 的现有注册表，无映射返回 `-1`，并有 `EXPORT_SYMBOL` |

**尚未恢复已安装 `r0-0fb9b10` 固件的最终 `.config`、Feeds 提交、内核生成配置、
原始 `Module.symvers` 和 OpenWrt kernel ABI hash。当前模块不能认定可用于旧固件。**
短 revision 和相同的 `uname -r` 都不能代替完整 ABI 核对。

因此 workflow 默认构建一套新的配套固件和模块，配置采用单设备、上游默认软件包，
而非原有 GENERAL 配置中的全部应用；没有运行修改网络默认值的 Settings.sh。
Feeds 固定在 `Config/NSS-USBNET-feeds.conf` 中，选用上游源码提交时间之前最后的
默认分支提交，每次构建再记录实际 checkout 提交。这是选定的可复现实验基线，
并非恢复出的旧固件 Feeds；不声称复现旧固件。
本实验也不依赖正常构建缓存，不触碰其缓存或发布步骤。

## 注入与独立编译

`Scripts/Packages.sh` 已经从 `wrt/package/` source `Scripts/PRIVATE.sh`。
新 PRIVATE 钩子默认无操作，只有同时满足以下条件才复制包，而且拒绝覆盖已有目录：

```text
NSS_USBNET_EXPERIMENT=1
GITHUB_REF=refs/heads/nss-usbnet-dev
WRT_CONFIG=IPQ60XX-NSS-USBNET
```

`Config/PRIVATE.txt` 默认禁用实验包。专用 workflow 按现有 Settings.sh 的优先级，
先拼接 PRIVATE，再追加 `CONFIG_PACKAGE_kmod-nss-usbnet=m`。包独立输出，不装进固件
rootfs，也不自动加载；NSS 和 CDC-NCM 使用上游/实验配置中正常选择的驱动。

本地全新构建的示例（另选容量充足的构建目录；`ci_repo` 指向当前仓库）：

```bash
ci_repo=/home/ygyl/Projects/OpenWRT-CI
build_root=/path/to/new/nss-usbnet-build
mkdir -p "$build_root"
git -C "$build_root" init
git -C "$build_root" remote add origin https://github.com/VIKINGYFY/immortalwrt.git
git -C "$build_root" fetch --depth=1 origin 0fb9b10cb9df51fb076470e1dd93d1c30dd89d83
git -C "$build_root" checkout --detach FETCH_HEAD
cd "$build_root"
cp "$ci_repo/Config/NSS-USBNET-feeds.conf" feeds.conf
./scripts/feeds update -a
./scripts/feeds install -a
./scripts/feeds uninstall squeezelite
export GITHUB_WORKSPACE="$ci_repo"
export GITHUB_REF=refs/heads/nss-usbnet-dev
export NSS_USBNET_EXPERIMENT=1 WRT_CONFIG=IPQ60XX-NSS-USBNET
cd package
source "$ci_repo/Scripts/PRIVATE.sh"
cd ..
cat "$ci_repo/Config/$WRT_CONFIG.txt" "$ci_repo/Config/PRIVATE.txt" > .config
echo 'CONFIG_PACKAGE_kmod-nss-usbnet=m' >> .config
make defconfig
make download -j"$(nproc)"
make -j"$(nproc)"
python3 "$ci_repo/Scripts/NSS-Usbnet-Artifacts.py" \
  "$build_root" "$build_root-artifacts" --verify
```

第一次必须完成配套固件构建。之后在**同一构建树、同一配置和已完成的内核/NSS
构建**下，独立重编译探测包：

```bash
make package/nss-usbnet/clean
make package/nss-usbnet/compile V=s
```

编译要求来自该树 `Build/InstallDev` 的 `staging_dir/target-*/usr/include/qca-nss-drv/`
头文件，包括 `nss_arch.h` 对应 IPQ60xx 64 位头文件；不在包内复制 NSS 头文件，
不自行声明 API。要求内核 `Module.symvers` 和
`build_dir/target-*/linux-qualcommax_ipq60xx/symvers/qca-nss-drv.symvers` 存在，
后者必须含真实导出的查询符号。`KERNEL_MAKE` 使用 OpenWrt 自己的
`KBUILD_EXTRA_SYMBOLS`，由标准 MODPOST/模块版本机制检查符号。
禁止缺失符号替身、`KBUILD_MODPOST_WARN`、忽略校验或强制加载。

锁定基线中的 squeezelite 音频配方会引入全局 Kconfig 循环依赖，虽然实验配置没有
选择该音频包，仍会影响 `defconfig`。上述 uninstall 只移除隔离构建树中生成的
`package/feeds/packages/squeezelite` 安装链接，不修改 Feeds 源码和正常构建流程。
收集器记录该排除项；workflow 额外拒绝含 Kconfig 错误的配置日志。

复现本次**新**构建时，将 artifact 的 `metadata/feeds.conf.lock` 作为新树的
`feeds.conf`，在更新 Feeds 前使用；恢复记录的源码提交、实验输入和最终 `.config`。
原始 OpenWrt ABI hash 见 `.vermagic`，内核 `CONFIG_MODVERSIONS` 状态见生成的内核
`.config`，导出 CRC 见符号表。这些证据仍不构成可直接使用的 SDK；应重建同一工具链和
内核，不能只拿裸 `.ko` 对照版本号安装。

## Actions 和产物

新增 `.github/workflows/NSS-USBNET.yml`，只允许 `nss-usbnet-dev`：

- 支持手动 dispatch 及仅实验文件发生变化的开发分支 push；源码 SHA 和 Feeds 固定，
  更换基线需要审查文件修改，不能只在 dispatch 时替换源码。
  首次 workflow 还不存在于默认分支时，push 入口用于启动；本次实施不会 push 或触发 CI。
- 使用 `contents: read`，不调用 WRT-CORE，不创建 Release/tag/PR，不修改 main 的定时任务。
- 完整编译固件和模块，成功后核对固定源码/Feeds、配置、实际 `.apk`/`.ipk`、模块
  AArch64 类型、NSS 导入与依赖、vermagic、NSS 头文件/符号表和对应设备 sysupgrade
  镜像。包格式必须与最终配置一致，当前 apk 环境使用实际 `.apk`。
- 失败也保存已产生的日志和构建证据，不把部分产物标成成功。

工作目录中的输出为 `artifacts/nss-usbnet/`：
收集器允许该目录中已有 workflow 日志，但拒绝覆盖既有构建产物；本地重复收集应使用
新的输出目录，避免将不同构建的固件和模块混在一起。

| 位置 | 内容 |
| --- | --- |
| `firmware/` | `bin/targets/qualcommax/ipq60xx/` 完整产物，保留 buildinfo、manifest、原始校验和及配套内核包 |
| `packages/` | 自动发现的 `kmod-nss-usbnet` 软件包，保留其 bin 下相对路径 |
| `metadata/` | 最终配置、Feeds 锁与排除记录、源码提交、软件包元数据/依赖图、真实 NSS 固件/驱动配方及导出头文件、内核配置/生成头文件、`.vermagic`、内核/NSS `Module.symvers`、探测 `.ko` 和 modinfo/导入列表 |
| `logs/` | Feeds、配置、下载、编译日志及主机软件包列表 |
| `SHA256SUMS` | 本次保存文件的 SHA256 |

Actions artifact 名称为 `nss-usbnet-v0.1-<run_id>-<run_attempt>`，申请保留 30 天。
**现有 Auto-Clean 会清理仓库 workflow runs，可能提前删除关联 artifact；应在构建后
立即下载到本地。** 本阶段不修改正常清理策略，也不借正常固件 Release 保存实验包。

## 手动硬件验证与回退

以下步骤只用于已经通过完整构建验证、并实际运行**同次构建的配套新固件**的设备。
本阶段不建议在原来的 6.18.52 / `r0-0fb9b10` 固件安装模块。

1. 留存现有可用固件及备份，核对新镜像的设备型号。刷机由用户另行安排，本模块不刷机。
2. 比较 artifact 的最终配置、内核 ABI hash、`modinfo` 和设备的 `uname -r`、
   `apk info -a kernel`。使用本次产出的包格式和正常软件包校验，不使用 force。
   新固件已经装有匹配 NSS 驱动；安装 probe 的本地 `.apk` 后不应出现自动加载文件。
3. 确认 NSS 驱动已经运行（`/sys/module/qca_nss_drv`），再手动
   `insmod /lib/modules/$(uname -r)/nss_usbnet.ko`。不使用会自动装载尚未运行的 NSS
   驱动的 modprobe 测试方式。debugfs 若尚未挂载，手动挂载后读取：

   ```sh
   cat /sys/kernel/debug/nss_usbnet/status
   ```

4. 保存加载前后 usb0 驱动、MTU、IP/路由、RPS 和网络连通性的观察结果，核对本模块
   没有改变它们。关闭/打开链路和 USB 拔插测试应由用户在可中断联网的时段执行；分别
   观察 `found=0/1`，检查内核日志无 Oops、UAF、锁异常或 `unregister_netdevice` 等待引用。
5. 关闭状态文件后 `rmmod nss_usbnet`，确认 debugfs 目录消失、USB WAN 继续工作。
   打开的文件导致模块 busy 时先关闭文件，不强制卸载。随后可用 `apk del kmod-nss-usbnet`
   移除实验包。软件包没有启动项，重启不会加载探测模块。

回退探测只需正常卸载/删除包；回退配套固件则使用用户已保存的可用镜像。
v0.1 的成功标准是只读观察和生命周期安全，不要求 ECM/NSS 加速计数增加。

## 本地验证的范围

提交前审查已在固定源码和上述五个锁定 Feeds 的实际构建树中执行 `make defconfig`，
确认 `CONFIG_PACKAGE_kmod-nss-usbnet=m`、`CONFIG_PACKAGE_nss-firmware=y`、
`CONFIG_KERNEL_DEBUG_FS=y` 和 `CONFIG_USE_APK=y` 保留。也已检查真实生成的包元数据
与编译依赖图，确认探测包依赖 NSS 驱动编译，展开后的构建目录正确且 `ARCH=arm64`。
同时执行 Bash/ShellCheck、Python 语法和产物收集失败路径检查、workflow 分支/权限
检查，并使用真实 NSS 导出头文件编译 C 对象。
主机 x86 Linux 头文件下的对象编译只覆盖 C/API 基本检查；它不验证 IPQ6018 的
Linux 6.18.52 模块链接、OpenWrt 包依赖、固件构建、硬件拔插或旧固件 ABI。
这些项目必须由上述完整构建及配套固件上的手动测试验证。
