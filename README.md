# RikkaHub · armeabi-v7a 自动构建

给 [RikkaHub](https://github.com/rikkahub/rikkahub) 补一个 **32 位 ARM (armeabi-v7a)** 版本——
上游官方只发布 `arm64-v8a` 和 `x86_64`。

上游每次更新，这里自动同步、打补丁、编译、发版。**不修改任何功能代码**，只动 ABI 配置。

> ⚠️ 非官方构建。签名与官方版不同，**无法覆盖安装**——要装得先卸载官方版（记得先导出数据）。

📦 **[下载最新构建](../../releases/tag/v7a-latest)**

---

## 为什么不能只改一行 `abiFilters`

因为上游把预编译的 `.so` 直接 commit 在仓库里，而且**只有 64 位版本**：

| 库 | 位置 | 加载时机 | 缺失后果 |
|---|---|---|---|
| `libsimple.so` | `app/` | **启动即用**——Room 的 `onOpen` 回调里当 SQLite 扩展加载，跑 `jieba_dict()` 并建 `fts5(tokenize='simple')` 表 | **开机就崩** |
| `libmupdf_java.so` | `document/` | 懒加载 | 打开 PDF 崩 |
| `libproot_exec/loader.so` | `workspace/` | 懒加载 | 终端功能不可用（优雅报错，不崩） |

只把 `abiFilters` 改成 `armeabi-v7a` 的话，编译能过，但 APK 里这几个 `.so` 是空的，装上去直接启动崩溃。
所以必须先把它们的 32 位版本准备好。

## 这些 .so 是怎么来的

| 库 | 来源 | 说明 |
|---|---|---|
| `libmupdf_java.so` | MuPDF 官方 AAR `com.artifex.mupdf:fitz` | 官方 AAR 本来就带 v7a，直接抽出来即可。版本经 JNI 符号集比对确认与上游 vendored 版一致（661 个符号完全吻合） |
| `libsimple.so` | 用 NDK 编译 [wangfenjin/simple](https://github.com/wangfenjin/simple) | 上游官方 release 也只发 arm64/x86_64，只能自己编。构建参数照抄该项目 CI 里的 Android job，只把 ABI 换成 v7a |
| `libproot_exec.so`<br>`libproot_loader.so`<br>`libtalloc.so`<br>`libandroid-shmem.so` | Termux 官方 `arm` 包 | RikkaHub 的 arm64 版是自己重编的（talloc/shmem 静态链接）。这里改用 Termux 现成二进制 + `patchelf` 改依赖名——因为 Android 只解压 `lib*.so` 形式的文件，`libtalloc.so.2` 这种带版本后缀的名字装不进 `nativeLibraryDir` |

## 仓库结构：为什么不维护分叉分支

要改的 `app/build.gradle.kts` 恰好是上游高频改动的文件。如果在 fork 里 commit 修改再 merge 上游，
**每次都要手工解冲突**，自动化就废了。

所以这里是这么组织的：

- **`v7a` 分支**（默认分支，你正在看的）— 只放构建配方，不放源码
- **`master` 分支** — 与上游逐字节镜像，由流水线自动 fast-forward，只为留档 AGPL 对应源码

每次构建都从上游拉一份**全新的 checkout**，在 CI 工作区里临时打补丁，**不产生任何 commit**。
上游怎么改都不会冲突。

补丁脚本 [`scripts/patch-v7a.sh`](scripts/patch-v7a.sh) 对三处锚点用的是**断言而非静默替换**：
上游一旦改动这些位置，构建会响亮地失败，而不是悄悄产出一个 ABI 不对的 APK。

## 两条流水线

| Workflow | 触发 | 干什么 |
|---|---|---|
| [`build-natives.yml`](.github/workflows/build-natives.yml) | 手动 | 产出 4+2 个 v7a `.so`，发到固定 tag `natives-v7a`。**跑一次就够**，只有上游换了原生库版本才需要重跑 |
| [`sync-build.yml`](.github/workflows/sync-build.yml) | 每天 UTC 19:30 / 手动 | 同步上游 → 打补丁 → 编译 → 发到固定 tag `v7a-latest`。上游没新提交则自动跳过 |

构建产物会校验：APK 里**有且仅有** `lib/armeabi-v7a/`，且 `libsimple.so` / `libmupdf_java.so` 确实在包里。

## 配置签名（可选）

不配也能跑——会自动回退到 debug 构建，包名带 `.debug` 后缀，**可以和官方版共存**，适合先验证 v7a 能不能跑。

想要 release 构建，就得有自己的签名密钥。有 JDK 的话直接用 `keytool`：

```bash
keytool -genkeypair -v -keystore release.jks -alias rikkahub-v7a -keyalg RSA -keysize 2048 -validity 10000
```

没装 JDK 也行——[`scripts/make-keystore.py`](scripts/make-keystore.py) 用纯 Python 生成等效的 PKCS#12 密钥库，密码交互式输入，不会进 shell 历史。没克隆仓库的话直接取脚本：

```bash
curl -fsSL -O https://raw.githubusercontent.com/Mr-Drinking/rikkahub-armeabi-v7a/v7a/scripts/make-keystore.py
```

```bash
pip install cryptography && python make-keystore.py release.jks
```

脚本跑完会按你的系统（PowerShell / bash）打印出对应的 `gh secret set` 命令，照着执行即可。需要这 4 个 secret：`KEYSTORE_BASE64`、`KEY_ALIAS`、`KEYSTORE_PASSWORD`、`KEY_PASSWORD`。

> 🔑 **务必备份 `release.jks`**。弄丢了就再也无法给已安装的 App 升级——只能卸载重装。

## 关于 Workspace（终端）功能

rootfs 的下载地址是在 App 里自己填的，不是写死的，所以在 v7a 上填一个 **armhf / armv7 的 rootfs** 即可
（arm64 的 rootfs 在 32 位设备上跑不了）。

## 许可

上游 RikkaHub 采用 **AGPL-3.0**。本仓库是其 fork，同样遵循 AGPL-3.0，
所发布 APK 的对应源码即 `master` 分支 + 本分支的补丁脚本。
