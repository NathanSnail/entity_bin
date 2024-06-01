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


path = sys.argv[1]
data = open(path, "rb").read()
reader = Reader(data)
print(data)
compressed_size, decompressed_size = reader.read_be(4), reader.read_be(4)
print(compressed_size, decompressed_size)
input_buffer = ctypes.create_string_buffer(data[reader.ptr :], compressed_size)
output_buffer = ctypes.create_string_buffer(decompressed_size)
print("??")
fastlz.fastlz_decompress.restype = ctypes.c_int32
print(
	fastlz.fastlz_decompress(
		input_buffer, compressed_size, output_buffer, decompressed_size
	)
)
output = b"".join([x for x in output_buffer])
print(output)
