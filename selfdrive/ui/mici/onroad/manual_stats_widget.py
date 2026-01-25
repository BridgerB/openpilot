"""
Live Manual Stats Widget

Small onroad overlay showing current drive statistics, RPM meter with rev-match helper,
shift grade feedback, and launch progress.
"""

import json
import pyray as rl

from openpilot.common.params import Params
from openpilot.selfdrive.ui.ui_state import ui_state
from openpilot.system.ui.lib.application import gui_app, FontWeight
from openpilot.system.ui.widgets import Widget


# Colors
GREEN = rl.Color(46, 204, 113, 220)
YELLOW = rl.Color(241, 196, 15, 220)
RED = rl.Color(231, 76, 60, 220)
ORANGE = rl.Color(230, 126, 34, 220)
CYAN = rl.Color(52, 152, 219, 220)
WHITE = rl.Color(255, 255, 255, 220)
GRAY = rl.Color(150, 150, 150, 200)
BG_COLOR = rl.Color(0, 0, 0, 160)

# RPM zones for BRZ (7500 redline)
RPM_REDLINE = 7500
RPM_ECONOMY_MAX = 2500
RPM_POWER_MIN = 4000
RPM_DANGER_MIN = 6500

# 2024 BRZ gear ratios for rev-match calculation
BRZ_GEAR_RATIOS = {1: 3.626, 2: 2.188, 3: 1.541, 4: 1.213, 5: 1.000, 6: 0.767}
BRZ_FINAL_DRIVE = 4.10
BRZ_TIRE_CIRCUMFERENCE = 1.977


def rpm_for_speed_and_gear(speed_ms: float, gear: int) -> float:
  """Calculate expected RPM for a given speed and gear"""
  if gear not in BRZ_GEAR_RATIOS or speed_ms <= 0:
    return 0.0
  return (speed_ms * BRZ_FINAL_DRIVE * BRZ_GEAR_RATIOS[gear] * 60) / BRZ_TIRE_CIRCUMFERENCE


class ManualStatsWidget(Widget):
  """Widget showing live manual driving stats, RPM meter, and feedback"""

  def __init__(self):
    super().__init__()
    self._params = Params()
    self._visible = False
    self._stats: dict = {}
    self._update_counter = 0
    # Shift grade flash state
    self._last_shift_grade = 0
    self._shift_flash_frames = 0
    self._flash_grade = 0  # The grade to display during flash
    # Track gear before clutch for rev-match display
    self._gear_before_clutch = 0
    self._last_clutch_state = False

  def set_visible(self, visible: bool):
    self._visible = visible

  def _render(self, rect: rl.Rectangle):
    if not self._visible:
      return

    # Update stats every ~15 frames (0.25s at 60fps)
    self._update_counter += 1
    if self._update_counter >= 15:
      self._update_counter = 0
      self._load_stats()

    # Get live data from CarState
    cs = ui_state.sm['carState'] if ui_state.sm.valid['carState'] else None
    if not cs:
      return

    # Widget dimensions - wider for RPM bar
    w = 180
    h = 160
    x = int(rect.x + rect.width - w - 10)
    y = int(rect.y + 10)

    # Background
    rl.draw_rectangle_rounded(rl.Rectangle(x, y, w, h), 0.1, 10, BG_COLOR)

    font = gui_app.font(FontWeight.MEDIUM)
    font_bold = gui_app.font(FontWeight.BOLD)
    px = x + 10
    py = y + 8

    # === RPM METER ===
    rpm = cs.engineRpm
    self._draw_rpm_meter(px, py, w - 20, 35, rpm, cs)
    py += 42

    # === GEAR + SHIFT GRADE FLASH ===
    gear = cs.gearActual
    gear_text = str(gear) if gear > 0 else "N"

    # Check for new shift - only trigger when shiftGrade goes from 0 to non-zero
    if cs.shiftGrade > 0 and self._last_shift_grade == 0:
      # New shift detected - start flash with this grade
      self._shift_flash_frames = 150  # Flash for 2.5s at 60fps
      self._flash_grade = cs.shiftGrade  # Store the grade to display
    # Track the raw shiftGrade value
    self._last_shift_grade = cs.shiftGrade

    # Draw gear with flash color if recently shifted
    if self._shift_flash_frames > 0:
      self._shift_flash_frames -= 1
      if self._flash_grade == 1:
        gear_color = GREEN
        grade_text = "✓"
      elif self._flash_grade == 2:
        gear_color = YELLOW
        grade_text = "~"
      else:
        gear_color = RED
        grade_text = "✗"
      rl.draw_text_ex(font_bold, gear_text, rl.Vector2(px, py), 38, 0, gear_color)
      rl.draw_text_ex(font_bold, grade_text, rl.Vector2(px + 30, py + 5), 28, 0, gear_color)
    else:
      rl.draw_text_ex(font_bold, gear_text, rl.Vector2(px, py), 38, 0, WHITE)

    # Shift suggestion arrow
    suggestion = self._stats.get('shift_suggestion', 'ok')
    if suggestion == 'upshift':
      rl.draw_text_ex(font_bold, "↑", rl.Vector2(px + 65, py + 5), 30, 0, GREEN)
    elif suggestion == 'downshift':
      rl.draw_text_ex(font_bold, "↓", rl.Vector2(px + 65, py + 5), 30, 0, YELLOW)

    py += 42

    # === LAUNCH FEEDBACK ===
    launches = self._stats.get('launches', 0)
    good_launches = self._stats.get('good_launches', 0)
    # Detect if currently launching (low speed, was stopped)
    if cs.vEgo < 5.0 and cs.vEgo > 0.5 and not cs.clutchPressed:
      rl.draw_text_ex(font, "LAUNCHING...", rl.Vector2(px, py), 18, 0, CYAN)
    elif launches > 0:
      pct = int(good_launches / launches * 100) if launches > 0 else 0
      color = GREEN if pct >= 75 else (YELLOW if pct >= 50 else GRAY)
      rl.draw_text_ex(font, f"Launch: {good_launches}/{launches}", rl.Vector2(px, py), 18, 0, color)
    else:
      rl.draw_text_ex(font, "Launch: -", rl.Vector2(px, py), 18, 0, GRAY)
    py += 22

    # === STATS ROW ===
    font_size = 17

    # Stalls & Lugs on same line
    stalls = self._stats.get('stalls', 0)
    lugs = self._stats.get('lugs', 0)
    is_lugging = cs.isLugging

    if is_lugging:
      rl.draw_text_ex(font, "LUGGING!", rl.Vector2(px, py), font_size, 0, RED)
    else:
      stall_color = GREEN if stalls == 0 else RED
      lug_color = GREEN if lugs == 0 else YELLOW
      rl.draw_text_ex(font, f"S:{stalls}", rl.Vector2(px, py), font_size, 0, stall_color)
      rl.draw_text_ex(font, f"L:{lugs}", rl.Vector2(px + 45, py), font_size, 0, lug_color)

    # Shift quality
    shifts = self._stats.get('shifts', 0)
    good_shifts = self._stats.get('good_shifts', 0)
    if shifts > 0:
      pct = int(good_shifts / shifts * 100)
      color = GREEN if pct >= 80 else (YELLOW if pct >= 50 else RED)
      rl.draw_text_ex(font, f"Sh:{pct}%", rl.Vector2(px + 95, py), font_size, 0, color)
    else:
      rl.draw_text_ex(font, "Sh:-", rl.Vector2(px + 95, py), font_size, 0, GRAY)

  def _draw_rpm_meter(self, x: int, y: int, w: int, h: int, rpm: float, cs):
    """Draw RPM bar with color zones and rev-match target"""
    font = gui_app.font(FontWeight.MEDIUM)

    # Bar background
    bar_h = 14
    bar_y = y + 18
    rl.draw_rectangle_rounded(rl.Rectangle(x, bar_y, w, bar_h), 0.3, 5, rl.Color(40, 40, 40, 200))

    # Calculate fill width
    rpm_pct = min(rpm / RPM_REDLINE, 1.0)
    fill_w = int(w * rpm_pct)

    # Color based on RPM zone
    if rpm < RPM_ECONOMY_MAX:
      bar_color = GREEN
    elif rpm < RPM_POWER_MIN:
      bar_color = YELLOW
    elif rpm < RPM_DANGER_MIN:
      bar_color = ORANGE
    else:
      bar_color = RED

    # Draw filled portion
    if fill_w > 0:
      rl.draw_rectangle_rounded(rl.Rectangle(x, bar_y, fill_w, bar_h), 0.3, 5, bar_color)

    # Track gear before clutch press for rev-match display
    if not cs.clutchPressed and cs.gearActual > 0:
      self._gear_before_clutch = cs.gearActual

    # Rev-match target line when clutch pressed (show target for downshift)
    if cs.clutchPressed and self._gear_before_clutch > 1:
      # Calculate target RPM for downshift to next lower gear
      target_gear = self._gear_before_clutch - 1
      target_rpm = rpm_for_speed_and_gear(cs.vEgo, target_gear)
      if 0 < target_rpm < RPM_REDLINE:
        target_x = x + int(w * (target_rpm / RPM_REDLINE))
        # Draw target line
        rl.draw_rectangle(target_x - 1, bar_y - 3, 3, bar_h + 6, CYAN)
        # Draw small target RPM text
        rl.draw_text_ex(font, f"{int(target_rpm)}", rl.Vector2(target_x - 15, bar_y - 14), 12, 0, CYAN)

    # RPM text
    rpm_text = f"{int(rpm)}"
    rl.draw_text_ex(font, rpm_text, rl.Vector2(x, y), 16, 0, WHITE)
    rl.draw_text_ex(font, "rpm", rl.Vector2(x + 45, y + 2), 12, 0, GRAY)

  def _load_stats(self):
    """Load current session stats"""
    try:
      data = self._params.get("ManualDriveLiveStats")
      self._stats = data if data else {}
    except Exception:
      self._stats = {}
