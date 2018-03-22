#!/usr/bin/env python

import itertools
import glob
import subprocess
import sys
import readchar
import serial
from time import localtime, strftime, time, sleep
import os
import scipy.ndimage
import numpy as np
import numpy.fft
import subprocess
import math
import psutil
import io
import logging
import gphoto2 as gp
import imageio
import scipy.optimize
import tornado.ioloop
import tornado.web
import tornado.websocket
import termios, tty
from termios import TCSANOW

LISTEN_PORT = 8080

ARDUINO_PORT_GLOBS = ["/dev/tty.usbmodem142?", "/dev/tty.wchusbserial142?"]
ARDUINO_SPEED = "115200"

CAMERA = None
DELTA = 40
REFERENCE_FFT_RESULT = None
REFERENCE_Z_POSITION = None
MAX_DELTA_TO_REFERENCE_Z_POSITION = 500
Z_POSITION = 0
AUTOFOCUS_BOUND = 50
AUTOFOCUS_STEP = 5
MOTOR_SLEEP_MULTIPLIER = 0.03
TIMELAPSE_INTERVAL_MS = 5000

class ImageWebSocket(tornado.websocket.WebSocketHandler):
    clients = set()

    def check_origin(self, origin):
        # Allow access from every origin
        return True

    def open(self):
        ImageWebSocket.clients.add(self)
        log("WebSocket opened from: " + self.request.remote_ip)

    def on_message(self, message):
        jpeg_bytes = get_preview_image().getvalue()
        self.write_message(jpeg_bytes, binary=True)

    def on_close(self):
        ImageWebSocket.clients.remove(self)
        log("WebSocket closed from: " + self.request.remote_ip)

class Error(Exception):
    """Base class for exceptions in this module."""
    pass

class PeripheralStatusError(Error):
    """Exception raised for errors related to the status of peripherals

    Attributes:
        message -- explanation of the error
    """

    def __init__(self, message):
        self.message = message

class SystemError(Error):
    """Exception raised for system errors when executing this script

    Attributes:
        message -- explanation of the error
    """

    def __init__(self, message):
        self.message = message

def flatten(list2d):
  return list(itertools.chain(*list2d))

def log(msg):
  print("[{time}] {msg}".format(time=strftime("%Y-%m-%d %H:%M:%S", localtime()), msg=msg))

# needed on OS X
def kill_ptpcamera():
  for proc in psutil.process_iter():
    if proc.name() == "PTPCamera":
      log("Killing {name} process {pid} which prevents gphoto2 from working".format(name=proc.name(),
                                                                                      pid=proc.pid))
      proc.kill()

def sample_and_fft(image_data):
  img = imageio.imread(image_data, "JPEG-PIL")
  res = None
  for i in range(0, img.shape[0], DELTA):
    vec = np.absolute(numpy.fft.fft(img[:][i].flatten()))**2
    if res is None:
      res = vec
    else:
      res = np.concatenate([res, vec])
  return res

def image_filename():
  return "data/image-{count}.jpg".format(count=math.trunc(time() * 1000))

def get_preview_image():
  camera_file = gp.check_result(gp.gp_camera_capture_preview(CAMERA))
  file_data = gp.check_result(gp.gp_file_get_data_and_size(camera_file))
  buf =	io.BytesIO(file_data)
  buf.seek(0) 
  return buf

def get_store_and_maybe_show_image(show_image=False):
  file_path = gp.check_result(gp.gp_camera_capture(CAMERA, gp.GP_CAPTURE_IMAGE))
  log('Camera file path: {0}/{1}'.format(file_path.folder, file_path.name))
  target = image_filename()
  log('Copying image to {target}'.format(target=target))
  camera_file = gp.check_result(gp.gp_camera_file_get(CAMERA, file_path.folder, file_path.name, gp.GP_FILE_TYPE_NORMAL))
  gp.check_result(gp.gp_file_save(camera_file, target))
  if show_image:
    subprocess.call(['open', target])
  return target

def current_position_take_preview_image_and_set_as_reference():
  global REFERENCE_FFT_RESULT, REFERENCE_Z_POSITION
  image = get_preview_image()
  REFERENCE_FFT_RESULT = sample_and_fft(image)
  REFERENCE_Z_POSITION = Z_POSITION
  log("Using current position {pos} as reference".format(pos=Z_POSITION))

def current_position_take_preview_image_and_get_correlation_with_reference():
  image = get_preview_image()
  fft_result = sample_and_fft(image)
  corr = np.corrcoef(REFERENCE_FFT_RESULT, fft_result)[1,0]
  log("Captured image position {pos} correlation {corr}".format(pos=Z_POSITION, corr=corr))
  return corr

def setup_arduino():
  for arduino_port in flatten([glob.glob(x) for x in ARDUINO_PORT_GLOBS]):
    try:
      ser = serial.Serial(arduino_port, baudrate=ARDUINO_SPEED)
    except serial.SerialException as err:
      raise PeripheralStatusError("Could not connect to Arduino: " + err.strerror)
    return ser

def connect_arduino():
  ser = setup_arduino()
  data = serial_readline(ser)
  if data != b"HELLO":
    raise SystemError("Expected HELLO, but got {data}".format(data=data))
  return ser
  
def connect_camera():
  global CAMERA
  logging.basicConfig(format='%(levelname)s: %(name)s: %(message)s', level=logging.ERROR)
  gp.check_result(gp.use_python_logging())
  CAMERA = gp.check_result(gp.gp_camera_new())
  gp.check_result(gp.gp_camera_init(CAMERA))

  log("Checking camera config")
  # get configuration tree
  config = gp.check_result(gp.gp_camera_get_config(CAMERA))
  # find the image format config item
  OK, image_format = gp.gp_widget_get_child_by_name(config, 'imageformat')
  if OK >= gp.GP_OK:
      # get current setting
      value = gp.check_result(gp.gp_widget_get_value(image_format))
      # make sure it's not raw
      if 'raw' in value.lower():
          raise PeripheralStatusError('Camera is setup to record raw, but we need previs, and preview does not work with raw images')
  # find the capture size class config item
  # need to set this on my Canon 350d to get preview to work at all
  OK, capture_size_class = gp.gp_widget_get_child_by_name( config, 'capturesizeclass')
  if OK >= gp.GP_OK:
      # set value
      value = gp.check_result(gp.gp_widget_get_choice(capture_size_class, 2))
      gp.check_result(gp.gp_widget_set_value(capture_size_class, value))
      # set config
      gp.check_result(gp.gp_camera_set_config(CAMERA, config))

def ready():
  log("Ready, ctrl-c = quit, a = -1, z = +1, t = timelapse, s = shoot and show image, r = use current position as reference, f = find position with highest correlation with reference")

def serial_writeline(ser, data):
  log("ARDUINO -> {data}".format(data=data))
  ser.write(("{data}\r\n".format(data=data)).encode())

def serial_readline(ser):
  data = ser.readline()[:-2]
  if data:
    log("ARDUINO <- {data}".format(data=data))
  return data

# focus camera using remote shutter port, wakes up the camera if asleep
def camera_focus(ser):
  serial_writeline(ser, "F");
  data = serial_readline(ser)
  if data != "OK F":
    raise PeripheralStatusError("Camera focus returned error: {}".format(data))

# shutter camera using remote shutter port, wakes up the camera if asleep
def camera_shutter(ser):
  serial_writeline(ser, "S");
  data = serial_readline(ser)
  if data != "OK S":
    raise PeripheralStatusError("Camera focus returned error: {}".format(data))

def move_z(ser, value):
  global Z_POSITION, REFERENCE_Z_POSITION, MAX_DELTA_TO_REFERENCE_Z_POSITION
  if REFERENCE_Z_POSITION is not None:
    if abs(Z_POSITION - REFERENCE_Z_POSITION) > MAX_DELTA_TO_REFERENCE_Z_POSITION:
        raise PeripheralStatusError("Reached maximum delta to reference z position")
  Z_POSITION += value
  serial_writeline(ser, "M" + str(value))
  sleep(MOTOR_SLEEP_MULTIPLIER * abs(value))
  log("Z: {z}".format(z=Z_POSITION))

def find_position_with_lowest_correlation_with_reference(ser, level=1):
  # bail out if we are moving more than 5 * (AUTOFOCUS_BOUND / 2)
  if level > 5:
    raise PeripheralStatusError("Reached maximum limit for autofocus")

  # start capturing images from -AUTOFOCUS_BOUND
  move_z(ser, -1 * AUTOFOCUS_BOUND)

  # find correlations for positions [-AUTOFOCUS_BOUND, AUTOFOCUS_BOUND]
  xa = range(-1 * AUTOFOCUS_BOUND, AUTOFOCUS_BOUND, AUTOFOCUS_STEP)
  ya = []

  for x in xa:
    move_z(ser, AUTOFOCUS_STEP)
    corr = current_position_take_preview_image_and_get_correlation_with_reference()
    log("Index %d has correlation %r)" % (x, corr))
    ya.append(corr)

  # fit correlations on a 2-degree polynomial
  z = np.polyfit(xa, ya, 2)
  p = np.poly1d(z)

  # optimize the polynomial
  result = scipy.optimize.minimize_scalar(-1 * p, method='bounded', bounds=[-1 * AUTOFOCUS_BOUND, AUTOFOCUS_BOUND])
  new_pos = round(result.x)

  # we are close to the start or end of the range, move to
  if abs(new_pos) + 3 > AUTOFOCUS_BOUND:
    move_z(ser, -1 * AUTOFOCUS_BOUND + new_pos)
    find_position_with_lowest_correlation_with_reference(ser, level + 1)
  else:
    move_z(ser, -1 * AUTOFOCUS_BOUND + new_pos)

def setup():
  try:
    ser = connect_arduino()
  except PeripheralStatusError as err:
    log("Could not connect to Arduino, motor movements disabled")
    return None
  if ser:
    camera_focus(ser)
  kill_ptpcamera()
  connect_camera()
  return ser

def read_key(fd):
  char = sys.stdin.read(1)
  # Ctrl-C = Break
  if char == '\x03':
    raise KeyboardInterrupt
  # Ctrl-D = EOF
  #elif char == '\x04':
  #  raise EOFError
  # Ctrl-Z = SIGTSTP
  #elif char == '\x1a':
  #  os.kill(0, signal.SIGTSTP)
  return char

def timelapse():
    get_store_and_maybe_show_image(False)

def keyboard_control(fd, arduino_serial, timelapse_callback):
  ready()
  ch = read_key(fd)
  if ch == 'a':
    if arduino_serial is None:
      log("No connection to scope controller, motor movements are disabled")
    else:
      move_z(arduino_serial, -1) 
  elif ch == 'z':
    if arduino_serial is None:
      log("No connection to scope controller , motor movements are disabled")
    else:
      move_z(arduino_serial, 1)
  elif ch == 't':
    log("Starting timelapse, interval between takes is {iv} ms".format(iv=TIMELAPSE_INTERVAL_MS))
    timelapse_callback.start()
  elif ch == 'g':
    log("Stopping timelapse")
    timelapse_callback.stop()
  elif ch == 's':
    get_store_and_maybe_show_image(True)
  elif ch == 'r':
    current_position_take_preview_image_and_set_as_reference()
  elif ch == 'f':
    if arduino_serial is None:
      log("No connection to scope controller , motor movements are disabled")
    else:
      find_position_with_lowest_correlation_with_reference(arduino_serial)

if __name__ == "__main__":
  script_path = os.path.dirname(os.path.realpath(__file__))
  static_path = script_path + '/static/'

  arduino_serial = setup()

  app = tornado.web.Application([
      (r"/websocket", ImageWebSocket),
      (r"/(.*)", tornado.web.StaticFileHandler, {'path': static_path, 'default_filename': 'index.html'}),
  ])
  app.listen(LISTEN_PORT)

  old_settings = termios.tcgetattr(sys.stdin)
  tty.setcbreak(sys.stdin, when=TCSANOW)

  timelapse_callback = tornado.ioloop.PeriodicCallback(
    timelapse, 
    TIMELAPSE_INTERVAL_MS)

  tornado.ioloop.IOLoop.current().add_handler(
    sys.stdin, 
    lambda fd, events: keyboard_control(fd, arduino_serial, timelapse_callback),
    tornado.ioloop.IOLoop.READ|tornado.ioloop.IOLoop.ERROR)

  log("Starting server: http://localhost:" + str(LISTEN_PORT) + "/")

  try:
    tornado.ioloop.IOLoop.current().start()

  finally:
    log("Exiting")
    termios.tcsetattr(sys.stdin, TCSANOW, old_settings)

    sys.exit(0)
  #except PeripheralStatusError as err:
  #  print err.message
  #  sys.exit(1)
