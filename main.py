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

from data import object_map

fastlz = ctypes.cdll.LoadLibrary("./fastlz.so")


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


@dataclass
class Component:
	name: str
	tags: list[str]
	fields: dict[str, Any]
	enabled: bool


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


def parse_entity(reader: Reader, type_sizes, component_data, child_counts):
	name_len = reader.read_be(4)
	name = bstr(reader.read_bytes(name_len))
	reader.assertion(1, b"\x00", "entity null expected")  # 0x00
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
	entity = Entity(name, path, tag, x, y, scale_x, scale_y, rotation, [], [])
	for _ in range(maybe_num_comps):
		entity.components.append(parse_component(reader, type_sizes, component_data))
	child_counts.append(reader.read_be(4))
	return entity


def bstr(a: bytes) -> str:
	return str(a)[2:-1]


def do_type(reader: Reader, t: str, type_sizes, component_data) -> Any:
	vec2 = "class ceng::math::CVector2<"
	xform = "struct ceng::math::CXForm<"
	lens = "struct LensValue<"
	vector = "class std::vector<"
	string = "class std::basic_string<char,struct std::char_traits<char>,class std::allocator<char> >"
	if t == "bool":  # for errors
		data = reader.read_bool()
	elif t == "float":
		data = struct.unpack("f", reader.read_bytes(4)[::-1])[0]
	elif t == "double":
		data = struct.unpack("d", reader.read_bytes(8)[::-1])[0]
	elif t == "int" or t == "int32":
		data = struct.unpack("i", reader.read_bytes(4)[::-1])[0]
	elif t == "__int64":
		data = struct.unpack("l", reader.read_bytes(8)[::-1])[0]
	elif t == "unsigned int" or t == "uint32":
		data = struct.unpack("I", reader.read_bytes(4)[::-1])[0]
	elif t == "unsigned __int64":
		data = struct.unpack("L", reader.read_bytes(8)[::-1])[0]
	elif t == "unsigned short":
		data = struct.unpack("H", reader.read_bytes(2)[::-1])[0]
	elif t[: len(vec2)] == vec2:
		true_type = t[len(vec2) : -1]
		data = (
			do_type(reader, true_type, type_sizes, component_data),
			do_type(reader, true_type, type_sizes, component_data),
		)
	elif t[: len(lens)] == lens:
		true_type = t[len(lens) : -1]

		data = do_type(reader, true_type, type_sizes, component_data)
		do_type(reader, true_type, type_sizes, component_data)
		do_type(reader, "int", type_sizes, component_data)
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


def parse_component(reader: Reader, type_sizes, component_data) -> Component:
	component_name_len = reader.read_be(4)
	component_name = bstr(reader.read_bytes(component_name_len))
	reader.assertion(1, b"\x01", "1 in component")  # first is ??? second is enabled
	enabled = reader.read_bool()
	component_tag_len = reader.read_be(4)
	component_tags = bstr(reader.read_bytes(component_tag_len))
	fields = component_data[component_name]
	data = {}
	for field in fields:
		# print(field.field, field.typename, hex(reader.ptr), end=" ")
		data[field.field] = do_type(reader, field.typename, type_sizes, component_data)
		# print(data[field.field])
	return Component(component_name, component_tags.split(","), data, enabled)


def parse_data(compressed_data, file):
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
	type_sizes = {}
	component_data = {}
	if hash != b"":
		schema_content = open(
			"/home/nathan/Documents/code/noitadata/data/schemas/"
			+ str(hash)[2:-1]
			+ ".xml",
			"r",
		).read()

		def fix(s):
			os = s
			s = re.sub(r'("[^\n]*)>([^\n]*")', r"\1&gt;\2", s)
			s = re.sub(r'("[^\n]*)<([^\n]*")', r"\1&lt;\2", s)
			if s == os:
				return s
			return fix(s)

		component_data: dict[str, list[ComponentFieldData]] = {}
		type_sizes: dict[str, int] = {}

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

	maybe_num_entities = data_reader.read_be(4)

	root = Entity("root", "??", [], 0, 0, 1, 1, 0, [], [])
	child_counts = [maybe_num_entities]
	entities = [root]
	# for _ in range(maybe_num_entities):
	# 	entities.append(
	# 		parse_entity(data_reader, type_sizes, component_data, child_counts)
	# 	)
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


if __name__ == "__main__":
	path = sys.argv[1]
	files = os.listdir(path)
	files = [x for x in files if "entities" in x]
	entities = []
	for file in files:
		compressed_data = open(path + file, "rb").read()

		parsed = parse_data(compressed_data, file)

		entities += parsed
	print(json.dumps({"entities": entities}, default=lambda x: x.__dict__))
