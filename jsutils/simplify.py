from .utils import JsonSchema
from .recurse import recurseSchema

def simplifySchema(schema: JsonSchema, url: str):

    def rwtSimpler(schema: JsonSchema, path: list[str]) -> JsonSchema:

        if isinstance(schema, bool):
            return schema
        assert isinstance(schema, dict)

        if "const" in schema and "enum" in schema:
            if schema["const"] in schema["enum"]:
                del schema["enum"]
            else:
                schema = False
        # TODO remove ignored stuff depending on type
        # TODO switch oneOf const to enum

        return schema

    return recurseSchema(schema, url, rwt=rwtSimpler)
