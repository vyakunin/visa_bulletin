"""COPY schema helpers for ingest pipeline."""

from dataclasses import dataclass
from typing import ClassVar


@dataclass(frozen=True)
class CopyFieldDescriptor:
    """Descriptor for a field in COPY operation."""

    name: str
    position: int
    field_type: type


@dataclass(frozen=True)
class ModelCopySchema:
    """Schema descriptor for model COPY operations."""

    model_class: type
    field_descriptors: dict[str, CopyFieldDescriptor]

    _schema_cache: ClassVar[dict[type, "ModelCopySchema"]] = {}

    @classmethod
    def from_model(cls, model_class) -> "ModelCopySchema":
        """
        Build schema from Django model (cached per model class).

        Uses class-level cache so schema is computed once per model type,
        shared across all orchestrator instances.
        """
        if model_class in cls._schema_cache:
            return cls._schema_cache[model_class]

        fields = [f for f in model_class._meta.fields if not f.primary_key]
        descriptors = {
            f.attname: CopyFieldDescriptor(
                name=f.attname,
                position=idx,
                field_type=type(f),
            )
            for idx, f in enumerate(fields)
        }

        schema = cls(model_class=model_class, field_descriptors=descriptors)
        cls._schema_cache[model_class] = schema
        return schema

    def __getattr__(self, name: str) -> int:
        """
        Allow attribute access: schema.wage_from returns position.

        Validates field exists and returns position in one operation.
        """
        if name.startswith("_"):
            raise AttributeError(f"'{type(self).__name__}' has no attribute '{name}'")

        if name in self.field_descriptors:
            return self.field_descriptors[name].position

        available = ", ".join(sorted(self.field_descriptors.keys()))
        raise AttributeError(
            f"Field '{name}' not in schema for {self.model_class.__name__}. "
            f"Available fields: {available}"
        )

    def get_field_position(self, field_name: str) -> int:
        """
        Get position of field (explicit method for dynamic field names).

        Use this when field name comes from a variable.
        """
        if field_name not in self.field_descriptors:
            available = ", ".join(sorted(self.field_descriptors.keys()))
            raise ValueError(
                f"Field '{field_name}' not in schema for {self.model_class.__name__}. "
                f"Available fields: {available}"
            )
        return self.field_descriptors[field_name].position
