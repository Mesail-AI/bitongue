"""Base structures for data schemas."""

from typing import Any, Self, cast

from msgspec import Struct, convert, json, to_builtins, toml, yaml

__all__ = ("BaseStruct",)


class BaseStruct(Struct):
    """Base structure for data schemas.

    Wraps msgspec's ``Struct`` with round-trip helpers across dicts and
    the JSON/TOML/YAML text formats. Serialization is stable: encoding
    with sorted keys means equal structures always produce identical
    payloads.
    """

    def to_dict(
        self,
        includes: set[str] | None = None,
        excludes: set[str] | None = None,
        exclude_none: bool = False,
    ) -> dict[str, Any]:
        """Convert to a dict of built-in values.

        Args:
            includes: Keep only these field names.
            excludes: Drop these field names.
            exclude_none: Also drop fields whose value is ``None``.

        Returns:
            Field name to built-in value mapping. Content is
            deterministic, but key order is not — use :meth:`to_jsonb`
            when a stable representation matters.
        """

        kvs = cast("dict[str, Any]", to_builtins(self))
        fields = set(kvs.keys())

        if includes:
            fields &= includes

        if excludes:
            fields -= excludes

        if exclude_none:
            fields = {f for f in fields if kvs[f] is not None}

        return {f: kvs[f] for f in fields}

    def to_jsonb(
        self,
        includes: set[str] | None = None,
        excludes: set[str] | None = None,
        exclude_none: bool = False,
    ) -> bytes:
        """Encode to JSON bytes with sorted keys.

        Equal structures produce identical bytes, which makes the
        output suitable for hashing and equality comparison.

        Args:
            includes: Field names to keep, as in :meth:`to_dict`.
            excludes: Field names to drop, as in :meth:`to_dict`.
            exclude_none: Drop ``None``-valued fields.
        """

        return json.encode(
            self.to_dict(
                includes=includes,
                excludes=excludes,
                exclude_none=exclude_none,
            ),
            order="sorted",
        )

    def to_json(
        self,
        includes: set[str] | None = None,
        excludes: set[str] | None = None,
        exclude_none: bool = False,
    ) -> str:
        """Encode to a JSON string, as :meth:`to_jsonb` but text.

        Args:
            includes: Field names to keep, as in :meth:`to_dict`.
            excludes: Field names to drop, as in :meth:`to_dict`.
            exclude_none: Drop ``None``-valued fields.
        """

        return self.to_jsonb(
            includes=includes,
            excludes=excludes,
            exclude_none=exclude_none,
        ).decode("utf-8")

    @classmethod
    def from_dict(cls, obj: dict[str, Any]) -> Self:
        """Build an instance from a mapping of built-in values."""

        return convert(obj, type=cls)

    @classmethod
    def from_jsonb(cls, obj: bytes, strict: bool = True) -> Self:
        """Decode an instance from JSON bytes.

        Args:
            obj: JSON bytes matching the structure layout.
            strict: When true, unknown keys are rejected instead of
                ignored.
        """

        return json.decode(obj.decode("utf-8"), type=cls, strict=strict)

    @classmethod
    def from_json(cls, obj: str, strict: bool = True) -> Self:
        """Decode an instance from a JSON string.

        Args:
            obj: JSON text matching the structure layout.
            strict: When true, unknown keys are rejected instead of
                ignored.
        """

        return json.decode(obj, type=cls, strict=strict)

    @classmethod
    def from_toml(cls, obj: str, strict: bool = True) -> Self:
        """Decode an instance from TOML text.

        Args:
            obj: TOML text matching the structure layout.
            strict: When true, unknown keys are rejected instead of
                ignored.
        """

        return toml.decode(obj, type=cls, strict=strict)

    @classmethod
    def from_yaml(cls, obj: str, strict: bool = True) -> Self:
        """Decode an instance from YAML text.

        Args:
            obj: YAML text matching the structure layout.
            strict: When true, unknown keys are rejected instead of
                ignored.
        """

        return yaml.decode(obj, type=cls, strict=strict)
