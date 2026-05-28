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

# ==========================================
# 🚀 1. Performance Tuning
# ==========================================
cv2.setUseOptimized(True)
cv2.setNumThreads(4)

FPS = 144
BALL_RADIUS = 16  
CUSHION_PADDING = 16

SCREEN_WIDTH = win32api.GetSystemMetrics(0)
SCREEN_HEIGHT = win32api.GetSystemMetrics(1)
TRANSPARENT = (0, 0, 0)

# 🎨 Color Schemes
WHITE = (255, 255, 255)
BLACK = (0, 0, 0)
YELLOW = (255, 255, 0)
RED = (255, 0, 0)
GREEN = (0, 255, 0)
BLUE = (0, 162, 232)
CYAN = (0, 200, 255)
NEON_ORANGE = (255, 69, 0) 
GUI_BG = (25, 25, 30)      

last_known_mx = SCREEN_WIDTH // 2
last_known_my = SCREEN_HEIGHT // 2

# ==========================================
# 🎛️ 2. GUI & Overlay State
# ==========================================
gui_x, gui_y = 50, 50       
gui_w, gui_h = 240, 340       
is_dragging = False          
drag_offset_x = 0
drag_offset_y = 0
is_mouse_hovering_gui = False
window_has_focus = True     
is_hidden = False             

current_power = 100           
line_thickness = 2            
is_cue_detect_enabled = True  
is_3line_enabled = True       
is_multibank_enabled = True   

class AutoBallTracker:
    def __init__(self):
        self.pos = None

    def update(self, current_det):
        if current_det is not None:
            self.pos = current_det
        return self.pos

white_tracker = AutoBallTracker()
target_tracker = AutoBallTracker()

selected_pocket = 0
table_region = None
last_lock_time = 0
last_hide_toggle_time = 0

# ==========================================
# 📐 3. Physics & Geometric Calculations
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

def draw_cue_ball_3lines(surface, start, end, radius):
    """
    🛠️ رسم مسار الكرة البيضاء الثلاثي مع الخط الأسود المميز في المنتصف 
    لتحقيق التباين العالي المطلوب وسهولة القراءة البصرية.
    """
    dx = end[0] - start[0]
    dy = end[1] - start[1]
    dist = math.hypot(dx, dy)
    if dist == 0: return

    ux = dx / dist
    uy = dy / dist
    nx = -uy * radius
    ny = ux * radius

    if is_3line_enabled:
        # الخطوط الخارجية البيضاء
        pygame.draw.line(surface, WHITE, (int(start[0] + nx), int(start[1] + ny)), (int(end[0] + nx), int(end[1] + ny)), line_thickness)
        pygame.draw.line(surface, WHITE, (int(start[0] - nx), int(start[1] - ny)), (int(end[0] - nx), int(end[1] - ny)), line_thickness)
        # الخط الأسود المركزي الإرشادي في المنتصف تماماً
        pygame.draw.line(surface, BLACK, (int(start[0]), int(start[1])), (int(end[0]), int(end[1])), line_thickness)
    else:
        pygame.draw.line(surface, WHITE, (int(start[0]), int(start[1])), (int(end[0]), int(end[1])), line_thickness)

def draw_target_ball_3lines(surface, start, end, radius, color):
    dx = end[0] - start[0]
    dy = end[1] - start[1]
    dist = math.hypot(dx, dy)
    if dist == 0: return

    ux = dx / dist
    uy = dy / dist
    nx = -uy * radius
    ny = ux * radius

    if is_3line_enabled:
        pygame.draw.line(surface, color, (int(start[0] + nx), int(start[1] + ny)), (int(end[0] + nx), int(end[1] + ny)), line_thickness)
        pygame.draw.line(surface, color, (int(start[0]), int(start[1])), (int(end[0]), int(end[1])), line_thickness)
        pygame.draw.line(surface, color, (int(start[0] - nx), int(start[1] - ny)), (int(end[0] - nx), int(end[1] - ny)), line_thickness)
    else:
        pygame.draw.line(surface, color, (int(start[0]), int(start[1])), (int(end[0]), int(end[1])), line_thickness)

def calculate_bank_point(target, pocket, bounds, side):
    left, top, right, bottom = bounds
    tx, ty = target
    px, py = pocket

    adj_top = top + BALL_RADIUS
    adj_bottom = bottom - BALL_RADIUS
    adj_left = left + BALL_RADIUS
    adj_right = right - BALL_RADIUS

    if side == 'top':
        if (adj_top - ty) + (adj_top - py) != 0:
            bx = tx + (px - tx) * (adj_top - ty) / ((adj_top - ty) + (adj_top - py))
            if left <= bx <= right: return (bx, adj_top)
    elif side == 'bottom':
        if (ty - adj_bottom) + (py - adj_bottom) != 0:
            bx = tx + (px - tx) * (adj_bottom - ty) / ((adj_bottom - ty) + (adj_bottom - py))
            if left <= bx <= right: return (bx, adj_bottom)
    elif side == 'left':
        if (adj_left - tx) + (adj_left - px) != 0:
            by = ty + (py - ty) * (adj_left - tx) / ((adj_left - tx) + (adj_left - px))
            if top <= by <= bottom: return (adj_left, by)
    elif side == 'right':
        if (tx - adj_right) + (px - adj_right) != 0:
            by = ty + (py - ty) * (adj_right - tx) / ((adj_right - tx) + (adj_right - px))
            if top <= by <= bottom: return (adj_right, by)
    return None

# ==========================================
# 🖼️ 4. Adaptive Computer Vision Engine
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

def is_white_ball_hsv(roi):
    """ فحص لوني مرن ومستمر متوافق مع إضاءة الطاولة وعصا اللعبة لمنع السقوط """
    if roi is None or roi.size == 0: return False
    hsv = cv2.cvtColor(roi, cv2.COLOR_BGR2HSV)
    lower_white = np.array([0, 0, 190]) 
    upper_white = np.array([180, 45, 255])
    mask = cv2.inRange(hsv, lower_white, upper_white)
    ratio = np.sum(mask == 255) / mask.size
    return ratio > 0.55

# ==========================================
# 🎮 5. Overlay Window Initialization
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

pocket_font = pygame.font.SysFont("Arial", 14, bold=True)
gui_font = pygame.font.SysFont("Segoe UI", 10, bold=True)
gui_title_font = pygame.font.SysFont("Segoe UI", 11, bold=True)

running = True

# ==========================================
# 🔄 6. Main Dynamic Loop
# ==========================================
while running:
    clock.tick(FPS)
    
    try:
        mx, my = win32api.GetCursorPos()
        last_known_mx, last_known_my = mx, my
    except Exception:
        mx, my = last_known_mx, last_known_my

    if keyboard.is_pressed("ctrl+h") and time.time() - last_hide_toggle_time > 0.3:
        is_hidden = not is_hidden
        last_hide_toggle_time = time.time()

    is_mouse_hovering_gui = (gui_x <= mx <= gui_x + gui_w) and (gui_y <= my <= gui_y + gui_h) if not is_hidden else False

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
                if (gui_x + 15 <= mx <= gui_x + 225) and (gui_y + 85 <= my <= gui_y + 110): is_cue_detect_enabled = not is_cue_detect_enabled
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

    # 🔍 كشف الكرات أوتوماتيكياً بالكامل وعزل الجيوب
    gray = cv2.cvtColor(table, cv2.COLOR_BGR2GRAY)
    blur = cv2.medianBlur(cv2.equalizeHist(gray), 5)
    circles = cv2.HoughCircles(blur, cv2.HOUGH_GRADIENT, dp=1.0, minDist=25, param1=65, param2=20, minRadius=13, maxRadius=19)

    detected_white = None
    detected_target = None

    pockets = [
        (x + 22, y + 22), (x + w // 2, y + 13), (x + w - 22, y + 22),
        (x + 22, y + h - 22), (x + w // 2, y + h - 13), (x + w - 22, y + h - 22)
    ]

    top_band, bottom_band = y + CUSHION_PADDING, y + h - CUSHION_PADDING
    left_band, right_band = x + CUSHION_PADDING, x + w - CUSHION_PADDING
    table_bounds = (left_band, top_band, right_band, bottom_band)

    if circles is not None:
        circles = np.round(circles[0, :]).astype("int")
        for (cx, cy, r) in circles:
            cx_global, cy_global = int(cx + x), int(cy + y)
            if any(distance((cx_global, cy_global), p) < 35 for p in pockets): continue

            roi = table[max(0, cy-r):min(h, cy+r), max(0, cx-r):min(w, cx+r)]
            
            # العزل التلقائي الدائم للكرة البيضاء
            if is_white_ball_hsv(roi):
                detected_white = (cx_global, cy_global)
            else:
                # تتبع أقرب كرة للماوس لتكون هي المستهدفة تلقائياً دون الحاجة للقفل والتعطيل
                if distance((cx_global, cy_global), (mx, my)) < 40:
                    detected_target = (cx_global, cy_global)

    # تحديث الذاكرة التلقائية المباشرة
    stable_white = white_tracker.update(detected_white)
    stable_target = target_tracker.update(detected_target)

    # تبديل الجيب النشط عبر لوحة الأرقام (1-6)
    for i in range(1, 7):
        if keyboard.is_pressed(str(i)): selected_pocket = i - 1

    for idx, p in enumerate(pockets):
        p_color = GREEN if idx == selected_pocket else RED
        pygame.gfxdraw.aacircle(screen, p[0], p[1], 6, p_color)

    # ==========================================
    # 🎯 7. Ultimate Multi-Bank Network Display
    # ==========================================
    if stable_white and stable_target:
        # رسم دائرة تأكيدية خفيفة حول الكرة البيضاء والمستهدفة المكتشفة تلقائياً
        pygame.gfxdraw.aacircle(screen, int(stable_white[0]), int(stable_white[1]), BALL_RADIUS, CYAN)
        pygame.gfxdraw.aacircle(screen, int(stable_target[0]), int(stable_target[1]), BALL_RADIUS, YELLOW)

        pockets_to_draw = pockets if is_multibank_enabled else [pockets[selected_pocket]]
        sides_to_check = ['top', 'bottom', 'left', 'right']

        for current_pocket in pockets_to_draw:
            for s in sides_to_check:
                bank_point = calculate_bank_point(stable_target, current_pocket, table_bounds, s)
                if bank_point:
                    g_pos = ghost_ball(stable_target, bank_point, BALL_RADIUS)
                    
                    # 1. رسم مسار الكرة البيضاء بالكامل إلى مكان الـ Ghost Ball (مع الخط الأسود الأوسط الثابت للتباين)
                    draw_cue_ball_3lines(screen, stable_white, g_pos, BALL_RADIUS)
                    pygame.gfxdraw.aacircle(screen, int(g_pos[0]), int(g_pos[1]), BALL_RADIUS, WHITE)
                    
                    # 2. رسم مسار الكرة المستهدفة المرتد من الباند إلى الجيب المختار بلون متناسق ومميز
                    draw_target_ball_3lines(screen, stable_target, bank_point, BALL_RADIUS, YELLOW)
                    pygame.draw.line(screen, NEON_ORANGE, (int(bank_point[0]), int(bank_point[1])), current_pocket, line_thickness)

    # ==========================================
    # 🖼️ 8. Render Control Panel
    # ==========================================
    pygame.draw.rect(screen, GUI_BG, (gui_x, gui_y, gui_w, gui_h), border_radius=8)
    pygame.draw.rect(screen, CYAN, (gui_x, gui_y, gui_w, gui_h), 1, border_radius=8)  
    pygame.draw.line(screen, CYAN, (gui_x, gui_y + 30), (gui_x + gui_w, gui_y + 30), 1) 
    screen.blit(gui_title_font.render("🎱 DYNAMIC MULTI-RULER", True, CYAN), (gui_x + 15, gui_y + 6))

    toggles = [
        ("Auto Detect Cue", is_cue_detect_enabled, gui_y + 65),
        ("3-Line Projection", is_3line_enabled, gui_y + 110),
        ("Multi-Bank Network", is_multibank_enabled, gui_y + 155)
    ]
    for label, state, t_y in toggles:
        state_color = GREEN if state else RED
        state_txt = "ON" if state else "OFF"
        pygame.draw.rect(screen, (40, 40, 45), (gui_x + 15, t_y, 210, 25), border_radius=4)
        pygame.draw.rect(screen, state_color, (gui_x + 185, t_y + 4, 35, 17), border_radius=3)
        screen.blit(gui_font.render(label, True, WHITE), (gui_x + 22, t_y + 5))
        screen.blit(gui_font.render(state_txt, True, WHITE), (gui_x + 193, t_y + 5))

    pygame.draw.rect(screen, (40, 40, 45), (gui_x + 15, gui_y + 200, 210, 25), border_radius=4)
    screen.blit(gui_font.render(f"Thickness: {line_thickness}", True, WHITE), (gui_x + 22, gui_y + 205))
    pygame.draw.rect(screen, CYAN, (gui_x + 140, gui_y + 202, 35, 21), border_radius=3)
    pygame.draw.rect(screen, CYAN, (gui_x + 185, gui_y + 202, 35, 21), border_radius=3)
    screen.blit(gui_font.render("-", True, BLACK), (gui_x + 154, gui_y + 204))
    screen.blit(gui_font.render("+", True, BLACK), (gui_x + 198, gui_y + 204))

    pygame.draw.rect(screen, (50, 150, 50), (gui_x + 15, gui_y + 250, 210, 28), border_radius=4)
    screen.blit(gui_font.render("HIDE TOOL (Ctrl+H)", True, WHITE), (gui_x + 65, gui_y + 256))

    pygame.draw.rect(screen, (200, 50, 50), (gui_x + 15, gui_y + 290, 210, 28), border_radius=4)
    screen.blit(gui_font.render("CLOSE TOOL (Ctrl+Q)", True, WHITE), (gui_x + 62, gui_y + 296))

    pygame.display.update()

camera.stop()
pygame.quit()
sys.exit()
