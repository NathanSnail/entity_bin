import ctypes
import re
import struct
import sys
import xml.dom.minidom
from typing import Any
from xml.dom.minidom import parseString

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

	def read_null_term(self) -> bytes:
		val = b""
		while True:
			x = self.data[self.ptr]
			self.ptr += 1
			if x == 0x00:
				return val
			val += bytes([x])

	def skip(self, count: int):
		self.ptr += count

	def read_bytes(self, count: int) -> bytes:
		v = self.data[self.ptr : self.ptr + count]
		self.skip(count)
		return v


class ComponentFieldData:
	size: int
	typename: str
	field: str
	variable_size: list[int]


class Component:
	name: str
	tags: list[str]
	fields: dict[str, Any]


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


path = sys.argv[1]
compressed_data = open(path, "rb").read()
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
data_reader.skip(8)
hash = data_reader.read_bytes(0x20)
schema_content = open(
	"/home/nathan/Documents/code/noitadata/data/schemas/" + str(hash)[2:-1] + ".xml",
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
		var_size = child.getAttribute("size")
		var_type = child.getAttribute("type")
		var_variable_size = []
		if "<" in var_type:
			var_special_t = var_type.split(" ")[1].split("<")[0]
			if var_special_t == "std::basic_string" or var_special_t == "std::vector":
				var_variable_size = [0]
				var_size = "0"
			if var_special_t == "class ConfigExplosion":
				print("??")
				var_variable_size = [5]

		data = ComponentFieldData()
		data.typename = var_type
		data.field = var_name
		data.size = int(var_size)
		data.variable_size = var_variable_size
		v.append(data)
		if not var_variable_size:
			type_sizes[var_type] = data.size

maybe_num_entities = data_reader.read_be(4)


def parse_entity(reader: Reader):
	name_len = reader.read_be(4)
	name = bstr(reader.read_bytes(name_len))
	print("N", name)
	reader.skip(1)  # 0x00
	path_len = reader.read_be(4)
	path = bstr(reader.read_bytes(path_len))
	print("!", path)
	tag_len = reader.read_be(4)
	tag = bstr(reader.read_bytes(tag_len)).split(",")
	x = reader.read_float()
	y = reader.read_float()
	scale_x = reader.read_float()
	scale_y = reader.read_float()
	rotation = reader.read_float()
	maybe_num_comps = reader.read_be(4)
	entity = Entity()
	entity.name = name
	entity.path = path
	entity.tags = tag
	entity.x = x
	entity.y = y
	entity.size_y = scale_x
	entity.size_y = scale_y
	entity.rotation = rotation
	entity.components = []
	for _ in range(maybe_num_comps):
		entity.components.append(parse_component(reader))
	return entity


def bstr(a):
	return str(a)[2:-1]


def do_type(data, t, f):
	vec2 = "class ceng::math::CVector2<"
	if t == "bool":
		data = data == b"\x01"
	elif t == "float":
		data = struct.unpack("f", data[::-1])[0]
	elif t == "int":
		data = struct.unpack("i", data[::-1])[0]
	elif t[: len(vec2)] == vec2:
		true_type = t[len(vec2) : -1]
		true_size = type_sizes[true_type]
		data = (
			do_type(data[:true_size], true_type, f),
			do_type(data[true_size:], true_type, f),
		)
	return data


def parse_component(reader: Reader) -> Component:
	comp = Component()
	component_name_len = reader.read_be(4)
	component_name = bstr(reader.read_bytes(component_name_len))
	reader.skip(2)  # 0x0101
	component_tag_len = reader.read_be(4)
	component_tags = bstr(reader.read_bytes(component_tag_len))
	fields = component_data[component_name]
	data = {}
	for field in fields:
		look_size = field.size
		print(field.field, look_size, field.typename, hex(reader.ptr))
		start = reader.ptr
		eaten = 0
		val = b""
		for offset in field.variable_size:
			print(offset)
			val += reader.read_bytes((offset + start + eaten) - reader.ptr)
			to_skip = reader.read_be(4)
			eaten += to_skip
			scale = reader.read_bytes(to_skip)
			print(scale)
			val += scale
		if len(field.variable_size) == 0:
			val = reader.read_bytes(look_size)
		data[field.field] = do_type(val, field.typename, field.field)
		print(field.field, data[field.field])
	comp.fields = data
	comp.name = component_name
	comp.tags = component_tags.split(",")
	return comp


for _ in range(maybe_num_entities):
	parse_entity(data_reader)
	data_reader.skip(4)  # ???
	print(data_reader.data[data_reader.ptr :])
