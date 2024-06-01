import ctypes
import sys

fastlz = ctypes.cdll.LoadLibrary("./fastlz.so")


class Reader:
	def __init__(self, data: bytes) -> None:
		self.data = data
		self.ptr = 0

	def read_be(self, count: int) -> int:
		val = 0
		self.ptr += count - 1
		for _ in range(count):
			val *= 0x100
			val += self.data[self.ptr]
			self.ptr -= 1
		self.ptr += count + 1
		return val

	def skip(self, count: int):
		self.ptr += count

	def read_bytes(self, count: int) -> bytes:
		v = self.data[self.ptr : self.ptr + count]
		self.skip(count)
		return v


path = sys.argv[1]
compressed_data = open(path, "rb").read()
compressed_reader = Reader(compressed_data)
compressed_size, decompressed_size = compressed_reader.read_be(
	4
), compressed_reader.read_be(4)
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
print("??")
print(data_reader.data[8])
print(data_reader.read_bytes(0x20))
