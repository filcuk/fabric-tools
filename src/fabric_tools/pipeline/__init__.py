"""DataPipeline (Fabric) sync operations."""

# Submodules are imported by callers so package import stays light.

__all__ = [
    "DefinitionError",
    "definition_has_platform",
    "definition_to_diff_text",
    "detect_pipeline_path",
    "display_name_from_path",
    "folder_to_diff_text",
    "load_pipeline_content",
    "pack_definition",
    "part_payloads",
    "unpack_definition",
    "validate_local_pipeline",
    "validate_pipeline_content_dict",
]
