from inspect import getmembers, isclass
from types import ModuleType
from typing import Any, Callable, Dict, Iterator, MutableSequence, NamedTuple, Optional, Type, Union

from pydantic import BaseModel, Extra, Field, NoneStr, validator

from .helpers import NodeKind

RESERVED_NODE_ATTRS_NAMES = {'kind', 'children'}
DEFAULT_NODE_SCHEMA_TITLE = 'Distilled node'
TEXT_NODE_KIND = NodeKind('text')
INVALID_NODE_KIND = NodeKind('invalid-node')


class NodeContext(NamedTuple):
    parent: Optional['Node'] = None
    data: Dict[str, Any] = {}


class BaseNode(BaseModel):
    kind: NodeKind

    def serialize(self, **kwargs: Any) -> Any:
        return self.dict(**kwargs)

class Node(BaseNode):
    kind: NodeKind = Field(default=None, title='Distilled node kind')
    children: 'NodeChildren' = Field(default=[], title='Distilled subnodes')

    # Custom kind value may be set only for base nodes without specific schema,
    # otherwise class name is used
    @validator('kind', pre=True, always=True)
    def set_node_kind(cls, value: NoneStr) -> NodeKind:
        if value is not None and cls is Node:  # type: ignore
            return NodeKind(value)
        return cls.get_node_kind_value()

    def serialize(self, **kwargs: Any) -> Dict[str, Any]:
        exclude = kwargs.get('exclude') or set()
        kwargs.update(exclude=exclude.union({'children'}))
        serialized: dict = self.dict(**kwargs)
        if self.children:
            children = map(lambda child: child.serialize(**kwargs), self.children)
            serialized.update(children=tuple(children))
        return serialized

    @classmethod
    def get_node_kind_value(cls) -> NodeKind:
        return NodeKind(cls.__name__)

    @classmethod
    def prepare_attrs(cls, attrs: Dict[str, Any]) -> Dict[str, Any]:
        # Exclude reserved attrs names from init
        attrs = {
            attr_name: attr
            for attr_name, attr in attrs.items()
            if attr_name not in RESERVED_NODE_ATTRS_NAMES
        }
        # Cast HTML boolean attrs (which are set as flags) to real bool type
        for field in filter(lambda f: f.type_ is bool, cls.__fields__.values()):
            field_attr_value = attrs.get(field.name)
            if field_attr_value is None:
                continue
            elif field_attr_value == 'false':
                attrs[field.name] = False
            else:
                attrs[field.name] = True
        cls.modify_attrs(attrs)
        return attrs

    @classmethod
    def modify_attrs(cls, attrs: Dict[str, Any]) -> None:
        ...  # pragma: no cover

    @property
    def post_init_method(self) -> Optional[Callable]:
        method = getattr(self, 'post_init', None)
        return method if callable(method) else None

    @property
    def context(self) -> NodeContext:
        return self._State.context

    def update_context(self, parent: 'Node' = None, **kwargs: Any) -> NodeContext:
        ctx = NodeContext(
            parent=parent or self._State.context.parent,
            data={**self._State.context.data, **kwargs},
        )
        self._State.context = ctx
        return ctx

    class _State:
        context: NodeContext = NodeContext()

    class Config:
        @staticmethod
        def _modify_node_schema(schema: Dict[str, Any], model: 'NodeType') -> None:
            title = schema.get('title', None)
            if title in {DEFAULT_NODE_SCHEMA_TITLE, None}:
                title = model.__name__
            properties = schema.get('properties', {})
            if model is not Node:
                properties = {
                    prop: schema
                    for prop, schema in properties.items()
                    if prop not in RESERVED_NODE_ATTRS_NAMES
                }
                properties['allOf'] = {'$ref': f'#/definitions/{Node.__name__}'}
            schema.update(title=title, properties=properties)

        title = DEFAULT_NODE_SCHEMA_TITLE
        extra = Extra.allow
        schema_extra = _modify_node_schema


class InvalidNode(BaseNode):
    kind: NodeKind = Field(default=INVALID_NODE_KIND, const=True)
    tagname: str = Field(title='Original node tag name')


class TextNode(BaseNode):
    kind: NodeKind = Field(default=TEXT_NODE_KIND, const=True)
    content: str = Field(default='', title='Text node inner content')

    @classmethod
    def create(cls, content: str) -> 'TextNode':
        return cls(content=content.strip('\n'))

    class Config:
        title = 'Text node'
        extra = Extra.forbid

    def __str__(self) -> str:
        return self.content

    def __repr__(self) -> str:
        return self.__str__()


AnyNode = Union[TextNode, Node, InvalidNode]
NodeChildren = MutableSequence[AnyNode]
NodeType = Type[Node]
Node.update_forward_refs()


def text(content: str = '') -> TextNode:
    return TextNode(content=content)


def load_nodes_types_from_module(module: Optional[ModuleType]) -> Iterator[NodeType]:
    for _, node_type in getmembers(module, _is_node_type):
        yield node_type


def _is_node_type(obj: Any) -> bool:
    return isclass(obj) and issubclass(obj, Node) and obj is not Node
