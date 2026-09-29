"""Composite the actual two Met 18.61.4 photographs into the catalogue scene.

The artifact photographs are scaled with preserved aspect ratio. No object
pixels are generated or retouched. The preceding evidence scene retains a
small matching photograph so a slight speech-duration change cannot leave
the requested 53-second point without the reference object.
"""
from pathlib import Path
import argparse, hashlib, json
from PIL import Image, ImageDraw, ImageFont, ImageOps

FONT='/System/Library/Fonts/Hiragino Sans GB.ttc'

def photo(canvas,path,box):
    im=Image.open(path).convert('RGB')
    im=ImageOps.contain(im,(box[2]-box[0],box[3]-box[1]),Image.Resampling.LANCZOS)
    canvas.paste(im,(box[0]+(box[2]-box[0]-im.width)//2,
                     box[1]+(box[3]-box[1]-im.height)//2))

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--scene-root',type=Path,required=True)
    p.add_argument('--baseline-scenes',type=Path,required=True)
    p.add_argument('--photos',type=Path,required=True)
    p.add_argument('--font',default=FONT)
    a=p.parse_args();a.scene_root.mkdir(parents=True,exist_ok=True)
    photos=[a.photos/'met-48607.jpg',a.photos/'met-48607-view2.jpg']
    im=Image.open(a.baseline_scenes/'02-scenarios.png').convert('RGB')
    d=ImageDraw.Draw(im);d.rectangle((92,180,1600,386),fill='#F5F3EA')
    serif=Path('/System/Library/Fonts/Supplemental/Songti.ttc')
    title_font=ImageFont.truetype(str(serif) if serif.exists() else a.font,65)
    d.text((96,193),'器物研究',font=title_font,fill='#173147')
    d.text((96,279),'状况记录　来源复核',font=title_font,fill='#173147')
    im.save(a.scene_root/'02-scenarios.png')
    # Use the reviewed plain-language title, with both original object
    # photographs and their shared collection identifier alongside it.
    im=Image.open(a.baseline_scenes/'06-catalogue.png').convert('RGB')
    font=lambda n:ImageFont.truetype(a.font,n)
    title=lambda n:ImageFont.truetype(str(serif) if serif.exists() else a.font,n)
    d=ImageDraw.Draw(im)
    d.rectangle((92,191,1005,475),fill='#F5F3EA')
    d.text((96,296),'馆藏资料',font=title(82),fill='#173147',anchor='ls')
    d.text((96,408),'先核对具体器物',font=title(82),fill='#173147',anchor='ls')
    d.rectangle((94,713,1000,835),fill='#F5F3EA')
    d.text((99,753),'先核对照片与馆藏编号，再比较',font=font(29),fill='#617381',anchor='ls')
    d.text((99,806),'器物特征和资料。',font=font(29),fill='#617381',anchor='ls')
    d.rectangle((1022,205,1830,854),fill='#FFFFFF')
    d.text((1055,231),'同一件器物 · 两个视角',font=font(30),fill='#22577C')
    for src,box in zip(photos,[(1055,285,1415,762),(1450,285,1810,762)]):
        d.rectangle(box,fill='#E9E7DF');photo(im,src,box)
    d=ImageDraw.Draw(im)
    d.text((1055,778),'正面原图',font=font(25),fill='#617381')
    d.text((1450,778),'另一面原图',font=font(25),fill='#617381')
    d.text((1055,819),'The Met · 18.61.4 · 公开馆藏 CC0',font=font(27),fill='#173147')
    im.save(a.scene_root/'06-catalogue.png')
    # This inset occupies unused lower-left space, without covering the
    # actual evidence interface, its title, or the permanent material label.
    im=Image.open(a.baseline_scenes/'05-read.png').convert('RGB')
    d=ImageDraw.Draw(im);d.rectangle((95,739,495,872),fill='#1A3B52')
    photo(im,photos[0],(106,744,188,868))
    d=ImageDraw.Draw(im)
    d.text((205,773),'参照对象 18.61.4',font=font(23),fill='#C7A977')
    d.text((205,816),'原图与出处一起核对',font=font(22),fill='#B8C7CF')
    im.save(a.scene_root/'05-read.png')
    im=Image.open(a.baseline_scenes/'18-closing.png').convert('RGB')
    d=ImageDraw.Draw(im);d.rectangle((90,276,956,585),fill='#102A3D')
    d.text((96,386),'原图出处可追溯',font=title(91),fill='#F5F3EA',anchor='ls')
    d.text((96,522),'判断理由可核查',font=title(91),fill='#F5F3EA',anchor='ls')
    d.rectangle((95,669,951,753),fill='#102A3D')
    d.text((101,729),'完整图文报告、源码和公开演示，入口在主页。',font=font(34),fill='#B8C7CF',anchor='ls')
    im.save(a.scene_root/'18-closing.png')
    receipt={'object_id':'Met 18.61.4','source_object_url':'https://www.metmuseum.org/art/collection/search/48607','scope':'CC0 public collection reference object, not an unknown object authentication',
             'photos':[{'path':x.name,'sha256':hashlib.sha256(x.read_bytes()).hexdigest()}for x in photos],
             'modified_scenes':['02-scenarios','05-read','06-catalogue','18-closing'],'operation':'User-approved scenario headings without periods, plain-language catalogue and closing titles; aspect-ratio-preserving photo compositing; no object retouching or generation'}
    (a.scene_root.parent/'photo-compositing-receipt.json').write_text(json.dumps(receipt,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps(receipt,ensure_ascii=False))

if __name__=='__main__':main()
