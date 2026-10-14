import cv2, numpy as np, subprocess, sys, math
from PIL import Image, ImageDraw, ImageFont, ImageFilter
SRC, OUT = sys.argv[1], sys.argv[2]
PREVIEW = len(sys.argv) > 3
TEXT = "現在はAIとDXの支援を中心に"
F0, F1 = 574, 687                     # original display frames (inclusive) - unchanged
BX0, BY0, BX1, BY1 = 364, 920, 1548, 1004  # original ink bbox
W, H = 1920, 1080
SS = 2                                 # supersampling
FONT = "/usr/share/fonts/opentype/noto/NotoSansCJK-Black.ttc"

# ---- fit font size so ink bbox width matches original ----
def ink_bbox(size):
    f = ImageFont.truetype(FONT, size, index=0)
    return f, f.getbbox(TEXT)
tw = (BX1 - BX0) * SS
lo, hi = 20, 400
while lo < hi:
    m = (lo + hi + 1) // 2
    _, bb = ink_bbox(m)
    if bb[2] - bb[0] <= tw: lo = m
    else: hi = m - 1
font, bb = ink_bbox(lo)
ink_w, ink_h = bb[2]-bb[0], bb[3]-bb[1]
cx, cy = (BX0+BX1)/2*SS, (BY0+BY1)/2*SS
ox, oy = cx - ink_w/2 - bb[0], cy - ink_h/2 - bb[1]
print("font size", lo/SS, "ink", ink_w/SS, ink_h/SS)

CW, CH = W*SS, H*SS
def text_mask(stroke):
    im = Image.new("L", (CW, CH), 0)
    ImageDraw.Draw(im).text((ox, oy), TEXT, font=font, fill=255, stroke_width=stroke, stroke_fill=255)
    return im

fill_m   = text_mask(0)
inner_m  = text_mask(5*SS)    # deep crimson edge
white_m  = text_mask(10*SS)   # white band
outer_m  = text_mask(13*SS)   # navy outline
def solid(rgb, mask):
    im = Image.new("RGBA", (CW, CH), rgb + (0,)); im.putalpha(mask); return im

# gold vertical gradient fill with a gloss line
top, bot = int(oy+bb[1]), int(oy+bb[3])
grad = np.zeros((CH, CW, 3), np.float32)
ys = np.clip((np.arange(CH) - top) / max(1, bot-top), 0, 1)[:, None]
c1, c2, c3 = np.array([255,252,214]), np.array([255,214,64]), np.array([245,140,10])
g = np.where(ys < 0.5, c1 + (c2-c1)*(ys/0.5), c2 + (c3-c2)*((ys-0.5)/0.5))
grad[:] = g[:, None, :]
gloss_y = top + (bot-top)*0.47
grad[int(gloss_y):int(gloss_y)+2*SS] = [255,240,150]
fill = Image.fromarray(grad.astype(np.uint8)).convert("RGBA"); fill.putalpha(fill_m)

# drop shadow
shadow = solid((0,0,20), outer_m.point(lambda v: v*0.75))
shadow = shadow.transform(shadow.size, Image.AFFINE, (1,0,-6*SS,0,1,-7*SS)).filter(ImageFilter.GaussianBlur(4*SS))

telop = Image.new("RGBA", (CW, CH), (0,0,0,0))
for layer in (shadow, solid((14,28,78), outer_m), solid((255,255,255), white_m),
              solid((150,20,10), inner_m), fill):
    telop = Image.alpha_composite(telop, layer)
telop = telop.resize((W, H), Image.LANCZOS)
tel = np.asarray(telop).astype(np.float32)
tel_rgb = tel[..., [2,1,0]]; tel_a = tel[..., 3:4] / 255.0   # BGR

# soft glow (halo around the telop)
halo = np.asarray(outer_m.resize((W, H), Image.LANCZOS)).astype(np.float32)/255
halo = cv2.dilate(halo, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (9,9)))
halo = 0.55*cv2.GaussianBlur(halo, (0,0), 14) + 0.45*cv2.GaussianBlur(halo, (0,0), 34)
halo = np.clip(halo/ halo.max(), 0, 1)[..., None]
glow_col = np.array([170, 235, 255], np.float32)   # warm light gold (BGR)
G_START, G_PEAK, G_END = F0+6, F0+18, F0+42        # single pulse ~1.2s
PEAK = 0.62
def glow_amt(n):
    if n <= G_START or n >= G_END: return 0.0
    if n <= G_PEAK: t = (n-G_START)/(G_PEAK-G_START); return PEAK*(0.5-0.5*math.cos(math.pi*t))
    t = (n-G_PEAK)/(G_END-G_PEAK); return PEAK*(0.5+0.5*math.cos(math.pi*t))

# region to erase original subtitle (white glyphs + its dark shadow)
RY0, RY1, RX0, RX1 = BY0-14, BY1+20, BX0-14, BX1+20
def process(f, n):
    roi = f[RY0:RY1, RX0:RX1]
    white = (roi.min(axis=2) > 170).astype(np.uint8)
    m = cv2.dilate(white, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5,5)), iterations=2)
    sh = np.zeros_like(m); sh[6:, 6:] = m[:-6, :-6]          # shadow offset
    m = ((m | sh) * 255).astype(np.uint8)
    f[RY0:RY1, RX0:RX1] = cv2.inpaint(roi, m, 6, cv2.INPAINT_TELEA)
    out = f.astype(np.float32)
    a = glow_amt(n)
    if a > 0:   # screen blend
        gl = halo * a * glow_col
        out = 255 - (255-out)*(255-gl)/255
    out = out*(1-tel_a) + tel_rgb*tel_a
    return np.clip(out+0.5, 0, 255).astype(np.uint8)

cap = cv2.VideoCapture(SRC)
if PREVIEW:
    for n in (574, 586, 592, 600, 630, 687, 688):
        cap.set(cv2.CAP_PROP_POS_FRAMES, n); ok, f = cap.read()
        if F0 <= n <= F1: f = process(f, n)
        cv2.imwrite(f"{OUT}_{n}.png", f)
    sys.exit()

enc = subprocess.Popen(["ffmpeg","-v","error","-y","-f","rawvideo","-pix_fmt","bgr24","-s",f"{W}x{H}",
    "-r","30000/1001","-i","-","-i",SRC,"-map","0:v","-map","1:a","-c:v","libx264","-preset","slow",
    "-crf","15","-pix_fmt","yuv420p","-profile:v","high","-c:a","copy","-movflags","+faststart",OUT],
    stdin=subprocess.PIPE)
n = 0
while True:
    ok, f = cap.read()
    if not ok: break
    if F0 <= n <= F1: f = process(f, n)
    enc.stdin.write(f.tobytes()); n += 1
enc.stdin.close(); enc.wait(); print("frames", n)
