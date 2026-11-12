"""
Key naming conventions (all uppercase):
  Certificates  : EINVOICE_CERT_{SOURCE_NUMBER}_{FIELD}
                  e.g.  EINVOICE_CERT_SYS001_PEM
                        EINVOICE_CERT_SYS001_KEY
                        EINVOICE_CERT_SYS001_PASSWORD

  Config creds  : EINVOICE_CONFIG_{SYSTEM_NUMBER}_{FIELD}
                  e.g.  EINVOICE_CONFIG_SYS001_CLIENT_ID
                        EINVOICE_CONFIG_SYS001_CLIENT_SECRET
                        EINVOICE_CONFIG_SYS001_API_KEY

  Tokens        : EINVOICE_TOKEN_{SYSTEM_NUMBER}_{FIELD}
                  e.g.  EINVOICE_TOKEN_SYS001_ACCESS
                        EINVOICE_TOKEN_SYS001_REFRESH
                        EINVOICE_TOKEN_SYS001_ENCRYPTION
                  (keyed by system_number, not token record id — one active
                   token per config, rotated in place on each auth refresh)
"""

import base64
import logging
import os

_logger = logging.getLogger(__name__)

_ENV_FILE: str = os.environ.get("EINVOICE_ENV_FILE", "/var/lib/odoo/einvoice.env")

# Systemd credentials directory (set automatically by systemd when
# LoadCredential= or SetCredential= is used in the unit file).
_SYSTEMD_CRED_DIR: str = os.environ.get(
    "CREDENTIALS_DIRECTORY", 
    "/run/credentials/odoo18.service", 
)


# Backend 1 — Systemd Credentials  (read-only from Odoo's perspective)
def _systemd_get(key: str) -> "str | None":
    if not os.path.isdir(_SYSTEMD_CRED_DIR):
        return None
    cred_path = os.path.join(_SYSTEMD_CRED_DIR, key)
    if not os.path.isfile(cred_path):
        return None
    try:
        with open(cred_path, "r", encoding="utf-8") as fh:
            return fh.read().strip() or None
    except OSError as exc:
        _logger.warning("einvoice: cannot read systemd credential '%s': %s", key, exc)
        return None


# Backend 2 — OS environment variables  (Docker / K8s / manual export)
def _os_env_get(key: str) -> "str | None":
    """
    Read a credential from the process environment.

    Docker provisioning example (docker-compose.yml):
        environment:
          EINVOICE_CONFIG_SYS001_CLIENT_ID: "my-client-id"
          EINVOICE_CONFIG_SYS001_CLIENT_SECRET: "my-secret"
          EINVOICE_CONFIG_SYS001_API_KEY: "my-api-key"
          EINVOICE_CERT_SYS001_PEM: "<base64-encoded PEM>"
          EINVOICE_CERT_SYS001_KEY: "<base64-encoded private key>"

    Or using an env_file in docker-compose.yml:
        env_file:
          - ./secrets/einvoice.env
    """
    return os.environ.get(key)


# Backend 3 — .env file  (plain Linux installs, writable from Odoo UI)
def _read_env_file() -> dict:
    # Parse /etc/odoo/einvoice.env into a plain dict.  Returns {} if missing
    env: dict = {}
    if not os.path.exists(_ENV_FILE):
        return env
    try:
        with open(_ENV_FILE, "r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                if "=" not in line:
                    continue
                key, _, value = line.partition("=")
                env[key.strip()] = value.strip()
    except OSError as exc:
        _logger.error("einvoice: cannot read env file %s: %s", _ENV_FILE, exc)
    return env


def _write_env_file(env: dict) -> None:
    #  Serialise *env* back to the .env file, creating it if needed (mode 0600)
    parent = os.path.dirname(_ENV_FILE)
    if parent:
        os.makedirs(parent, exist_ok=True)
    lines = [f"{k}={v}\n" for k, v in env.items()]
    try:
        with open(_ENV_FILE, "w", encoding="utf-8") as fh:
            fh.writelines(lines)
        os.chmod(_ENV_FILE, 0o600)
    except OSError as exc:
        _logger.error("einvoice: cannot write env file %s: %s", _ENV_FILE, exc)
        raise


def _env_file_get(key: str) -> "str | None":
    return _read_env_file().get(key)

# Unified get / set / delete
def _get(key: str) -> "str | None":
    return (
        _systemd_get(key)
        or _os_env_get(key)
        or _env_file_get(key)
    )


def _set(key: str, value: str) -> None:
    # Write / update one key in the .env file (the only writable backend)
    env = _read_env_file()
    env[key] = value
    _write_env_file(env)


def _delete(key: str) -> None:
    env = _read_env_file()
    if key in env:
        del env[key]
        _write_env_file(env)


# Key-name helpers
def _safe(value: str) -> str:
    return value.replace(" ", "_").upper()

def _cert_key(source_number: str, field: str) -> str:
    return f"EINVOICE_CERT_{_safe(source_number)}_{field}"

def _config_key(system_number: str, field: str) -> str:
    return f"EINVOICE_CONFIG_{_safe(system_number)}_{field}"

def _token_key(system_number: str, field: str) -> str:
    return f"EINVOICE_TOKEN_{_safe(system_number)}_{field}"

# Certificate helpers  (keyed by source_number)
def get_certificate_pem(source_number: str) -> "bytes | None":
    # Return raw PEM bytes decoded from the base64-encoded stored value
    raw = _get(_cert_key(source_number, "PEM"))
    if raw is None:
        return None
    try:
        return base64.b64decode(raw)
    except Exception:
        return raw.encode("utf-8")

def set_certificate_pem(source_number: str, pem_b64: str) -> None:
    _set(_cert_key(source_number, "PEM"), pem_b64)

def get_private_key_pem(source_number: str) -> "bytes | None":
    raw = _get(_cert_key(source_number, "KEY"))
    if raw is None:
        return None
    try:
        return base64.b64decode(raw)
    except Exception:
        return raw.encode("utf-8")

def set_private_key_pem(source_number: str, key_b64: str) -> None:
    _set(_cert_key(source_number, "KEY"), key_b64)

def get_private_key_password(source_number: str) -> "str | None":
    return _get(_cert_key(source_number, "PASSWORD"))

def set_private_key_password(source_number: str, password: str) -> None:
    if password:
        _set(_cert_key(source_number, "PASSWORD"), password)
    else:
        _delete(_cert_key(source_number, "PASSWORD"))

def delete_certificate(source_number: str) -> None:
    for field in ("PEM", "KEY", "PASSWORD"):
        _delete(_cert_key(source_number, field))

# Company config credentials  (keyed by system_number)
def get_client_id(system_number: str) -> "str | None":
    return _get(_config_key(system_number, "CLIENT_ID"))

def set_client_id(system_number: str, value: str) -> None:
    _set(_config_key(system_number, "CLIENT_ID"), value)

def get_client_secret(system_number: str) -> "str | None":
    return _get(_config_key(system_number, "CLIENT_SECRET"))

def set_client_secret(system_number: str, value: str) -> None:
    _set(_config_key(system_number, "CLIENT_SECRET"), value)

def get_api_key(system_number: str) -> "str | None":
    return _get(_config_key(system_number, "API_KEY"))

def set_api_key(system_number: str, value: str) -> None:
    _set(_config_key(system_number, "API_KEY"), value)

def delete_config_credentials(system_number: str) -> None:
    for field in ("CLIENT_ID", "CLIENT_SECRET", "API_KEY"):
        _delete(_config_key(system_number, field))

# Token helpers  (keyed by system_number — one active token per config)
def get_access_token(system_number: str) -> "str | None":
    return _get(_token_key(system_number, "ACCESS"))

def set_access_token(system_number: str, value: str) -> None:
    _set(_token_key(system_number, "ACCESS"), value)

def get_refresh_token(system_number: str) -> "str | None":
    return _get(_token_key(system_number, "REFRESH"))

def set_refresh_token(system_number: str, value: str) -> None:
    _set(_token_key(system_number, "REFRESH"), value)

def get_encryption_key(system_number: str) -> "str | None":
    return _get(_token_key(system_number, "ENCRYPTION"))

def set_encryption_key(system_number: str, value: str) -> None:
    if value:
        _set(_token_key(system_number, "ENCRYPTION"), value)

def delete_token(system_number: str) -> None:
    for field in ("ACCESS", "REFRESH", "ENCRYPTION"):
        _delete(_token_key(system_number, field))