#!/usr/bin/env python3
import logging
import queue
import threading
import traceback
from enum import Enum, auto
from typing import Optional

import numpy as np

from msgq.visionipc import VisionIpcServer, VisionStreamType
from openpilot.tools.lib.framereader import FrameReader

log = logging.getLogger("replay")

BUFFER_COUNT = 40


def get_nv12_info(width: int, height: int) -> tuple[int, int, int]:
  """Calculate NV12 buffer parameters matching C++ VENUS macros."""
  # VENUS_Y_STRIDE for NV12: align to 128
  nv12_width = (width + 127) & ~127
  # VENUS_Y_SCANLINES for NV12: align to 32
  nv12_height = (height + 31) & ~31
  # Buffer size from v4l2_format (matches C++ implementation)
  nv12_buffer_size = 2346 * nv12_width
  return nv12_width, nv12_height, nv12_buffer_size


class CameraType(Enum):
  ROAD = 0
  DRIVER = 1
  WIDE_ROAD = 2


CAMERA_STREAM_TYPES = {
  CameraType.ROAD: VisionStreamType.VISION_STREAM_ROAD,
  CameraType.DRIVER: VisionStreamType.VISION_STREAM_DRIVER,
  CameraType.WIDE_ROAD: VisionStreamType.VISION_STREAM_WIDE_ROAD,
}


class Camera:
  def __init__(self, cam_type: CameraType):
    self.type = cam_type
    self.stream_type = CAMERA_STREAM_TYPES[cam_type]
    self.width = 0
    self.height = 0
    self.nv12_buffer_size = 0  # Padded buffer size for VisionIPC
    self.thread: Optional[threading.Thread] = None
    self.queue: queue.Queue = queue.Queue()
    self.cached_frames: dict[int, np.ndarray] = {}


class CameraServer:
  def __init__(self, camera_sizes: Optional[dict[CameraType, tuple[int, int]]] = None):
    self._cameras = {
      CameraType.ROAD: Camera(CameraType.ROAD),
      CameraType.DRIVER: Camera(CameraType.DRIVER),
      CameraType.WIDE_ROAD: Camera(CameraType.WIDE_ROAD),
    }

    if camera_sizes:
      for cam_type, (w, h) in camera_sizes.items():
        self._cameras[cam_type].width = w
        self._cameras[cam_type].height = h

    self._vipc_server: Optional[VisionIpcServer] = None
    self._publishing = 0
    self._publishing_lock = threading.Lock()
    self._exit = False

    self._start_vipc_server()

  def __del__(self):
    self._exit = True
    for cam in self._cameras.values():
      if cam.thread is not None and cam.thread.is_alive():
        # Signal termination
        cam.queue.put(None)
        cam.thread.join()

  def _start_vipc_server(self) -> None:
    self._vipc_server = VisionIpcServer("camerad")

    for cam in self._cameras.values():
      cam.cached_frames.clear()

      if cam.width > 0 and cam.height > 0:
        nv12_width, nv12_height, nv12_buffer_size = get_nv12_info(cam.width, cam.height)
        cam.nv12_buffer_size = nv12_buffer_size
        log.info(f"camera[{cam.type.name}] frame size {cam.width}x{cam.height}, nv12 buffer size {nv12_buffer_size}")
        self._vipc_server.create_buffers_with_sizes(
          cam.stream_type, BUFFER_COUNT, cam.width, cam.height,
          nv12_buffer_size, nv12_width, nv12_width * nv12_height
        )

        if cam.thread is None or not cam.thread.is_alive():
          cam.thread = threading.Thread(
            target=self._camera_thread,
            args=(cam,),
            daemon=True
          )
          cam.thread.start()

    self._vipc_server.start_listener()

  def _camera_thread(self, cam: Camera) -> None:
    while not self._exit:
      try:
        item = cam.queue.get(timeout=0.1)
      except queue.Empty:
        continue

      if item is None:  # Termination signal
        break

      fr, event = item

      try:
        # Get encode index from the event
        eidx = event.roadEncodeIdx if cam.type == CameraType.ROAD else \
               event.driverEncodeIdx if cam.type == CameraType.DRIVER else \
               event.wideRoadEncodeIdx

        segment_id = eidx.segmentId
        frame_id = eidx.frameId

        # Get the frame
        yuv = self._get_frame(cam, fr, segment_id, frame_id)
        if yuv is not None:
          # Send via VisionIPC - flatten to 1D and pad to match buffer size
          timestamp_sof = eidx.timestampSof
          timestamp_eof = eidx.timestampEof
          yuv_bytes = yuv.flatten().tobytes()
          # Pad to match the NV12 buffer size expected by VisionIPC
          if len(yuv_bytes) < cam.nv12_buffer_size:
            yuv_bytes = yuv_bytes + bytes(cam.nv12_buffer_size - len(yuv_bytes))
          self._vipc_server.send(cam.stream_type, yuv_bytes, frame_id, timestamp_sof, timestamp_eof)

        # Prefetch next frame
        self._get_frame(cam, fr, segment_id + 1, frame_id + 1)

      except Exception as e:
        log.error(f"camera[{cam.type.name}] error: {e}\n{traceback.format_exc()}")

      with self._publishing_lock:
        self._publishing -= 1

  def _get_frame(self, cam: Camera, fr: FrameReader, segment_id: int, frame_id: int) -> Optional[np.ndarray]:
    # Check cache
    if frame_id in cam.cached_frames:
      return cam.cached_frames[frame_id]

    # Get frame from reader
    try:
      # FrameReader uses local frame index (0-based within segment)
      local_idx = frame_id % 1200  # ~60s at 20fps
      if local_idx < fr.frame_count:
        yuv = fr.get(local_idx)
        cam.cached_frames[frame_id] = yuv
        # Limit cache size
        if len(cam.cached_frames) > BUFFER_COUNT:
          oldest = min(cam.cached_frames.keys())
          del cam.cached_frames[oldest]
        return yuv
    except Exception as e:
      log.warning(f"Failed to decode frame {frame_id}: {e}")
    return None

  def push_frame(self, cam_type: CameraType, fr: FrameReader, event) -> None:
    cam = self._cameras[cam_type]

    # Check if frame size changed
    if cam.width != fr.w or cam.height != fr.h:
      cam.width = fr.w
      cam.height = fr.h
      self.wait_for_sent()
      self._start_vipc_server()

    with self._publishing_lock:
      self._publishing += 1
    cam.queue.put((fr, event))

  def wait_for_sent(self) -> None:
    while True:
      with self._publishing_lock:
        if self._publishing <= 0:
          break
      threading.Event().wait(0.001)  # Small sleep to avoid busy waiting
