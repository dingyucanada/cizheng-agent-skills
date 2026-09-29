"""Replace the user-disapproved corner motto in all fixed scene images."""
from pathlib import Path
import argparse,hashlib,json
from PIL import Image,ImageDraw,ImageFont
p=argparse.ArgumentParser(description=__doc__)
p.add_argument('--scene-root',type=Path,required=True)
p.add_argument('--font',default='/System/Library/Fonts/Hiragino Sans GB.ttc')
a=p.parse_args();font=ImageFont.truetype(a.font,25);rows=[]
for path in sorted(a.scene_root.glob('*.png')):
    im=Image.open(path).convert('RGB');bg=im.getpixel((1410,25))
    foreground='#617381'if sum(bg)>600 else '#B8C7CF'
    d=ImageDraw.Draw(im);d.rectangle((1380,35,1840,95),fill=bg)
    d.text((1435,75),'从材料出发，让判断有据。',font=font,anchor='ls',fill=foreground)
    im.save(path)
    rows.append({'scene':path.name,'sha256':hashlib.sha256(path.read_bytes()).hexdigest()})
assert len(rows)==18
(a.scene_root.parent/'motto-revision.json').write_text(json.dumps({'motto':'从材料出发，让判断有据。','scenes':rows},ensure_ascii=False,indent=2)+'\n')
print('Updated the motto consistently in all 18 scene images.')
