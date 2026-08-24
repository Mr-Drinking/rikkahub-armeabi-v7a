#!/usr/bin/env python3
"""生成一个 Android 应用签名用的 PKCS#12 密钥库, 不需要装 JDK。

等价于:
    keytool -genkeypair -keystore release.jks -alias rikkahub-v7a \
            -keyalg RSA -keysize 2048 -validity 10000

密码是交互式输入的, 不会出现在命令行参数或 shell 历史里。

依赖: pip install cryptography
"""
import datetime, getpass, os, sys

try:
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.hazmat.primitives.serialization import pkcs12
    from cryptography.x509.oid import NameOID
except ImportError:
    sys.exit("缺少依赖, 请先运行:  pip install cryptography")

OUT   = sys.argv[1] if len(sys.argv) > 1 else "release.jks"
ALIAS = sys.argv[2] if len(sys.argv) > 2 else "rikkahub-v7a"
YEARS = 30

if os.path.exists(OUT):
    sys.exit(f"{OUT} 已存在。签名密钥绝不能覆盖 —— 换个文件名, 或先备份好旧的。")

pw = getpass.getpass("给密钥库设置一个密码: ")
if len(pw) < 6:
    sys.exit("密码至少 6 位(Android 签名工具的硬性要求)")
if pw != getpass.getpass("再输一次确认: "):
    sys.exit("两次输入不一致")

print("正在生成 RSA-2048 密钥对 ...")
key = rsa.generate_private_key(public_exponent=65537, key_size=2048)

name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, ALIAS)])
now  = datetime.datetime.now(datetime.timezone.utc)
cert = (
    x509.CertificateBuilder()
    .subject_name(name)
    .issuer_name(name)                       # 自签名
    .public_key(key.public_key())
    .serial_number(x509.random_serial_number())
    .not_valid_before(now - datetime.timedelta(days=1))
    .not_valid_after(now + datetime.timedelta(days=365 * YEARS))
    .sign(key, hashes.SHA256())
)

blob = pkcs12.serialize_key_and_certificates(
    name=ALIAS.encode(),
    key=key,
    cert=cert,
    cas=None,
    # Android 的 apksigner 读不了 AES-256 加密的 PKCS#12, 必须用传统兼容算法
    encryption_algorithm=serialization.BestAvailableEncryption(pw.encode()),
)
with open(OUT, "wb") as f:
    f.write(blob)
os.chmod(OUT, 0o600)

print(f"""
已生成 {OUT}  (alias: {ALIAS}, 有效期 {YEARS} 年)

接下来把它设成仓库 secret:

    gh secret set KEYSTORE_BASE64   < <(base64 -w0 {OUT})
    gh secret set KEY_ALIAS         <<< '{ALIAS}'
    gh secret set KEYSTORE_PASSWORD      # 粘贴刚才那个密码
    gh secret set KEY_PASSWORD           # 同上(本脚本两者一致)

务必把 {OUT} 和密码备份好 —— 弄丢了就再也无法给已安装的 App 升级。
""")
