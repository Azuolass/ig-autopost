"""Download one Drive image by date/slot/number, report what it is, try to repair it."""
import io, json, sys
from datetime import date
from pathlib import Path
from PIL import Image, ImageFile
from autopost import drive

day, slot, num = date.fromisoformat(sys.argv[1]), int(sys.argv[2]), int(sys.argv[3])
d = drive.Drive()
month = drive.find_month_folder(d.list_children(drive.root_folder_id()), day)
folder, _ = drive.find_day_folder(d.list_children(month.id), day)
pf = drive.find_post_folder(d.list_children(folder.id), slot)
files = d.list_children(pf.id)
f = next(x for x in files if drive.leading_number(x.name) == num and x.mime.startswith("image/"))
meta = d.s.get(f"{drive.API}/files/{f.id}", params={**d._params, "fields": "name,mimeType,size,md5Checksum,modifiedTime", "supportsAllDrives": "true"}).json()
data = d.download(f.id)
out = Path("out"); out.mkdir(exist_ok=True)
(out / "raw.bin").write_bytes(data)
info = {"meta": meta, "downloaded": len(data), "head": data[:16].hex(), "tail": data[-16:].hex()}
for strict in (True, False):
    ImageFile.LOAD_TRUNCATED_IMAGES = not strict
    try:
        im = Image.open(io.BytesIO(data)); fmt = im.format; im = im.convert("RGB")
        im.save(out / f"repaired_{'strict' if strict else 'loose'}.png")
        info[f"open_{'strict' if strict else 'loose'}"] = f"ok {fmt} {im.size}"
    except Exception as e:
        info[f"open_{'strict' if strict else 'loose'}"] = f"fail {e}"
(out / "info.json").write_text(json.dumps(info, indent=2))
print(json.dumps(info, indent=2))
