# JSON Schema to JSON Model Conversion

Some discussion about how to convert some advanced features.

## Logical keyword elimination

Keywords `if then else not dependentSchemas` can be
replaced with `anyOf andOf oneOf` equivalents as shown below.

### Keyword `not`

Expression _not(S)_ is converted to _oneOf(true, S)_.

### Keyword `if then else`

Expression _if(C) then(T) else(E)_ is converted to
_oneOf(allOf(C, T), allOf(not(C), E))_
which, given that _C_ and _not(C)_ are disjunct, is
_anyOf(allOf(C, T), allOf(not(C), E))_.

### Keyword `dependentSchemas`

Expression _deps(P -> S)_ is converted to
_if(required(P)) then(S)_, using `allOf` as a wrapper if there are several.

### `xxxOf` and `$ref` reductions

Adjacent `xxxOf` and `$ref` keywords can be reduced to a hierarchy involving
only one of these keywords.

Expression _allOf(L1) oneOf(L2) anyOf(L3) ref others_ is converted to
_allOf(L1, oneOf(L2), anyOf(L3), ref, others)_.

## Dynamic Stuff

How to handle `$dynamicAnchor` and `$dynamicRef`.

### Feature

The `$anchor` keyword defines a new _name_ inside the current `$id` or the
schema, so such a name cannot be reused in the same scope.

```json
{
  "$id": "https://foo.com/bla.json",
  "$defs": {
    "fun": {
      "$anchor": "myfun",
      "type": "string",
      "$comment": "current id is `https://foo.com/bla.json#myfun`"
    }
  }
  "$ref": "#myfun",
  "$comment": "this refers to `https://foo.com/bla.json#myfun`, aka `#/$defs/fun`"
}

```

The `$dynamicAnchor` keyword allows to push a name which can be `$dynamicRef`
or `$^ref` later on, thus the name may be reused, the _last_ dynamic one is
expected to win, which is the _first_ static one by the way, i.e. the _outer_
lexical definition?

_If the initially resolved starting point URI includes a fragment that was
created by the "$dynamicAnchor" keyword, the initial URI MUST be replaced by the
URI (including the fragment) for the outermost schema resource in the dynamic
scope (Section 7.1) that defines an identically named fragment with
"$dynamicAnchor"._

See pretty strange
[example](https://json-schema.org/draft/2020-12/json-schema-core#recursive-example)
which involves **2** schemas, merged into one here:

```json
{
  "$def": {
    "tree": {
      "$dynamicAnchor": "node",
      "type": "object",
      "properties": {
        "data": true,
        "children": {
          "type": "array",
          "items": {
            "$dynamicRef": "#node"
          }
        }
      }
    }
  },
  "$dynamicAnchor": "node",
  "$ref": "#/$defs/tree",
  "unevaluatedProperties": false
}
```

Comment: the dynamic anchor inside `tree` is shadowed by the one at the root
when invoked from the `$ref` there.

There seems to be a strange limitation which is that it seems to _only_ work with
recursive things because the dynamic definition needs to be in the current scope,
so it seems to mean that you cannot really use the feature simply to change the
type of a list, for instance, like a template?

How to use it more than once:

```json
{
  "$defs": {
    "foo": {
      "$dynamicAnchor": "FOO",
      "type": "object",
      "properties": {
        "bla": {
          "type": "array",
          "items": {
            "$dynamicRef": "#FOO"
          }
        }
      }
    },
    "bla": {
      "$comment": "simple reference, `#FOO` is `#/$defs/foo`",
      "$ref": "#/$defs/foo"
    },
    "xxx": {
      "$comment": "from here `#FOO` is `#/$defs/xxx`",
      "$dynamicAnchor": "Foo",
      "$ref": "#/$defs/foo",
      "required": ["bla"]
    },
    "yyy": {
      "$comment": "from here `#FOO` is `#/$defs/yyy`",
      "$dynamicAnchor": "Foo",
      "$ref": "#/$defs/foo",
      "maxProperties": 3
    }
  },
  "type": "object",
  "properties": {
    "b": { "$ref": "#/$defs/bla" },
    "x": { "$ref": "#/$defs/xxx" },
    "y": { "$ref": "#/$defs/yyy" }
  }
}
```

There seems to exist a subtlety:

- Using `$ref` means resolving against the local static scope,
  thus it does not matter if it was defined by `$anchor` or `$dynamicAnchor`,
  the result is the same?
- Using `$dynamicRef` means resolving against the dynamic scope,
  which is path dependent.

Note dynamicAnchor/anchor and dynamicRef/ref precise interactions are unclear.

It seems that it may be resolved with inlining, however that requires
to inline the _same_ schema several times to cater for the different
references?

TODO can the same semantics expressed without the dynamic stuff?

### Static Compilation

If there is only one occurence of a dynamic anchor definition, it can be
switched to a static one and dynamoc references can be updated to static
references.
However this cannot be done locally, it depends on the outside references?

If there are several occurences of a dynamic anchor, maybe some dynamic references
can be resolved statically?

If the same reference can be invoked with different definitions, the idea is to
turn it into a static reference, possibly using some schema duplication.

### Model Extension

Only if absolutely necessary…

Add an extension, eg `{"\`": "name"}` and `{"\`": "$name"}` to define direct or
indirect function pointers to implement the feature in the model backend, with
minimal overhead.

## Keyword `unevaluatedItems`

### Feature

`unevaluatedItems`: last resort after `contains`, `items` and `prefixItems`,
or in place: `allOf anyOf oneOf if then else not dependentSchemas`.
FIXME what about `$ref`?

### Handling

- if alone, same as `items`?
- if `items`, it is ignored?
- otherwise applies after `prefixItems` when `contains` does not
  (this implies that contains was applied to all possible items).
- when combined, eg `anyOf`, this suggest that it should be forwarded there?? 

## Keyword `unevaluatedProperties`

### Feature

`unevaluatedProperties`: last resort after `properties patternProperties
additionalProperties`… and for some strange reason `unevaluatedProperties`.

The definition seems recursive.

_Validation with "unevaluatedProperties" applies only to the child values of
instance names that do not appear in the "properties", "patternProperties",
"additionalProperties", or "unevaluatedProperties" annotation results that apply
to the instance location being validated._

I do not understand how a `unevaluatedProperties` can be triggered after
an `additionalProperties` or another `unevaluatedProperties`, if any.

### Handling

Compilation: just forward `unevaluatedProperties` as `additionalProperties`
when not already set?

Forward: what does it mean to forward in the presence of refs, ofs, conditions? 
