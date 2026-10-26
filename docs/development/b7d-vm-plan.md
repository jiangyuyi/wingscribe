# B7d 本机干净 Windows 虚拟机验收方案

2026-10-25。用户最终决定改用 VirtualBox 并授权安装配置；此前“先保留、不安装”已被本次指令替代。账户验证、许可界面和必要重启仍单独处理，不自动关闭宿主安全功能。

## 本机核对与选择

- 当前系统为 Windows 11 家庭版，64 位，版本 10.0.26300；处理器 Ultra 7 255H，16 个逻辑处理器，可见内存约 95.4 GiB，D 盘约 827 GiB 可用（瞬时值）。
- `HypervisorPresent=true`，但处理器 WMI 虚拟化与 SLAT 字段均为 false；已有 hypervisor 时不能仅凭这些字段断言 BIOS 未开启。安装前核对所选工具的兼容诊断，不据此修改 BIOS 或关闭安全功能。
- 未发现 PATH 中的 Sandbox、VBoxManage、vmrun 或 Get-VM，也未发现常见 Oracle/VMware 安装目录。此检查不能证明所有自定义位置均不存在。
- Windows 家庭版不支持客户端 Hyper-V 角色；Windows Sandbox 支持版本表亦未包含 Home。不建议为了这次验收先升级系统版本或使用非官方启用脚本。
- 按用户最终选择使用 VirtualBox 7.2.22（175245），Windows 11 x64 来宾；清华镜像直连下载，官方 SHA-256 与 Oracle Authenticode 已验证。仅安装 VBoxApplication，使用 NAT，不安装 Extension Pack、桥接或 USB 组件。

依据：[Hyper-V 安装要求](https://learn.microsoft.com/en-us/windows-server/virtualization/hyper-v/get-started/install-hyper-v)、[Sandbox 支持版本](https://learn.microsoft.com/en-us/windows/security/application-security/application-isolation/windows-sandbox/)、[VirtualBox 安装说明](https://docs.oracle.com/en/virtualization/virtualbox/7.2/user/installation.html)、[虚拟机 TPM/安全启动](https://docs.oracle.com/en/virtualization/virtualbox/7.2/user/working-with-vms.html)。

## 预定资源与边界

| 项目 | 方案 |
| --- | --- |
| 虚拟机位置 | 建议独立 `D:\VMs\WingScribe-QA`，实施时确认；不放 Git 仓库或照片目录 |
| CPU / 内存 | 4 vCPU / 12 GiB；必要时在资源允许范围调整 |
| 磁盘 | 100 GiB 动态磁盘，预留快照空间；保留至少 150 GiB 可用余量 |
| 固件 | UEFI、Secure Boot、TPM 2.0，按官方支持方式配置 |
| 客体系统 | 微软官方 Windows 11 x64 ISO 或官方评估镜像；记录来源、版本、摘要和合法使用期限，由用户处理账户/许可步骤 |
| 网络 | 默认 NAT，不建立宿主入站转发；首次配置完成后断网验证离线启动 |
| 文件交换 | 只读验收包目录，包含安装器全部分卷、摘要清单、授权测试副本；不共享照片源目录、整个用户目录或 NAS 凭据 |
| 快照 | 干净系统基线、安装前、升级前；每次变体测试还原基线 |

下载遵循用户预设：可信国内镜像有同版本时优先直连并验证官方哈希/签名，否则说明后使用官方来源；不关闭 TLS 校验、不改全局代理。VirtualBox 安装会增加宿主驱动，用户已授权安装；若需要重启，先通知用户，不自动重启。

## 分步执行及验收

1. 确认所选虚拟机工具、宿主安装和存放目录；核对现有 hypervisor 的兼容性。不主动关闭 VBS、内存完整性或其他安全功能。
2. 固定安装包/ISO 版本，验证官方摘要或签名，保存取证信息。安装宿主软件与客体；需要许可接受、账户登录或重启时交给用户。
3. 不装 Python、Git、CUDA Toolkit 或开发依赖，记录干净客体清单，创建基线快照。Guest Additions 若必须使用，应明确记录，不能因此混入开发环境。
4. CPU 正式包：校验摘要、新装、首次配置、快捷方式/页面、8 张副本流程、元数据、选片缓存和人工标记。断网复验，区分缺模型与缺依赖。
5. CPU 升级/卸载：用测试配置、真实测试 SQLite、JPEG 副本和备份验证跨版本保留；旧代际日志验证拒绝覆盖。所有输入/输出在验收目录中。
6. GPU 包：仅验证完整分卷、新装、应用启动、无可用 CUDA 时的错误提示/既有回退。普通桌面虚拟机的虚拟显卡不等于 NVIDIA CUDA 直通；不据 VM 结果声称真实 GPU 推理通过。真实 CUDA 继续以宿主 RTX 5060 的隔离验证为独立证据。
7. NAS 故障另建最小测试共享，用照片副本和专用访问权限验证断连/重连；不对生产 NAS 断网或修改共享。虚拟网卡断开只能证明该测试拓扑，不能代表所有 SMB 超时行为。
8. 导出日志、截图、版本和 SHA-256，按 [发布验收清单](release-checklist.md) 分项记录。恢复基线，保留可复用虚拟机；不自动发布。

## 仍需确认

VirtualBox 宿主安装配置已获授权。Windows 来宾镜像来源、许可/账户及必要重启仍需用户参与。


## VMware 性能判断与下载依据

- 本机当前 `HypervisorPresent=true`。VMware 在 Hyper-V/VBS 活跃时使用 Windows Hypervisor Platform；换成 VMware 不保证消除这一后端的性能影响，不据 WMI 的单项 false 判定 BIOS 关闭。
- 不把 VirtualBox 的体验差直接归因于用户配置。先固定 4 vCPU、12 GiB 内存、SSD 上的动态磁盘、同一客体和测试负载；安装 VMware Tools 后分别评估界面响应、磁盘和 CPU 工作。不给客体过多 vCPU，不用虚拟显卡宣称 CUDA 直通。
- 不为了跑分关闭 VBS、内存完整性或其他宿主保护。若存在性能问题，记录实际 WHP 模式后再讨论取舍。
- 官方下载需要 Broadcom 基础账户，可能需要完整资料审核与条款确认。用户处理账户步骤；不填写虚构资料，不用汉化重封装或破解安装包。

来源：[免费政策](https://blogs.vmware.com/cloud-foundation/2024/11/11/vmware-fusion-and-workstation-are-now-free-for-all-users/)、[26H1 官方说明](https://blogs.vmware.com/cloud-foundation/2026/05/14/announcing-vmware-workstation-and-fusion-26h1/)、[WHP/VBS 运行模式](https://knowledge.broadcom.com/external/article?legacyId=76918)、[官方下载流程](https://knowledge.broadcom.com/external/article/397417/downloading-free-software-from-the-broad.html)。


## VirtualBox 最终执行选择

用户随后改回 VirtualBox，上述 VMware 性能讨论仅作选型记录。VirtualBox 不承诺与 VMware 相同性能。基础配置：4 vCPU、12 GiB 内存、100 GiB 动态 VDI、UEFI/TPM 2.0、安全启动、NAT；暂不开启 3D，安装客体增强功能后再测试显示性能。保留宿主 hypervisor/VBS，不修改系统代理。

安装包：`VirtualBox-7.2.22-175245-Win.exe`；SHA-256 `afd0ff1656cbe04ed88ce619594ae021419d97cce89fa9bdc443e9a963f1713f`；Authenticode Valid，Oracle America, Inc.。来源为清华同版本镜像，摘要对照 [Oracle 官方清单](https://download.virtualbox.org/virtualbox/7.2.22/SHA256SUMS)。


## 已配置的环境（2026-10-25）

- 用户完成 VirtualBox 安装，实际目录 `D:\Program Files\Oracle\VirtualBox`，命令行版本 `7.2.22r175245`。
- 已创建 `D:\VMs\WingScribe-QA\WingScribe-QA.vbox`，UUID `d15d556b-6bd2-4c38-8dd6-cca60d4e9546`。4 vCPU、12288 MiB、128 MiB 显存、VBoxSVGA（3D 关闭）、100 GiB 动态 VDI/SATA SSD、NAT；剪贴板/拖放关闭，无共享目录。
- EFI、TPM 2.0、微软签名/Oracle 平台密钥已配置，SecureBoot=on。
- 用户 ISO：`D:\Download\Windows11_Client_x64_zh-cn_26300_9457.iso`，9112440832 字节；本地 SHA-256 `B795B52D598BF8FDEA5975844731F4A50C5713876CEFC513884354272B023AF0`。结构含 EFI 光盘引导、boot.wim、install.wim；未取得官方摘要，不声称来源校验通过。
- 虚拟机已实际启动至光盘引导；错过 CD/DVD 按键倒计时后出现 VMBootFail。UI 截图已确认提示，但自动点击/按键没有效果，交由用户重置并在倒计时按空格；尚未安装 Windows，不标记干净系统验收通过。

## 客体基线已就绪（2026-10-26）

- 用户手动完成 Windows 和增强功能安装，创建快照后授权继续。现场读取：Windows 11 `10.0.26300.9457`、Guest Additions `7.2.22 r175245`，系统服务/桌面集成/显示设施均处于活动状态；桌面截图正常。
- 用户快照名 `备份 1`，UUID `5e124d08-13b4-45af-8992-eb592d018d5b`；保留此快照，不覆盖。客体正在运行，当前差分磁盘独立于基线。
- 硬件保持 4 vCPU、12288 MiB、VBoxSVGA/128 MiB、3D 关闭、NAT；未启用共享剪贴板、拖放或共享文件夹。增强功能安装成功不等于已完成性能基准。
- 下一批按顺序执行：重新暂存当前源码并生成 0.0.0.5 CPU 包和摘要；建立仅含验收文件的只读共享；客体清单与安装前检查；CPU 新装/首次启动/离线检查；业务副本验证；升级与卸载；最后独立验证 GPU 无 CUDA 环境。每批记录结果，不把宿主结果代替客体结果。
- 用户确认客体账户有密码，选择手动启动验收脚本；不在聊天收集凭据。B7dQA 为安装文件的临时只读共享，B7dReports 为单独空目录的可写日志回传共享；不包含其他宿主资料。暂未进行客体应用安装。
