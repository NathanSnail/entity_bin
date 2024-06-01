import ctypes
import struct
import sys

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
			print(x)
			val += bytes([x])

	def skip(self, count: int):
		self.ptr += count

	def read_bytes(self, count: int) -> bytes:
		v = self.data[self.ptr : self.ptr + count]
		self.skip(count)
		return v


path = sys.argv[1]
compressed_data = open(path, "rb").read()
compressed_reader = Reader(compressed_data)
compressed_size, decompressed_size = compressed_reader.read_le(
	4
), compressed_reader.read_le(4)
print(compressed_size, decompressed_size)
input_buffer = ctypes.create_string_buffer(
	compressed_data[compressed_reader.ptr :], compressed_size
)
output_buffer = ctypes.create_string_buffer(decompressed_size)
fastlz.fastlz_decompress.restype = ctypes.c_int32
fastlz.fastlz_decompress(
	input_buffer, compressed_size, output_buffer, decompressed_size
)
decompressed = b"".join([x for x in output_buffer])
print(decompressed)
open("./out", "wb").write(decompressed)
data_reader = Reader(decompressed)
data_reader.skip(8)
hash = data_reader.read_bytes(0x20)
print(hash)
unknown = data_reader.read_be(4)
name_len = data_reader.read_be(4)
name = data_reader.read_bytes(name_len)
data_reader.skip(1)
print(name)
path_len = data_reader.read_be(4)
path = data_reader.read_bytes(path_len)
print(path)
tag_len = data_reader.read_be(4)
tag = data_reader.read_bytes(tag_len)
print(tag)
x = data_reader.read_float()
y = data_reader.read_float()
scale_x = data_reader.read_float()
scale_y = data_reader.read_float()
rotation = data_reader.read_float()
print(x, y, scale_x, scale_y, rotation)
unknown = data_reader.read_be(4)
component_name_len = data_reader.read_be(4)
component_name = data_reader.read_bytes(component_name_len)
print(component_name)
data_reader.skip(2)
component_tag_len = data_reader.read_be(4)
