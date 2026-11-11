import cv2
import numpy as np

img = cv2.imread('IMG_2472.jpeg')
img_upright = cv2.rotate(img, cv2.ROTATE_90_COUNTERCLOCKWISE)
gray = cv2.cvtColor(img_upright, cv2.COLOR_BGR2GRAY)
h, w = gray.shape

# 1. Clean background using fast downscaled Gaussian blur
small = cv2.resize(gray, (w // 4, h // 4))
bg_small = cv2.GaussianBlur(small, (31, 31), 0)
bg = cv2.resize(bg_small, (w, h))
norm = cv2.divide(gray, bg, scale=255)

# Ink threshold using adaptive on gray
ink = cv2.adaptiveThreshold(norm, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY_INV, 31, 10)

# Clear borders (~3%)
m_x = max(2, int(w * 0.03))
m_y = max(2, int(h * 0.03))
ink[:m_y, :] = 0; ink[-m_y:, :] = 0; ink[:, :m_x] = 0; ink[:, -m_x:] = 0

# 2. Line detection (dimension frame + leader line)
edges = cv2.Canny(norm, 50, 150)
lines = cv2.HoughLinesP(edges, 1, np.pi / 180, threshold=50, minLineLength=35, maxLineGap=12)
line_mask = np.zeros_like(ink)
if lines is not None:
    for x1, y1, x2, y2 in lines.reshape(-1, 4):
        angle = abs(np.arctan2(float(y2 - y1), float(x2 - x1)) * 180.0 / np.pi)
        length = np.hypot(x2 - x1, y2 - y1)
        is_dim = (angle < 12 or angle > 168 or abs(angle - 90) < 12)
        # Leader line to pocket
        is_leader = (min(x1, x2) < w * 0.45 and max(y1, y2) > h * 0.60 and length > 25)
        if is_dim or is_leader:
            cv2.line(line_mask, (int(x1), int(y1)), (int(x2), int(y2)), 255, 3)

# Filter clutter: remove barcode, small text, and lines
clean_ink = ink.copy()
clean_ink[line_mask == 255] = 0

ret, labels, stats, _ = cv2.connectedComponentsWithStats(clean_ink, connectivity=8)
filtered_ink = np.zeros_like(clean_ink)
for i in range(1, ret):
    area = stats[i, cv2.CC_STAT_AREA]
    bx = stats[i, cv2.CC_STAT_LEFT]
    by = stats[i, cv2.CC_STAT_TOP]
    bw = stats[i, cv2.CC_STAT_WIDTH]
    bh = stats[i, cv2.CC_STAT_HEIGHT]
    if area < 30:
        continue
    # Barcode
    if (bx > w * 0.85 or by > h * 0.85 or bx < w * 0.15 or by < h * 0.15) and max(bw, bh) / (min(bw, bh) + 1e-3) > 7:
        continue
    filtered_ink[labels == i] = 255

# 3. Outer outline
k_close = max(5, int(max(h, w) * 0.012)) | 1
closed = cv2.morphologyEx(filtered_ink, cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k_close, k_close)))

flood = closed.copy()
f_mask = np.zeros((h + 2, w + 2), np.uint8)
cv2.floodFill(flood, f_mask, (0, 0), 128)
enclosed = (flood != 128).astype(np.uint8) * 255

# Prune spurs (like the leader line tip) with morph open
pruned = cv2.morphologyEx(enclosed, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (7, 7)))

conts, _ = cv2.findContours(pruned, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
valid = [c for c in conts if cv2.contourArea(c) > 2000 and cv2.contourArea(c) / (cv2.boundingRect(c)[2] * cv2.boundingRect(c)[3]) < 0.94]
outline = max(valid, key=cv2.contourArea)

outline_mask = np.zeros((h, w), np.uint8)
cv2.drawContours(outline_mask, [outline], -1, 255, -1)

# 4. Pocket detection:
# Inside outline mask, look at raw ink
bbox = cv2.boundingRect(outline)
bw, bh = bbox[2], bbox[3]
erode_r = max(4, int(min(bw, bh) * 0.035))
inner_mask = cv2.erode(outline_mask, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (erode_r * 2 + 1, erode_r * 2 + 1)))

ink_inside = cv2.bitwise_and(ink, inner_mask)

# Density blur
k_dens = max(11, int(min(bw, bh) * 0.07)) | 1
density = cv2.GaussianBlur(ink_inside.astype(np.float32), (k_dens, k_dens), 0)
max_d = float(np.max(density))

print('Outline area:', cv2.contourArea(outline), 'Max pocket density:', max_d)

if max_d > 8.0:
    # Threshold density
    thresh_d = max(5.0, 0.22 * max_d)
    p_mask = (density > thresh_d).astype(np.uint8) * 255
    k_pclose = max(11, int(min(bw, bh) * 0.08)) | 1
    p_closed = cv2.morphologyEx(p_mask, cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k_pclose, k_pclose)))
    pf = p_closed.copy()
    pf_mask = np.zeros((h + 2, w + 2), np.uint8)
    cv2.floodFill(pf, pf_mask, (0, 0), 128)
    p_filled = (pf != 128).astype(np.uint8) * 255
    p_conts, _ = cv2.findContours(p_filled, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
    pocket = max(p_conts, key=cv2.contourArea)
    print('Pocket area:', cv2.contourArea(pocket))

    vis = img_upright.copy()
    cv2.drawContours(vis, [outline], -1, (0, 255, 0), 2)
    cv2.drawContours(vis, [pocket], -1, (0, 0, 255), 2)
    cv2.imwrite('tuned_result.png', vis)
    print('Saved tuned_result.png!')
