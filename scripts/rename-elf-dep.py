#!/usr/bin/env python3
"""就地把 ELF 的 DT_NEEDED / DT_SONAME 字符串改短, 不动任何结构。

patchelf 会重排 ELF (新增/移动 PT_LOAD), 在 Android 的 bionic 链接器上有兼容风险。
新名字比旧名字短时, 直接在 .dynstr 里覆写即可, 文件除这几个字节外完全不变。
"""
import struct, sys

DT_NEEDED, DT_SONAME, DT_STRTAB, DT_STRSZ = 1, 14, 5, 10

def patch(path, old, new):
    assert len(new) < len(old), "新名字必须更短才能就地覆写"
    d = bytearray(open(path, 'rb').read())
    assert d[:4] == b'\x7fELF' and d[4] == 1, "只处理 ELF32"

    e_phoff, = struct.unpack_from('<I', d, 0x1c)
    e_phentsize, e_phnum = struct.unpack_from('<HH', d, 0x2a)

    segs, dyn_off = [], None
    for i in range(e_phnum):
        o = e_phoff + i * e_phentsize
        # Elf32_Phdr: type, offset, vaddr, paddr, filesz, memsz, flags, align
        p_type, p_offset, p_vaddr, _paddr, p_filesz = struct.unpack_from('<IIIII', d, o)
        if p_type == 1: segs.append((p_vaddr, p_offset, p_filesz))       # PT_LOAD
        if p_type == 2: dyn_off = p_offset                                # PT_DYNAMIC
    assert dyn_off is not None, "没有 PT_DYNAMIC"

    def v2o(v):
        for vaddr, off, sz in segs:
            if vaddr <= v < vaddr + sz:
                return off + (v - vaddr)
        raise SystemExit(f"虚拟地址 {v:#x} 不在任何 PT_LOAD 内")

    # 收集动态表, 同时记下所有指向 dynstr 的偏移(用于安全校验)
    entries, strtab_v, strsz = [], None, None
    o = dyn_off
    while True:
        tag, val = struct.unpack_from('<iI', d, o)
        if tag == 0: break
        entries.append((o, tag, val))
        if tag == DT_STRTAB: strtab_v = val
        if tag == DT_STRSZ:  strsz = val
        o += 8
    assert strtab_v is not None and strsz, "找不到 .dynstr"
    strtab = v2o(strtab_v)

    blob = bytes(d[strtab:strtab + strsz])
    target = old.encode() + b'\0'
    hits = [i for i in range(len(blob)) if blob.startswith(target, i)]
    assert len(hits) == 1, f"{old!r} 在 .dynstr 中出现 {len(hits)} 次, 期望 1 次"
    rel = hits[0]

    # 安全校验: 覆写会截短这个字符串, 若有别的引用指向它的内部(后缀共享), 就会被破坏
    interior = range(rel + 1, rel + len(old) + 1)
    refs = [v for _, t, v in entries if t in (DT_NEEDED, DT_SONAME)]
    # .dynsym 里的符号名也在同一个 dynstr 中
    for _, tag, val in entries:
        if tag == 6:  # DT_SYMTAB
            symo = v2o(val)
            n = (strtab - symo) // 16          # .dynsym 通常紧邻 .dynstr 之前
            if 0 < n < 500000 and symo + n * 16 <= len(d):
                refs += [struct.unpack_from('<I', d, symo + i * 16)[0] for i in range(n)]
    bad = [r for r in refs if r in interior]
    assert not bad, f"有引用指向该字符串内部, 不能就地截短: {bad}"

    changed = [t for _, t, v in entries if t in (DT_NEEDED, DT_SONAME) and v == rel]
    assert changed, f"没有 DT_NEEDED/DT_SONAME 指向 {old!r}"

    at = strtab + rel
    d[at:at + len(old) + 1] = new.encode() + b'\0' * (len(old) - len(new) + 1)
    open(path, 'wb').write(d)
    names = {DT_NEEDED: 'DT_NEEDED', DT_SONAME: 'DT_SONAME'}
    print(f"  {path}: {old} -> {new}  ({', '.join(names[t] for t in changed)})")

if __name__ == '__main__':
    patch(sys.argv[1], sys.argv[2], sys.argv[3])
