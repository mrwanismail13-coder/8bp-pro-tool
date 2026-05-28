import pygame
import pygame.gfxdraw
import win32gui
import win32con
import win32api
import dxcam
import cv2
import numpy as np
import math
import sys
import time
import keyboard
from filterpy.kalman import KalmanFilter

# ==========================================
# 🚀 1. OpenCV & Performance Optimization
# ==========================================
cv2.setUseOptimized(True)
cv2.setNumThreads(4)

# ==========================================
# ⚙️ 2. Configuration & Hyperparameters
# ==========================================
FPS = 144
BALL_RADIUS = 16  
CUSHION_PADDING = 16

SCREEN_WIDTH = win32api.GetSystemMetrics(0)
SCREEN_HEIGHT = win32api.GetSystemMetrics(1)
TRANSPARENT = (0, 0, 0)

# Colors Palette
WHITE = (255, 255, 255)
BLACK = (0, 0, 0)
YELLOW = (255, 255, 0)
RED = (255, 0, 0)
GREEN = (0, 255, 0)
BLUE = (0, 162, 232)
PINK = (255, 0, 128)
ORANGE = (255, 165, 0)
CYAN = (0, 200, 255)
GUI_BG = (25, 25, 30)      
GUI_TEXT = (240, 240, 240)  
GUI_ACTIVE_COLOR = (0, 162, 232)
GUI_INACTIVE_COLOR = (60, 60, 65)

last_known_mx = SCREEN_WIDTH // 2
last_known_my = SCREEN_HEIGHT // 2

# ==========================================
# 🎛️ 3. GUI Menu State & Custom Controls
# ==========================================
gui_x, gui_y = 50, 50       
gui_w, gui_h = 240, 340       
is_dragging = False          
drag_offset_x = 0
drag_offset_y = 0
is_mouse_hovering_gui = False
window_has_focus = True     
is_hidden = False             

# مفاتيح تشغيل الأنظمة والأزرار
current_power = 100           # 50, 75, 100
line_thickness = 2            # سُمك الخطوط القابل للتعديل
is_cue_detect_enabled = True  # نظام تتبع خط اللعبة والعصا تلقائياً
is_3line_enabled = True       # نظام الجسد الكامل (3 خطوط)
is_multibank_enabled = True   # نظام التنبؤ الشامل (باندات البيضاء والهدف فقط)

# ==========================================
# 🧠 4. Stable Memory & Tracking Systems
# ==========================================
class PermanentWhiteBallMemory:
    def __init__(self):
        self.last_valid_pos = None  

    def update(self, raw_white):
        if raw_white is not None:
            self.last_valid_pos = raw_white
            return raw_white
        return self.last_valid_pos
        
    def manual_lock(self, x, y):
        self.last_valid_pos = (x, y)

class TargetBallManager:
    def __init__(self):
        self.locked_pos = None
        self.kf = None

    def init_kf(self, x, y):
        self.kf = KalmanFilter(dim_x=4, dim_z=2)
        self.kf.x = np.array([x, y, 0., 0.]) 
        self.kf.F = np.array([[1., 0., 1./FPS, 0.],
                             [0., 1., 0., 1./FPS],
                             [0., 0., 1., 0.],
                             [0., 0., 0., 1.]])
        self.kf.H = np.array([[1., 0., 0., 0.],
                             [0., 1., 0., 0.]])
        self.kf.P *= 2.
        self.kf.R *= 0.01  
        self.kf.Q *= 0.005

    def lock_new(self, x, y):
        self.locked_pos = (x, y)
        self.init_kf(x, y)

    def update(self):
        if self.kf is not None and self.locked_pos is not None:
            self.kf.predict()
            self.kf.update(np.array(self.locked_pos))
            return (float(self.kf.x[0]), float(self.kf.x[1]))
        return self.locked_pos

    def clear(self):
        self.locked_pos = None
        self.kf = None

white_memory = PermanentWhiteBallMemory()
target_manager = TargetBallManager()

selected_pocket = 0
table_region = None
last_lock_time = 0
last_white_lock_time = 0
last_hide_toggle_time = 0
last_power_toggle_time = 0

# ==========================================
# 📐 5. Advanced Math & Custom Line Rendering
# ==========================================
def distance(p1, p2):
    return math.hypot(p1[0] - p2[0], p1[1] - p2[1])

def ghost_ball(target, pocket, radius):
    dx = target[0] - pocket[0]
    dy = target[1] - pocket[1]
    dist = math.hypot(dx, dy)
    if dist == 0: return target
    ratio = (dist + radius * 2) / dist
    return (pocket[0] + dx * ratio, pocket[1] + dy * ratio)

def draw_custom_3lines(surface, start, end, radius, is_white_ball=False, ball_color=YELLOW):
    dx = end[0] - start[0]
    dy = end[1] - start[1]
    dist = math.hypot(dx, dy)
    if dist == 0: return

    ux = dx / dist
    uy = dy / dist
    nx = -uy * radius
    ny = ux * radius

    if is_3line_enabled:
        if is_white_ball:
            pygame.draw.line(surface, WHITE, (int(start[0] + nx), int(start[1] + ny)), (int(end[0] + nx), int(end[1] + ny)), line_thickness)
            pygame.draw.line(surface, BLACK, (int(start[0]), int(start[1])), (int(end[0]), int(end[1])), line_thickness)
            pygame.draw.line(surface, WHITE, (int(start[0] - nx), int(start[1] - ny)), (int(end[0] - nx), int(end[1] - ny)), line_thickness)
        else:
            pygame.draw.line(surface, ball_color, (int(start[0] + nx), int(start[1] + ny)), (int(end[0] + nx), int(end[1] + ny)), line_thickness)
            pygame.draw.line(surface, ball_color, (int(start[0]), int(start[1])), (int(end[0]), int(end[1])), line_thickness)
            pygame.draw.line(surface, ball_color, (int(start[0] - nx), int(start[1] - ny)), (int(end[0] - nx), int(end[1] - ny)), line_thickness)
    else:
        main_color = WHITE if is_white_ball else ball_color
        pygame.draw.line(surface, main_color, (int(start[0]), int(start[1])), (int(end[0]), int(end[1])), line_thickness)

def calculate_manual_bank_point(target, pocket, bounds, side, power):
    left, top, right, bottom = bounds
    tx, ty = target
    px, py = pocket

    adjusted_top = top + BALL_RADIUS
    adjusted_bottom = bottom - BALL_RADIUS
    adjusted_left = left + BALL_RADIUS
    adjusted_right = right - BALL_RADIUS

    if power == 100:
        angle_factor = 1.0
    elif power == 75:
        angle_factor = 1.5
    else:
        angle_factor = 2.0 

    if side == 'top':
        dist_y = py - adjusted_top
        mirrored_py = adjusted_top - (dist_y * angle_factor)
        if (mirrored_py - ty) != 0:
            bx = tx + (px - tx) * (adjusted_top - ty) / (mirrored_py - ty)
            if left <= bx <= right: return (bx, adjusted_top)
    elif side == 'bottom':
        dist_y = adjusted_bottom - py
        mirrored_py = adjusted_bottom + (dist_y * angle_factor)
        if (mirrored_py - ty) != 0:
            bx = tx + (px - tx) * (adjusted_bottom - ty) / (mirrored_py - ty)
            if left <= bx <= right: return (bx, adjusted_bottom)
    elif side == 'left':
        dist_x = px - adjusted_left
        mirrored_px = adjusted_left - (dist_x * angle_factor)
        if (mirrored_px - tx) != 0:
            by = ty + (py - ty) * (adjusted_left - tx) / (mirrored_px - tx)
            if top <= by <= bottom: return (adjusted_left, by)
    elif side == 'right':
        dist_x = adjusted_right - px
        mirrored_px = adjusted_right + (dist_x * angle_factor)
        if (mirrored_px - tx) != 0:
            by = ty + (py - ty) * (adjusted_right - tx) / (mirrored_px - tx)
            if top <= by <= bottom: return (adjusted_right, by)
    return None

# ==========================================
# 🖼️ 6. Multi-Radius Scan & Strict Verification
# ==========================================
def detect_table(frame):
    hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
    lower = np.array([30, 40, 40])
    upper = np.array([100, 255, 255])
    mask = cv2.inRange(hsv, lower, upper)
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if contours:
        largest = max(contours, key=cv2.contourArea)
        if cv2.contourArea(largest) > 40000:
            x, y, w, h = cv2.boundingRect(largest)
            return {"left": x, "top": y, "width": w, "height": h}
    return None

def track_game_aim_line_angle(table_img, white_table_pos):
    """
    🔍 نظام مسح متعدد الأقطار ثنائي النطاق (Multi-Radius Multi-Sample Scan):
    يقوم بالبحث الدائري عبر 3 حلقات فحص منفصلة تبدأ من القطر الخارجي للكرة لمنع تجاهل الخط أو سقوطه.
    """
    if white_table_pos is None: return None
    h, w, _ = table_img.shape
    wx, wy = int(white_table_pos[0]), int(white_table_pos[1])
    
    # مسح عبر ثلاث حلقات مختلفة لضمان الإمساك بخط اللعبة الممتد من العصا
    scan_radii = [BALL_RADIUS + 8, BALL_RADIUS + 16, BALL_RADIUS + 24]
    num_samples = 360  
    
    best_angle = None
    max_brightness = 0
    
    for r_scan in scan_radii:
        for i in range(num_samples):
            angle = i * (np.pi / 180.0)
            sx = int(wx + r_scan * math.cos(angle))
            sy = int(wy + r_scan * math.sin(angle))
            
            if 0 <= sx < w and 0 <= sy < h:
                pixel = table_img[sy, sx]
                # حساب شدة سطوع اللون الأبيض الصافي
                brightness = int(pixel[0]) + int(pixel[1]) + int(pixel[2])
                if brightness > 710 and brightness > max_brightness:
                    max_brightness = brightness
                    best_angle = angle
                    
    return best_angle

def get_ball_color_from_roi(roi):
    if roi is None or roi.size == 0: return YELLOW
    avg_bgr = cv2.mean(roi)[:3]
    # تجنب إرجاع درجات الرمادي أو البياض لخط الباند
    if abs(avg_bgr[0] - avg_bgr[1]) < 15 and abs(avg_bgr[1] - avg_bgr[2]) < 15 and avg_bgr[0] > 180:
        return BLUE
    return (int(avg_bgr[2]), int(avg_bgr[1]), int(avg_bgr[0]))

def is_strictly_white_ball(roi):
    """
    🛡️ مصفاة الفحص الصارم (Strict Isolation Filter):
    تفحص نقاء البياض الداخلي بالكامل وتلغي أي كرة مخططة أو كرات تداخل تحتوي على أرقام أو ألوان داكنة.
    """
    if roi is None or roi.size == 0: return False
    hsv = cv2.cvtColor(roi, cv2.COLOR_BGR2HSV)
    
    # فحص صارم لنقاء اللون الأبيض (حساسية منخفضة للتشبع وسقف عالي جداً للسطوع)
    lower_white = np.array([0, 0, 200]) 
    upper_white = np.array([180, 35, 255])
    mask = cv2.inRange(hsv, lower_white, upper_white)
    
    white_ratio = np.sum(mask == 255) / mask.size
    if white_ratio < 0.75: return False 
    
    # فحص خلو المركز من أي نقوش سوداء أو ألوان
    h, w = mask.shape
    center_block = mask[int(h*0.3):int(h*0.7), int(w*0.3):int(w*0.7)]
    center_ratio = np.sum(center_block == 255) / center_block.size
    return center_ratio > 0.92

def find_precise_ball_center_near_mouse(table_img, mouse_table_x, mouse_table_y, search_radius=25):
    h, w, _ = table_img.shape
    min_x = max(0, mouse_table_x - search_radius)
    max_x = min(w, mouse_table_x + search_radius)
    min_y = max(0, mouse_table_y - search_radius)
    max_y = min(h, mouse_table_y + search_radius)
    
    roi = table_img[min_y:max_y, min_x:max_x]
    if roi.size == 0: return None
    
    gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
    blur = cv2.medianBlur(cv2.equalizeHist(gray), 5)
    circles = cv2.HoughCircles(blur, cv2.HOUGH_GRADIENT, dp=1.0, minDist=30, param1=50, param2=15, minRadius=12, maxRadius=20)
    
    if circles is not None:
        circles = np.round(circles[0, :]).astype("int")
        best_circle = min(circles, key=lambda c: math.hypot(c[0] - search_radius, c[1] - search_radius))
        return (min_x + best_circle[0], min_y + best_circle[1])
    return None

# ==========================================
# 🎮 7. Initialize DirectX Overlay & Pygame
# ==========================================
pygame.init()
pygame.font.init()

screen = pygame.display.set_mode((SCREEN_WIDTH, SCREEN_HEIGHT), pygame.NOFRAME)
hwnd = pygame.display.get_wm_info()["window"]

styles = win32gui.GetWindowLong(hwnd, win32con.GWL_EXSTYLE)
win32gui.SetWindowLong(hwnd, win32con.GWL_EXSTYLE, styles | win32con.WS_EX_LAYERED | win32con.WS_EX_TRANSPARENT | win32con.WS_EX_TOPMOST | win32con.WS_EX_NOACTIVATE)
win32gui.SetLayeredWindowAttributes(hwnd, win32api.RGB(*TRANSPARENT), 0, win32con.LWA_COLORKEY)

camera = dxcam.create(output_color="BGR")
camera.start(target_fps=FPS, video_mode=True)
clock = pygame.time.Clock()

pocket_font = pygame.font.SysFont("Arial", 15, bold=True)
gui_font = pygame.font.SysFont("Segoe UI", 10, bold=True)
gui_title_font = pygame.font.SysFont("Segoe UI", 11, bold=True)

running = True

# ==========================================
# 🔄 8. Core Application Loop
# ==========================================
while running:
    clock.tick(FPS)
    
    try:
        mx, my = win32api.GetCursorPos()
        last_known_mx, last_known_my = mx, my
    except Exception:
        mx, my = last_known_mx, last_known_my

    if keyboard.is_pressed("f3") and time.time() - last_power_toggle_time > 0.2:
        current_power = 50
        last_power_toggle_time = time.time()
    elif keyboard.is_pressed("f4") and time.time() - last_power_toggle_time > 0.2:
        current_power = 75
        last_power_toggle_time = time.time()
    elif keyboard.is_pressed("f5") and time.time() - last_power_toggle_time > 0.2:
        current_power = 100
        last_power_toggle_time = time.time()

    if keyboard.is_pressed("ctrl+h") and time.time() - last_hide_toggle_time > 0.3:
        is_hidden = not is_hidden
        last_hide_toggle_time = time.time()

    if not is_hidden:
        is_mouse_hovering_gui = (gui_x <= mx <= gui_x + gui_w) and (gui_y <= my <= gui_y + gui_h)
    else:
        is_mouse_hovering_gui = False

    if is_mouse_hovering_gui and not window_has_focus:
        win32gui.SetWindowLong(hwnd, win32con.GWL_EXSTYLE, styles | win32con.WS_EX_LAYERED | win32con.WS_EX_TOPMOST)
        window_has_focus = True
    elif not is_mouse_hovering_gui and window_has_focus:
        win32gui.SetWindowLong(hwnd, win32con.GWL_EXSTYLE, styles | win32con.WS_EX_LAYERED | win32con.WS_EX_TRANSPARENT | win32con.WS_EX_TOPMOST | win32con.WS_EX_NOACTIVATE)
        window_has_focus = False
        is_dragging = False

    for event in pygame.event.get():
        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            if is_mouse_hovering_gui:
                if (gui_x + 15 <= mx <= gui_x + 80) and (gui_y + 45 <= my <= gui_y + 70): current_power = 50
                elif (gui_x + 85 <= mx <= gui_x + 150) and (gui_y + 45 <= my <= gui_y + 70): current_power = 75
                elif (gui_x + 155 <= mx <= gui_x + 220) and (gui_y + 45 <= my <= gui_y + 70): current_power = 100
                elif (gui_x + 15 <= mx <= gui_x + 225) and (gui_y + 85 <= my <= gui_y + 110): is_cue_detect_enabled = not is_cue_detect_enabled
                elif (gui_x + 15 <= mx <= gui_x + 225) and (gui_y + 120 <= my <= gui_y + 145): is_3line_enabled = not is_3line_enabled
                elif (gui_x + 15 <= mx <= gui_x + 225) and (gui_y + 155 <= my <= gui_y + 180): is_multibank_enabled = not is_multibank_enabled
                elif (gui_x + 140 <= mx <= gui_x + 175) and (gui_y + 200 <= my <= gui_y + 225): line_thickness = max(1, line_thickness - 1)
                elif (gui_x + 185 <= mx <= gui_x + 220) and (gui_y + 200 <= my <= gui_y + 225): line_thickness = min(6, line_thickness + 1)
                elif (gui_x + 15 <= mx <= gui_x + 225) and (gui_y + 250 <= my <= gui_y + 280): is_hidden = True
                elif (gui_x + 15 <= mx <= gui_x + 225) and (gui_y + 290 <= my <= gui_y + 320): running = False
                else:
                    is_dragging = True
                    drag_offset_x = mx - gui_x
                    drag_offset_y = my - gui_y
        elif event.type == pygame.MOUSEBUTTONUP and event.button == 1:
            is_dragging = False

    if is_dragging:
        gui_x = max(0, min(SCREEN_WIDTH - gui_w, mx - drag_offset_x))
        gui_y = max(0, min(SCREEN_HEIGHT - gui_h, my - drag_offset_y))

    if keyboard.is_pressed("ctrl+q"): running = False

    win32gui.SetWindowPos(hwnd, win32con.HWND_TOPMOST, 0, 0, 0, 0, win32con.SWP_NOMOVE | win32con.SWP_NOSIZE | win32con.SWP_NOACTIVATE)
    screen.fill(TRANSPARENT)

    if is_hidden:
        pygame.display.update()
        continue

    frame = camera.get_latest_frame()
    if frame is None: continue

    if table_region is None:
        table_region = detect_table(frame)
        continue

    x, y, w, h = table_region["left"], table_region["top"], table_region["width"], table_region["height"]
    table = frame[y:y+h, x:x+w]
    if table.size == 0: continue

    gray = cv2.cvtColor(table, cv2.COLOR_BGR2GRAY)
    blur = cv2.medianBlur(cv2.equalizeHist(gray), 5)
    circles = cv2.HoughCircles(blur, cv2.HOUGH_GRADIENT, dp=1.0, minDist=30, param1=70, param2=22, minRadius=12, maxRadius=20)

    raw_white_det = None
    detected_target_color = YELLOW

    pockets = [
        (x + 24, y + 24), (x + w // 2, y + 14), (x + w - 24, y + 24),
        (x + 24, y + h - 24), (x + w // 2, y + h - 14), (x + w - 24, y + h - 24)
    ]

    top_band, bottom_band = y + CUSHION_PADDING, y + h - CUSHION_PADDING
    left_band, right_band = x + CUSHION_PADDING, x + w - CUSHION_PADDING
    table_bounds = (left_band, top_band, right_band, bottom_band)

    if circles is not None:
        circles = np.round(circles[0, :]).astype("int")
        for (cx, cy, r) in circles:
            cx_global, cy_global = int(cx + x), int(cy + y)
            if any(distance((cx_global, cy_global), p) < 40 for p in pockets): continue

            roi = table[max(0, cy-r):min(h, cy+r), max(0, cx-r):min(w, cx+r)]
            if is_strictly_white_ball(roi):
                raw_white_det = (cx_global, cy_global)
            
            stable_tgt = target_manager.update()
            if stable_tgt and distance((cx_global, cy_global), stable_tgt) < 20:
                detected_target_color = get_ball_color_from_roi(roi)

    if keyboard.is_pressed("a") and time.time() - last_white_lock_time > 0.15:
        precise_white = find_precise_ball_center_near_mouse(table, mx - x, my - y)
        if precise_white is not None:
            white_memory.manual_lock(int(precise_white[0] + x), int(precise_white[1] + y))
        else:
            white_memory.manual_lock(mx, my)
        last_white_lock_time = time.time()

    stable_white = white_memory.update(raw_white_det)

    if stable_white:
        pygame.gfxdraw.aacircle(screen, int(stable_white[0]), int(stable_white[1]), BALL_RADIUS, WHITE)
        pygame.gfxdraw.aacircle(screen, int(stable_white[0]), int(stable_white[1]), BALL_RADIUS - 2, CYAN)

    if keyboard.is_pressed("z") and time.time() - last_lock_time > 0.15:
        precise_center = find_precise_ball_center_near_mouse(table, mx - x, my - y)
        if precise_center is not None:
            target_manager.lock_new(int(precise_center[0] + x), int(precise_center[1] + y))
        else:
            target_manager.lock_new(mx, my)
        last_lock_time = time.time()

    if keyboard.is_pressed("x"): target_manager.clear()

    stable_target = target_manager.update()

    if stable_target:
        pygame.gfxdraw.aacircle(screen, int(stable_target[0]), int(stable_target[1]), BALL_RADIUS, BLUE)
        pygame.gfxdraw.aacircle(screen, int(stable_target[0]), int(stable_target[1]), BALL_RADIUS - 2, YELLOW)

    for i in range(1, 7):
        if keyboard.is_pressed(str(i)): selected_pocket = i - 1

    for idx, p in enumerate(pockets):
        p_color = GREEN if idx == selected_pocket else RED
        pygame.gfxdraw.aacircle(screen, p[0], p[1], 6, p_color)
        txt = pocket_font.render(f"{idx+1}", True, WHITE if idx == selected_pocket else ORANGE)
        screen.blit(txt, (p[0] - 5, p[1] - 25 if idx < 3 else p[1] + 10))

    # ==========================================
    # 🎯 9. Main Physics & Auto Track Engine
    # ==========================================
    if stable_white and stable_target:
        cue_angle = None
        
        if is_cue_detect_enabled:
            white_table_pos = (stable_white[0] - x, stable_white[1] - y)
            cue_angle = track_game_aim_line_angle(table, white_table_pos)

        pockets_to_check = pockets if is_multibank_enabled else [pockets[selected_pocket]]

        for current_pocket in pockets_to_check:
            current_ball_color = detected_target_color

            chosen_side = None
            if keyboard.is_pressed("i"): chosen_side = 'top'
            elif keyboard.is_pressed("m"): chosen_side = 'bottom'
            elif keyboard.is_pressed("j"): chosen_side = 'left'
            elif keyboard.is_pressed("k"): chosen_side = 'right'

            if chosen_side or is_multibank_enabled:
                sides = [chosen_side] if chosen_side else ['top', 'bottom', 'left', 'right']
                for s in sides:
                    bank_point = calculate_manual_bank_point(stable_target, current_pocket, table_bounds, s, current_power)
                    if bank_point:
                        g_pos = ghost_ball(stable_target, bank_point, BALL_RADIUS)
                        
                        # رسم خطوط البيضاء بالـ 3 خطوط متوازية والخط الأسود الأوسط للتباين العالي
                        draw_custom_3lines(screen, stable_white, g_pos, BALL_RADIUS, is_white_ball=True)
                        pygame.gfxdraw.aacircle(screen, int(g_pos[0]), int(g_pos[1]), BALL_RADIUS, WHITE)
                        
                        # فصل ألوان خطوط الارتداد بشكل صافٍ ومميز حسب لون الكرة المستهدفة
                        draw_custom_3lines(screen, stable_target, bank_point, BALL_RADIUS, is_white_ball=False, ball_color=current_ball_color)
                        pygame.draw.line(screen, current_ball_color, (int(bank_point[0]), int(bank_point[1])), current_pocket, line_thickness)
                        pygame.gfxdraw.filled_circle(screen, int(bank_point[0]), int(bank_point[1]), 4, CYAN)
            else:
                g_pos = ghost_ball(stable_target, current_pocket, BALL_RADIUS)
                draw_custom_3lines(screen, stable_white, g_pos, BALL_RADIUS, is_white_ball=True)
                pygame.gfxdraw.aacircle(screen, int(g_pos[0]), int(g_pos[1]), BALL_RADIUS, WHITE)
                draw_custom_3lines(screen, stable_target, current_pocket, BALL_RADIUS, is_white_ball=False, ball_color=current_ball_color)

    # ==========================================
    # 🖼️ 10. Rendering Advanced Control GUI Panel
    # ==========================================
    pygame.draw.rect(screen, GUI_BG, (gui_x, gui_y, gui_w, gui_h), border_radius=8)
    pygame.draw.rect(screen, CYAN, (gui_x, gui_y, gui_w, gui_h), 1, border_radius=8)  
    pygame.draw.line(screen, CYAN, (gui_x, gui_y + 30), (gui_x + gui_w, gui_y + 30), 1) 

    screen.blit(gui_title_font.render("🎱 8BP PRO CONTROL PANEL", True, CYAN), (gui_x + 15, gui_y + 6))

    for idx, p_val in enumerate([50, 75, 100]):
        btn_x = gui_x + 15 + (idx * 70)
        btn_color = GUI_ACTIVE_COLOR if current_power == p_val else GUI_INACTIVE_COLOR
        pygame.draw.rect(screen, btn_color, (btn_x, gui_y + 45, 65, 25), border_radius=4)
        screen.blit(gui_font.render(f"{p_val}%", True, WHITE), (btn_x + 20, gui_y + 50))

    toggles = [
        ("Auto Detect Cue", is_cue_detect_enabled, gui_y + 85),
        ("3-Line Projection", is_3line_enabled, gui_y + 120),
        ("Multi-Bank Predict", is_multibank_enabled, gui_y + 155)
    ]
    for label, state, t_y in toggles:
        state_color = GREEN if state else RED
        state_txt = "ON" if state else "OFF"
        pygame.draw.rect(screen, GUI_INACTIVE_COLOR, (gui_x + 15, t_y, 210, 25), border_radius=4)
        pygame.draw.rect(screen, state_color, (gui_x + 185, t_y + 4, 35, 17), border_radius=3)
        screen.blit(gui_font.render(label, True, WHITE), (gui_x + 22, t_y + 5))
        screen.blit(gui_font.render(state_txt, True, WHITE), (gui_x + 193, t_y + 5))

    pygame.draw.rect(screen, GUI_INACTIVE_COLOR, (gui_x + 15, gui_y + 200, 210, 25), border_radius=4)
    screen.blit(gui_font.render(f"Line Thickness: {line_thickness}", True, WHITE), (gui_x + 22, gui_y + 205))
    pygame.draw.rect(screen, CYAN, (gui_x + 140, gui_y + 202, 35, 21), border_radius=3)
    pygame.draw.rect(screen, CYAN, (gui_x + 185, gui_y + 202, 35, 21), border_radius=3)
    screen.blit(gui_font.render("-", True, BLACK), (gui_x + 154, gui_y + 204))
    screen.blit(gui_font.render("+", True, BLACK), (gui_x + 198, gui_y + 204))

    pygame.draw.rect(screen, (50, 150, 50), (gui_x + 15, gui_y + 250, 210, 28), border_radius=4)
    screen.blit(gui_font.render("HIDE TOOL (Ctrl+H)", True, WHITE), (gui_x + 65, gui_y + 256))

    pygame.draw.rect(screen, (200, 50, 50), (gui_x + 15, gui_y + 290, 210, 28), border_radius=4)
    screen.blit(gui_font.render("CLOSE TOOL (Ctrl+Q)", True, WHITE), (gui_x + 62, gui_y + 296))

    pygame.draw.rect(screen, (100, 100, 100), (gui_x + 15, gui_y + 325, 210, 10), border_radius=2)

    pygame.display.update()

camera.stop()
pygame.quit()
sys.exit()
