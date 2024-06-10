import ctypes
import json
import os
import re
import struct
import sys
import xml.dom.minidom
from dataclasses import dataclass
from typing import Any
from xml.dom.minidom import parseString

import config
from data import object_map

fastlz = ctypes.cdll.LoadLibrary("./fastlz.dll" if config.windows else "./fastlz.so")


class Reader:
	def __init__(self, data: bytes) -> None:
		self.data = data
		self.ptr = 0

	def read_le(self, count: int) -> int:
		val = 0
		self.ptr += count - 1
		for _ in range(count):
			val *= 0x100
			val += self.data[self.ptr]
			self.ptr -= 1
		self.ptr += count + 1
		return val

	def read_be(self, count: int) -> int:
		val = 0
		for _ in range(count):
			val *= 0x100
			val += self.data[self.ptr]
			self.ptr += 1
		return val

	def read_float(self) -> float:
		return struct.unpack("f", self.read_bytes(4)[::-1])[0]

	def assertion(self, count: int, value: bytes, message: str):
		if self.read_bytes(count) != value:
			raise Exception(message)

	def read_null_term(self) -> bytes:
		val = b""
		while True:
			x = self.data[self.ptr]
			self.ptr += 1
			if x == 0x00:
				return val
			val += bytes([x])

	def read_bool(self) -> bool:
		v = self.read_bytes(1)
		if v[0] > 1:
			raise Exception("invalid bool")
		return v == b"\x01"

	def mystery(self, count: int, message: str):
		print(message, self.read_bytes(count))

	def read_bytes(self, count: int) -> bytes:
		v = self.data[self.ptr : self.ptr + count]
		self.ptr += count
		return v


class ComponentFieldData:
	typename: str
	field: str


ComponentData = dict[str, list[ComponentFieldData]]


@dataclass
class Component:
	name: str
	tags: list[str]
	fields: dict[str, Any]
	enabled: bool
	not_deleted_maybe: bytes


@dataclass
class Entity:
	name: str
	path: str
	tags: list[str]
	x: float
	y: float
	size_x: float
	size_y: float
	rotation: float
	components: list[Component]
	children: list["Entity"]
	deleted_maybe: bytes


def parse_entity(reader: Reader, type_sizes, component_data, child_counts):
	name_len = reader.read_be(4)
	name = bstr(reader.read_bytes(name_len))
	deleted_maybe = reader.read_bytes(1)  # 0x00
	path_len = reader.read_be(4)
	path = bstr(reader.read_bytes(path_len))
	tag_len = reader.read_be(4)
	tag = bstr(reader.read_bytes(tag_len)).split(",")
	x = reader.read_float()
	y = reader.read_float()
	scale_x = reader.read_float()
	scale_y = reader.read_float()
	rotation = reader.read_float()
	maybe_num_comps = reader.read_be(4)
	entity = Entity(
		name, path, tag, x, y, scale_x, scale_y, rotation, [], [], deleted_maybe
	)
	for _ in range(maybe_num_comps):
		entity.components.append(parse_component(reader, type_sizes, component_data))
	child_counts.append(reader.read_be(4))
	return entity


def bstr(a: bytes) -> str:
	return str(a)[2:-1]


trivial_types: dict[str, tuple[int, str]] = {
	"float": (4, "f"),
	"double": (8, "d"),
	"int": (4, "i"),
	"int32": (4, "i"),
	"__int64": (8, "l"),
	"unsigned int": (4, "I"),
	"uint32": (4, "I"),
	"unsigned __int64": (8, "L"),
	"unsigned short": (2, "H"),
	"bool": (1, "b"),
}


def do_type(reader: Reader, t: str, type_sizes, component_data) -> Any:
	vec2 = "class ceng::math::CVector2<"
	xform = "struct ceng::math::CXForm<"
	lens = "struct LensValue<"
	vector = "class std::vector<"
	string = "class std::basic_string<char,struct std::char_traits<char>,class std::allocator<char> >"
	if t == "bool":  # for errors
		data = reader.read_bool()
	elif t in trivial_types.keys():
		pair = trivial_types[t]
		data = struct.unpack(pair[1], reader.read_bytes(pair[0])[::-1])[0]
	elif t[: len(vec2)] == vec2:
		true_type = t[len(vec2) : -1]
		data = (
			do_type(reader, true_type, type_sizes, component_data),
			do_type(reader, true_type, type_sizes, component_data),
		)
	elif t[: len(lens)] == lens:
		true_type = t[len(lens) : -1]

		data = {
			"value": do_type(reader, true_type, type_sizes, component_data),
			"default": do_type(reader, true_type, type_sizes, component_data),
			"frame": do_type(reader, "int", type_sizes, component_data),
		}
		# data = {
		# 	"later": do_type(reader, true_type, type_sizes, component_data),
		# 	"earlier": do_type(reader, true_type, type_sizes, component_data),
		# 	"frame": do_type(reader, "int", type_sizes, component_data),
		# }
	elif t[: len(xform)] == xform:
		true_type = t[len(xform) : -1]
		data = {
			"position": do_type(
				reader, vec2 + true_type + ">", type_sizes, component_data
			),
			"scale": do_type(
				reader, vec2 + true_type + ">", type_sizes, component_data
			),
			"rotation": do_type(reader, true_type, type_sizes, component_data),
		}
	elif t[: len(vector)] == vector:
		partial_type = t[len(vector) :]
		true_type = ""
		count = 0
		for k, c in enumerate(partial_type):
			if c == "," and count == 0:
				true_type = partial_type[:k]
			elif c == "<":
				count += 1
			elif c == ">":
				count -= 1
		data = [
			do_type(reader, true_type, type_sizes, component_data)
			for _ in range(reader.read_be(4))
		]
	elif t == string or t == "string":
		size = reader.read_be(4)
		data = bstr(reader.read_bytes(size))
	elif t == "UintArrayInline" or t == "struct UintArrayInline":
		size = reader.read_be(4)
		data = [reader.read_be(4) for _ in range(size)]
	elif t[-4:] == "Enum":
		data = reader.read_be(type_sizes[t])
	elif t == "struct SpriteStains *":
		data = None
	else:
		if t in object_map.keys():
			component_object = {}
			for field in object_map[t]:
				component_object[field[0]] = do_type(
					reader, field[1], type_sizes, component_data
				)
			return component_object
		raise Exception("unknown type: " + t + " at " + hex(reader.ptr))
	return data


def parse_component(
	reader: Reader, type_sizes: dict[str, int], component_data: ComponentData
) -> Component:
	component_name_len = reader.read_be(4)
	component_name = bstr(reader.read_bytes(component_name_len))
	deleted = reader.read_bytes(1)  # first is ??? second is enabled
	enabled = reader.read_bool()
	component_tag_len = reader.read_be(4)
	component_tags = bstr(reader.read_bytes(component_tag_len))
	fields = component_data[component_name]
	data = {}
	for field in fields:
		# print(field.field, field.typename, hex(reader.ptr), end=" ")
		data[field.field] = do_type(reader, field.typename, type_sizes, component_data)
		# print(data[field.field])
	return Component(component_name, component_tags.split(","), data, enabled, deleted)


def get_schema_data(hash):
	type_sizes: dict[str, int] = {}
	component_data: ComponentData = {}
	if hash != b"":
		schema_content = open(
			config.schema_path + str(hash)[2:-1] + ".xml",
			"r",
		).read()

		def fix(s):
			os = s
			s = re.sub(r'("[^\n]*)>([^\n]*")', r"\1&gt;\2", s)
			s = re.sub(r'("[^\n]*)<([^\n]*")', r"\1&lt;\2", s)
			if s == os:
				return s
			return fix(s)

		schema_content = fix(schema_content)
		tree = parseString(schema_content)
		for i in tree.documentElement.childNodes:
			if not isinstance(i, xml.dom.minidom.Element):
				continue
			comp_name = i.getAttribute("component_name")
			v: list[ComponentFieldData] = []
			component_data[comp_name] = v
			for child in i.childNodes:
				if not isinstance(child, xml.dom.minidom.Element):
					continue
				var_name = child.getAttribute("name")
				var_size = int(child.getAttribute("size"))
				var_type = child.getAttribute("type")
				data = ComponentFieldData()
				data.typename = var_type
				data.field = var_name
				v.append(data)
				type_sizes[var_type] = var_size
	return type_sizes, component_data


def parse_data(compressed_data: bytes) -> list[Entity]:
	compressed_reader = Reader(compressed_data)
	compressed_size, decompressed_size = compressed_reader.read_le(
		4
	), compressed_reader.read_le(4)
	input_buffer = ctypes.create_string_buffer(
		compressed_data[compressed_reader.ptr :], compressed_size
	)
	output_buffer = ctypes.create_string_buffer(decompressed_size)
	fastlz.fastlz_decompress.restype = ctypes.c_int32
	fastlz.fastlz_decompress(
		input_buffer, compressed_size, output_buffer, decompressed_size
	)
	decompressed = b"".join([x for x in output_buffer])
	open("./out", "wb").write(decompressed)
	data_reader = Reader(decompressed)
	empty = data_reader.read_bytes(4)
	if empty == b"\x00\x02\x00\x20":
		pass  # empty file
	elif empty == b"\x00\x00\x00\x02":
		pass  # file with content
	else:
		raise Exception("invalid empty flag")
	# empty is useless because hash size is 0 if empty
	hash_size = data_reader.read_be(4)  # size info
	# hash size is 0x20 if not empty
	hash = data_reader.read_bytes(hash_size)
	type_sizes, component_data = get_schema_data(hash)

	maybe_num_entities = data_reader.read_be(4)

	root = Entity("root", "??", [], 0, 0, 1, 1, 0, [], [], b"")
	child_counts = [maybe_num_entities]
	entities = [root]
	i = 0
	while i < sum(child_counts):
		e = parse_entity(data_reader, type_sizes, component_data, child_counts)
		entities.append(e)
		i = i + 1

	def adjust(a):
		return {"name": a.name, "children": [adjust(c) for c in a.children]}

	def handle(data: list[tuple[Entity, int]]) -> Entity:
		v = data.pop(0)
		for _ in range(v[1]):
			v[0].children.append(handle(data))
		return v[0]

	parented = handle(list(zip(entities, child_counts)))
	return parented.children


def save_type(
	t: str, value: Any, type_sizes: dict[str, int], component_data: ComponentData
) -> bytes:
	data = b""
	vec2 = "class ceng::math::CVector2<"
	xform = "struct ceng::math::CXForm<"
	lens = "struct LensValue<"
	vector = "class std::vector<"
	string = "class std::basic_string<char,struct std::char_traits<char>,class std::allocator<char> >"
	print(t, value)
	if t in trivial_types.keys():
		data = struct.pack(trivial_types[t][1], value)[::-1]
	elif t[: len(vec2)] == vec2:
		true_type = t[len(vec2) : -1]
		data = save_type(true_type, value[0], type_sizes, component_data) + save_type(
			true_type, value[1], type_sizes, component_data
		)
	elif t[: len(lens)] == lens:
		true_type = t[len(lens) : -1]
		data = (
			save_type(true_type, value["value"], type_sizes, component_data)
			+ save_type(true_type, value["default"], type_sizes, component_data)
			+ save_type("int", value["frame"], type_sizes, component_data)
		)
	elif t[: len(xform)] == xform:
		true_type = t[len(xform) : -1]
		data = (
			save_type(
				vec2 + true_type + ">", value["position"], type_sizes, component_data
			)
			+ save_type(
				vec2 + true_type + ">", value["scale"], type_sizes, component_data
			)
			+ save_type(true_type, value["rotation"], type_sizes, component_data)
		)
	elif t[: len(vector)] == vector:
		partial_type = t[len(vector) :]
		true_type = ""
		count = 0
		for k, c in enumerate(partial_type):
			if c == "," and count == 0:
				true_type = partial_type[:k]
			elif c == "<":
				count += 1
			elif c == ">":
				count -= 1
		data = save_type("int", len(value), type_sizes, component_data)
		for v in value:
			data += save_type(true_type, v, type_sizes, component_data)
	elif t == string or t == "string":
		data = save_type("int", len(value), type_sizes, component_data) + value.encode()
	elif t == "UintArrayInline" or t == "struct UintArrayInline":
		data = save_type("int", len(value), type_sizes, component_data)
		for v in value:
			data += save_type("uint32", v, type_sizes, component_data)
	elif t[-4:] == "Enum":
		data = save_type("uint32", value, type_sizes, component_data)
	elif t == "struct SpriteStains *":
		pass
	else:
		if t in object_map.keys():
			for field in object_map[t]:
				print(field)
				data += save_type(field[1], value[field[0]], type_sizes, component_data)
			return data
		raise Exception("unknown type: " + t)
	return data


def save_component(
	component: Component, type_sizes: dict[str, int], component_data: ComponentData
) -> bytes:
	data = b""
	component_type = component.name
	data += struct.pack("i", len(component_type))[::-1]
	data += component_type.encode()
	data += component.not_deleted_maybe
	data += struct.pack("b", component.enabled)
	tags = ",".join(component.tags)
	data += struct.pack("i", len(tags))[::-1]
	data += tags.encode()
	component_fields = component_data[component_type]
	for field in component_fields:
		ty = field.typename
		data += save_type(ty, component.fields[field.field], type_sizes, component_data)

	return data


def save_entity(entity: Entity, type_sizes, component_data) -> bytes:
	data = b""
	data += struct.pack("i", len(entity.name))[::-1]
	data += entity.name.encode()
	data += entity.deleted_maybe
	data += struct.pack("i", len(entity.path))[::-1]
	data += entity.path.encode()
	tags = ",".join(entity.tags)
	data += struct.pack("i", len(tags))[::-1]
	data += tags.encode()
	data += struct.pack("f", entity.x)[::-1]
	data += struct.pack("f", entity.y)[::-1]
	data += struct.pack("f", entity.size_x)[::-1]
	data += struct.pack("f", entity.size_y)[::-1]
	data += struct.pack("f", entity.rotation)[::-1]
	data += struct.pack("i", len(entity.components))[::-1]
	for component in entity.components:
		data += save_component(component, type_sizes, component_data)
	data += struct.pack("i", len(entity.children))[::-1]
	for child in entity.children:
		save_entity(child, type_sizes, component_data)
	return data


def save(entities: list[Entity], schema: str) -> bytes:
	data = b""
	if len(entities) == 0:
		data += b"\x00\x02\x00\x20"
		data += b"\x00\x00\x00\x00"
		data += (
			b"\x00" * 0x24
		)  # ?? maybe hash of 00 00, and entity count of 0? 0x20 + 0x04 = 0x24
		return data
	data += b"\x00\x00\x00\x02"
	data += b"\x00\x00\x00\x20"
	data += schema.encode()
	data += struct.pack("i", len(entities))[::-1]
	type_sizes, component_data = get_schema_data(schema.encode())
	for entity in entities:
		data += save_entity(entity, type_sizes, component_data)
	return data


if __name__ == "__main__":
	path = sys.argv[1]
	entities = []
	if os.path.isdir(path):
		files = os.listdir(path)
		files = [x for x in files if "entities" in x]
		entities = []
		for file in files:
			compressed_data = open(path + file, "rb").read()

			try:
				parsed = parse_data(compressed_data)
			except Exception as e:
				raise Exception("Error in file " + file) from e

			entities += parsed
	else:
		entities = parse_data(open(path, "rb").read())
	open("output.json", "w").write(
		json.dumps({"entities": entities}, default=lambda x: x.__dict__)
	)
	open("saved", "wb").write(save(entities, "c8ecfb341d22516067569b04563bff9c"))
