from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

DEFAULT_COGNITION_PRESETS_PATH = (
    "/Users/braydon/projects/experiments/paia-agent-runtime/config/cognition-presets.toml"
)


@dataclass(frozen=True)
class ResolvedModelRoute:
    route_key: str
    surface: str
    provider: str
    model: str
    base_url: str
    endpoint_url: str
    timeout_seconds: float
    max_tokens_default: int | None
    credential_alias: str
    credential_env_var: str
    api_key: str | None


def _require_str(value: Any, *, field_name: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise ValueError(f"missing required registry field: {field_name}")
    return text


def resolve_model_route(
    *,
    route_key: str,
    service_name: str,
    registry_path: str = DEFAULT_COGNITION_PRESETS_PATH,
) -> ResolvedModelRoute:
    payload = tomllib.loads(Path(registry_path).read_text(encoding="utf-8"))
    routes = payload.get("model_routes", {})
    route = routes.get(route_key)
    if not isinstance(route, dict):
        raise ValueError(f"model route not found in registry: {route_key}")

    surface_name = _require_str(route.get("surface"), field_name=f"model_routes.{route_key}.surface")
    model = _require_str(route.get("model"), field_name=f"model_routes.{route_key}.model")
    provider = _require_str(route.get("provider"), field_name=f"model_routes.{route_key}.provider")
    max_tokens_raw = route.get("max_tokens_default")
    max_tokens = int(max_tokens_raw) if max_tokens_raw is not None else None

    surfaces = payload.get("provider_surfaces", {})
    surface = surfaces.get(surface_name)
    if not isinstance(surface, dict):
        raise ValueError(f"provider surface not found in registry: {surface_name}")
    base_url = _require_str(surface.get("base_url"), field_name=f"provider_surfaces.{surface_name}.base_url")
    timeout_seconds = float(surface.get("start_timeout_seconds") or 30)
    api_key_required = bool(surface.get("api_key_required", True))

    assignments = payload.get("service_credential_assignments", {})
    service_credentials = assignments.get(service_name, {})
    credential_alias = service_credentials.get(provider)
    if not credential_alias:
        credential_alias = payload.get("provider_credential_defaults", {}).get(provider)
    credential_alias = _require_str(
        credential_alias,
        field_name=(
            f"service_credential_assignments.{service_name}.{provider} "
            f"or provider_credential_defaults.{provider}"
        ),
    )

    credentials = payload.get("credentials", {})
    credential = credentials.get(credential_alias)
    if not isinstance(credential, dict):
        raise ValueError(f"credential alias not found in registry: {credential_alias}")
    credential_env_var = _require_str(
        credential.get("env_var"),
        field_name=f"credentials.{credential_alias}.env_var",
    )
    api_key = os.environ.get(credential_env_var)
    if api_key_required and not api_key:
        raise ValueError(
            f"missing configured credential env var: {credential_env_var} "
            f"(route={route_key}, service={service_name})"
        )

    return ResolvedModelRoute(
        route_key=route_key,
        surface=surface_name,
        provider=provider,
        model=model,
        base_url=base_url.rstrip("/"),
        endpoint_url=f"{base_url.rstrip('/')}/chat/completions",
        timeout_seconds=timeout_seconds,
        max_tokens_default=max_tokens,
        credential_alias=credential_alias,
        credential_env_var=credential_env_var,
        api_key=api_key,
    )
