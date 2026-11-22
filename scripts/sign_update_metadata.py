#!/usr/bin/env python3
"""Generate rustdesk-update.json and .sig for a custom-client release.

The signature must match src/update_metadata.rs exactly:
    signed_bytes = b"RustDesk update metadata v1\n" + <rustdesk-update.json bytes>
    signature    = base64(ed25519_detached(signed_bytes))   [standard base64]

The private key is read from UPDATE_SIGNING_SEED_HEX (32-byte hex seed), which
comes from a repository secret. Nothing is written unless every artifact listed
on the command line exists and hashes correctly.
"""
import argparse
import base64
import hashlib
import json
import os
import sys

SIGNATURE_CONTEXT = b"RustDesk update metadata v1\n"
KEY_ID = "2026-custom-ed25519-main"
ALGORITHM = "ed25519"


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def platform_arch_format(name):
    """Infer (platform, arch, format) from an asset file name.

    Mirrors current_update_platform/arch/format in src/updater/artifact.rs:
      platform: "windows" / "macos" / otherwise std::env::consts::OS
      arch:     std::env::consts::ARCH, so x86_64 / aarch64 / arm
      format:   exe / msi / dmg / (linux formats are not queried by clients)

    Returns a list of candidate arch values, most specific first, because a
    single guess silently mislabelled armeabi-v7a as x86_64: the name contains
    neither "x86_64" nor "aarch64", so the fallback picked x86_64 and an ARM
    client would never have matched its own package.
    """
    lower = name.lower()

    if "arm64-v8a" in lower or "aarch64" in lower or "arm64" in lower:
        archs = ["aarch64"]
    elif "armeabi-v7a" in lower or "armv7" in lower or "armhf" in lower:
        # Rust reports std::env::consts::ARCH = "arm" on 32-bit ARM.
        archs = ["arm"]
    elif "x86_64" in lower or "amd64" in lower:
        archs = ["x86_64"]
    elif "i686" in lower or "i386" in lower:
        archs = ["x86"]
    else:
        archs = []

    if lower.endswith(".msi"):
        return [("windows", a, "msi") for a in archs]
    if lower.endswith(".exe"):
        return [("windows", a, "exe") for a in archs]
    if lower.endswith(".dmg"):
        return [("macos", a, "dmg") for a in archs]
    if lower.endswith(".deb"):
        return [("linux", a, "deb") for a in archs]
    if lower.endswith(".rpm"):
        return [("linux", a, "rpm") for a in archs]
    if lower.endswith(".apk"):
        return [("android", a, "apk") for a in archs]
    return []


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", required=True, help="owner/name, e.g. kumu7y/rustdesk-custom")
    ap.add_argument("--tag", required=True, help="release tag, e.g. 1.5.3-1")
    ap.add_argument("--version", required=True, help="display version, e.g. 1.5.3-1")
    ap.add_argument("--published-at", default="")
    ap.add_argument("--out-dir", default="dist")
    ap.add_argument(
        "--merge-platform",
        default="",
        help="merge artifacts of other platforms from an existing rustdesk-update.json "
             "in --out-dir, so parallel per-platform runs do not clobber each other",
    )
    ap.add_argument("assets", nargs="+", help="release asset files")
    args = ap.parse_args()

    seed_hex = os.environ.get("UPDATE_SIGNING_SEED_HEX", "").strip()
    if len(seed_hex) != 64:
        sys.exit("UPDATE_SIGNING_SEED_HEX must be 64 hex chars (a 32-byte ed25519 seed)")
    try:
        seed = bytes.fromhex(seed_hex)
    except ValueError:
        sys.exit("UPDATE_SIGNING_SEED_HEX is not valid hex")
    if len(seed) != 32:
        sys.exit("seed must decode to exactly 32 bytes")

    try:
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
        from cryptography.hazmat.primitives import serialization
    except ImportError:
        sys.exit("pip install cryptography")

    private_key = Ed25519PrivateKey.from_private_bytes(seed)
    public_raw = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    print("public key:", public_raw.hex(), file=sys.stderr)

    artifacts = []
    for path in args.assets:
        if not os.path.isfile(path):
            sys.exit("missing asset: %s" % path)
        name = os.path.basename(path)
        kinds = platform_arch_format(name)
        if not kinds:
            print("skipping unsupported asset type: %s" % name, file=sys.stderr)
            continue
        for platform, arch, fmt in kinds:
            artifacts.append({
                "platform": platform,
                "arch": arch,
                "format": fmt,
                "url": "https://github.com/%s/releases/download/%s/%s" % (args.repo, args.tag, name),
                "file_name": name,
                "size": os.path.getsize(path),
                "sha256": sha256_file(path),
            })

    if not artifacts:
        sys.exit("no supported assets given")

    # Windows, Linux and Android publish from separate workflows. Each one signs
    # only what it can see, so carry over the entries of platforms this run did
    # not produce - otherwise the last writer would drop the others.
    if args.merge_platform:
        existing_path = os.path.join(args.out_dir, "rustdesk-update.json")
        if os.path.isfile(existing_path):
            try:
                with open(existing_path, "rb") as fh:
                    previous = json.load(fh)
                keep = [a for a in previous.get("artifacts", [])
                        if a.get("platform") != args.merge_platform]
                known = {a["url"] for a in artifacts}
                for a in keep:
                    if a.get("url") not in known:
                        artifacts.append(a)
                        known.add(a.get("url"))
                print("merged %d artifact(s) from other platforms" % (len(artifacts) - len(keep)),
                      file=sys.stderr)
            except Exception as exc:
                print("could not merge existing metadata (%s); writing this platform only" % exc,
                      file=sys.stderr)

    metadata = {
        "schema_version": 1,
        "app": "rustdesk",
        "package_id": "rustdesk",
        "version": args.version,
        "release_id": args.tag,
        "published_at": args.published_at,
        "signature_key_id": KEY_ID,
        "artifacts": artifacts,
    }
    # Compact, deterministic bytes: the signature covers exactly what is uploaded.
    body = json.dumps(metadata, separators=(",", ":"), sort_keys=False).encode("utf-8")
    signature = private_key.sign(SIGNATURE_CONTEXT + body)
    envelope = {
        "schema_version": 1,
        "algorithm": ALGORITHM,
        "key_id": KEY_ID,
        "signature": base64.b64encode(signature).decode("ascii"),
    }

    os.makedirs(args.out_dir, exist_ok=True)
    meta_path = os.path.join(args.out_dir, "rustdesk-update.json")
    sig_path = meta_path + ".sig"
    with open(meta_path, "wb") as fh:
        fh.write(body)
    with open(sig_path, "w", encoding="ascii") as fh:
        json.dump(envelope, fh, separators=(",", ":"))

    print("wrote %s (%d artifacts, %d bytes)" % (meta_path, len(artifacts), len(body)), file=sys.stderr)
    print("wrote %s" % sig_path, file=sys.stderr)


if __name__ == "__main__":
    main()
