#!/usr/bin/env bash
# 把一份纯净的上游 checkout 就地改造成 armeabi-v7a 构建。
# 只在 CI 工作区里跑，不产生任何 commit —— 这样上游怎么改都不会有 merge 冲突。
#
#   用法: patch-v7a.sh <上游源码目录> <natives目录> [ABI列表，逗号分隔]
set -euo pipefail

SRC="${1:?需要上游源码目录}"
NATIVES="${2:?需要 natives 目录}"
ABIS="${3:-armeabi-v7a}"

echo "==> 打补丁: SRC=$SRC ABIS=$ABIS"

# ---------------------------------------------------------------- 1. ABI 配置
# 用 assert 而非静默替换: 上游一旦改动这几处锚点, 构建必须响亮地失败,
# 绝不能悄悄产出一个 ABI 不对的 APK。
python3 - "$SRC/app/build.gradle.kts" "$ABIS" <<'PY'
import sys, re
path, abis = sys.argv[1], sys.argv[2]
lst = ", ".join(f'"{a}"' for a in abis.split(","))
s = open(path, encoding="utf-8").read()

# ndk.abiFilters 决定 APK 里最终打包哪些 ABI —— 这一处是正确性的关键。
s, n_filter = re.subn(r'abiFilters\s*\+=\s*listOf\([^)]*\)',
                      f'abiFilters += listOf({lst})', s)

# 同时必须关掉 ABI splits: AGP 不允许同一个 ABI 既在 ndk.abiFilters 里
# 又在 splits.abi 的过滤器里, 否则报 "Conflicting configuration"。
# 只出一个 ABI 的话本来也不需要 splits, 关掉还更快, 产物就是 app-<type>.apk。
s, n_split  = re.subn(r'isEnable\s*=\s*!isBuildingBundle',
                      'isEnable = false', s)

problems = []
if n_filter != 1: problems.append(f"abiFilters 命中 {n_filter} 次(期望 1)")
if n_split  != 1: problems.append(f"splits.abi.isEnable 命中 {n_split} 次(期望 1)")
if problems:
    sys.exit("上游 build.gradle.kts 的补丁锚点已变化, 需要人工更新 patch-v7a.sh:\n  - "
             + "\n  - ".join(problems))

open(path, "w", encoding="utf-8").write(s)
print("    app/build.gradle.kts: ABI 已改为", lst)
PY

# ------------------------------------------------------- 2. 放入 v7a 原生库
# 上游把这些 .so 直接 commit 在仓库里, 但只有 arm64-v8a / x86_64 两份。
declare -A DEST=(
  [libsimple.so]="app/src/main/jniLibs"
  [libmupdf_java.so]="document/src/main/jniLibs"
  [libproot_exec.so]="workspace/src/main/jniLibs"
  [libproot_loader.so]="workspace/src/main/jniLibs"
  [libtalloc.so]="workspace/src/main/jniLibs"
  [libandroid-shmem.so]="workspace/src/main/jniLibs"
)
# 缺了会直接崩的: libsimple 在 Room 的 onOpen 回调里当 SQLite 扩展加载, 缺失 = 开机即崩。
REQUIRED="libsimple.so libmupdf_java.so"

for so in "${!DEST[@]}"; do
  if [[ -f "$NATIVES/$so" ]]; then
    install -D "$NATIVES/$so" "$SRC/${DEST[$so]}/armeabi-v7a/$so"
    echo "    + ${DEST[$so]}/armeabi-v7a/$so ($(stat -c%s "$NATIVES/$so") bytes)"
  elif [[ " $REQUIRED " == *" $so "* ]]; then
    echo "!! 缺少必需的原生库 $so —— 装上去也会崩, 拒绝构建" >&2
    exit 1
  else
    echo "    - $so 缺失(该功能在 v7a 上不可用)"
  fi
done

# --------------------------------------------------- 3. Firebase 占位配置
# 上游走 secret 注入, fork 里没有。google-services 插件找不到文件会直接 fail,
# 且 debug 变体有 .debug 后缀, 两个包名都得列出来, 否则报 "No matching client".
if [[ ! -f "$SRC/app/google-services.json" ]]; then
  python3 - "$SRC/app/google-services.json" <<'PY'
import json, sys
def client(pkg, n):
    return {
        "client_info": {
            "mobilesdk_app_id": f"1:000000000000:android:{n:022d}",
            "android_client_info": {"package_name": pkg},
        },
        "oauth_client": [],
        "api_key": [{"current_key": "AIzaSyDummyDummyDummyDummyDummyDummyDum"}],
        "services": {"appinvite_service": {"other_platform_oauth_client": []}},
    }
json.dump({
    "project_info": {
        "project_number": "000000000000",
        "project_id": "rikkahub-v7a-placeholder",
        "storage_bucket": "rikkahub-v7a-placeholder.appspot.com",
    },
    "client": [client("me.rerere.rikkahub", 1), client("me.rerere.rikkahub.debug", 2)],
    "configuration_version": "1",
}, open(sys.argv[1], "w"), indent=2)
PY
  echo "    + app/google-services.json (占位, 遥测不会真正上报)"
fi

echo "==> 补丁完成"
