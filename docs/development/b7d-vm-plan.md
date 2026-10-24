# B7d 本机干净 Windows 虚拟机验收方案

2026-10-25。用户选择先另行规划本机虚拟机环境。本文件是实施方案，尚未授权安装宿主虚拟机软件、接受许可或重启。

## 本机核对与选择

- 当前系统为 Windows 11 家庭版，64 位，版本 10.0.26300；处理器 Ultra 7 255H，16 个逻辑处理器，可见内存约 95.4 GiB，D 盘约 827 GiB 可用（瞬时值）。
- `HypervisorPresent=true`，但处理器 WMI 虚拟化与 SLAT 字段均为 false；已有 hypervisor 时不能仅凭这些字段断言 BIOS 未开启。安装前核对所选工具的兼容诊断，不据此修改 BIOS 或关闭安全功能。
- 未发现 PATH 中的 Sandbox、VBoxManage、vmrun 或 Get-VM，也未发现常见 Oracle/VMware 安装目录。此检查不能证明所有自定义位置均不存在。
- Windows 家庭版不支持客户端 Hyper-V 角色；Windows Sandbox 支持版本表亦未包含 Home。不建议为了这次验收先升级系统版本或使用非官方启用脚本。
- 首选评估 VirtualBox 7.2 系列基础包，使用 Windows 11 x64 来宾。具体补丁版本在真正实施时依据官方发布和签名重新核定并锁定，不把搜索缓存的“最新版”直接写入下载脚本。不需要 Extension Pack。

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

下载遵循用户预设：可信国内镜像有同版本时优先直连并验证官方哈希/签名，否则说明后使用官方来源；不关闭 TLS 校验、不改全局代理。VirtualBox 安装会增加宿主驱动，可能影响虚拟网络或需要重启，真正安装前须确认。

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

安装工具和宿主驱动、虚拟机目录、Windows 来宾来源/许可由用户确认后实施。若不接受该环境方案，B7d 保持未验证，不阻止其他本地代码维护。
