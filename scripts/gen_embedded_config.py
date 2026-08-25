#!/usr/bin/env python3
"""Generate src/embedded_config.rs from RD_* environment variables.

All provided server/password values are XOR-obfuscated into the generated
module, so plain strings never appear in the compiled binary's static data.
The plaintext itself only exists inside the CI process and is never printed.

Environment variables (all optional - omitting everything produces a
"behaviour-only" module that injects nothing):

  RD_ID_SERVER         ID server host[:port]
  RD_RELAY_SERVER      relay server host[:port]
  RD_API_SERVER        API server URL
  RD_KEY               server Ed25519 public key (base64)
  RD_PRESET_PASSWORD   unattended access password (plaintext; hashed here with a
                       random salt - the plaintext is never written anywhere)
  RD_RELEASE_REPO      "owner/repo" of the public releases repository used by
                       the update checker (default: <GITHUB_REPOSITORY_OWNER>/rustdesk-release)
  RD_HIDE_NETWORK_UI   hide the whole Network settings tab   (default: true)
  RD_ALLOW_HIDE_CM     enable hiding the CM window            (default: true)

Usage: gen_embedded_config.py [output-path]   (default: src/embedded_config.rs)
"""
import hashlib
import os
import re
import secrets
import sys

XOR_KEY = 0x5A


def xor_arr(value: str) -> str:
    """Encode a string as the XOR-obfuscated byte array literal used by the module."""
    arr = [f"0x{b ^ XOR_KEY:02x}" for b in value.encode("utf-8")]
    lines = [", ".join(arr[i:i + 8]) for i in range(0, len(arr), 8)]
    return "&[" + (",\n          ".join(lines)) + "]"


def preset_password_parts(plaintext: str):
    salt = secrets.token_urlsafe(24)
    digest = hashlib.sha256((plaintext + salt).encode("utf-8")).digest()
    return "00" + _b64(digest), salt


def _b64(data: bytes) -> str:
    import base64

    return base64.b64encode(data).decode("ascii")


def main() -> int:
    out_path = sys.argv[1] if len(sys.argv) > 1 else os.path.join(
        "src", "embedded_config.rs")

    def env(name: str, default: str = "") -> str:
        return os.environ.get(name, default).strip()

    id_server = env("RD_ID_SERVER")
    relay_server = env("RD_RELAY_SERVER")
    api_server = env("RD_API_SERVER")
    key = env("RD_KEY")
    preset_password = env("RD_PRESET_PASSWORD")

    repo_owner = env("GITHUB_REPOSITORY_OWNER", "")
    release_repo = env("RD_RELEASE_REPO") or (
        f"{repo_owner}/rustdesk-release" if repo_owner else "")

    hide_network_ui = env("RD_HIDE_NETWORK_UI", "true").lower() != "false"
    allow_hide_cm = env("RD_ALLOW_HIDE_CM", "true").lower() != "false"

    # --- locked server options --------------------------------------------
    entries = []
    for k, v in (("custom-rendezvous-server", id_server),
                 ("relay-server", relay_server),
                 ("api-server", api_server),
                 ("key", key)):
        if v:
            entries.append(f'    (\n        "{k}",\n        {xor_arr(v)},\n    ),')
    if entries:
        server_section = (
            "// (option key, obfuscated value) - injected as locked overrides\n"
            "#[rustfmt::skip]\n"
            "const LOCKED_SERVER_OPTIONS: &[(&str, &[u8])] = &[\n"
            + ",\n".join(entries) + ",\n];")
    else:
        server_section = (
            "// No server values configured - nothing to inject.\n"
            "const LOCKED_SERVER_OPTIONS: &[(&str, &[u8])] = &[];")

    # --- UI gates ----------------------------------------------------------
    hidden_ui = []
    if hide_network_ui:
        hidden_ui += ["hide-network-settings",
                      "hide-server-settings",
                      "hide-websocket-settings"]
    if hidden_ui:
        ui_section = ('const HIDDEN_UI_OPTIONS: &[&str] = &[\n'
                      + "".join(f'    "{k}",\n' for k in hidden_ui)
                      + '];')
        ui_init = ('    let mut builtin = config::BUILTIN_SETTINGS.write().unwrap();\n'
                   '    for k in HIDDEN_UI_OPTIONS {\n'
                   '        builtin.insert(k.to_string(), "Y".to_string());\n'
                   '    }\n')
    else:
        ui_section = 'const HIDDEN_UI_OPTIONS: &[&str] = &[];'
        ui_init = ''

    # --- preset password ---------------------------------------------------
    if preset_password:
        salt = secrets.token_urlsafe(24)
        digest = hashlib.sha256(
            (preset_password + salt).encode("utf-8")).digest()
        pw_storage = "00" + _b64(digest)
        pw_salt = salt
        pw_consts = (
            f'const PRESET_PASSWORD_STORAGE: &str = "{pw_storage}";\n'
            f'const PRESET_PASSWORD_SALT: &str = "{pw_salt}";\n')
        pw_init = (
            '    let mut hard_settings = config::HARD_SETTINGS.write().unwrap();\n'
            '    hard_settings.insert(\n'
            '        "password".to_string(),\n'
            '        PRESET_PASSWORD_STORAGE.to_string(),\n'
            '    );\n'
            '    hard_settings.insert(\n'
            '        "salt".to_string(),\n'
            '        PRESET_PASSWORD_SALT.to_string(),\n'
            '    );\n')
    else:
        pw_consts = ""
        pw_init = ""

    

    release_owner, _, release_name = release_repo.partition("/")
    if not release_name:
        release_owner, release_name = "", ""

    module = f'''// GENERATED FILE - do not edit by hand.
// Produced by scripts/gen_embedded_config.py from CI configuration.
// Values are XOR-obfuscated at build time; see the generator for details.
use hbb_common::config;

pub const UPDATE_RELEASE_REPO_OWNER: &str = "{release_owner}";
pub const UPDATE_RELEASE_REPO_NAME: &str = "{release_name}";

const OBFUSCATION_KEY: u8 = {XOR_KEY:#04x};

{server_section}

{ui_section}

{pw_consts}fn deobfuscate(data: &[u8]) -> String {{
    String::from_utf8(data.iter().map(|b| b ^ OBFUSCATION_KEY).collect::<Vec<u8>>())
        .unwrap_or_default()
}}

/// Unattended-mode gate consumed by ipc.rs: only requires the explicit
/// allow-hide switch, so temporary random passwords remain usable.
pub fn unattended_hide_cm() -> bool {{
    use hbb_common::config::{{self, option2bool}};
    option2bool("allow-hide-cm", &config::Config::get_option("allow-hide-cm"))
}}

pub fn init() {{
{ui_init}{pw_init}    let mut settings = config::OVERWRITE_SETTINGS.write().unwrap();
    for (k, v) in LOCKED_SERVER_OPTIONS {{
        settings
            .entry(k.to_string())
            .or_insert_with(|| deobfuscate(v));
    }}
}}
'''

    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    with open(out_path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(module)
    # Regression guard: every byte literal must be comma-separated. A bare
    # space between hex bytes is invalid Rust and silently breaks the module
    # (all symbols inside become "not found").
    if re.search(r"0x[0-9a-f]{2}[ \t]+0x", module):
        raise SystemExit("BUG: generated byte array lacks commas - aborting")
    print(f"generated {out_path} "
          f"(server_entries={len(entries)}, hide_ui={hide_network_ui}, "
          f"allow_hide_cm={allow_hide_cm}, preset_password={bool(preset_password)}, "
          f"release_repo='{release_repo}')")
    return 0


if __name__ == "__main__":
    sys.exit(main())
