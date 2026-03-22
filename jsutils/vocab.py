#
# $vocabulary handling
#
# vocabularies are URIs associated to set of keywords
# this is a meta-schema specific stuff
#

from .utils import JsonSchema, SchemaPath, log
from .resolver import Resolver
from .recurse import recurseSchema, goFlt

V8 = "https://json-schema.org/draft/2019-09"
V9 = "https://json-schema.org/draft/2020-12"

# $schema official URIs
SCHEMA_VERSION = {
    "http://json-schema.org/draft-03/schema#": 3,
    "http://json-schema.org/draft-04/schema#": 4,
    "http://json-schema.org/draft-06/schema#": 6,
    "http://json-schema.org/draft-07/schema#": 7,
    f"{V8}/schema": 8,
    f"{V9}/schema": 9,
}

# hardcoded vocabularie contents
VOCABULARIES = {
    #
    # 2020-12
    #
    f"{V9}/vocab/core": {
        "$id", "$schema", "$ref", "$anchor", "$dynamicRef", "$dynamicAnchor",
        "$vocabulary", "$comment", "$defs",
    },
    f"{V9}/vocab/applicator": {
        "prefixItems", "items", "contains", "additionalProperties", "properties",
        "patternProperties", "dependentSchemas", "propertyNames",
        "if", "then", "else", "not", "allOf", "anyOf", "oneOf",
    },
    f"{V9}/vocab/unevaluated": {
        "unevaluatedItems", "unevaluatedProperties",
    },
    f"{V9}/vocab/validation": {
        "type", "const", "enum", "multipleOf", "maximum", "exclusiveMaximum",
        "minimum", "exclusiveMinimum", "maxLength", "minLength", "pattern",
        "maxItems", "minItems", "uniqueItems", "maxContains", "minContains",
        "maxProperties", "minProperties", "required", "dependentRequired",
    },
    f"{V9}/vocab/meta-data": {
        "title", "default", "description", "deprecated", "readOnly", "writeOnly", "examples",
    },
    # format: annotation are ignored, assertions are checked
    f"{V9}/vocab/format-annotation": {
        "format"
    },
    f"{V9}/vocab/format-assertion": {
        "format"
    },
    f"{V9}/vocab/content": {
        "contentEncoding", "contentMediaType", "contentSchema",
    },
    #
    # 2019-09
    #
    f"{V8}/vocab/core": {
        "$id", "$schema", "$ref", "$anchor", "$recursiveRef", "$recursiveAnchor",
        "$vocabulary", "$comment", "$defs",
    },
    f"{V8}/vocab/applicator": {
        "additionalItems", "items", "contains", "additionalProperties", "properties",
        "patternProperties", "dependentSchemas", "propertyNames",
        "if", "then", "else", "not", "allOf", "anyOf", "oneOf",
        "unevaluatedItems", "unevaluatedProperties",
    },
    f"{V8}/vocab/validation": {
        "type", "const", "enum", "multipleOf", "maximum", "exclusiveMaximum",
        "minimum", "exclusiveMinimum", "maxLength", "minLength", "pattern",
        "maxItems", "minItems", "uniqueItems", "maxProperties", "minProperties",
        "required", "dependentRequired",
    },
    f"{V8}/vocab/meta-data": {
        "title", "default", "description", "deprecated", "readOnly", "writeOnly", "examples",
    },
    # true means active check, false means ignore silently
    f"{V8}/vocab/format": {
        "format"
    },
    f"{V8}/vocab/content": {
        "contentEncoding", "contentMediaType", "contentSchema",
    },
}

# hard-coded content of official meta-schema vocabularies to avoid retrieving them
# FIXME should there be a deprecated vocabulary?
META_SCHEMA_VOCABULARIES = {
    9: {
        f"{V9}/vocab/core": True,
        f"{V9}/vocab/applicator": True,
        f"{V9}/vocab/unevaluated": True,
        f"{V9}/vocab/validation": True,
        f"{V9}/vocab/meta-data": True,
        f"{V9}/vocab/format-annotation": True,
        f"{V9}/vocab/content": True,
    },
    8: {
        f"{V8}/vocab/core": True,
        f"{V8}/vocab/applicator": True,
        f"{V8}/vocab/validation": True,
        f"{V8}/vocab/meta-data": True,
        f"{V8}/vocab/format": False,
        f"{V8}/vocab/content": True,
    }
}

_FORMAT = "$__format__"

def getMetaSchemaKeywords(
            schema: JsonSchema,
            resolver: Resolver,
        ) -> dict[str, bool]:
    """Retrieve all metaschema keywords and whether they are active."""

    if isinstance(schema, bool):
        return {}
    assert isinstance(schema, dict)
    if "$schema" not in schema:
        log.info(f"no $schema found")
        return {}
    ms_url = schema["$schema"]
    assert isinstance(ms_url, str), f"$schema is a string"

    ms_version: int = SCHEMA_VERSION.get(ms_url, 0)
    ms_ms_version: int = 0
    vocabulary: dict[str, bool]

    # only retrieve if unknown
    if ms_version == 0:
        metaschema: JsonSchema
        try:
            metaschema = resolver.get(ms_url)
        except Exception as e:
            log.warning(f"failed to retrieve {ms_url} ({e})")
            return {}
        assert isinstance(metaschema, dict), "loaded metaschema is an object"
        if "$schema" in metaschema:  # meta-schema recursion
            ms_ms_url = metaschema["$schema"]
            ms_ms_version = SCHEMA_VERSION.get(ms_ms_url, 0)
        if "$vocabulary" not in metaschema:
            log.warning(f"no $vocabulary in {ms_url}")
            return {}
        vocabulary = metaschema["$vocabulary"]
    elif ms_version in META_SCHEMA_VOCABULARIES:
        vocabulary = META_SCHEMA_VOCABULARIES[ms_version]
    else:
        log.warning(f"no $vocabulary for {ms_url}")
        return {}
    assert isinstance(vocabulary, dict), "$vocabularies is an object"

    # whether a keyword is active or to be ignored
    keywords: dict[str, bool] = {}

    # gather explicitely declared vocabularies
    for voc, active in vocabulary.items():
        if voc not in VOCABULARIES:
            log.warning(f"ignoring unexpected vocabulary: {voc}")
            continue
        for k in VOCABULARIES[voc]:
            keywords[k] = active
        # whether to assert formats
        if voc.endswith("/format") or voc.endswith("/format-assertion"):
            keywords[_FORMAT] = active
        elif voc.endswith("/format-annotation") and active:
            keywords[_FORMAT] = False

    # missing standard vocabularies are considered false, unless core
    if ms_ms_version:
        for voc in META_SCHEMA_VOCABULARIES.get(ms_ms_version, {}):
            if voc not in vocabulary:
                active = voc.endswith("/core")
                for k in VOCABULARIES[voc]:
                    if k not in keywords:
                        keywords[k] = active

    return keywords

def cleanupKeywords(schema: JsonSchema, keywords: dict[str, bool]):
    """Remove inactive keywords from schema."""

    remove = { k for k in keywords if not keywords[k] }

    def rmKeywords(sm: JsonSchema, path: SchemaPath):
        if isinstance(sm, dict):
            for k in remove:
                if k in sm:
                    del sm[k]
        return sm

    recurseSchema(schema, ".", goFlt, rmKeywords)

def vocabularizeSchema(schema: JsonSchema, resolver: Resolver) -> bool|None:
    """Handle $vocabulary by coldly removing inactive keywords, return format assert."""
    if active_kws := getMetaSchemaKeywords(schema, resolver):
        cleanupKeywords(schema, active_kws)
    return active_kws.get(_FORMAT, None)
