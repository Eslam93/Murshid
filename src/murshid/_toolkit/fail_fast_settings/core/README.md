# Settings that fail fast at boot

A project's settings class, read from environment variables, that refuses to start the process
when a value is missing or out of bounds, and never prints a value while it refuses.

## How to call it

```python
from pydantic import Field, SecretStr
from toolkit.fail_fast_settings.core import CommaSeparated, FailFastSettings, load_settings


class Settings(FailFastSettings):
    database_url: str
    session_secret: SecretStr
    sweep_seconds: int = Field(default=60, ge=10, le=3600)  # a floor and a ceiling
    allowed_origins: CommaSeparated = Field(default_factory=list)


settings = load_settings(Settings)  # SettingsError names every bad variable
```

`SettingsError.problems` is a list such as `["SWEEP_SECONDS: Input should be greater than or equal
to 10"]`. The raised error has no cause attached, so a traceback does not carry the value either.

## Seams

- `CommaSeparated` reads `a, b,,c` as `["a", "b", "c"]` without JSON.
- `env_prefix` in the class's `model_config` is included in the names the error reports.
- Checks that compare several values (a secret against a role name, a setting that is refused in
  production) belong in a `model_validator` of the project's class, or in the boot preflight.

## When lifting, change

Nothing in the core. Write your own settings class on top of it.

Needs: pydantic, pydantic-settings. Tests: `toolkit/fail_fast_settings/tests/`.
