#!/usr/bin/env python3
"""Backport V8 protection and Chromium cursor fixes to pinned x86 WeCom CEF."""
import argparse
import hashlib
import json
from pathlib import Path
import struct


SOURCE_SHA256 = '007385e85fce0e70788dbc362792d0738f6a7f5a045858924ab4789fa58a369f'
OUTPUT_SHA256 = '02b6cd5185af5fa390c41116f9c4a07912dc2175c8f8a75d0ec3f41256220265'
UPSTREAM_COMMIT = 'https://github.com/v8/v8/commit/df1eaa2bd84bf9cc8ff2d6b5e7ca53290546e4ab'
CURSOR_UPSTREAM_COMMIT = 'https://github.com/chromium/chromium/commit/fe73f3f71c1cc1be0734906e841922d9a60c0f0a'
CURSOR_PATCH_RVA = 0x0234227f
CURSOR_RESUME_RVA = 0x0234228b
CURSOR_ORIGINAL = bytes.fromhex('ff 75 ec ff 75 e8 ff 15 68 52 74 1a')
GET_CURSOR_POS_IAT_RVA = 0x0a745018
WINDOW_FROM_POINT_IAT_RVA = 0x0a745268
PATCH_RVA = 0x016a55e4
SUCCESS_RVA = 0x016a55f1
FAILURE_RVA = 0x016a59ac
ORIGINAL_CHECK = bytes.fromhex('83 bd 2c ff ff ff 04 0f 85 bb 03 00 00')


def align(value, alignment):
    return (value + alignment - 1) & ~(alignment - 1)


def branch(opcode, source_rva, target_rva):
    return opcode + struct.pack('<i', target_rva - source_rva - len(opcode) - 4)


def cursor_trampoline(rva):
    # The old fallback sends DIPs to WindowFromPoint. Refresh a native POINT;
    # retain the existing legacy-parent and Aura-root checks after this call.
    stub = bytearray(b'\x53\xe8\x00\x00\x00\x00\x5b')  # save EBX; get PC in EBX
    stub.extend(b'\x81\xeb' + struct.pack('<I', rva + 6))  # image base, independent of ASLR
    stub.extend(bytes.fromhex('83 ec 08 8d 04 24 50'))  # local POINT; GetCursorPos(&point)
    stub.extend(b'\xff\x93' + struct.pack('<I', GET_CURSOR_POS_IAT_RVA))
    stub.extend(bytes.fromhex('85 c0 0f 84 10 00 00 00'))  # failure returns a null HWND
    stub.extend(bytes.fromhex('ff 74 24 04 ff 74 24 04'))  # push y, then x
    stub.extend(b'\xff\x93' + struct.pack('<I', WINDOW_FROM_POINT_IAT_RVA))
    stub.extend(bytes.fromhex('eb 02 31 c0 83 c4 08 5b'))  # release POINT; restore EBX
    stub.extend(branch(b'\xe9', rva + len(stub), CURSOR_RESUME_RVA))
    return bytes(stub)


def patch_bytes(original):
    if hashlib.sha256(original).hexdigest() != SOURCE_SHA256:
        raise ValueError('Unsupported source SHA256; use the unmodified official x86 libcef.dll')
    pe = struct.unpack_from('<I', original, 0x3c)[0]
    machine, count = struct.unpack_from('<HH', original, pe + 4)
    optional_size = struct.unpack_from('<H', original, pe + 20)[0]
    optional = pe + 24
    if original[pe:pe + 4] != b'PE\0\0' or machine != 0x14c:
        raise ValueError('Expected an x86 PE image')
    if struct.unpack_from('<H', original, optional)[0] != 0x10b:
        raise ValueError('Expected a PE32 optional header')
    section_alignment, file_alignment = struct.unpack_from('<II', original, optional + 32)
    image_size, headers_size = struct.unpack_from('<II', original, optional + 56)
    section_table = optional + optional_size
    new_header = section_table + count * 40
    if new_header + 40 > headers_size or any(original[new_header:new_header + 40]):
        raise ValueError('No unused section header slot')
    sections = []
    for index in range(count):
        header = section_table + index * 40
        virtual_size, rva, raw_size, raw_offset = struct.unpack_from('<IIII', original, header + 8)
        sections.append((rva, virtual_size, raw_offset, raw_size))
    text = next(section for section in sections if section[0] <= PATCH_RVA < section[0] + section[3])
    patch_offset = text[2] + PATCH_RVA - text[0]
    trap_offset = text[2] + FAILURE_RVA - text[0]
    if original[patch_offset:patch_offset + len(ORIGINAL_CHECK)] != ORIGINAL_CHECK:
        raise ValueError('Unexpected old-protection check bytes')
    if original[trap_offset:trap_offset + 3] != bytes.fromhex('cc 0f 0b'):
        raise ValueError('Unexpected original failure trap')
    cursor_offset = text[2] + CURSOR_PATCH_RVA - text[0]
    if original[cursor_offset:cursor_offset + len(CURSOR_ORIGINAL)] != CURSOR_ORIGINAL:
        raise ValueError('Unexpected Chromium cursor fallback instructions')

    # The V8 check keeps its original compare-only branch semantics.
    new_rva = align(max(image_size, max(rva + max(size, raw) for rva, size, _, raw in sections)),
                    section_alignment)
    stub = bytearray(bytes.fromhex('83 bd 2c ff ff ff 04'))  # cmp dword [ebp-0xd4], 4
    stub.extend(branch(b'\x0f\x84', new_rva + len(stub), SUCCESS_RVA))
    stub.extend(bytes.fromhex('83 bd 2c ff ff ff 08'))       # cmp dword [ebp-0xd4], 8
    stub.extend(branch(b'\x0f\x85', new_rva + len(stub), FAILURE_RVA))
    stub.extend(branch(b'\xe9', new_rva + len(stub), SUCCESS_RVA))
    v8_stub_size = len(stub)
    stub.extend(b'\xcc' * (align(len(stub), 16) - len(stub)))
    cursor_rva = new_rva + len(stub)
    cursor_stub = cursor_trampoline(cursor_rva)
    stub.extend(cursor_stub)
    raw_offset = align(len(original), file_alignment)
    raw_size = align(len(stub), file_alignment)
    result = bytearray(original)
    result.extend(bytes(raw_offset - len(result)))
    result.extend(stub)
    result.extend(b'\xcc' * (raw_size - len(stub)))
    replacement = branch(b'\xe9', PATCH_RVA, new_rva) + b'\x90' * (len(ORIGINAL_CHECK) - 5)
    result[patch_offset:patch_offset + len(replacement)] = replacement
    # Replace only the two EBP-relative pushes. The original absolute IAT call
    # stays unreachable, retaining its HIGHLOW relocation unchanged for ASLR.
    cursor_replacement = branch(b'\xe9', CURSOR_PATCH_RVA, cursor_rva) + b'\x90'
    result[cursor_offset:cursor_offset + 6] = cursor_replacement
    struct.pack_into('<H', result, pe + 6, count + 1)
    code_size = struct.unpack_from('<I', original, optional + 4)[0]
    struct.pack_into('<I', result, optional + 4, code_size + raw_size)
    struct.pack_into('<I', result, optional + 56, align(new_rva + len(stub), section_alignment))
    struct.pack_into('<I', result, optional + 64, 0)  # CheckSum
    struct.pack_into('<II', result, optional + 96 + 4 * 8, 0, 0)  # Authenticode security directory
    struct.pack_into('<8sIIIIIIHHI', result, new_header, b'.wcompat', len(stub), new_rva,
                     raw_size, raw_offset, 0, 0, 0, 0, 0x60000020)  # Code, read, execute; never write.
    summary = dict(upstream_commit=UPSTREAM_COMMIT, source_sha256=SOURCE_SHA256,
                   output_sha256=hashlib.sha256(result).hexdigest(), source_bytes=len(original),
                   output_bytes=len(result), patch_rva=hex(PATCH_RVA), original_check=ORIGINAL_CHECK.hex(' '),
                   replacement=replacement.hex(' '), trampoline_rva=hex(new_rva), trampoline=stub.hex(' '),
                   success_rva=hex(SUCCESS_RVA), failure_rva=hex(FAILURE_RVA),
                   accepted_old_protection=[4, 8], section_name='.wcompat', section_characteristics='0x60000020',
                   signature='invalidated; certificate directory cleared; original certificate bytes retained',
                   v8_trampoline_size=v8_stub_size,
                   cursor=dict(upstream_commit=CURSOR_UPSTREAM_COMMIT,
                               patch_rva=hex(CURSOR_PATCH_RVA), resume_rva=hex(CURSOR_RESUME_RVA),
                               original_instructions=CURSOR_ORIGINAL.hex(' '),
                               replacement=cursor_replacement.hex(' '), trampoline_rva=hex(cursor_rva),
                               trampoline=cursor_stub.hex(' '),
                               get_cursor_pos_iat_rva=hex(GET_CURSOR_POS_IAT_RVA),
                               window_from_point_iat_rva=hex(WINDOW_FROM_POINT_IAT_RVA),
                               failure='GetCursorPos failure yields null HWND; existing root check rejects update',
                               source_equivalent='GetCursorPos(&point) ? WindowFromPoint(point) : nullptr'),
                   scope='V8 old-protection acceptance and Chromium legacy cursor coordinate bug only')
    return bytes(result), summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if args.source.resolve(strict=True) == args.output.resolve(strict=False):
        parser.error('Source and output must be different files')
    result, summary = patch_bytes(args.source.read_bytes())
    if summary['output_sha256'] != OUTPUT_SHA256:
        raise ValueError('Unexpected output SHA256; refusing to write')
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open('xb') as output:
        output.write(result)
    print(json.dumps(summary, indent=2))


if __name__ == '__main__':
    main()
