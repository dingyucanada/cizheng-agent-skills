"""Display-oriented image derivatives with reversible normalized coordinates."""
import hashlib
import io
import math

from PIL import Image, ImageOps

PREPROCESS = 'exif-display-rgb-overview1536-region2048-jpeg92-v2'
DISPLAY_TO_FILE = {
    1: [1, 0, 0, 0, 1, 0], 2: [-1, 0, 1, 0, 1, 0],
    3: [-1, 0, 1, 0, -1, 1], 4: [1, 0, 0, 0, -1, 1],
    5: [0, 1, 0, 1, 0, 0], 6: [0, 1, 0, -1, 0, 1],
    7: [0, -1, 1, -1, 0, 1], 8: [0, -1, 1, 1, 0, 0],
}


def derivative(raw, media_id, region=None):
    with Image.open(io.BytesIO(raw)) as source:
        orientation = source.getexif().get(274, 1)
        if orientation not in DISPLAY_TO_FILE:
            orientation = 1
        original_size = source.size
        image = ImageOps.exif_transpose(source).convert('RGB')
        display_width, display_height = image.size
        bounds = [0, 0, display_width, display_height]
        if region is not None:
            if len(region) != 4 or not all(math.isfinite(x) for x in region):
                raise ValueError('区域必须为有限的四个坐标')
            x0, y0, x1, y1 = region
            if not (0 <= x0 < x1 <= 1 and 0 <= y0 < y1 <= 1):
                raise ValueError('区域越界或面积无效')
            bounds = [math.floor(x0*display_width), math.floor(y0*display_height),
                      math.ceil(x1*display_width), math.ceil(y1*display_height)]
            image = image.crop(tuple(bounds))
        actual_region = [bounds[0]/display_width, bounds[1]/display_height,
                         bounds[2]/display_width, bounds[3]/display_height]
        crop_size = image.size
        image.thumbnail((2048, 2048) if region else (1536, 1536))
        stream = io.BytesIO()
        image.save(stream, format='JPEG', quality=92)
        data = stream.getvalue()
        metadata = {'media_id': media_id, 'original_sha256': hashlib.sha256(raw).hexdigest(),
                    'derived_sha256': hashlib.sha256(data).hexdigest(), 'width': image.width,
                    'height': image.height, 'original_width': original_size[0], 'original_height': original_size[1],
                    'display_width': display_width, 'display_height': display_height,
                    'exif_orientation': orientation, 'display_to_file_normalized': DISPLAY_TO_FILE[orientation],
                    'display_region': actual_region, 'crop_pixels': bounds,
                    'downsampled': image.size != crop_size, 'preprocess': PREPROCESS}
        return data, metadata


def region_to_display(local, bounds):
    x0, y0, x1, y1 = bounds
    return [x0+local[0]*(x1-x0), y0+local[1]*(y1-y0),
            x0+local[2]*(x1-x0), y0+local[3]*(y1-y0)]
