import os
windows = os.name == "nt"
if windows:
	schema_path = "C:/Program Files (x86)/Steam/steamapps/common/Noita/data/schemas/"
else:
	schema_path = "~/.local/share/Steam/steamapps/common/Noita/data/schemas/"
