from .utils import JsonSchema
from .recurse import recurseSchema

# type-specific properties
# TODO complete
TYPED_PROPS: dict[str, set[str]] = {
    "string": {"minLength", "maxLength", "pattern"},
    "number": {"minimum", "exclusiveMinimum", "maximum", "exclusiveMaximum", "multipleOf"},
    "object": {"additionalProperties", "unevaluatedProperties", "patternProperties", "required",
        "properties", "minProperties", "maxProperties"},
    "array": {"items", "minItems", "maxItems", "prefixItems", "contains", "minContains",
        "maxContains"},
    "boolean": set(),
    "null": set()
}

def incompatibleProps(st: str):
    props = set()
    [ props := props.union(p) for t, p in TYPED_PROPS.items() if t != st ]
    return props

# TODO string-specific formats?

def simplifySchema(schema: JsonSchema, url: str):

    def rwtSimpler(schema: JsonSchema, path: list[str]) -> JsonSchema:

        if isinstance(schema, bool):
            return schema
        assert isinstance(schema, dict)

        if "const" in schema and "enum" in schema:
            if schema["const"] in schema["enum"]:
                del schema["enum"]
            else:
                return False

        if "type" in schema and isinstance(schema["type"], str):
            stype = schema["type"]
            if stype == "integer":
                stype = "number"
            # remove type-specific properties
            if stype in TYPED_PROPS:
                for p in incompatibleProps(stype):
                    schema.pop(p, None)
            
        # TODO switch oneOf const to enum

        return schema

    return recurseSchema(schema, url, rwt=rwtSimpler)
