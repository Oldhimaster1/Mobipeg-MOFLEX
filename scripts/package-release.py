"""Produce split hosted downloads and one complete source ZIP (no private input media)."""
from pathlib import Path
import zipfile,shutil
root=Path(__file__).resolve().parent.parent;out=root/'dist/downloads';out.mkdir(parents=True,exist_ok=True)
def eligible(p):
 rel=p.relative_to(root);parts=rel.parts
 return p.is_file() and not any(x in ['.git','.build','.build-linux','local','node_modules','test-results','playwright-report','__pycache__'] for x in parts) and not(rel.parts[:2]==('dist','downloads')) and not(rel.parts[:2]==('reports','outputs')) and p.suffix not in ['.bak','.pyc']
files=sorted(p for p in root.rglob('*')if eligible(p))
def make(path,paths):
 with zipfile.ZipFile(path,'w',zipfile.ZIP_DEFLATED,compresslevel=6)as z:
  for p in paths:z.write(p,p.relative_to(root))
 print(path,path.stat().st_size)
make(out/'MobiPEG_V15_Native_Source.zip',[p for p in files if p.relative_to(root).parts[0]=='native'])
make(out/'MobiPEG_Web_App_and_WASM.zip',[p for p in files if p.relative_to(root).parts[0]!='native'])
make(out/'MobiPEG_Web_Validation.zip',[p for p in files if p.relative_to(root).parts[0]=='reports'])
for name,target in [('anime-full','Anime_Web_V15.moflex'),('avatar-full-3d','Avatar_3D_Web_V15.moflex'),('yip-full','Yip_Web_V15.moflex')]:shutil.copyfile(root/f'reports/outputs/{name}-wasm.moflex',out/target)
make(root.parent/'MobiPEG_Web_V15_Complete_Source_and_WASM.zip',files)
