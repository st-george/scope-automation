#!/usr/bin/env python

import subprocess
import sys
#import select
import readchar
import serial
from time import localtime, strftime, time
import os
import scipy.ndimage
import numpy as np
import numpy.fft
import subprocess
import math
import psutil
from serial.serialutil import SerialException 
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

ARDUINO_PORT = "/dev/tty.usbmodem1421"
ARDUINO_SPEED = "115200"

CAMERA = None
DELTA = 40
REFERENCE_FFT_RESULT = None
REFERENCE_Z_POSITION = None
MAX_DELTA_TO_REFERENCE_Z_POSITION = 500
Z_POSITION = 0
AUTOFOCUS_BOUND = 50

class ImageWebSocket(tornado.websocket.WebSocketHandler):
    clients = set()

    def check_origin(self, origin):
        # Allow access from every origin
        return True

    def open(self):
        ImageWebSocket.clients.add(self)
        print("WebSocket opened from: " + self.request.remote_ip)

    def on_message(self, message):
        jpeg_bytes = get_preview_image()
        self.write_message(jpeg_bytes, binary=True)

    def on_close(self):
        ImageWebSocket.clients.remove(self)
        print("WebSocket closed from: " + self.request.remote_ip)

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

def log(msg):
  print "[{time}] {msg}".format(time=strftime("%Y-%m-%d %H:%M:%S", localtime()), msg=msg)

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
  for i in xrange(0, img.shape[0], DELTA):
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
  buf = io.BytesIO(file_data)
  buf.seek(0)
  return buf

def get_store_and_show_image():
  file_path = gp.check_result(gp.gp_camera_capture(CAMERA, gp.GP_CAPTURE_IMAGE))
  log('Camera file path: {0}/{1}'.format(file_path.folder, file_path.name))
  target = image_filename()
  print 'Copying image to {target}'.format(target=target)
  camera_file = gp.check_result(gp.gp_camera_file_get(CAMERA, file_path.folder, file_path.name, gp.GP_FILE_TYPE_NORMAL))
  gp.check_result(gp.gp_file_save(camera_file, target))
  subprocess.call(['open', target])
  return target

def current_position_take_preview_image_and_set_as_reference():
  global REFERENCE_FFT_RESULT, REFERENCE_Z_POSITION
  image = get_preview_image()
  REFERENCE_FFT_RESULT = sample_and_fft(image)
  REFERENCE_Z_POSITION = Z_POSITION
  print "Using current position {pos} as reference".format(pos=Z_POSITION)

def current_position_take_image_and_get_correlation_with_reference():
  image = get_preview_image()
  fft_result = sample_and_fft(image)
  corr = np.corrcoef(REFERENCE_FFT_RESULT, fft_result)[1,0]
  log("Captured image position {pos} correlation {corr}".format(pos=Z_POSITION, corr=corr))
  return corr

def connect_arduino(ser):
  data = serial_readline(ser)
  if data != "HELLO":
    raise SystemError("Expected HELLO, but got {data}".format(data=data))
  
def connect_camera():
  global CAMERA

  logging.basicConfig(format='%(levelname)s: %(name)s: %(message)s', level=logging.WARNING)
  gp.check_result(gp.use_python_logging())
  CAMERA = gp.check_result(gp.gp_camera_new())
  gp.check_result(gp.gp_camera_init(CAMERA))

  # required configuration will depend on camera type!
  print "Checking camera config"
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
  log("Ready, q = quit, a = -1, z = +1, t = take and show image, r = use current position as reference, f = find position with highest correlation with reference")

def setup():
  try:
    ser = serial.Serial(ARDUINO_PORT, baudrate=ARDUINO_SPEED)
  except SerialException as err:
    raise PeripheralStatusError("Could not connect to Arduino: " + err.strerror)

  return ser

def getchar():
  #i, o, e = select.select([sys.stdin], [], [], 10)

  char = readchar.readchar()

  if char == '\x03':
    raise KeyboardInterrupt
  elif char == '\x04':
    raise EOFError
  elif char == '\x1a':
    os.kill(0, signal.SIGTSTP)
  return char

def serial_writeline(ser, data):
  log("ARDUINO -> {data}".format(data=data))
  ser.write("{data}\r\n".format(data=data));

def serial_readline(ser):
  data = ser.readline()[:-2]
  if data:
    log("ARDUINO <- {data}".format(data=data))
  return data

def move_z(ser, value):
  global Z_POSITION
  if abs(Z_POSITION - REFENCE_Z_POSITION) > MAX_DELTA_TO_REFERENCE_Z_POSITION:
    raise PeripheralStatusError("Reached maximum delta to reference z position")
  Z_POSITION += value
  serial_writeline(ser, value)
  log("Z: {z}".format(z=Z_POSITION))

def find_position_with_lowest_correlation_with_reference(ser, level=1):
  if level > 5:
    raise PeripheralStatusError("Reached maximum limit for autofocus")
  move_z(ser, -1 * AUTOFOCUS_BOUND)
  xa = xrange(-1 * AUTOFOCUS_BOUND, AUTOFOCUS_BOUND, 5)
  ya = []
  for i in xa:
    move_z(ser, 2)
    corr = current_position_take_image_and_get_correlation_with_reference()
    log("Index %d has correlation %r)" % (i, corr))
    ya.append(corr)
  z = np.polyfit(xa, ya, 2)
  p = np.poly1d(z)
  result = scipy.optimize.minimize_scalar(-1 * p, method='bounded', bounds=[-1 * AUTOFOCUS_BOUND, AUTOFOCUS_BOUND])
  new_pos = round(result.x)
  move_z(ser, -1 * AUTOFOCUS_BOUND + new_pos)
  if abs(new_pos) + 3 > AUTOFOCUS_BOUND:
    find_position_with_lowest_correlation_with_reference(ser, level + 1)

def main():
  ser = setup()
  kill_ptpcamera()
  connect_camera()
  connect_arduino(ser)

def read_key(fd):
  print "IN READ KEY"
  sys.stdin.read(1)

def keyboard_control(fd, events):
  ch = read_key(fd)
  if ch == 'a':
    move_z(ser, -1)
  elif ch == 'z':
    move_z(ser, 1)
  elif ch == 't':
    get_and_store_image()
  elif ch == 'r':
    current_position_take_preview_image_and_set_as_reference()
  elif ch == 'f':
    find_position_with_lowest_correlation_with_reference(ser)
  elif ch == 'q':
    log("Exiting");
    sys.exit(0)

if __name__ == "__main__":
  script_path = os.path.dirname(os.path.realpath(__file__))
  static_path = script_path + '/static/'

  app = tornado.web.Application([
      (r"/websocket", ImageWebSocket),
      (r"/(.*)", tornado.web.StaticFileHandler, {'path': static_path, 'default_filename': 'index.html'}),
  ])
  app.listen(LISTEN_PORT)

  old_settings = termios.tcgetattr(sys.stdin)
  tty.setcbreak(sys.stdin, when=TCSANOW)
  tornado.ioloop.IOLoop.current().add_handler(sys.stdin, keyboard_control, tornado.ioloop.IOLoop.READ|tornado.ioloop.IOLoop.ERROR)

  print("Starting server: http://localhost:" + str(LISTEN_PORT) + "/")

  try:
    tornado.ioloop.IOLoop.current().start()

  finally:
    print "out of loop"
    termios.tcsetattr(sys.stdin, TCSANOW, old_settings)

    sys.exit(0)
  #except PeripheralStatusError as err:
  #  print err.message
  #  sys.exit(1)
